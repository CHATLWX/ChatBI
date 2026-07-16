from __future__ import annotations

import json

from config import AppConfig, settings
from main import ChatBISystem
from models import ExecutionContext, ExecutionPlan, QueryOptions, StepExecutionResult, UserContext
from result_store import ResultStore, build_result_store


class StepExecutor:
    def __init__(
        self,
        system: ChatBISystem,
        config: AppConfig = settings,
        result_store: ResultStore | None = None,
    ):
        self.system = system
        self.config = config
        self.result_store = result_store or build_result_store(config)

    def execute(
        self,
        plan: ExecutionPlan,
        original_question: str,
        options: QueryOptions,
        security_context: UserContext,
        source_id: str | None = None,
    ) -> tuple[list[StepExecutionResult], ExecutionContext]:
        context = ExecutionContext(original_question=original_question)
        results: list[StepExecutionResult] = []
        aborted = False
        for step in plan.steps:
            if aborted:
                result = self._build_skipped(step, "前序步骤失败，执行策略为 abort。")
            else:
                failed_dependencies = [
                    dependency
                    for dependency in step.depends_on
                    if dependency not in context.results or not context.results[dependency].success
                ]
                if failed_dependencies:
                    result = self._build_skipped(
                        step,
                        f"依赖步骤失败，当前步骤已跳过：{', '.join(failed_dependencies)}",
                    )
                else:
                    result = self._execute_step(step, context, options, security_context, source_id)
                    if not result.success and self.config.runtime.agent_failure_policy == "abort":
                        aborted = True
            results.append(result)
            context.results[step.step_id] = result
        return results, context

    def _execute_step(
        self,
        step,
        context: ExecutionContext,
        options: QueryOptions,
        security_context: UserContext,
        source_id: str | None,
    ) -> StepExecutionResult:
        context_text = self._build_context(step.depends_on, context)
        last_result = None
        for attempt in range(1, self.config.runtime.agent_max_retries + 2):
            last_result = self.system.run(
                step.question,
                options,
                security_context,
                context_text,
                source_id,
            )
            if last_result.success:
                reference = self.result_store.put(step.step_id, last_result.columns, last_result.rows)
                context.memory[reference] = {
                    "columns": last_result.columns,
                    "rows": last_result.rows,
                    "formatted": last_result.formatted,
                    "sql": last_result.sql,
                }
                return StepExecutionResult(
                    step_id=step.step_id,
                    task_id=step.task_id,
                    step_name=step.step_name,
                    success=True,
                    status="completed",
                    attempts=attempt,
                    question=step.question,
                    depends_on=step.depends_on,
                    context_used=context_text,
                    storage_backend=self.result_store.backend,
                    result_reference=reference,
                    sql=last_result.sql,
                    columns=last_result.columns,
                    rows=last_result.rows,
                    formatted=last_result.formatted,
                    metadata=last_result.metadata,
                )
        assert last_result is not None
        return StepExecutionResult(
            step_id=step.step_id,
            task_id=step.task_id,
            step_name=step.step_name,
            success=False,
            status="failed",
            attempts=self.config.runtime.agent_max_retries + 1,
            question=step.question,
            depends_on=step.depends_on,
            context_used=context_text,
            sql=last_result.sql,
            error=last_result.error,
            error_type=last_result.error_type,
            metadata=last_result.metadata,
        )

    @staticmethod
    def _build_skipped(step, error: str) -> StepExecutionResult:
        return StepExecutionResult(
            step_id=step.step_id,
            task_id=step.task_id,
            step_name=step.step_name,
            success=False,
            status="skipped",
            attempts=0,
            question=step.question,
            depends_on=step.depends_on,
            error=error,
            error_type="dependency_failed",
        )

    @staticmethod
    def _build_context(dependencies: list[str], context: ExecutionContext) -> str:
        blocks = []
        for dependency in dependencies:
            result = context.results.get(dependency)
            if result and result.success:
                blocks.append(
                    json.dumps(
                        {
                            "step_id": result.step_id,
                            "step_name": result.step_name,
                            "columns": result.columns,
                            "rows": result.rows,
                            "result_reference": result.result_reference,
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                )
        return "\n".join(blocks)

    def close(self) -> None:
        self.result_store.cleanup()
