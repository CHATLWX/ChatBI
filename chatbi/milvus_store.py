from __future__ import annotations

from typing import Any

from langchain_core.documents import Document
from pymilvus import DataType, MilvusClient

from config import AppConfig, settings
from embeddings import get_embeddings


def connection_args(config: AppConfig = settings) -> dict[str, Any]:
    args: dict[str, Any] = {"uri": config.milvus.uri, "db_name": config.milvus.db_name}
    if config.milvus.token:
        args["token"] = config.milvus.token
    return args


class MilvusVectorStore:
    """Milvus-backed VectorStore abstraction used by all three retrievers."""

    def __init__(self, kind: str, config: AppConfig = settings):
        self.kind = kind
        self.config = config
        self.collection_name = config.milvus.collections[kind]
        self.client = MilvusClient(**connection_args(config))
        self.embeddings = get_embeddings(config)

    def rebuild(self, documents: list[Document], ids: list[str]) -> None:
        if len(documents) != len(ids):
            raise ValueError("documents 与 ids 数量不一致")
        if self.client.has_collection(self.collection_name):
            self.client.drop_collection(self.collection_name)
        schema = MilvusClient.create_schema(auto_id=True, enable_dynamic_field=True)
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.config.llm.embedding_dimension)
        schema.add_field("text", DataType.VARCHAR, max_length=8192)
        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 64},
        )
        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
            consistency_level="Strong",
        )
        vectors = self.embeddings.embed_documents([document.page_content for document in documents])
        rows = []
        for document_id, document, vector in zip(ids, documents, vectors):
            rows.append(
                {
                    "vector": vector,
                    "text": document.page_content,
                    "document_id": document_id,
                    **document.metadata,
                }
            )
        self.client.insert(self.collection_name, rows)

    def similarity_search_with_relevance_scores(
        self, query: str, k: int = 4, filter_expression: str = ""
    ) -> list[tuple[Document, float]]:
        vector = self.embeddings.embed_query(query)
        results = self.client.search(
            collection_name=self.collection_name,
            data=[vector],
            filter=filter_expression,
            limit=k,
            output_fields=["*"],
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
        )
        output = []
        for hit in results[0] if results else []:
            entity = dict(hit.get("entity") or {})
            text = entity.pop("text", "")
            entity.pop("vector", None)
            output.append((Document(page_content=text, metadata=entity), float(hit.get("distance", 0.0))))
        return output

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()


def get_vectorstore(kind: str, config: AppConfig = settings) -> MilvusVectorStore:
    return MilvusVectorStore(kind, config)


def rebuild_collection(kind: str, documents: list[Document], ids: list[str], config: AppConfig = settings) -> None:
    store = MilvusVectorStore(kind, config)
    try:
        store.rebuild(documents, ids)
    finally:
        store.close()


def list_collections(config: AppConfig = settings) -> list[str]:
    client = MilvusClient(**connection_args(config))
    try:
        return client.list_collections()
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("无效的 chunk_size/chunk_overlap")
    if len(text) <= chunk_size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start : start + chunk_size])
        if start + chunk_size >= len(text):
            break
        start += chunk_size - overlap
    return chunks
