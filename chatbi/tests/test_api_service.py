from types import SimpleNamespace
from urllib.parse import quote
from decimal import Decimal

from fastapi.testclient import TestClient

import api_service


class FakeDB:
    connection_pool = SimpleNamespace(close=lambda: None)

    def validate_connection(self):
        return True


class FakeSystem:
    def __init__(self):
        self.db = FakeDB()
        self.llm = SimpleNamespace(model="fake-qwen")

    def run_stream(self, question, _options, _user, _source_id):
        yield {"event": "status", "data": {"stage": "sql_generation"}}
        yield {
            "event": "result",
            "data": {"success": True, "question": question, "rows": [{"value": 1}]},
        }
        yield {"event": "done", "data": {}}


class FakeApplication:
    def __init__(self, result=None):
        self.system = FakeSystem()
        self.result = result or {
            "mode": "text2sql",
            "success": True,
            "question": "查询",
            "rows": [{"value": 1}],
        }
        self.user = None
        self.force_complex = None
        self.conversation_context = None

    def is_complex(self, _question):
        return False

    def query(
        self,
        _question,
        _options,
        user,
        force_complex,
        _source_id,
        conversation_context="",
    ):
        self.user = user
        self.force_complex = force_complex
        self.conversation_context = conversation_context
        return self.result


def client_with(monkeypatch, fake_application):
    monkeypatch.setattr(api_service, "get_application", lambda: fake_application)
    return TestClient(api_service.app)


def test_health_reports_mysql_qwen_and_milvus(monkeypatch):
    monkeypatch.setattr(api_service, "DatabaseClient", lambda _settings: FakeDB())
    monkeypatch.setattr(
        api_service,
        "inspect_collections",
        lambda _settings: {
            kind: {
                "collection": name,
                "healthy": True,
                "loaded": True,
                "readable": True,
                "row_count": 1,
                "error": None,
            }
            for kind, name in api_service.settings.milvus.collections.items()
        },
    )
    client = client_with(monkeypatch, FakeApplication())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["database_connected"] is True
    assert response.json()["model"] == api_service.settings.llm.model
    assert response.json()["vector_store"] == "milvus"
    assert response.json()["vector_store_connected"] is True
    assert all(item["healthy"] for item in response.json()["collection_health"].values())


def test_health_is_degraded_when_collection_is_unreadable(monkeypatch):
    monkeypatch.setattr(api_service, "DatabaseClient", lambda _settings: FakeDB())
    monkeypatch.setattr(
        api_service,
        "inspect_collections",
        lambda _settings: {
            "tables": {
                "collection": "table_descriptions",
                "healthy": False,
                "loaded": False,
                "readable": False,
                "row_count": 9,
                "error": "no available shard leaders",
            }
        },
    )
    client = client_with(monkeypatch, FakeApplication())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["vector_store_connected"] is False


def test_query_uses_request_user_context(monkeypatch):
    fake = FakeApplication()
    client = client_with(monkeypatch, fake)

    response = client.post(
        "/api/v1/query",
        json={"question": "查询"},
        headers={
            "x-user-id": "u1",
            "x-user-role": "sales",
            "x-user-region": quote("华东"),
        },
    )

    assert response.status_code == 200
    assert fake.user.user_id == "u1"
    assert fake.user.role == "sales"
    assert fake.user.region == "华东"


def test_query_maps_database_connection_error_to_503(monkeypatch):
    fake = FakeApplication(
        {
            "mode": "text2sql",
            "success": False,
            "question": "查询",
            "error": "连接失败",
            "error_type": "database_connection_error",
        }
    )
    client = client_with(monkeypatch, fake)

    response = client.post("/api/v1/query", json={"question": "查询"})

    assert response.status_code == 503
    assert response.json()["error_type"] == "database_connection_error"


def test_simple_sse_contains_status_result_and_done(monkeypatch):
    client = client_with(monkeypatch, FakeApplication())

    response = client.post("/api/v1/query/stream", json={"question": "查询"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["connection"] == "keep-alive"
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: status" in response.text
    assert "event: result" in response.text
    assert "event: done" in response.text


def test_sse_serializes_decimal_as_number():
    event = api_service._sse_event("result", {"amount": Decimal("19915.00")})

    assert '"amount": 19915.0' in event
    assert '"amount": "19915.00"' not in event


def test_openapi_documents_query_groups_and_stream_contract():
    schema = api_service.app.openapi()

    assert {item["name"] for item in schema["tags"]} == {"查询", "系统"}
    stream = schema["paths"]["/api/v1/query/stream"]["post"]
    assert stream["summary"].startswith("SSE 流式查询")
    assert "sql_chunk" in api_service.app.description
    query_schema = schema["components"]["schemas"]["QueryResponse"]
    assert "duration_ms" in query_schema["properties"]


def test_conversation_context_forces_agent_route(monkeypatch):
    fake = FakeApplication()
    client = client_with(monkeypatch, fake)

    response = client.post(
        "/api/v1/query/stream",
        json={"question": "下一步建议做什么？", "conversation_context": "上一轮利润下降"},
    )

    assert response.status_code == 200
    assert fake.force_complex is True
    assert fake.conversation_context == "上一轮利润下降"
    assert "event: result" in response.text
