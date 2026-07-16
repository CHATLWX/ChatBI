from __future__ import annotations

import re

from llm_client import LLMClient
from models import DecompositionPlan
from indicator_metadata import INDICATOR_DEFINITIONS
from schema_metadata import TABLE_METADATA


MAX_TASKS = 6
MAX_DIMENSIONS_PER_TASK = 2
ABSOLUTE_DATE_PATTERN = re.compile(
    r"20\d{2}(?:[-/]\d{1,2}(?:[-/]\d{1,2})?|年(?:\d{1,2}月(?:\d{1,2}日)?)?)"
)

DIMENSION_ALIASES = {
    "月份": "月份",
    "month": "月份",
    "year_month": "月份",
    "时间": "月份",
    "大区": "大区",
    "区域": "大区",
    "region": "大区",
    "国家": "国家",
    "country": "国家",
    "客户类型": "客户类型",
    "customer_type": "客户类型",
    "行业": "行业",
    "industry": "行业",
    "产品线": "产品线",
    "product_line": "产品线",
    "产品类别": "产品类别",
    "category": "产品类别",
    "技术路线": "技术路线",
    "tech_route": "技术路线",
    "部门": "部门",
    "department": "部门",
    # 第 26 课要求未建模维度回退到最接近的已建模维度。
    "渠道": "客户类型",
    "销售渠道": "客户类型",
    "channel": "客户类型",
}
AVAILABLE_DIMENSIONS = tuple(dict.fromkeys(DIMENSION_ALIASES.values()))
AVAILABLE_INDICATORS = tuple(item["name"] for item in INDICATOR_DEFINITIONS)
RAW_EXPENSE_METRICS = (
    "rd_expense",
    "selling_expense",
    "admin_expense",
    "finance_expense",
)
AVAILABLE_METRICS = AVAILABLE_INDICATORS + RAW_EXPENSE_METRICS

SALES_DIMENSIONS = {
    "月份",
    "大区",
    "国家",
    "客户类型",
    "行业",
    "产品线",
    "产品类别",
    "技术路线",
}
METRIC_ALLOWED_DIMENSIONS = {
    "收入": SALES_DIMENSIONS,
    "销量": SALES_DIMENSIONS,
    "订单量": SALES_DIMENSIONS,
    "销售成本": SALES_DIMENSIONS,
    "毛利": SALES_DIMENSIONS,
    "毛利率": SALES_DIMENSIONS,
    "客单价": SALES_DIMENSIONS,
    "产品线收入": {"月份", "产品线"},
    "期间费用": {"月份", "部门"},
    "rd_expense": {"月份", "部门"},
    "selling_expense": {"月份", "部门"},
    "admin_expense": {"月份", "部门"},
    "finance_expense": {"月份", "部门"},
    "研发费用率": {"月份"},
    "销售费用率": {"月份"},
    # 费用表没有客户、产品和区域维度，未定义分摊规则时利润只能按月份计算。
    "利润": {"月份"},
    "利润率": {"月份"},
}


def _schema_block() -> str:
    lines = []
    for table_name, metadata in TABLE_METADATA.items():
        lines.append(
            f"- {table_name}：{metadata['description']}；关键字段：{metadata['key_fields']}"
        )
    return "\n".join(lines)


def _indicator_block() -> str:
    return "\n".join(
        f"- {indicator['name']}：{indicator['definition']}；公式：{indicator['formula']}"
        for indicator in INDICATOR_DEFINITIONS
    )


def build_decomposition_prompt(user_question: str, retry_feedback: str = "") -> tuple[str, str]:
    system_msg = (
        "你是企业级 ChatBI 系统中的任务拆解器。"
        "请把复杂分析问题拆成可执行的子任务列表，"
        "输出必须是 JSON，不要输出额外解释。"
    )
    feedback = f"\n上一次拆解未通过校验：{retry_feedback}\n请重新拆解。" if retry_feedback else ""
    prompt = f"""
请将下面的复杂分析问题拆解为结构化子任务，并严格输出 JSON：

用户问题：{user_question}

当前数据库 Schema：
{_schema_block()}

可用分析维度：{', '.join(AVAILABLE_DIMENSIONS)}
metrics 可用值：{', '.join(AVAILABLE_METRICS)}
可用指标及口径：
{_indicator_block()}

输出要求：
1. 顶层字段包含 question_type、analysis_goal、subtasks
2. subtasks 是有序数组，每个任务必须包含 task_id、task_name、task_type、description、depends_on、dimensions、metrics
3. task_id 使用 task_1、task_2 这类格式
4. depends_on 只能引用前面已经出现的 task_id
5. 如果问题涉及时间对比、维度对比、指标拆解，请显式拆成多个子任务
6. 每个任务只承担一个清晰、可执行的分析目标，最多 {MAX_TASKS} 个任务
7. dimensions 只能从可用分析维度中选择；用户提到未建模维度时，回退到最接近的可用维度
8. 单个任务最多使用 {MAX_DIMENSIONS_PER_TASK} 个维度（通常是月份加一个业务维度）；多个业务维度必须拆成不同任务，避免单条 SQL 过宽
9. description 必须原样保留用户的相对时间范围。例如“最近三个月”仍写“最近三个月”，用户未给出年份、月份或具体日期时，绝对禁止猜测或补写任何绝对日期
10. 只能使用当前 Schema、所选 dimensions 和上述指标口径，不得改写成 standard_cost 等其他口径
11. metrics 只能从“metrics 可用值”中选择。利润/利润率只能按月份分析；期间费用及费用分项只能按月份或部门分析；客户、产品、区域等维度没有费用分摊规则，必须使用毛利/毛利率而不是利润/利润率
12. 仅返回 JSON 对象，不要使用 Markdown{feedback}
""".strip()
    return system_msg, prompt


