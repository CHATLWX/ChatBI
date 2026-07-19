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
        findings = [self._summarize_result(result) for result in successful]
        text = f"完成 {len(successful)}/{len(results)} 个步骤。"
        if successful:
            names = "、".join(result.step_name for result in successful[:4])
            suffix = "等" if len(successful) > 4 else ""
            text += f"已获得{names}{suffix}的可用证据。"
        return AnalysisSummary(
            completed_steps=len(successful),
            total_steps=len(results),
            key_findings=findings,
            text=text,
        )

    @classmethod
    def _summarize_result(cls, result: StepExecutionResult) -> str:
        preview_rows = result.rows[:1]
        if len(result.rows) > 1:
            preview_rows += result.rows[-1:]
        previews = [cls._summarize_row(row) for row in preview_rows]
        evidence = "；".join(item for item in previews if item)
        suffix = f"；首尾证据：{evidence}" if evidence else ""
        return f"{result.step_name}：返回 {len(result.rows)} 行{suffix}"

    @staticmethod
    def _summarize_row(row: dict) -> str:
        pairs = []
        for key, value in list(row.items())[:6]:
            if isinstance(value, float):
                rendered = f"{value:,.2f}".rstrip("0").rstrip(".")
            elif isinstance(value, int):
                rendered = f"{value:,}"
            else:
                rendered = str(value)
            pairs.append(f"{key}={rendered}")
        return "，".join(pairs)
