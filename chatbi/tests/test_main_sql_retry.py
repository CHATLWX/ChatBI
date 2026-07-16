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

    def generate_sql(self, *_args):
        return "SELECT broken FROM sales_orders"

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
