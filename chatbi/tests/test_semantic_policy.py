import pytest

from field_matcher import FieldMatcher
from semantic_policy import SemanticPolicyError, apply_semantic_policy


def test_profit_by_sales_dimension_falls_back_to_gross_profit():
    result = apply_semantic_policy("按客户类型看上个月的利润")

    assert result.adjusted is True
    assert result.effective_question == "按客户类型看上个月的毛利"
    assert result.dimensions == ("客户类型",)
    assert result.effective_metric == "毛利"


def test_profit_rate_by_region_falls_back_to_gross_margin():
    result = apply_semantic_policy("欧洲市场各区域的净利润率")

    assert result.effective_question == "欧洲市场各区域的毛利率"
    assert result.effective_metric == "毛利率"


def test_monthly_profit_keeps_period_expense_metric():
    result = apply_semantic_policy("查询上个月利润")

    assert result.adjusted is False
    assert result.effective_question == "查询上个月利润"


def test_department_profit_is_rejected_instead_of_inventing_sales_grain():
    with pytest.raises(SemanticPolicyError, match="不支持部门维度"):
        apply_semantic_policy("按部门查看利润")


@pytest.mark.parametrize(
    ("question", "metric", "dimension"),
    [
        ("按产品线分析研发费用率", "研发费用率", "产品线"),
        ("按部门分析销售费用率", "销售费用率", "部门"),
    ],
)
def test_expense_rate_dimension_conflict_is_rejected(question, metric, dimension):
    with pytest.raises(SemanticPolicyError) as exc_info:
        apply_semantic_policy(question)

    message = str(exc_info.value)
    assert metric in message
    assert dimension in message
    assert "按月份查询" in message


def test_monthly_expense_rate_is_kept_without_metric_substitution():
    result = apply_semantic_policy("查询上个月研发费用率")

    assert result.adjusted is False
    assert result.effective_question == "查询上个月研发费用率"


def test_gross_profit_field_rules_do_not_force_period_expense_table():
    force_include, _force_exclude, _reasons = FieldMatcher._active_rules("各产品线毛利率")

    assert "sales_orders.net_amount" in force_include
    assert "finance_expenses.expense_date" not in force_include


def test_profit_field_rules_keep_period_expense_time_field():
    force_include, _force_exclude, _reasons = FieldMatcher._active_rules("查询月度利润")

    assert "finance_expenses.expense_date" in force_include
