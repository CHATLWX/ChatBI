from __future__ import annotations

from config import AppConfig, settings
from indicator_metadata import INDICATOR_CATALOG, IndicatorCatalog
from obsidian_indicator_store import ObsidianIndicatorStore


class IndicatorKnowledge:
    """Local fallback plus Obsidian-backed metric detection and dependency resolution."""

    def __init__(
        self,
        config: AppConfig = settings,
        store: ObsidianIndicatorStore | None = None,
    ):
        self.config = config
        self.store = store or ObsidianIndicatorStore(config)

    def _runtime_catalog(self) -> tuple[IndicatorCatalog, str]:
        return self.store.runtime_catalog(INDICATOR_CATALOG)

    def detect_indicators(self, question: str) -> list[str]:
        catalog, _ = self._runtime_catalog()
        return catalog.detect(question)

    @staticmethod
    def get_indicator_text(indicator_name: str, catalog: IndicatorCatalog) -> str:
        indicator = catalog.by_name.get(indicator_name)
        if not indicator:
            return ""
        lines = [
            f"指标：{indicator.name}",
            f"  层级：{indicator.level}",
            f"  定义：{indicator.definition}",
            f"  计算公式：{indicator.formula}",
            f"  数据来源：{', '.join(indicator.data_source)}",
            f"  时间字段：{indicator.time_field}",
        ]
        if indicator.depends_on:
            lines.append(f"  依赖指标：{', '.join(indicator.depends_on)}")
        if indicator.filters:
            lines.append(f"  强制过滤：{' AND '.join(indicator.filters)}")
        if indicator.notes:
            lines.append(f"  注意：{indicator.notes}")
        return "\n".join(lines)

    @staticmethod
    def get_dependency_text(indicator_name: str, catalog: IndicatorCatalog) -> str:
        """Compact dependency context; full lineage stays in response metadata."""
        indicator = catalog.by_name.get(indicator_name)
        if not indicator:
            return ""
        return "\n".join(
            [
                f"依赖指标：{indicator.name}",
                f"  计算公式：{indicator.formula}",
                f"  强制过滤：{' AND '.join(indicator.filters) or '无'}",
            ]
        )

    def get_indicator_context(self, question: str) -> dict:
        catalog, source = self._runtime_catalog()
        detected = catalog.detect(question)
        if not detected:
            return {
                "detected_indicators": [],
                "indicator_block": "",
                "indicator_source": source,
                "dependency_graph": {},
            }

        resolved = catalog.resolve_dependencies(detected, recursive=True)
        root_names = set(detected)
        blocks = [f"【指标知识｜来源：{source}】"]
        for item in resolved:
            if item.indicator.name in root_names:
                blocks.append(self.get_indicator_text(item.indicator.name, catalog))
            else:
                blocks.append(self.get_dependency_text(item.indicator.name, catalog))
        names = [item.indicator.name for item in resolved]
        return {
            "detected_indicators": names,
            "indicator_block": "\n\n".join(blocks),
            "indicator_source": source,
            "dependency_graph": catalog.dependency_graph(names),
            "dependency_paths": {
                item.indicator.name: list(item.dependency_path)
                for item in resolved
            },
        }
