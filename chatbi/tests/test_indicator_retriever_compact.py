from config import ObsidianConfig, settings
from indicator_metadata import INDICATOR_CATALOG
from indicator_retriever import IndicatorRetriever
from obsidian_indicator_store import ObsidianIndicatorStore


class EmptyVectorStore:
    def similarity_search_with_relevance_scores(self, _query, k):
        assert k > 0
        return []


def _retriever(tmp_path):
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
    retriever = object.__new__(IndicatorRetriever)
    retriever.config = config
    retriever.store = store
    retriever.vectorstore = EmptyVectorStore()
    retriever.last_resolution = {}
    return retriever


def test_dependencies_use_compact_prompt_but_keep_full_lineage_metadata(tmp_path):
    retriever = _retriever(tmp_path)

    block, indicators = retriever.build_knowledge_block("查询上个月利润")
    by_name = {item["name"]: item for item in indicators}

    assert "指标：利润" in block
    assert "定义：毛利减期间费用" in block
    assert "依赖指标：毛利" in block
    assert "依赖指标：收入" in block
    assert "定义：销售收入减销售成本" not in block
    assert "依赖路径：" not in block
    assert by_name["利润"]["query_root"] is True
    assert by_name["毛利"]["query_root"] is False
    assert retriever.last_resolution["dependency_paths"]["收入"] == ["利润", "毛利", "收入"]


def test_explicit_metric_remains_full_even_if_also_reached_as_dependency(tmp_path):
    retriever = _retriever(tmp_path)

    block, indicators = retriever.build_knowledge_block("查询利润率和毛利")
    by_name = {item["name"]: item for item in indicators}

    assert by_name["毛利"]["query_root"] is True
    assert "指标：毛利" in block
    assert "定义：销售收入减销售成本" in block
