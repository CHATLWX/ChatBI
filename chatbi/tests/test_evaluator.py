from evaluator import Evaluator


class FakeDB:
    def execute(self, sql, user=None):
        if "expected" in sql:
            return ["value"], [{"value": 10}]
        return ["alias"], [{"alias": 10}]


def test_execution_match_ignores_alias_for_pure_aggregate():
    evaluator = Evaluator(FakeDB())
    case = {
        "id": "S01",
        "category": "simple",
        "question": "总数",
        "expected_sql": "SELECT SUM(expected) FROM t",
    }
    result = evaluator.evaluate_one(case, lambda _: "SELECT SUM(generated) FROM t")
    assert result["execution_match"] is True


def test_execution_match_checks_column_names_for_dimension_query():
    assert not Evaluator.results_equivalent(
        ["wrong"],
        [{"wrong": "欧洲"}],
        "SELECT wrong FROM t",
        ["region"],
        [{"region": "欧洲"}],
        "SELECT region FROM t",
    )


def test_dimension_query_ignores_only_aggregate_alias_difference():
    assert Evaluator.results_equivalent(
        ["product_line", "total_revenue_cny"],
        [{"product_line": "储能", "total_revenue_cny": 10}],
        "SELECT product_line, SUM(amount) AS total_revenue_cny FROM t GROUP BY product_line",
        ["product_line", "total_revenue"],
        [{"product_line": "储能", "total_revenue": 10}],
        "SELECT product_line, SUM(amount) AS total_revenue FROM t GROUP BY product_line",
    )