class QueryDecomposer:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def decompose(self, user_question: str) -> DecompositionPlan:
        question = user_question.strip()
        if not question:
            raise ValueError("输入问题不能为空")

        feedback = ""
        last_error: Exception | None = None
        for _ in range(2):  # 第 26 课：超出边界时最多重拆一次
            system_msg, prompt = build_decomposition_prompt(question, feedback)
            try:
                data = self.llm.generate_json(
                    system_msg,
                    prompt,
                    self.llm.config.llm.max_tokens,
                )
                plan = DecompositionPlan.model_validate(data)
                self._validate_plan(plan, question)
                return plan
            except Exception as exc:
                last_error = exc
                feedback = str(exc)
        assert last_error is not None
        raise last_error

    @classmethod
    def _validate_plan(cls, plan: DecompositionPlan, original_question: str = "") -> None:
        if not plan.subtasks:
            raise ValueError("subtasks 不能为空")
        if len(plan.subtasks) > MAX_TASKS:
            raise ValueError(f"子任务数量不能超过 {MAX_TASKS}")

        seen_ids: set[str] = set()
        for task in plan.subtasks:
            if not task.task_id or task.task_id in seen_ids:
                raise ValueError(f"task_id 无效或重复：{task.task_id}")
            for dependency in task.depends_on:
                if dependency not in seen_ids:
                    raise ValueError(f"任务 {task.task_id} 依赖了不存在的任务：{dependency}")

            normalized_dimensions = []
            for dimension in task.dimensions:
                normalized = DIMENSION_ALIASES.get(dimension.strip().lower())
                if normalized is None:
                    raise ValueError(f"任务 {task.task_id} 使用了未建模维度：{dimension}")
                if normalized not in normalized_dimensions:
                    normalized_dimensions.append(normalized)
            if len(normalized_dimensions) > MAX_DIMENSIONS_PER_TASK:
                raise ValueError(
                    f"任务 {task.task_id} 包含 {len(normalized_dimensions)} 个维度，"
                    f"超过单步上限 {MAX_DIMENSIONS_PER_TASK}"
                )
            task.dimensions = normalized_dimensions

            invalid_metrics = set(task.metrics) - set(AVAILABLE_METRICS)
            if invalid_metrics:
                raise ValueError(
                    f"任务 {task.task_id} 使用了未定义指标："
                    + "、".join(sorted(invalid_metrics))
                )
            for metric in task.metrics:
                allowed_dimensions = METRIC_ALLOWED_DIMENSIONS.get(metric)
                if allowed_dimensions is None:
                    continue
                incompatible = set(normalized_dimensions) - allowed_dimensions
                if incompatible:
                    raise ValueError(
                        f"任务 {task.task_id} 的指标 {metric} 不支持维度："
                        + "、".join(sorted(incompatible))
                        + "；未定义费用分摊规则时请改用毛利类指标"
                    )

            description = task.description.lower()
            mentioned_dimensions = {
                canonical
                for alias, canonical in DIMENSION_ALIASES.items()
                if alias in description
            }
            unselected_dimensions = mentioned_dimensions - set(normalized_dimensions)
            if unselected_dimensions:
                raise ValueError(
                    f"任务 {task.task_id} 的 description 提到了未选择的维度："
                    + "、".join(sorted(unselected_dimensions))
                    + "；请拆成独立任务或补入 dimensions"
                )
            seen_ids.add(task.task_id)

        original_dates = set(ABSOLUTE_DATE_PATTERN.findall(original_question))
        generated_text = " ".join(
            [plan.analysis_goal]
            + [task.task_name for task in plan.subtasks]
            + [task.description for task in plan.subtasks]
        )
        invented_dates = set(ABSOLUTE_DATE_PATTERN.findall(generated_text)) - original_dates
        if invented_dates:
            raise ValueError(
                "拆解结果添加了用户未提供的绝对日期："
                + "、".join(sorted(invented_dates))
                + "；必须保留原始相对时间范围"
            )
