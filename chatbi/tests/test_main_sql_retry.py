from types import SimpleNamespace

from database import QueryExecutionError
from main import ChatBISystem
from models import QueryOptions, UserContext


class FakeParser:
    def parse(self, question):
        return question

    def validate(self, parsed):
        return bool(parsed)


class FakeLLM:
    model = "fake-qwen"

    def __init__(self):
        self.repair_calls = 0
        self.prompts = []
        self.generated_sql = "SELECT broken FROM sales_orders"

    def generate_sql(self, *_args):
        self.prompts.append(_args[1])
        return self.generated_sql

    def repair_sql(self, *_args):
        self.repair_calls += 1
        return "SELECT 1 AS value"


class FakeDB:
    def __init__(self, error_type="sql_syntax"):
        self.error_type = error_type
        self.calls = 0
        self.last_query_info = {}
        self.config = SimpleNamespace(runtime=SimpleNamespace(sql_retry_count=2))

    def execute(self, _sql, _user):
        self.calls += 1
        if self.calls == 1:
            raise QueryExecutionError(self.error_type, "database error")
        self.last_query_info = {"row_count": 1}
        return ["value"], [{"value": 1}]


class FakeFormatter:
    def format(self, _columns, _rows):
        return "value\n1"


def build_system(error_type="sql_syntax"):
    llm = FakeLLM()
    db = FakeDB(error_type)
    runtime = SimpleNamespace(
        source_id="test",
        parser=FakeParser(),
        llm=llm,
        db=db,
        formatter=FakeFormatter(),
        schema_linker=SimpleNamespace(),
        indicator_knowledge=SimpleNamespace(),
        indicator_retriever=SimpleNamespace(),
    )
    return ChatBISystem(runtime=runtime), llm, db


def disabled_retrieval_options():
    return QueryOptions(
        use_schema_linking=False,
        use_indicator_knowledge=False,
        use_indicator_rag=False,
    )


def test_repairs_sql_syntax_error_then_executes_again():
    system, llm, db = build_system()

    result = system.run(
        "查询指标",
        disabled_retrieval_options(),
        UserContext.demo_admin(),
    )

    assert result.success is True
    assert result.sql == "SELECT 1 AS value"
    assert result.metadata["sql_attempts"] == 2
    assert llm.repair_calls == 1
    assert db.calls == 2


def test_does_not_repair_security_or_permission_errors():
    system, llm, db = build_system("security")

    result = system.run(
        "查询指标",
        disabled_retrieval_options(),
        UserContext.demo_admin(),
    )

    assert result.success is False
    assert result.error_type == "security"
    assert llm.repair_calls == 0
    assert db.calls == 1


def test_stream_reports_unexpected_schema_linking_failure():
    system, _llm, _db = build_system()

    def fail_link(_question):
        raise RuntimeError("milvus unavailable")

    system.runtime.schema_linker.link = fail_link
    events = list(
        system.run_stream(
            "查询销售额",
            QueryOptions(use_indicator_knowledge=False, use_indicator_rag=False),
            UserContext.demo_admin(),
        )
    )

    assert events[-2]["event"] == "error"
    assert events[-2]["data"]["error_type"] == "internal"
    assert "milvus unavailable" not in events[-2]["data"]["error"]
    assert events[-1]["event"] == "done"
    assert events[-1]["data"]["duration_ms"] >= 0


def test_stream_uses_lesson_event_contract_and_filters_empty_chunks():
    system, llm, db = build_system()
    db.calls = 1
    llm.generate_sql_stream = lambda *_args: iter(["", "SELECT ", "1 AS value"])
    llm.extract_sql = lambda raw: raw.strip()

    events = list(
        system.run_stream(
            "查询指标",
            disabled_retrieval_options(),
            UserContext.demo_admin(),
        )
    )

    chunks = [event for event in events if event["event"] == "sql_chunk"]
    assert [event["data"]["content"] for event in chunks] == ["SELECT ", "1 AS value"]
    assert any(event["event"] == "sql_done" for event in events)
    result = next(event for event in events if event["event"] == "result")
    assert result["data"]["row_count"] == 1
    assert result["data"]["metadata"]["duration_ms"] >= 0


def test_simple_query_falls_back_to_gross_profit_for_customer_dimension():
    system, llm, db = build_system()
    llm.generated_sql = "SELECT 1 AS gross_profit"
    db.calls = 1

    result = system.run(
        "按客户类型看上个月的利润",
        disabled_retrieval_options(),
        UserContext.demo_admin(),
    )

    assert result.success is True
    assert "按客户类型看上个月的毛利" in llm.prompts[0]
    assert result.metadata["effective_question"] == "按客户类型看上个月的毛利"
    assert result.metadata["semantic_adjustment"]["effective_metric"] == "毛利"


def test_simple_query_rejects_department_profit_without_allocation_rule():
    system, llm, db = build_system()

    result = system.run(
        "按部门查看上个月利润",
        disabled_retrieval_options(),
        UserContext.demo_admin(),
    )

    assert result.success is False
    assert result.error_type == "validation"
    assert "不支持部门维度" in result.error
    assert llm.prompts == []
    assert db.calls == 0
