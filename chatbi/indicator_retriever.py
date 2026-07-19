from __future__ import annotations

from config import AppConfig, settings
from index_builder import ensure_indexes
from indicator_metadata import INDICATOR_CATALOG
from milvus_store import get_vectorstore
from obsidian_indicator_store import ObsidianIndicatorStore


class IndicatorRetriever:
    def __init__(
        self,
        config: AppConfig = settings,
        store: ObsidianIndicatorStore | None = None,
    ):
        self.config = config
        self.store = store or ObsidianIndicatorStore(config)
        ensure_indexes(config)
        self.vectorstore = get_vectorstore("indicators", config)
        self.last_resolution: dict = {}

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        score_threshold: float | None = None,
        expand_dependencies: bool = True,
    ) -> list[dict]:
        catalog, source = self.store.runtime_catalog(INDICATOR_CATALOG)
        k = top_k or self.config.retrieval.indicator_top_k
        threshold = score_threshold if score_threshold is not None else self.config.retrieval.indicator_score_threshold

        root_scores: dict[str, float] = {}
        root_methods: dict[str, str] = {}
        for name in catalog.detect(query):
            root_scores[name] = 1.0
            root_methods[name] = "obsidian-alias"

        results = self.vectorstore.similarity_search_with_relevance_scores(query, k=k)
        for document, score in results:
            name = document.metadata.get("indicator_name")
            if not name or score < threshold or name not in catalog.by_name:
                continue
            if score > root_scores.get(name, -1.0):
                root_scores[name] = score
                root_methods[name] = "milvus-semantic"

        resolved = catalog.resolve_dependencies(
            root_scores,
            recursive=expand_dependencies,
        )
        matched: list[dict] = []
        for item in resolved:
            value = item.to_dict()
            is_query_root = item.indicator.name in root_scores
            value.update(
                {
                    "score": root_scores.get(item.indicator.name, 0.0) if is_query_root else 0.0,
                    "match_method": root_methods.get(item.indicator.name, "obsidian-dependency"),
                    "dependency_expanded": not is_query_root,
                    "query_root": is_query_root,
                    "knowledge_source": source,
                    "obsidian_note": str(self.store.note_path(item.indicator.name)),
                    "obsidian_uri": self.store.obsidian_uri(f"指标/{item.indicator.name}"),
                }
            )
            matched.append(value)

        self.last_resolution = {
            "source": source,
            "roots": list(root_scores),
            "resolved": [item.indicator.name for item in resolved],
            "dependency_graph": catalog.dependency_graph(item.indicator.name for item in resolved),
            "dependency_paths": {
                item.indicator.name: list(item.dependency_path)
                for item in resolved
            },
            "knowledge_root": str(self.store.root),
        }
        return matched

    def build_knowledge_block(self, query: str) -> tuple[str, list[dict]]:
        indicators = self.retrieve(query)
        if not indicators:
            return "", []
        source = indicators[0]["knowledge_source"]
        lines = [f"【指标知识｜来源：{source}】"]
        for item in indicators:
            if item["query_root"]:
                lines.extend(
                    [
                        f"指标：{item['name']}",
                        f"  层级：{item['level']}",
                        f"  定义：{item['definition']}",
                        f"  计算公式：{item['formula']}",
                        f"  直接依赖：{', '.join(item['depends_on']) or '无'}",
                        f"  数据来源：{', '.join(item['data_source'])}",
                        f"  时间字段：{item['time_field']}",
                        f"  强制过滤：{', '.join(item['filters']) or '无'}",
                        f"  注意：{item['notes']}",
                    ]
                )
            else:
                lines.extend(
                    [
                        f"依赖指标：{item['name']}",
                        f"  计算公式：{item['formula']}",
                        f"  强制过滤：{', '.join(item['filters']) or '无'}",
                    ]
                )
        return "\n".join(lines), indicators

    def close(self) -> None:
        self.vectorstore.close()
