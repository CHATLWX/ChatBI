from types import SimpleNamespace

import milvus_store


class FakeHealthClient:
    def __init__(self, row_counts=None, unreadable=None):
        self.row_counts = row_counts or {}
        self.unreadable = set(unreadable or [])
        self.closed = False

    def list_collections(self):
        return ["table_descriptions", "field_descriptions", "indicator_definitions"]

    def load_collection(self, _name):
        return None

    def get_load_state(self, _name):
        return {"state": "Loaded"}

    def get_collection_stats(self, name):
        return {"row_count": self.row_counts.get(name, 1)}

    def query(self, collection_name, **_kwargs):
        if collection_name in self.unreadable:
            raise RuntimeError("no available shard leaders")
        return [{"document_id": "sample"}]

    def close(self):
        self.closed = True


def test_inspect_collections_checks_readability_not_only_existence(monkeypatch):
    fake = FakeHealthClient(unreadable={"field_descriptions"})
    monkeypatch.setattr(milvus_store, "MilvusClient", lambda **_kwargs: fake)

    health = milvus_store.inspect_collections()

    assert health["tables"]["healthy"] is True
    assert health["fields"]["healthy"] is False
    assert "no available shard leaders" in health["fields"]["error"]
    assert fake.closed is True


def test_rebuild_embeds_before_drop_then_flushes_and_loads():
    events = []

    class FakeEmbeddings:
        def embed_documents(self, texts):
            events.append("embed")
            return [[0.0] * 1024 for _ in texts]

    class FakeClient:
        def has_collection(self, _name):
            return True

        def drop_collection(self, _name):
            events.append("drop")

        def create_collection(self, **_kwargs):
            events.append("create")

        def insert(self, _name, _rows):
            events.append("insert")

        def flush(self, _name):
            events.append("flush")

        def load_collection(self, _name):
            events.append("load")

    store = milvus_store.MilvusVectorStore.__new__(milvus_store.MilvusVectorStore)
    store.collection_name = "table_descriptions"
    store.client = FakeClient()
    store.embeddings = FakeEmbeddings()
    store.config = SimpleNamespace(llm=SimpleNamespace(embedding_dimension=1024))
    document = SimpleNamespace(page_content="sales", metadata={"kind": "table"})

    store.rebuild([document], ["table::sales"])

    assert events == ["embed", "drop", "create", "insert", "flush", "load"]
