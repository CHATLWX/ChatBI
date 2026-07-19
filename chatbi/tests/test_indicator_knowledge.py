from config import ObsidianConfig, settings
from indicator_knowledge import IndicatorKnowledge
from indicator_metadata import INDICATOR_CATALOG
from obsidian_indicator_store import ObsidianIndicatorStore


def _store(tmp_path):
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
    store = ObsidianIndicatorStore(config)
    store.sync_catalog(INDICATOR_CATALOG, overwrite=True)
    return config, store


def test_profit_injects_all_recursive_dependencies_from_obsidian(tmp_path):
    config, store = _store(tmp_path)
    context = IndicatorKnowledge(config, store).get_indicator_context("查询利润")

    assert context["detected_indicators"] == [
        "利润",
        "毛利",
        "收入",
        "销售成本",
        "期间费用",
    ]
    assert context["indicator_source"].startswith("Obsidian:")
    assert context["dependency_graph"]["利润"] == ["毛利", "期间费用"]
    assert context["dependency_paths"]["收入"] == ["利润", "毛利", "收入"]
    assert "指标：利润" in context["indicator_block"]
    assert "依赖指标：毛利" in context["indicator_block"]
    assert "定义：销售收入减销售成本" not in context["indicator_block"]
    assert context["indicator_block"].count("  数据来源：") == 1


def test_longest_alias_wins_for_overlapping_indicator_names(tmp_path):
    config, store = _store(tmp_path)
    knowledge = IndicatorKnowledge(config, store)

    assert knowledge.detect_indicators("查询上个月利润率") == ["利润率"]
