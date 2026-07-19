import copy

import pytest

from indicator_metadata import INDICATOR_CATALOG, IndicatorCatalog


def test_catalog_resolves_transitive_dependency_paths():
    resolved = INDICATOR_CATALOG.resolve_dependencies(["利润率"])
    by_name = {item.indicator.name: item for item in resolved}

    assert by_name["销售成本"].dependency_path == ("利润率", "利润", "毛利", "销售成本")
    assert by_name["期间费用"].depth == 2
    assert by_name["收入"].depth >= 1


def test_catalog_rejects_dependency_cycles():
    payload = copy.deepcopy(INDICATOR_CATALOG.to_dict())
    revenue = next(item for item in payload["indicators"] if item["name"] == "收入")
    revenue["depends_on"] = ["利润率"]

    with pytest.raises(ValueError, match="循环"):
        IndicatorCatalog.from_dict(payload)


def test_expense_rates_have_explicit_numerator_dependencies():
    assert INDICATOR_CATALOG.by_name["研发费用率"].depends_on == ("研发费用", "收入")
    assert INDICATOR_CATALOG.by_name["销售费用率"].depends_on == ("销售费用", "收入")
