import json

from config import ObsidianConfig, settings
from indicator_metadata import INDICATOR_CATALOG
from obsidian_indicator_store import ObsidianIndicatorStore


def _configured_store(tmp_path):
    config = settings.model_copy(
        update={
            "obsidian": ObsidianConfig(
                vault_path=str(tmp_path),
                indicator_folder="ChatBI指标知识库",
                auto_discover=False,
                runtime_preferred=True,
            )
        }
    )
    return ObsidianIndicatorStore(config)


def test_sync_generates_graph_links_and_runtime_catalog(tmp_path):
    store = _configured_store(tmp_path)
    result = store.sync_catalog(INDICATOR_CATALOG, overwrite=True)

    profit_note = store.note_path("利润").read_text(encoding="utf-8")
    overview = store.overview_path.read_text(encoding="utf-8")
    catalog, source = store.runtime_catalog()

    assert result["indicator_count"] == 15
    assert "- [[毛利]]" in profit_note
    assert "- [[期间费用]]" in profit_note
    assert "[[指标/利润|利润]]" in overview
    assert source.startswith("Obsidian:")
    assert catalog.by_name["利润"].depends_on == ("毛利", "期间费用")


def test_runtime_reads_frontmatter_edits_from_obsidian(tmp_path):
    store = _configured_store(tmp_path)
    store.sync_catalog(INDICATOR_CATALOG, overwrite=True)
    note_path = store.note_path("收入")
    original = note_path.read_text(encoding="utf-8")
    note_path.write_text(
        original.replace(
            "definition: 已完成订单的不含税销售收入，按订单月份和币种汇率折算为人民币。",
            "definition: Obsidian 中维护的新收入口径。",
        ),
        encoding="utf-8",
    )

    catalog, source = store.runtime_catalog()

    assert source.startswith("Obsidian:")
    assert catalog.by_name["收入"].definition == "Obsidian 中维护的新收入口径。"


def test_standalone_vault_uses_vault_root_without_nested_folder(tmp_path):
    config = settings.model_copy(
        update={
            "obsidian": ObsidianConfig(
                vault_path=str(tmp_path / "ChatBI指标知识库"),
                indicator_folder=".",
                auto_discover=False,
                runtime_preferred=True,
            )
        }
    )
    store = ObsidianIndicatorStore(config)
    store.sync_catalog(INDICATOR_CATALOG, overwrite=True)

    assert store.root == store.vault_path
    assert (store.vault_path / ".obsidian" / "app.json").exists()
    assert (store.vault_path / "指标" / "利润.md").exists()
    assert not (store.vault_path / "ChatBI指标知识库").exists()


def test_registers_standalone_vault_without_replacing_existing_vaults(tmp_path):
    store = _configured_store(tmp_path / "standalone")
    store.sync_catalog(INDICATOR_CATALOG, overwrite=True)
    registry = tmp_path / "obsidian.json"
    registry.write_text(
        '{"vaults":{"existing":{"path":"C:/notes","ts":1,"open":true}}}',
        encoding="utf-8",
    )

    registration = store.register_vault(registry)
    payload = json.loads(registry.read_text(encoding="utf-8"))

    assert "existing" in payload["vaults"]
    assert registration["vault_id"] in payload["vaults"]
    assert payload["vaults"][registration["vault_id"]]["path"] == str(store.vault_path)
