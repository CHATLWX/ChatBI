from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


# Local secrets stay in chatbi/.env (ignored by Git). Existing process-level
# variables keep precedence so Docker/CI deployments can override this file.
load_dotenv(Path(__file__).with_name(".env"), override=False)


class DataSourceConfig(BaseModel):
    driver: str = "mysql"
    host: str = "127.0.0.1"
    port: int = 3306
    database: str = "chatbi"
    user: str = "root"
    password: str = ""


class LLMConfig(BaseModel):
    model: str = "qwen-plus"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key: str = ""
    temperature: float = 0.0
    timeout: float = 90
    max_tokens: int = 4000
    embedding_model: str = "text-embedding-v3"
    embedding_dimension: int = 1024
    chunk_size: int = 800
    chunk_overlap: int = 120


class MilvusConfig(BaseModel):
    uri: str = "http://localhost:19530"
    token: str = ""
    db_name: str = "default"
    collections: dict[str, str] = Field(
        default_factory=lambda: {
            "tables": "table_descriptions",
            "fields": "field_descriptions",
            "indicators": "indicator_definitions",
        }
    )


class RetrievalConfig(BaseModel):
    table_top_k: int = 5
    field_top_k: int = 12
    indicator_top_k: int = 3
    table_score_threshold: float = 0.20
    field_score_threshold: float = 0.25
    indicator_score_threshold: float = 0.30
    field_rule_weight: float = 0.30


class ObsidianConfig(BaseModel):
    vault_path: str = ""
    indicator_folder: str = "ChatBI指标知识库"
    auto_discover: bool = True
    runtime_preferred: bool = True


class RuntimeConfig(BaseModel):
    pool_size: int = 5
    pool_max_overflow: int = 5
    pool_timeout: float = 3
    connect_timeout: int = 5
    read_timeout: int = 30
    write_timeout: int = 30
    slow_query_threshold_ms: float = 200
    query_timeout_ms: int = 15000
    query_max_rows: int = 500
    sql_retry_count: int = 2
    agent_max_retries: int = 2
    agent_failure_policy: Literal["abort", "skip"] = "skip"
    agent_storage_backend: Literal["memory", "temp_table"] = "memory"


class FeatureConfig(BaseModel):
    few_shot: bool = True
    rules: bool = True
    guards: bool = True
    indicator_knowledge: bool = True
    schema_linking: bool = True
    indicator_rag: bool = True
    agent_planning: bool = True
    report: bool = True


class AppConfig(BaseModel):
    app: dict[str, Any] = Field(default_factory=dict)
    data_source_name: str = "mysql_main"
    data_source: DataSourceConfig
    data_sources: dict[str, DataSourceConfig] = Field(default_factory=dict)
    llm: LLMConfig
    milvus: MilvusConfig
    obsidian: ObsidianConfig = Field(default_factory=ObsidianConfig)
    retrieval: RetrievalConfig
    runtime: RuntimeConfig
    features: FeatureConfig

    def for_source(self, source_id: str | None = None) -> "AppConfig":
        resolved = source_id or self.data_source_name
        if resolved == self.data_source_name:
            return self
        if resolved not in self.data_sources:
            raise ValueError(f"未知数据源：{resolved}")
        return self.model_copy(
            update={"data_source_name": resolved, "data_source": self.data_sources[resolved]}
        )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path or os.getenv("CHATBI_CONFIG", Path(__file__).with_name("config.yaml")))
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    data = raw.get("data", {})
    source_name = os.getenv("DATA_SOURCE", data.get("default_source", "mysql_main"))
    raw_sources = data.get("sources", {})
    source = dict(raw_sources.get(source_name, {}))
    source.update(
        {
            "host": os.getenv("DB_HOST", source.get("host", "127.0.0.1")),
            "port": int(os.getenv("DB_PORT", source.get("port", 3306))),
            "database": os.getenv("DB_NAME", source.get("database", "chatbi")),
            "user": os.getenv("DB_USER", source.get("user", "root")),
            "password": os.getenv("DB_PASSWORD", ""),
        }
    )
    llm = dict(raw.get("llm", {}))
    llm.update(
        {
            "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
            "base_url": os.getenv("DASHSCOPE_BASE_URL", llm.get("base_url")),
            "model": os.getenv("QWEN_MODEL", llm.get("model")),
            "max_tokens": int(os.getenv("LLM_MAX_TOKENS", llm.get("max_tokens", 4000))),
            "embedding_model": os.getenv("EMBEDDING_MODEL", llm.get("embedding_model")),
            "embedding_dimension": int(os.getenv("EMBEDDING_DIMENSION", llm.get("embedding_dimension", 1024))),
        }
    )
    milvus = dict(raw.get("milvus", {}))
    milvus.update(
        {
            "uri": os.getenv("MILVUS_URI", milvus.get("uri")),
            "token": os.getenv("MILVUS_TOKEN", milvus.get("token", "")),
            "db_name": os.getenv("MILVUS_DB_NAME", milvus.get("db_name", "default")),
        }
    )
    obsidian = dict(raw.get("obsidian", {}))
    obsidian.update(
        {
            "vault_path": os.getenv("OBSIDIAN_VAULT_PATH", obsidian.get("vault_path", "")),
            "indicator_folder": os.getenv(
                "OBSIDIAN_INDICATOR_FOLDER",
                obsidian.get("indicator_folder", "ChatBI指标知识库"),
            ),
            "auto_discover": _env_bool(
                "OBSIDIAN_AUTO_DISCOVER",
                bool(obsidian.get("auto_discover", True)),
            ),
            "runtime_preferred": _env_bool(
                "OBSIDIAN_RUNTIME_PREFERRED",
                bool(obsidian.get("runtime_preferred", True)),
            ),
        }
    )
    features = dict(raw.get("features", {}))
    for key in list(features):
        features[key] = _env_bool(f"FEATURE_{key.upper()}", bool(features[key]))
    data_sources = {
        name: DataSourceConfig(**source_config)
        for name, source_config in raw_sources.items()
    }
    selected_source = DataSourceConfig(**source)
    data_sources[source_name] = selected_source
    return AppConfig(
        app=raw.get("app", {}),
        data_source_name=source_name,
        data_source=selected_source,
        data_sources=data_sources,
        llm=LLMConfig(**llm),
        milvus=MilvusConfig(**milvus),
        obsidian=ObsidianConfig(**obsidian),
        retrieval=RetrievalConfig(**raw.get("retrieval", {})),
        runtime=RuntimeConfig(**raw.get("runtime", {})),
        features=FeatureConfig(**features),
    )


settings = load_config()
