from llm_client import LLMClient


def test_extract_sql_removes_markdown_escaped_identifier_underscores():
    sql = LLMClient.extract_sql(
        "SELECT r.rate\\_to\\_cny, p.material\\_cost FROM exchange\\_rates r"
    )

    assert sql == "SELECT r.rate_to_cny, p.material_cost FROM exchange_rates r"
