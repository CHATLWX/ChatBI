from __future__ import annotations

import time
from collections.abc import Callable, Generator
from typing import Any

from config import AppConfig, settings
from database import DatabaseClient, QueryExecutionError
from llm_client import LLMClient, LLMError
from models import QueryOptions, QueryResult, UserContext
from prompt_builder import build_prompt
from query_parser import QueryParser
from result_formatter import ResultFormatter
from runtime_factory import AppRuntime, build_runtime
from schema_linking import SchemaLinkingPipeline


class ChatBISystem:
    """课程第 29 课定义的统一查询入口；对象装配由 runtime factory 负责。"""

    def __init__(
        self,
        config: AppConfig = settings,
        runtime: AppRuntime | None = None,
        runtime_factory: Callable[[AppConfig, str | None], AppRuntime] = build_runtime,
        parser: QueryParser | None = None,
        llm: LLMClient | None = None,
        db: DatabaseClient | None = None,
        formatter: ResultFormatter | None = None,
        schema_linker: SchemaLinkingPipeline | None = None,
    ):
        self.config = config
        self.runtime_factory = runtime_factory
        if runtime is None and any((parser, llm, db, formatter, schema_linker)):
            default = build_runtime(config)
            runtime = AppRuntime(
                source_id=config.data_source_name,
                parser=parser or default.parser,
                llm=llm or default.llm,
                db=db or default.db,
                formatter=formatter or default.formatter,
                schema_linker=schema_linker or default.schema_linker,
                indicator_knowledge=default.indicator_knowledge,
                indicator_retriever=default.indicator_retriever,
            )
        self.runtime = runtime or self.runtime_factory(config, config.data_source_name)
        self._runtimes: dict[str, AppRuntime] = {self.runtime.source_id: self.runtime}

        # 保留课程前序模块直接访问这些属性的兼容入口。
        self.parser = self.runtime.parser
        self.llm = self.runtime.llm
        self.db = self.runtime.db
        self.formatter = self.runtime.formatter
        self.schema_linker = self.runtime.schema_linker
        self.indicator_knowledge = self.runtime.indicator_knowledge
        self.indicator_retriever = self.runtime.indicator_retriever

    @staticmethod
    def _resolve_indicator_context(
        runtime: AppRuntime,
        user_question: str,
        use_indicator_knowledge: bool,
        use_indicator_rag: bool,
    ) -> tuple[list[str], str]:
        detected_indicators: list[str] = []
        indicator_block = ""
        if use_indicator_rag:
            try:
                indicator_block, indicators = runtime.indicator_retriever.build_knowledge_block(user_question)
                detected_indicators = [item["name"] for item in indicators]
            except Exception:
                detected_indicators = []
                indicator_block = ""
            if use_indicator_knowledge and not indicator_block:
                context = runtime.indicator_knowledge.get_indicator_context(user_question)
                detected_indicators = context["detected_indicators"]
                indicator_block = context["indicator_block"]
        elif use_indicator_knowledge:
            context = runtime.indicator_knowledge.get_indicator_context(user_question)
            detected_indicators = context["detected_indicators"]
            indicator_block = context["indicator_block"]
        return detected_indicators, indicator_block

    def _get_runtime(self, source_id: str | None = None) -> AppRuntime:
        resolved = source_id or self.runtime.source_id
        if resolved not in self._runtimes:
            self._runtimes[resolved] = self.runtime_factory(self.config, resolved)
        return self._runtimes[resolved]

    @staticmethod
    def _database_error_type(error_type: str) -> str:
        return {
            "security": "security",
            "sql_syntax": "database_sql_syntax",
            "query_timeout": "database_query_timeout",
            "permission_denied": "database_permission_denied",
            "database_connection": "database_connection_error",
            "pool_timeout": "database_connection_error",
        }.get(error_type, "database")

    def run(
        self,
        user_question: str,
        options: QueryOptions | None = None,
        security_context: UserContext | None = None,
        execution_context: str = "",
        source_id: str | None = None,
    ) -> QueryResult:
        started = time.perf_counter()
        options = options or QueryOptions()
        runtime = self._get_runtime(source_id)
        parsed = runtime.parser.parse(user_question)
        if not runtime.parser.validate(parsed):
            return QueryResult(success=False, question=user_question, error="输入问题为空", error_type="validation")
        try:
            linking = (
                runtime.schema_linker.link(user_question)
                if options.use_schema_linking
                else self._full_schema_fallback()
            )
            detected_indicators, indicator_context = self._resolve_indicator_context(
                runtime,
                user_question,
                options.use_indicator_knowledge,
                options.use_indicator_rag,
            )
            system_msg, prompt = build_prompt(
                user_question,
                linking["schema_context"],
                indicator_context,
                use_few_shot=options.use_few_shot,
                use_rules=options.use_rules,
                use_guards=options.use_guards,
                execution_context=execution_context,
            )
            sql = runtime.llm.generate_sql(system_msg, prompt)
            sql_attempts = 1
            while True:
                try:
                    columns, rows = runtime.db.execute(sql, security_context)
                    break
                except QueryExecutionError as exc:
                    repair_count = sql_attempts - 1
                    if (
                        exc.error_type != "sql_syntax"
                        or repair_count >= runtime.db.config.runtime.sql_retry_count
                    ):
                        raise
                    sql = runtime.llm.repair_sql(
                        user_question,
                        sql,
                        f"{exc.error_type}: {exc}",
                        prompt,
                    )
                    sql_attempts += 1
            return QueryResult(
                success=True,
                question=user_question,
                sql=sql,
                columns=columns,
                rows=rows,
                formatted=runtime.formatter.format(columns, rows),
                metadata={
                    "model": runtime.llm.model,
                    "source_id": runtime.source_id,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "selected_tables": linking["selected_tables"],
                    "matched_fields": [item["field_key"] for item in linking["fields"]],
                    "matched_indicators": detected_indicators,
                    "join_plan": linking["join_plan"],
                    "query_info": runtime.db.last_query_info,
                    "sql_attempts": sql_attempts,
                    "prompt_context": prompt,
                },
            )
        except LLMError as exc:
            return QueryResult(success=False, question=user_question, error=str(exc), error_type="llm")
        except QueryExecutionError as exc:
            return QueryResult(
                success=False,
                question=user_question,
                sql=locals().get("sql", ""),
                error=str(exc),
                error_type=self._database_error_type(exc.error_type),
                metadata=exc.metadata,
            )

    def run_stream(
        self,
        user_question: str,
        options: QueryOptions | None = None,
        security_context: UserContext | None = None,
        source_id: str | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        options = options or QueryOptions()
        runtime = self._get_runtime(source_id)
        parsed = runtime.parser.parse(user_question)
        if not runtime.parser.validate(parsed):
            yield {"event": "error", "data": {"error": "输入问题为空", "error_type": "validation"}}
            return
        try:
            yield {"event": "status", "data": {"stage": "schema_linking", "message": "正在检索表、字段与指标"}}
            linking = (
                runtime.schema_linker.link(user_question)
                if options.use_schema_linking
                else self._full_schema_fallback()
            )
            detected_indicators, indicator_context = self._resolve_indicator_context(
                runtime,
                user_question,
                options.use_indicator_knowledge,
                options.use_indicator_rag,
            )
            system_msg, prompt = build_prompt(
                user_question,
                linking["schema_context"],
                indicator_context,
                options.use_few_shot,
                options.use_rules,
                options.use_guards,
            )
            yield {"event": "status", "data": {"stage": "sql_generation", "message": "正在生成 SQL"}}
            raw_parts = []
            for token in runtime.llm.generate_sql_stream(system_msg, prompt):
                raw_parts.append(token)
                yield {"event": "sql_delta", "data": {"content": token}}
            sql = runtime.llm.extract_sql("".join(raw_parts))
            yield {"event": "sql", "data": {"sql": sql}}
            yield {"event": "status", "data": {"stage": "execution", "message": "正在执行安全查询"}}
            sql_attempts = 1
            while True:
                try:
                    columns, rows = runtime.db.execute(sql, security_context)
                    break
                except QueryExecutionError as exc:
                    repair_count = sql_attempts - 1
                    if (
                        exc.error_type != "sql_syntax"
                        or repair_count >= runtime.db.config.runtime.sql_retry_count
                    ):
                        raise
                    yield {
                        "event": "status",
                        "data": {
                            "stage": "sql_repair",
                            "message": f"SQL 执行失败，正在进行第 {repair_count + 1} 次修复",
                        },
                    }
                    sql = runtime.llm.repair_sql(
                        user_question,
                        sql,
                        f"{exc.error_type}: {exc}",
                        prompt,
                    )
                    sql_attempts += 1
                    yield {"event": "sql", "data": {"sql": sql, "attempt": sql_attempts}}
            result = QueryResult(
                success=True,
                question=user_question,
                sql=sql,
                columns=columns,
                rows=rows,
                formatted=runtime.formatter.format(columns, rows),
                metadata={
                    "model": runtime.llm.model,
                    "source_id": runtime.source_id,
                    "selected_tables": linking["selected_tables"],
                    "matched_indicators": detected_indicators,
                    "sql_attempts": sql_attempts,
                },
            )
            yield {"event": "result", "data": result.model_dump()}
        except (LLMError, QueryExecutionError) as exc:
            yield {
                "event": "error",
                "data": {
                    "error": str(exc),
                    "error_type": (
                        self._database_error_type(exc.error_type)
                        if isinstance(exc, QueryExecutionError)
                        else "llm"
                    ),
                },
            }
        finally:
            yield {"event": "done", "data": {}}

    @staticmethod
    def _full_schema_fallback() -> dict:
        from schema_metadata import FIELD_METADATA

        lines = ["【完整 Schema】"] + [f"- {key}: {description}" for key, description in FIELD_METADATA.items()]
        return {
            "selected_tables": sorted({key.split(".")[0] for key in FIELD_METADATA}),
            "fields": [],
            "join_plan": {},
            "schema_context": "\n".join(lines),
        }

    def close(self) -> None:
        closed: set[int] = set()
        for runtime in self._runtimes.values():
            if id(runtime) not in closed:
                runtime.close()
                closed.add(id(runtime))
