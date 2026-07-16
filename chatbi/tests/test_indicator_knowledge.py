from indicator_knowledge import IndicatorKnowledge


def test_profit_injects_one_level_dependencies():
    context = IndicatorKnowledge().get_indicator_context("查询利润")
    assert "利润" in context["detected_indicators"]
    assert "毛利" in context["detected_indicators"]
    assert "期间费用" in context["detected_indicators"]
    assert "收入" not in context["detected_indicators"]
