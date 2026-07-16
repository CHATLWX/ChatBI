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
        "action_suggestions": ["补充更多月份数据后再验证。"],
    }
    plan, results, summary = fixtures()

    report = ReportGenerator(FakeLLM(response=response)).generate(
        "利润为什么下降？", plan, results, summary
    )

    assert report.title == "利润分析"
    assert "# 利润分析" in report.markdown
    assert "## 归因分析" in report.markdown


def test_falls_back_when_model_json_is_invalid():
    plan, results, summary = fixtures()

    report = ReportGenerator(FakeLLM(error=ValueError("invalid"))).generate(
        "利润为什么下降？", plan, results, summary
    )

    assert "证据不足" in report.root_causes[0]
    assert report.markdown.startswith("# ")
