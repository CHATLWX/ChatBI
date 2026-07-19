from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


INDICATOR_JSON_PATH = Path(__file__).with_name("indicators.json")


@dataclass(frozen=True)
class IndicatorDefinition:
    id: str
    name: str
    level: str
    aliases: tuple[str, ...]
    definition: str
    formula: str
    sql_template: str
    data_source: tuple[str, ...]
    depends_on: tuple[str, ...]
    time_field: str
    filters: tuple[str, ...]
    unit: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, value: dict) -> "IndicatorDefinition":
        return cls(
            id=str(value["id"]).strip(),
            name=str(value["name"]).strip(),
            level=str(value["level"]).strip(),
            aliases=tuple(str(item).strip() for item in value.get("aliases", []) if str(item).strip()),
            definition=str(value.get("definition", "")).strip(),
            formula=str(value.get("formula", "")).strip(),
            sql_template=str(value.get("sql_template", "")).strip(),
            data_source=tuple(str(item).strip() for item in value.get("data_source", []) if str(item).strip()),
            depends_on=tuple(str(item).strip() for item in value.get("depends_on", []) if str(item).strip()),
            time_field=str(value.get("time_field", "")).strip(),
            filters=tuple(str(item).strip() for item in value.get("filters", []) if str(item).strip()),
            unit=str(value.get("unit", "")).strip(),
            notes=str(value.get("notes", "")).strip(),
        )

    def to_dict(self) -> dict:
        value = asdict(self)
        for key in ("aliases", "data_source", "depends_on", "filters"):
            value[key] = list(value[key])
        return value


@dataclass(frozen=True)
class ResolvedIndicator:
    indicator: IndicatorDefinition
    root: str
    depth: int
    dependency_path: tuple[str, ...]

    def to_dict(self) -> dict:
        value = self.indicator.to_dict()
        value.update(
            {
                "dependency_expanded": self.depth > 0,
                "dependency_root": self.root,
                "dependency_depth": self.depth,
                "dependency_path": list(self.dependency_path),
            }
        )
        return value


class IndicatorCatalog:
    """Validated indicator catalog with deterministic detection and dependency traversal."""

    def __init__(self, indicators: Iterable[IndicatorDefinition], version: int = 1):
        self.version = version
        self.definitions = tuple(indicators)
        self.by_name = {item.name: item for item in self.definitions}
        self.by_id = {item.id: item for item in self.definitions}
        self.alias_map: dict[str, str] = {}
        self._validate()

    @classmethod
    def from_dict(cls, payload: dict) -> "IndicatorCatalog":
        records = payload.get("indicators", [])
        return cls(
            (IndicatorDefinition.from_dict(record) for record in records),
            version=int(payload.get("version", 1)),
        )

    @classmethod
    def from_json(cls, path: str | Path = INDICATOR_JSON_PATH) -> "IndicatorCatalog":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(payload)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "indicators": [item.to_dict() for item in self.definitions],
        }

    def as_dicts(self) -> list[dict]:
        return [item.to_dict() for item in self.definitions]

    def detect(self, question: str) -> list[str]:
        """Detect metric aliases while preferring the longest overlapping phrase."""
        text = question.casefold()
        candidates: list[tuple[int, int, str]] = []
        for alias, name in self.alias_map.items():
            start = text.find(alias)
            while start >= 0:
                candidates.append((start, start + len(alias), name))
                start = text.find(alias, start + 1)
        candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))

        occupied: list[tuple[int, int]] = []
        detected: list[str] = []
        for start, end, name in candidates:
            if any(start < used_end and end > used_start for used_start, used_end in occupied):
                continue
            occupied.append((start, end))
            if name not in detected:
                detected.append(name)
        return detected

    def resolve_dependencies(
        self,
        indicator_names: Iterable[str],
        *,
        recursive: bool = True,
    ) -> list[ResolvedIndicator]:
        """Return roots and dependencies with traceable paths, de-duplicated by metric name."""
        resolved: list[ResolvedIndicator] = []
        seen: set[str] = set()

        def visit(name: str, root: str, path: tuple[str, ...]) -> None:
            if name not in self.by_name:
                raise ValueError(f"指标 {root} 依赖未定义指标：{name}")
            if name in path:
                cycle = " -> ".join((*path, name))
                raise ValueError(f"指标依赖存在循环：{cycle}")
            current_path = (*path, name)
            if name not in seen:
                seen.add(name)
                resolved.append(
                    ResolvedIndicator(
                        indicator=self.by_name[name],
                        root=root,
                        depth=len(current_path) - 1,
                        dependency_path=current_path,
                    )
                )
            if recursive or len(current_path) == 1:
                for dependency in self.by_name[name].depends_on:
                    visit(dependency, root, current_path)

        for name in indicator_names:
            if name in self.by_name:
                visit(name, name, ())
        return resolved

    def dependency_graph(self, indicator_names: Iterable[str] | None = None) -> dict[str, list[str]]:
        names = list(indicator_names) if indicator_names is not None else list(self.by_name)
        return {
            name: list(self.by_name[name].depends_on)
            for name in names
            if name in self.by_name
        }

    def dependents_of(self, indicator_name: str) -> list[str]:
        return [
            item.name
            for item in self.definitions
            if indicator_name in item.depends_on
        ]

    def _validate(self) -> None:
        if not self.definitions:
            raise ValueError("指标目录不能为空")
        if len(self.by_name) != len(self.definitions):
            raise ValueError("指标名称必须唯一")
        if len(self.by_id) != len(self.definitions):
            raise ValueError("指标 id 必须唯一")

        for indicator in self.definitions:
            if not indicator.id or not indicator.name:
                raise ValueError("指标 id 和名称不能为空")
            for phrase in (indicator.name, *indicator.aliases):
                key = phrase.casefold()
                owner = self.alias_map.get(key)
                if owner and owner != indicator.name:
                    raise ValueError(f"指标别名冲突：{phrase} 同时属于 {owner} 和 {indicator.name}")
                self.alias_map[key] = indicator.name
            for dependency in indicator.depends_on:
                if dependency not in self.by_name:
                    raise ValueError(f"指标 {indicator.name} 依赖未定义指标：{dependency}")

        # A full traversal validates cycles even for indicators not queried at runtime.
        for indicator in self.definitions:
            self._validate_path(indicator.name, ())

    def _validate_path(self, name: str, path: tuple[str, ...]) -> None:
        if name in path:
            cycle = " -> ".join((*path, name))
            raise ValueError(f"指标依赖存在循环：{cycle}")
        for dependency in self.by_name[name].depends_on:
            self._validate_path(dependency, (*path, name))


INDICATOR_CATALOG = IndicatorCatalog.from_json()

# Backward-compatible views for existing Milvus indexing and prompt modules.
INDICATOR_DEFINITIONS = INDICATOR_CATALOG.as_dicts()
INDICATOR_BY_NAME = {item["name"]: item for item in INDICATOR_DEFINITIONS}
