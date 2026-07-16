from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from config import AppConfig, settings


def get_embeddings(config: AppConfig = settings) -> OpenAIEmbeddings:
    if not config.llm.api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法调用 Embedding API")
    return OpenAIEmbeddings(
        model=config.llm.embedding_model,
        dimensions=config.llm.embedding_dimension,
        base_url=config.llm.base_url,
        api_key=config.llm.api_key,
        check_embedding_ctx_length=False,
        chunk_size=10,
    )
