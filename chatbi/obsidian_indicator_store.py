from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import yaml

from config import AppConfig, settings
from indicator_metadata import INDICATOR_CATALOG, IndicatorCatalog, IndicatorDefinition


class ObsidianIndicatorStore:
    """Synchronize metric definitions to Obsidian and load them back at query time."""

    def __init__(self, config: AppConfig = settings):
        self.config = config
        self.vault_path = self._resolve_vault_path()
        indicator_folder = config.obsidian.indicator_folder.strip()
        self.root = (
            self.vault_path
            if indicator_folder in {"", ".", "/", "\\"}
            else self.vault_path / indicator_folder
        )
        self.indicator_dir = self.root / "指标"
        self.snapshot_path = self.root / "indicators.json"
        self.overview_path = self.root / "指标关系总览.md"
        self._cached_catalog: IndicatorCatalog | None = None
        self._cached_fingerprint: tuple | None = None
        self.last_error = ""

    @property
    def is_available(self) -> bool:
        return self.vault_path.is_dir() and self.indicator_dir.is_dir()

    @property
    def source_label(self) -> str:
        return f"Obsidian:{self.root}"

    def sync_catalog(self, catalog: IndicatorCatalog = INDICATOR_CATALOG, *, overwrite: bool = False) -> dict:
        self.vault_path.mkdir(parents=True, exist_ok=True)
        # A dedicated .obsidian directory makes this folder an independent vault.
        obsidian_config_dir = self.vault_path / ".obsidian"
        obsidian_config_dir.mkdir(exist_ok=True)
        app_config_path = obsidian_config_dir / "app.json"
        if not app_config_path.exists():
            app_config_path.write_text("{}\n", encoding="utf-8")
        self.indicator_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_path.write_text(
            json.dumps(catalog.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        written: list[Path] = []
        preserved: list[Path] = []
        for indicator in catalog.definitions:
            path = self.indicator_dir / f"{indicator.name}.md"
            if path.exists() and not overwrite:
                preserved.append(path)
                continue
            path.write_text(self._render_note(indicator, catalog), encoding="utf-8")
            written.append(path)

        if overwrite or not self.overview_path.exists():
            self.overview_path.write_text(self._render_overview(catalog), encoding="utf-8")
            written.append(self.overview_path)

        self._cached_catalog = None
        self._cached_fingerprint = None
        return {
            "vault_path": str(self.vault_path),
            "knowledge_root": str(self.root),
            "written": [str(path) for path in written],
            "preserved": [str(path) for path in preserved],
            "indicator_count": len(catalog.definitions),
            "obsidian_uri": self.obsidian_uri("指标关系总览"),
        }

    def load_catalog(self) -> IndicatorCatalog:
        fingerprint = self._fingerprint()
        if self._cached_catalog is not None and fingerprint == self._cached_fingerprint:
            return self._cached_catalog
        if not self.snapshot_path.exists() or not self.indicator_dir.is_dir():
            raise FileNotFoundError(f"Obsidian 指标知识库尚未导入：{self.root}")

        snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        expected_names = [str(item["name"]) for item in snapshot.get("indicators", [])]
        records: list[dict] = []
        for name in expected_names:
            note_path = self.indicator_dir / f"{name}.md"
            if not note_path.exists():
                raise FileNotFoundError(f"Obsidian 指标笔记缺失：{note_path}")
            frontmatter = self._read_frontmatter(note_path)
            if not frontmatter.get("chatbi_indicator"):
                raise ValueError(f"不是 ChatBI 指标笔记：{note_path}")
            records.append(self._frontmatter_to_record(frontmatter))

        catalog = IndicatorCatalog.from_dict(
            {"version": int(snapshot.get("version", 1)), "indicators": records}
        )
        self._cached_catalog = catalog
        self._cached_fingerprint = fingerprint
        self.last_error = ""
        return catalog

    def runtime_catalog(self, fallback: IndicatorCatalog = INDICATOR_CATALOG) -> tuple[IndicatorCatalog, str]:
        if not self.config.obsidian.runtime_preferred:
            return fallback, "project-json"
        try:
            return self.load_catalog(), self.source_label
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError) as exc:
            self.last_error = str(exc)
            return fallback, "project-json-fallback"

    def note_path(self, indicator_name: str) -> Path:
        return self.indicator_dir / f"{indicator_name}.md"

    def obsidian_uri(self, note_name: str) -> str:
        indicator_folder = self.config.obsidian.indicator_folder.strip().strip("/\\")
        relative = f"{indicator_folder}/{note_name}" if indicator_folder not in {"", "."} else note_name
        return f"obsidian://open?vault={quote(self.vault_path.name)}&file={quote(relative)}"

    def register_vault(self, registry_path: str | Path | None = None) -> dict:
        """Register the standalone folder in Obsidian's vault switcher without opening it."""
        appdata = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
        path = Path(registry_path) if registry_path else appdata / "obsidian" / "obsidian.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"vaults": {}}
        vaults = payload.setdefault("vaults", {})
        target = str(self.vault_path.resolve())

        vault_id = ""
        for candidate_id, candidate in vaults.items():
            candidate_path = Path(str(candidate.get("path", "")))
            try:
                is_same = candidate_path.resolve() == self.vault_path.resolve()
            except OSError:
                is_same = str(candidate_path).casefold() == target.casefold()
            if is_same:
                vault_id = candidate_id
                break
        if not vault_id:
            vault_id = hashlib.sha1(target.casefold().encode("utf-8")).hexdigest()[:16]

        previous = vaults.get(vault_id, {})
        vaults[vault_id] = {
            "path": target,
            "ts": int(time.time() * 1000),
            "open": bool(previous.get("open", False)),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return {"vault_id": vault_id, "registry_path": str(path), "vault_path": target}

    def _resolve_vault_path(self) -> Path:
        configured = self.config.obsidian.vault_path.strip()
        if configured:
            return Path(configured).expanduser().resolve()
        if self.config.obsidian.auto_discover:
            discovered = self.discover_open_vault()
            if discovered is not None:
                return discovered
        return Path(__file__).with_name("obsidian_vault").resolve()

    @staticmethod
    def discover_open_vault() -> Path | None:
        appdata = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
        config_path = appdata / "obsidian" / "obsidian.json"
        if not config_path.exists():
            return None
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        vaults = payload.get("vaults", {})
        candidates = sorted(
            vaults.values(),
            key=lambda value: (bool(value.get("open")), int(value.get("ts", 0))),
            reverse=True,
        )
        for candidate in candidates:
            path = Path(str(candidate.get("path", ""))).expanduser()
            if path.is_dir():
                return path.resolve()
        return None

    def _fingerprint(self) -> tuple:
        paths = [self.snapshot_path]
        if self.snapshot_path.exists():
            try:
                snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
                paths.extend(
                    self.indicator_dir / f"{item['name']}.md"
                    for item in snapshot.get("indicators", [])
                )
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                pass
        return tuple(
            (str(path), path.stat().st_mtime_ns, path.stat().st_size)
            if path.exists()
            else (str(path), None, None)
            for path in paths
        )

    @staticmethod
    def _read_frontmatter(path: Path) -> dict:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError(f"指标笔记缺少 YAML frontmatter：{path}")
        try:
            raw = text.split("---\n", 2)[1]
        except IndexError as exc:
            raise ValueError(f"指标笔记 frontmatter 未闭合：{path}") from exc
        value = yaml.safe_load(raw) or {}
        if not isinstance(value, dict):
            raise ValueError(f"指标笔记 frontmatter 必须是对象：{path}")
        return value

    @staticmethod
    def _frontmatter_to_record(frontmatter: dict) -> dict:
        return {
            "id": frontmatter["indicator_id"],
            "name": frontmatter["indicator_name"],
            "level": frontmatter["level"],
            "aliases": frontmatter.get("aliases", []),
            "definition": frontmatter.get("definition", ""),
            "formula": frontmatter.get("formula", ""),
            "sql_template": frontmatter.get("sql_template", ""),
            "data_source": frontmatter.get("data_source", []),
            "depends_on": frontmatter.get("depends_on", []),
            "time_field": frontmatter.get("time_field", ""),
            "filters": frontmatter.get("filters", []),
            "unit": frontmatter.get("unit", ""),
            "notes": frontmatter.get("notes", ""),
        }

    def _render_note(self, indicator: IndicatorDefinition, catalog: IndicatorCatalog) -> str:
        frontmatter = {
            "chatbi_indicator": True,
            "indicator_id": indicator.id,
            "indicator_name": indicator.name,
            "level": indicator.level,
            "aliases": list(indicator.aliases),
            "definition": indicator.definition,
            "formula": indicator.formula,
            "sql_template": indicator.sql_template,
            "data_source": list(indicator.data_source),
            "depends_on": list(indicator.depends_on),
            "time_field": indicator.time_field,
            "filters": list(indicator.filters),
            "unit": indicator.unit,
            "notes": indicator.notes,
            "tags": ["chatbi/indicator", f"chatbi/indicator/{indicator.level}"],
        }
        yaml_text = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
        dependencies = "\n".join(f"- [[{name}]]" for name in indicator.depends_on) or "- 无（原子指标）"
        dependents = "\n".join(f"- [[{name}]]" for name in catalog.dependents_of(indicator.name)) or "- 无"
        sources = "\n".join(f"- `{name}`" for name in indicator.data_source) or "- 无"
        filters = "\n".join(f"- `{value}`" for value in indicator.filters) or "- 无"
        return (
            f"---\n{yaml_text}\n---\n\n"
            f"# {indicator.name}\n\n"
            f"> {indicator.definition}\n\n"
            f"- 指标层级：`{indicator.level}`\n"
            f"- 计量单位：`{indicator.unit or '未定义'}`\n"
            f"- 时间字段：`{indicator.time_field or '未定义'}`\n\n"
            f"## 计算口径\n\n`{indicator.formula}`\n\n"
            f"## 依赖指标\n\n{dependencies}\n\n"
            f"## 被依赖指标\n\n{dependents}\n\n"
            f"## 数据来源\n\n{sources}\n\n"
            f"## 强制过滤\n\n{filters}\n\n"
            f"## SQL 模板\n\n```sql\n{indicator.sql_template}\n```\n\n"
            f"## 注意事项\n\n{indicator.notes or '无'}\n"
        )

    def _render_overview(self, catalog: IndicatorCatalog) -> str:
        groups: dict[str, list[IndicatorDefinition]] = {}
        for indicator in catalog.definitions:
            groups.setdefault(indicator.level, []).append(indicator)
        sections = [
            "---",
            "tags:",
            "  - chatbi/indicator-map",
            "---",
            "",
            "# ChatBI 指标关系总览",
            "",
            "> 每条 `[[指标链接]]` 都会成为 Obsidian Graph View 中的一条关系边；查询运行时读取各笔记的 frontmatter 并递归检查依赖。",
            "",
        ]
        for level, indicators in groups.items():
            sections.extend([f"## {level}", ""])
            for indicator in indicators:
                dependencies = "、".join(f"[[指标/{name}|{name}]]" for name in indicator.depends_on)
                suffix = f" → 依赖：{dependencies}" if dependencies else ""
                sections.append(f"- [[指标/{indicator.name}|{indicator.name}]]{suffix}")
            sections.append("")
        return "\n".join(sections).rstrip() + "\n"


def _main() -> int:
    parser = argparse.ArgumentParser(description="ChatBI 指标 JSON 与 Obsidian 同步工具")
    parser.add_argument("command", choices=("sync", "status"))
    parser.add_argument("--force", action="store_true", help="覆盖已有指标笔记")
    parser.add_argument("--register-vault", action="store_true", help="注册到 Obsidian vault 列表")
    args = parser.parse_args()
    store = ObsidianIndicatorStore(settings)
    if args.command == "sync":
        result = store.sync_catalog(INDICATOR_CATALOG, overwrite=args.force)
        if args.register_vault:
            result["registration"] = store.register_vault()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    catalog, source = store.runtime_catalog()
    print(
        json.dumps(
            {
                "source": source,
                "vault_path": str(store.vault_path),
                "knowledge_root": str(store.root),
                "indicator_count": len(catalog.definitions),
                "last_error": store.last_error,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
