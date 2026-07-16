from __future__ import annotations

import json

from llm_client import LLMClient
from models import AnalysisReport, AnalysisSummary, ExecutionPlan, StepExecutionResult


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
                "formatted": result.formatted[:1200],
                "result_reference": result.result_reference,
                "rows_preview": result.rows[:5],
                "error": result.error,
            }
            for result in results
        ]
        prompt = f"""请根据 Agent 的真实执行结果生成结构化分析报告。
原问题：{original_question}
分析目标：{plan.analysis_goal}
步骤摘要：{summary.text}
执行结果：{json.dumps(compressed, ensure_ascii=False, default=str)}

约束：
1. 只能引用执行结果中的数据，不得补充未查询到的原因或数值。
2. 证据不足时必须明确写“证据不足”。
3. root_causes 只能写查询结果直接支持的驱动因素；相关性不能写成已经证实的因果关系。
4. trend_judgment 只概括已查询时间段，不得预测未来月份，不得引用行业基准或外部知识。
5. action_suggestions 只能基于已查询异常提出后续核查或改进方向；未查询因素必须明确写成“待验证”，不得把汇率、一次性收益、本地化成本等猜测写成事实。
6. 只返回 JSON，包含 title、executive_summary、key_findings、root_causes、trend_judgment、action_suggestions。
"""
        try:
            report = AnalysisReport.model_validate(
                self.llm.generate_json(
                    "你是严谨的制造业财务分析师。",
                    prompt,
                    self.llm.config.llm.max_tokens,
                )
            )
        except Exception:
            report = self._fallback(original_question, results, summary)
        report.markdown = self.render_markdown(report)
        return report

    @staticmethod
    def _fallback(
        question: str, results: list[StepExecutionResult], summary: AnalysisSummary
    ) -> AnalysisReport:
        return AnalysisReport(
            title=f"{question}分析报告",
            executive_summary=summary.text,
            key_findings=summary.key_findings or ["没有成功执行的分析步骤。"],
            root_causes=["证据不足，无法形成可靠归因。"],
            trend_judgment="请查看步骤明细并补充数据。",
            action_suggestions=["修复失败步骤后重新运行分析。"],
        )

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
