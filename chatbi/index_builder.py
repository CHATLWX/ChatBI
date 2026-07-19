from __future__ import annotations

import json

from langchain_core.documents import Document

from config import AppConfig, settings
from indicator_metadata import INDICATOR_DEFINITIONS
from milvus_store import chunk_text, inspect_collections, rebuild_collection
from schema_metadata import FIELD_METADATA, TABLE_METADATA


def build_table_index(config: AppConfig = settings) -> int:
    documents, ids = [], []
    for table_name, meta in TABLE_METADATA.items():
        text = f"表名：{table_name}\n业务域：{meta['domain']}\n描述：{meta['description']}\n关键字段：{meta['key_fields']}"
        for index, chunk in enumerate(chunk_text(text, config.llm.chunk_size, config.llm.chunk_overlap)):
            ids.append(f"table::{table_name}::{index}")
            documents.append(Document(page_content=chunk, metadata={"table_name": table_name, "domain": meta["domain"], "doc_type": "table"}))
    rebuild_collection("tables", documents, ids, config)
    return len(documents)


def build_field_index(config: AppConfig = settings) -> int:
    documents, ids = [], []
    for field_key, description in FIELD_METADATA.items():
        table_name, field_name = field_key.split(".", 1)
        text = f"字段：{field_key}\n业务描述：{description}"
        for index, chunk in enumerate(chunk_text(text, config.llm.chunk_size, config.llm.chunk_overlap)):
            ids.append(f"field::{field_key}::{index}")
            documents.append(Document(page_content=chunk, metadata={"table_name": table_name, "field_name": field_name, "field_key": field_key, "doc_type": "field"}))
    rebuild_collection("fields", documents, ids, config)
    return len(documents)


def build_indicator_index(config: AppConfig = settings) -> int:
    documents, ids = [], []
    for indicator in INDICATOR_DEFINITIONS:
        text = (
            f"指标：{indicator['name']}（{', '.join(indicator['aliases'])}）\n"
            f"层级：{indicator['level']}\n定义：{indicator['definition']}\n"
            f"计算公式：{indicator['formula']}\n注意：{indicator['notes']}"
        )
        for index, chunk in enumerate(chunk_text(text, config.llm.chunk_size, config.llm.chunk_overlap)):
            ids.append(f"indicator::{indicator['name']}::{index}")
            documents.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "indicator_name": indicator["name"],
                        "level": indicator["level"],
                        "depends_on": json.dumps(indicator["depends_on"], ensure_ascii=False),
                        "doc_type": "indicator",
                    },
                )
            )
    rebuild_collection("indicators", documents, ids, config)
    return len(documents)


def ensure_indexes(config: AppConfig = settings, force_rebuild: bool = False) -> dict[str, int]:
    health = inspect_collections(config)
    result = {}
    for kind, builder in (
        ("tables", build_table_index),
        ("fields", build_field_index),
        ("indicators", build_indicator_index),
    ):
        if force_rebuild or not health[kind]["healthy"]:
            result[kind] = builder(config)
        else:
            result[kind] = -1
    return result


if __name__ == "__main__":
    print(ensure_indexes(force_rebuild=True))
