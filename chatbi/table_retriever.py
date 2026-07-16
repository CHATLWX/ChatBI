from __future__ import annotations

from config import AppConfig, settings
from index_builder import ensure_indexes
from milvus_store import get_vectorstore


class TableRetriever:
    def __init__(self, config: AppConfig = settings):
        self.config = config
        ensure_indexes(config)
        self.vectorstore = get_vectorstore("tables", config)

    def retrieve(self, query: str, top_k: int | None = None, score_threshold: float | None = None) -> list[dict]:
        k = top_k or self.config.retrieval.table_top_k
        threshold = score_threshold if score_threshold is not None else self.config.retrieval.table_score_threshold
        results = self.vectorstore.similarity_search_with_relevance_scores(query, k=k)
        output, seen = [], set()
        for document, score in results:
            table_name = document.metadata.get("table_name")
            if not table_name or table_name in seen or score < threshold:
                continue
            seen.add(table_name)
            output.append({"table_name": table_name, "score": score, "description": document.page_content, "metadata": document.metadata})
        return output

    def close(self) -> None:
        self.vectorstore.close()
