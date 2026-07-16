from __future__ import annotations

import time

from config import AppConfig, settings
from main import ChatBISystem
from models import AgentResult, QueryOptions, UserContext
from query_decomposer import QueryDecomposer
from agent_planner import AgentPlanner
from report_generator import ReportGenerator
from result_summarizer import ResultSummarizer
from step_executor import StepExecutor


class PlanAndExecuteAgent:
    def __init__(self, system: ChatBISystem, config: AppConfig = settings):
        self.system = system
        self.config = config
        self.decomposer = QueryDecomposer(system.llm)
        self.planner = AgentPlanner()
        self.executor = StepExecutor(system, config)
        self.summarizer = ResultSummarizer(system.llm)
        self.report_generator = ReportGenerator(system.llm)

    def run(
        self,
        user_question: str,
        options: QueryOptions | None = None,
        security_context: UserContext | None = None,
        source_id: str | None = None,
    ) -> AgentResult:
        started = time.perf_counter()
        options = options or QueryOptions()
        security_context = security_context or UserContext.demo_admin()
        try:
            decomposition = self.decomposer.decompose(user_question)
            plan = self.planner.create_plan(decomposition)
            results, execution_context = self.executor.execute(
                plan, user_question, options, security_context, source_id
            )
            summary = self.summarizer.summarize(user_question, plan, results)
            report = self.report_generator.generate(user_question, plan, results, summary)
            success = any(result.success for result in results)
            return AgentResult(
                success=success,
                question=user_question,
                plan=plan,
                step_results=results,
                summary=summary,
                report=report,
                metadata={
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "execution_memory_keys": list(execution_context.memory),
                },
                error=None if success else "所有分析步骤均失败",
                error_type=None if success else "execution_failed",
            )
        except Exception as exc:
            return AgentResult(
                success=False,
                question=user_question,
                error=str(exc),
                error_type="agent",
                metadata={"duration_ms": round((time.perf_counter() - started) * 1000, 2)},
            )

    def close(self) -> None:
        self.executor.close()
