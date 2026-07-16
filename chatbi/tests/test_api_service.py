from types import SimpleNamespace
from urllib.parse import quote

from fastapi.testclient import TestClient

import api_service


class FakeDB:
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

    def is_complex(self, _question):
        return False

    def query(self, _question, _options, user, _force_complex, _source_id):
        self.user = user
        return self.result


def client_with(monkeypatch, fake_application):
    monkeypatch.setattr(api_service, "get_application", lambda: fake_application)
    return TestClient(api_service.app)


def test_health_reports_mysql_qwen_and_milvus(monkeypatch):
    client = client_with(monkeypatch, FakeApplication())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["database_connected"] is True
    assert response.json()["model"] == "fake-qwen"
    assert response.json()["vector_store"] == "milvus"


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
    assert "event: status" in response.text
    assert "event: result" in response.text
    assert "event: done" in response.text
