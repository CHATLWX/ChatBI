from __future__ import annotations

from llm_client import LLMClient
from models import AnalysisSummary, ExecutionPlan, StepExecutionResult


class ResultSummarizer:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def summarize(
        self, original_question: str, plan: ExecutionPlan, results: list[StepExecutionResult]
    ) -> AnalysisSummary:
        successful = [result for result in results if result.success]
        findings = [
            f"{result.step_name}：返回 {len(result.rows)} 行；{result.formatted[:300]}"
            for result in successful
        ]
        text = f"完成 {len(successful)}/{len(results)} 个步骤。" + " ".join(findings)
        return AnalysisSummary(
            completed_steps=len(successful),
            total_steps=len(results),
            key_findings=findings,
            text=text,
        )
