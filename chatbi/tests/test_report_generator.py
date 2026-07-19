from types import SimpleNamespace

from models import (
    AnalysisSummary,
    ExecutionPlan,
    PlanStep,
    StepExecutionResult,
)
from report_generator import ReportGenerator


class FakeLLM:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.config = SimpleNamespace(llm=SimpleNamespace(max_tokens=4000))

    def generate_json(self, *_args):
        if self.error:
            raise self.error
        return self.response


class FlakyLLM(FakeLLM):
    def __init__(self, response):
        super().__init__(response=response)
        self.calls = 0

    def generate_json(self, *_args):
        self.calls += 1
        if self.calls == 1:
            raise ValueError("temporary invalid JSON")
        return self.response


def fixtures():
    plan = ExecutionPlan(
        question_type="trend",
        analysis_goal="分析利润变化",
        steps=[
            PlanStep(
                step_id="step_1",
                task_id="task_1",
                step_name="利润趋势",
                task_type="trend",
                question="最近三个月利润",
                description="按月份分析利润",
                metrics=["利润"],
                dimensions=["月份"],
                expected_output="月度利润",
            )
        ],
    )
    results = [
        StepExecutionResult(
            step_id="step_1",
            task_id="task_1",
            step_name="利润趋势",
            success=True,
            question="最近三个月利润",
            columns=["month", "profit"],
            rows=[{"month": "2026-06", "profit": 10}],
            formatted="month | profit\n2026-06 | 10",
            result_reference="memory://step_1",
        )
    ]
    summary = AnalysisSummary(
        completed_steps=1,
        total_steps=1,
        key_findings=["2026-06 利润为 10"],
        text="完成 1/1 个步骤",
    )
    return plan, results, summary


def test_generates_structured_report_and_markdown():
    response = {
        "title": "利润分析",
        "executive_summary": "2026-06 利润为 10。",
        "key_findings": ["2026-06 利润为 10"],
        "root_causes": ["证据不足，尚不能归因"],
        "trend_judgment": "当前仅有一个月份，无法判断趋势。",
        "action_suggestions": ["显著低于制造业常见水平，需要核查。", "补充更多月份数据后再验证。"],
    }
    plan, results, summary = fixtures()

    report = ReportGenerator(FakeLLM(response=response)).generate(
        "利润为什么下降？", plan, results, summary
    )

    assert report.title == "利润分析"
    assert "# 利润分析" in report.markdown
    assert "## 归因分析" in report.markdown
    assert report.trend_judgment == "当前仅有单期数据，无法形成可靠的趋势判断。"
    assert all("常见水平" not in item for item in report.action_suggestions)
    assert "核查销售成本归集范围" in report.action_suggestions[0]


def test_falls_back_when_model_json_is_invalid():
    plan, results, summary = fixtures()

    report = ReportGenerator(FakeLLM(error=ValueError("invalid"))).generate(
        "利润为什么下降？", plan, results, summary
    )

    assert "证据不足" in report.root_causes[0]
    assert report.markdown.startswith("# ")
    assert all("失败步骤" not in item for item in report.action_suggestions)
    assert any("环比或同比" in item for item in report.action_suggestions)


def test_removes_ascii_tables_from_generated_report():
    response = {
        "title": "利润分析",
        "executive_summary": "month | profit\n------+-------\n2026-06 | 10",
        "key_findings": ["month | profit | margin | cost\n2026-06 | 10 | 20 | 5"],
        "root_causes": ["证据不足，尚不能归因"],
        "trend_judgment": "单月数据",
        "action_suggestions": ["补充更多月份数据"],
    }
    plan, results, summary = fixtures()

    report = ReportGenerator(FakeLLM(response=response)).generate(
        "利润为什么下降？", plan, results, summary
    )

    assert "|" not in report.executive_summary
    assert all("|" not in item for item in report.key_findings)
    assert report.key_findings == summary.key_findings


def test_retries_report_generation_once_before_fallback():
    response = {
        "title": "利润分析",
        "executive_summary": "2026-06 利润为 10。",
        "key_findings": ["2026-06 利润为 10"],
        "root_causes": ["证据不足，尚不能归因"],
        "trend_judgment": "单月数据。",
        "action_suggestions": ["补充更多月份数据。"],
    }
    llm = FlakyLLM(response)
    plan, results, summary = fixtures()

    report = ReportGenerator(llm).generate("利润为什么下降？", plan, results, summary)

    assert llm.calls == 2
    assert report.title == "利润分析"


def test_accepts_wrapped_report_and_coerces_string_lists():
    response = {
        "analysis_report": {
            "title": "利润分析",
            "executive_summary": "2026-06 利润为 10。",
            "key_findings": "2026-06 利润为 10",
            "root_causes": [{"conclusion": "证据不足，尚不能归因"}],
            "trend_judgment": "单月数据。",
            "action_suggestions": "补充更多月份数据。",
        }
    }
    plan, results, summary = fixtures()

    report = ReportGenerator(FakeLLM(response=response)).generate(
        "利润为什么下降？", plan, results, summary
    )

    assert report.title == "利润分析"
    assert report.key_findings == ["2026-06 利润为 10"]
    assert report.root_causes == ["证据不足，尚不能归因"]


def test_evidence_rows_preserves_head_and_tail_periods():
    rows = [{"month": f"2026-{month:02d}"} for month in range(1, 13)]

    evidence = ReportGenerator._evidence_rows(rows, limit=6)

    assert [row["month"] for row in evidence] == [
        "2026-01",
        "2026-02",
        "2026-03",
        "2026-10",
        "2026-11",
        "2026-12",
    ]


def test_clean_text_removes_internal_step_identifiers():
    assert ReportGenerator._clean_text("请复核 step_4 和 task-2 的数据") == "请复核 对应查询 和 对应查询 的数据"


def test_rejects_unverified_wanyuan_unit_conversion():
    response = {
        "title": "利润分析",
        "executive_summary": "6月收入减少9995万元。",
        "key_findings": ["6月收入减少9995万元。"],
        "root_causes": ["收入下降是主要驱动因素。"],
        "trend_judgment": "6月利润为874万元。",
        "action_suggestions": ["复核收入确认节奏。"],
    }
    plan, results, summary = fixtures()

    report = ReportGenerator(FakeLLM(response=response)).generate(
        "利润为什么下降？", plan, results, summary
    )

    assert "万元" not in report.executive_summary
    assert all("万元" not in item for item in report.key_findings)
    assert "万元" not in report.trend_judgment
