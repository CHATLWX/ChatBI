from __future__ import annotations

from config import AppConfig, settings
from index_builder import ensure_indexes
from milvus_store import get_vectorstore
from schema_metadata import FIELD_METADATA, FIELD_RULES


class FieldMatcher:
    def __init__(self, config: AppConfig = settings):
        self.config = config
        ensure_indexes(config)
        self.vectorstore = get_vectorstore("fields", config)

    def match(
        self,
        query: str,
        candidate_tables: list[str] | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> list[dict]:
        k = top_k or self.config.retrieval.field_top_k
        threshold = score_threshold if score_threshold is not None else self.config.retrieval.field_score_threshold
        rule_weight = self.config.retrieval.field_rule_weight
        force_include, force_exclude, reasons = self._active_rules(query)
        results = self.vectorstore.similarity_search_with_relevance_scores(query, k=max(k * 3, len(FIELD_METADATA)))
        scored, seen = [], set()
        for document, embedding_score in results:
            field_key = document.metadata.get("field_key")
            table_name = document.metadata.get("table_name")
            if not field_key or field_key in seen or (candidate_tables and table_name not in candidate_tables):
                continue
            seen.add(field_key)
            rule_score = 1.0 if field_key in force_include else -1.0 if field_key in force_exclude else 0.0
            final_score = (1 - rule_weight) * embedding_score + rule_weight * rule_score
            if final_score >= threshold or field_key in force_include:
                scored.append(
                    {
                        "field_key": field_key,
                        "table_name": table_name,
                        "field_name": document.metadata.get("field_name"),
                        "embedding_score": embedding_score,
                        "rule_score": rule_score,
                        "score": final_score,
                        "rule_applied": reasons.get(field_key, ""),
                        "description": FIELD_METADATA.get(field_key, document.page_content),
                    }
                )
        for field_key in force_include - seen:
            table_name, field_name = field_key.split(".", 1)
            if not candidate_tables or table_name in candidate_tables:
                scored.append(
                    {
                        "field_key": field_key,
                        "table_name": table_name,
                        "field_name": field_name,
                        "embedding_score": 0.0,
                        "rule_score": 1.0,
                        "score": rule_weight,
                        "rule_applied": reasons.get(field_key, "强制包含"),
                        "description": FIELD_METADATA[field_key],
                    }
                )
        return sorted(scored, key=lambda item: item["score"], reverse=True)[:k]

    @staticmethod
    def _active_rules(query: str) -> tuple[set[str], set[str], dict[str, str]]:
        include, exclude, reasons = set(), set(), {}
        for rule in FIELD_RULES:
            if not any(keyword in query for keyword in rule["trigger_keywords"]):
                continue
            for key in rule.get("force_include", []):
                include.add(key)
                reasons[key] = rule["reason"]
            for key in rule.get("force_exclude", []):
                exclude.add(key)
                reasons[key] = rule["reason"]
        exclude -= include
        return include, exclude, reasons

    def close(self) -> None:
        self.vectorstore.close()
