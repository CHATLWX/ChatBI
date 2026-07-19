from models import AnalysisSummary, ExecutionPlan, PlanStep, StepExecutionResult
from result_summarizer import ResultSummarizer


def test_summary_uses_compact_key_value_evidence_instead_of_ascii_table():
    plan = ExecutionPlan(
        question_type="trend",
        analysis_goal="分析利润趋势",
        steps=[
            PlanStep(
                step_id="step_1",
                task_id="task_1",
                step_name="月度利润趋势",
                task_type="trend",
                question="最近三个月利润",
                description="最近三个月利润",
                metrics=["利润"],
                dimensions=["月份"],
                expected_output="月度利润",
            )
        ],
    )
    result = StepExecutionResult(
        step_id="step_1",
        task_id="task_1",
        step_name="月度利润趋势",
        success=True,
        question="最近三个月利润",
        columns=["month", "profit"],
        rows=[{"month": "2026-04", "profit": 8702760.0}],
        formatted="month | profit\n------+-------\n2026-04 | 8702760",
    )

    summary: AnalysisSummary = ResultSummarizer(None).summarize("利润趋势", plan, [result])

    assert "month=2026-04" in summary.key_findings[0]
    assert "profit=8,702,760" in summary.key_findings[0]
    assert "|" not in summary.text
    assert "profit=" not in summary.text
