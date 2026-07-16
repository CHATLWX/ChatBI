from __future__ import annotations

from config import AppConfig, settings
from field_matcher import FieldMatcher
from join_resolver import JoinResolver
from table_retriever import TableRetriever


class SchemaLinkingPipeline:
    def __init__(self, config: AppConfig = settings):
        self.config = config
        self.table_retriever = TableRetriever(config)
        self.field_matcher = FieldMatcher(config)
        self.join_resolver = JoinResolver()

    def link(self, query: str) -> dict:
        table_results = self.table_retriever.retrieve(query)
        tables = [item["table_name"] for item in table_results]
        field_results = self.field_matcher.match(query, tables)
        join_plan = self.join_resolver.resolve(query, tables)
        schema_lines = ["【动态 Schema】"]
        for table in tables:
            schema_lines.append(f"表：{table}")
            for field in field_results:
                if field["table_name"] == table:
                    schema_lines.append(f"- {field['field_name']}：{field['description']}")
        if join_plan["anchor_table"]:
            schema_lines.append(f"锚表：{join_plan['anchor_table']}")
        if join_plan["joins"]:
            schema_lines.append("Join 路径：")
            schema_lines.extend(f"- JOIN {item['table']} ON {item['condition']}" for item in join_plan["joins"])
        return {
            "tables": table_results,
            "selected_tables": tables,
            "fields": field_results,
            "join_plan": join_plan,
            "schema_context": "\n".join(schema_lines),
        }

    def close(self) -> None:
        self.table_retriever.close()
        self.field_matcher.close()
