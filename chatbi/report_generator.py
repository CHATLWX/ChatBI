from __future__ import annotations

import json
import logging
import re

from llm_client import LLMClient
from models import AnalysisReport, AnalysisSummary, ExecutionPlan, StepExecutionResult


logger = logging.getLogger(__name__)


class ReportGenerator:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def generate(
        self,
        original_question: str,
        plan: ExecutionPlan,
        results: list[StepExecutionResult],
        summary: AnalysisSummary,
    ) -> AnalysisReport:
        compressed = [
            {
                "step_id": result.step_id,
                "step_name": result.step_name,
                "status": result.status,
                "success": result.success,
                "columns": result.columns,
                "row_count": len(result.rows),
                "result_reference": result.result_reference,
                "rows_preview": self._evidence_rows(result.rows),
                "error": result.error,
            }
            for result in results
        ]
        prompt = f"""请根据 Agent 的真实执行结果生成结构化分析报告。
原问题：{original_question}
分析目标：{plan.analysis_goal}
步骤完成情况：{summary.completed_steps}/{summary.total_steps}
执行结果：{json.dumps(compressed, ensure_ascii=False, default=str)}

约束：
1. 只能引用执行结果中的数据，不得补充未查询到的原因或数值。
2. 证据不足时必须明确写“证据不足”。
3. root_causes 只能写查询结果直接支持的驱动因素；相关性不能写成已经证实的因果关系。
4. trend_judgment 只概括已查询时间段，不得预测未来月份，不得引用行业基准或外部知识。
5. action_suggestions 只能基于已查询异常提出后续核查或改进方向；未查询因素必须明确写成“待验证”，不得把汇率、一次性收益、本地化成本等猜测写成事实。
6. 不得复制 ASCII 表格、字段分隔线或原始 formatted 文本；必须把证据提炼成简洁业务结论。executive_summary 不超过 280 字，其他单条不超过 160 字。
7. 只返回 JSON，包含 title、executive_summary、key_findings、root_causes、trend_judgment、action_suggestions。
8. 报告面向业务用户，不得出现 step_1、task_2、rows_preview 等系统字段或执行编号。
9. 金额必须保持查询结果的原始数值和单位，不得自行换算为“万元”或“亿元”，避免量级误差。
"""
        report = None
        for attempt in range(2):
            try:
                payload = self.llm.generate_json(
                    "你是严谨的制造业财务分析师。",
                    prompt,
                    self.llm.config.llm.max_tokens,
                )
                report = self._coerce_report_payload(
                    payload, original_question, results, summary
                )
                break
            except Exception:
                if attempt == 0:
                    logger.warning("Structured report generation failed once; retrying", exc_info=True)
                else:
                    logger.exception(
                        "Failed to generate structured analysis report twice; using evidence-only fallback"
                    )
        if report is None:
            report = self._fallback(original_question, results, summary)
        report = self._enforce_evidence_boundaries(report, results, summary)
        report.markdown = self.render_markdown(report)
        return report

    @staticmethod
    def _evidence_rows(rows: list[dict], limit: int = 10) -> list[dict]:
        """Preserve both early and late periods when evidence must be compressed."""
        if len(rows) <= limit:
            return rows
        head_size = limit // 2
        return rows[:head_size] + rows[-(limit - head_size) :]

    @staticmethod
    def _coerce_report_payload(
        payload: dict,
        question: str,
        results: list[StepExecutionResult],
        summary: AnalysisSummary,
    ) -> AnalysisReport:
        """Keep useful Qwen content when list fields or wrappers vary slightly."""
        data = payload
        for key in ("report", "analysis_report", "data", "result"):
            candidate = data.get(key) if isinstance(data, dict) else None
            if isinstance(candidate, dict):
                data = candidate
                break
        if not isinstance(data, dict) or not data:
            raise ValueError("empty report payload")

        def text_value(key: str, default: str) -> str:
            value = data.get(key, default)
            if isinstance(value, (dict, list)):
                return default
            return str(value or default)

        def list_value(key: str, default: list[str]) -> list[str]:
            value = data.get(key)
            if isinstance(value, str):
                return [value]
            if isinstance(value, list):
                items = []
                for item in value:
                    if isinstance(item, str):
                        items.append(item)
                    elif isinstance(item, dict):
                        rendered = next(
                            (str(v) for v in item.values() if isinstance(v, (str, int, float))),
                            "",
                        )
                        if rendered:
                            items.append(rendered)
                return items or default
            return default

        fallback_suggestions = ReportGenerator._fallback_suggestions(results, [])
        return AnalysisReport(
            title=text_value("title", f"{question}分析报告"),
            executive_summary=text_value("executive_summary", summary.text),
            key_findings=list_value("key_findings", summary.key_findings),
            root_causes=list_value("root_causes", ["证据不足，无法形成可靠归因。"]),
            trend_judgment=text_value(
                "trend_judgment", "当前执行结果不足以形成可靠的趋势判断。"
            ),
            action_suggestions=list_value("action_suggestions", fallback_suggestions),
        )

    @staticmethod
    def _enforce_evidence_boundaries(
        report: AnalysisReport,
        results: list[StepExecutionResult],
        summary: AnalysisSummary,
    ) -> AnalysisReport:
        """Apply deterministic guards after LLM generation as required by the report lesson."""
        external_benchmark = re.compile(r"行业|常见水平|平均水平|外部基准|行业基准")
        key_findings = ReportGenerator._clean_list(report.key_findings)
        if not key_findings:
            key_findings = ReportGenerator._clean_list(summary.key_findings)
        root_causes = ReportGenerator._clean_list(report.root_causes)
        if not root_causes:
            root_causes = ["证据不足，无法形成可靠归因。"]
        suggestions = [
            item
            for item in ReportGenerator._clean_list(report.action_suggestions)
            if not external_benchmark.search(item)
        ]
        if len(suggestions) != len(report.action_suggestions):
            suggestions.insert(0, "核查销售成本归集范围是否完整，并确认其与当前指标口径一致。")

        if not suggestions:
            suggestions = ["补充对比期间或细分维度数据后，再制定可验证的改进动作。"]

        executive_summary = ReportGenerator._clean_text(report.executive_summary, 420)
        if ReportGenerator._looks_like_table(
            report.executive_summary
        ) or ReportGenerator._contains_scaled_money(report.executive_summary):
            executive_summary = ReportGenerator._clean_text(summary.text, 420)

        has_multiple_period_rows = ReportGenerator._has_multiple_periods(results)
        trend_judgment = ReportGenerator._clean_text(report.trend_judgment, 320)
        if not has_multiple_period_rows:
            trend_judgment = "当前仅有单期数据，无法形成可靠的趋势判断。"
        elif ReportGenerator._contains_scaled_money(trend_judgment):
            trend_judgment = "已获得多个期间的查询结果，趋势方向以关键发现中的原始数值为准。"

        return report.model_copy(
            update={
                "executive_summary": executive_summary,
                "key_findings": key_findings,
                "root_causes": root_causes,
                "trend_judgment": trend_judgment,
                "action_suggestions": suggestions,
            }
        )

    @staticmethod
    def _clean_text(value: str, limit: int = 360) -> str:
        text = re.sub(r"\b(?:step|task)[_\s-]?\d+\b", "对应查询", str(value or ""), flags=re.I)
        return re.sub(r"\s+", " ", text).strip()[:limit]

    @classmethod
    def _clean_list(cls, values: list[str]) -> list[str]:
        cleaned = []
        for value in values or []:
            if cls._looks_like_table(value) or cls._contains_scaled_money(value):
                continue
            item = cls._clean_text(value, 220)
            if item and item not in cleaned:
                cleaned.append(item)
        return cleaned[:8]

    @staticmethod
    def _looks_like_table(value: str) -> bool:
        text = str(value or "")
        return text.count("|") >= 3 or "+---" in text or "---+" in text

    @staticmethod
    def _contains_scaled_money(value: str) -> bool:
        return bool(re.search(r"(?:万|亿)元", str(value or "")))

    @staticmethod
    def _has_multiple_periods(results: list[StepExecutionResult]) -> bool:
        periods = set()
        for result in results:
            if not result.success:
                continue
            for row in result.rows:
                for key, value in row.items():
                    normalized = key.lower()
                    if "month" in normalized or "date" in normalized or key in {"月份", "日期"}:
                        periods.add(str(value))
        return len(periods) > 1

    @staticmethod
    def _fallback(
        question: str, results: list[StepExecutionResult], summary: AnalysisSummary
    ) -> AnalysisReport:
        failed_steps = [result.step_name for result in results if not result.success]
        suggestions = ReportGenerator._fallback_suggestions(results, failed_steps)
        if failed_steps:
            suggestions = (
            [
                f"补充或重试未完成的分析步骤：{', '.join(failed_steps)}；当前建议仅基于已完成证据。",
                *suggestions,
            ]
            if failed_steps and summary.completed_steps
            else [f"修复并重试失败步骤：{', '.join(failed_steps)}。"]
            )
        return AnalysisReport(
            title=f"{question}分析报告",
            executive_summary=summary.text,
            key_findings=summary.key_findings or ["没有成功执行的分析步骤。"],
            root_causes=["证据不足，无法形成可靠归因。"],
            trend_judgment="当前执行结果不足以形成可靠的趋势判断。",
            action_suggestions=suggestions,
        )

    @staticmethod
    def _fallback_suggestions(
        results: list[StepExecutionResult], failed_steps: list[str]
    ) -> list[str]:
        columns = {
            column.lower()
            for result in results
            if result.success
            for column in result.columns
        }
        suggestions = []
        if "revenue" in columns:
            suggestions.append(
                "优先复盘收入下滑最大的相邻月份，结合已查询的产品线和客户类型结果，锁定收入缺口来源。"
            )
        if columns.intersection(
            {"period_expense", "rd_expense", "selling_expense", "admin_expense", "finance_expense"}
        ):
            suggestions.append(
                "将期间费用增量拆到研发、销售、管理和财务费用，优先复核增幅最大项，并验证是否为持续性支出。"
            )
        if "gross_margin" in columns:
            suggestions.append(
                "对收入和毛利率设置月度联动监控，分开评估规模变化与成本结构变化的影响。"
            )
        if not suggestions:
            suggestions.extend(
                [
                    "补充环比或同比期间数据，验证指标变化趋势。",
                    "按产品线、区域等业务维度拆分结果，定位差异来源。",
                ]
            )
        return suggestions[:3]

    @staticmethod
    def render_markdown(report: AnalysisReport) -> str:
        bullet = lambda values: "\n".join(f"- {item}" for item in values) or "- 无"
        return (
            f"# {report.title}\n\n## 执行摘要\n{report.executive_summary}\n\n"
            f"## 关键发现\n{bullet(report.key_findings)}\n\n"
            f"## 归因分析\n{bullet(report.root_causes)}\n\n"
            f"## 趋势判断\n{report.trend_judgment}\n\n"
            f"## 行动建议\n{bullet(report.action_suggestions)}"
        )
