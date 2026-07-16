from error_analyzer import ErrorAnalyzer


def test_detects_income_field_and_join_errors():
    result = ErrorAnalyzer().categorize_error(
        "SELECT SUM(gross_amount) FROM sales_orders",
        "查询总收入",
    )
    assert result["error_type"] == "field_error"
    assert "join_error" in result["all_error_types"]
