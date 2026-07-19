from __future__ import annotations

from dataclasses import dataclass

from config import AppConfig, settings
from database import DatabaseClient
from indicator_knowledge import IndicatorKnowledge
from indicator_retriever import IndicatorRetriever
from llm_client import LLMClient
from obsidian_indicator_store import ObsidianIndicatorStore
from query_parser import QueryParser
from result_formatter import ResultFormatter
from schema_linking import SchemaLinkingPipeline


@dataclass
class AppRuntime:
    source_id: str
    parser: QueryParser
    llm: LLMClient
    db: DatabaseClient
    formatter: ResultFormatter
    schema_linker: SchemaLinkingPipeline
    indicator_knowledge: IndicatorKnowledge
    indicator_retriever: IndicatorRetriever

    def close(self) -> None:
        self.db.connection_pool.close()
        self.schema_linker.close()
        self.indicator_retriever.close()


def build_runtime(
    app_config: AppConfig = settings,
    source_id: str | None = None,
) -> AppRuntime:
    resolved_config = app_config.for_source(source_id)
    indicator_store = ObsidianIndicatorStore(resolved_config)
    return AppRuntime(
        source_id=resolved_config.data_source_name,
        parser=QueryParser(),
        llm=LLMClient(resolved_config),
        db=DatabaseClient(resolved_config),
        formatter=ResultFormatter(),
        schema_linker=SchemaLinkingPipeline(resolved_config),
        indicator_knowledge=IndicatorKnowledge(resolved_config, indicator_store),
        indicator_retriever=IndicatorRetriever(resolved_config, indicator_store),
    )
