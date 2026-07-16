from __future__ import annotations

from config import AppConfig, settings
from index_builder import ensure_indexes
from indicator_metadata import INDICATOR_BY_NAME
from milvus_store import get_vectorstore


class IndicatorRetriever:
    def __init__(self, config: AppConfig = settings):
        self.config = config
        ensure_indexes(config)
        self.vectorstore = get_vectorstore("indicators", config)

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        score_threshold: float | None = None,
        expand_dependencies: bool = True,
    ) -> list[dict]:
        k = top_k or self.config.retrieval.indicator_top_k
        threshold = score_threshold if score_threshold is not None else self.config.retrieval.indicator_score_threshold
        results = self.vectorstore.similarity_search_with_relevance_scores(query, k=k)
        matched, seen = [], set()
        for document, score in results:
            name = document.metadata.get("indicator_name")
            if not name or name in seen or score < threshold or name not in INDICATOR_BY_NAME:
                continue
            seen.add(name)
            item = dict(INDICATOR_BY_NAME[name])
            item.update({"score": score, "dependency_expanded": False})
            matched.append(item)
        if expand_dependencies:
            for item in list(matched):
                for dependency in item["depends_on"]:  # PDF: expand exactly one level
                    if dependency in seen or dependency not in INDICATOR_BY_NAME:
                        continue
                    seen.add(dependency)
                    dep = dict(INDICATOR_BY_NAME[dependency])
                    dep.update({"score": 0.0, "dependency_expanded": True})
                    matched.append(dep)
        return matched

    def build_knowledge_block(self, query: str) -> tuple[str, list[dict]]:
        indicators = self.retrieve(query)
        if not indicators:
            return "", []
        lines = ["【指标知识】"]
        for item in indicators:
            suffix = "（依赖指标）" if item["dependency_expanded"] else ""
            lines.extend(
                [
                    f"指标：{item['name']}{suffix}",
                    f"  层级：{item['level']}",
                    f"  定义：{item['definition']}",
                    f"  计算公式：{item['formula']}",
                    f"  数据来源：{', '.join(item['data_source'])}",
                    f"  时间字段：{item['time_field']}",
                    f"  强制过滤：{', '.join(item['filters']) or '无'}",
                    f"  注意：{item['notes']}",
                ]
            )
        return "\n".join(lines), indicators

    def close(self) -> None:
        self.vectorstore.close()
