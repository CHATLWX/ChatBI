from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from application import ChatBIApplication
from config import AppConfig, settings
from database import DatabaseClient
from index_builder import ensure_indexes
from milvus_store import inspect_collections
from models import QueryOptions, UserContext

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("chatbi.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    if get_application.cache_info().currsize:
        get_application().close()
        get_application.cache_clear()


app = FastAPI(
    title=settings.app.get("name", "Enterprise ChatBI"),
    version=settings.app.get("version", "1.0.0"),
    description="""Schema Linking + 指标 RAG + Plan-and-Execute 的企业级 ChatBI。

SSE 流式接口事件契约：

| 事件 | 说明 | data 主要字段 |
| --- | --- | --- |
| `sql_chunk` | SQL 增量文本 | `content` |
| `sql_done` | 完整 SQL | `sql`, `duration_ms` |
| `result` | 查询结果 | `columns`, `rows`, `row_count` |
| `error` | 异常信息 | `error`, `error_type`, `sql` |
| `done` | 流结束 | `duration_ms` |
""",
    openapi_tags=[
        {"name": "查询", "description": "自然语言查询与 SSE 流式分析接口"},
        {"name": "系统", "description": "服务、数据库和语义检索健康状态"},
    ],
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1"],
    allow_origin_regex=r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    force_complex: bool = False
    conversation_context: str | None = Field(default=None, max_length=12000)
    source_id: str | None = None
    use_few_shot: bool | None = None
    use_rules: bool | None = None
    use_guards: bool | None = None
    use_indicator_knowledge: bool | None = None
    use_schema_linking: bool | None = None
    use_indicator_rag: bool | None = None


class CollectionHealthResponse(BaseModel):
    collection: str
    healthy: bool
    loaded: bool
    readable: bool
    row_count: int
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database_connected: bool
    model: str
    vector_store: str
    vector_store_connected: bool
    collections: dict[str, str]
    collection_health: dict[str, CollectionHealthResponse]


class QueryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: Literal["text2sql", "agent"]
    success: bool
    question: str
    sql: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0
    error: str | None = None
    error_type: str | None = None


@lru_cache(maxsize=1)
def get_application() -> ChatBIApplication:
    ensure_indexes(settings)
    return ChatBIApplication(settings)


def _resolve_options(payload: QueryRequest, config: AppConfig = settings) -> QueryOptions:
    features = config.features
    return QueryOptions(
        use_few_shot=payload.use_few_shot if payload.use_few_shot is not None else features.few_shot,
        use_rules=payload.use_rules if payload.use_rules is not None else features.rules,
        use_guards=payload.use_guards if payload.use_guards is not None else features.guards,
        use_indicator_knowledge=(
            payload.use_indicator_knowledge
            if payload.use_indicator_knowledge is not None
            else features.indicator_knowledge
        ),
        use_schema_linking=(
            payload.use_schema_linking if payload.use_schema_linking is not None else features.schema_linking
        ),
        use_indicator_rag=(
            payload.use_indicator_rag if payload.use_indicator_rag is not None else features.indicator_rag
        ),
    )


def _user_context(request: Request) -> UserContext:
    return request.state.user_context


def _json_serializer(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _sse_event(event: str, data: Any) -> str:
    encoded = json.dumps(data, ensure_ascii=False, default=_json_serializer)
    return f"event: {event}\ndata: {encoded}\n\n"


@app.middleware("http")
async def attach_user_context(request: Request, call_next):
    encoded_region = request.headers.get("x-user-region")
    request.state.user_context = UserContext(
        user_id=request.headers.get("x-user-id", "demo_admin"),
        role=request.headers.get("x-user-role", "admin"),
        region=unquote(encoded_region) if encoded_region else None,
    )
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"success": False, "error_type": "validation", "error": str(exc)})


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"success": False, **detail})


@app.exception_handler(Exception)
async def unknown_error(_: Request, exc: Exception):
    logger.exception("Unhandled API error")
    return JSONResponse(status_code=500, content={"success": False, "error_type": "internal", "error": "系统内部错误"})


@app.get("/health", response_model=HealthResponse, tags=["系统"], summary="健康检查")
def health() -> HealthResponse:
    database = DatabaseClient(settings)
    try:
        database_connected = database.validate_connection()
    finally:
        database.connection_pool.close()

    try:
        collection_health = inspect_collections(settings)
        vector_store_connected = bool(collection_health) and all(
            detail["healthy"] for detail in collection_health.values()
        )
    except Exception as exc:
        logger.warning("Milvus health check failed: %s", exc)
        vector_store_connected = False
        collection_health = {
            kind: {
                "collection": name,
                "healthy": False,
                "loaded": False,
                "readable": False,
                "row_count": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
            for kind, name in settings.milvus.collections.items()
        }
    return HealthResponse(
        status="ok" if database_connected and vector_store_connected else "degraded",
        database_connected=database_connected,
        model=settings.llm.model,
        vector_store="milvus",
        vector_store_connected=vector_store_connected,
        collections=settings.milvus.collections,
        collection_health=collection_health,
    )


@app.post(
    "/api/v1/query",
    response_model=QueryResponse,
    tags=["查询"],
    summary="同步自然语言查询",
)
def query(payload: QueryRequest, request: Request) -> dict:
    result = get_application().query(
        payload.question,
        _resolve_options(payload),
        _user_context(request),
        payload.force_complex,
        payload.source_id,
        payload.conversation_context or "",
    )
    if not result.get("success"):
        error_type = result.get("error_type")
        status = {
            "validation": 422,
            "database_sql_syntax": 422,
            "security": 403,
            "database_permission_denied": 403,
            "database_connection_error": 503,
            "database_query_timeout": 504,
            "llm": 502,
        }.get(error_type, 500)
        raise HTTPException(status_code=status, detail=result)
    return result


@app.post(
    "/api/v1/query/stream",
    tags=["查询"],
    summary="SSE 流式查询（逐步推送）",
    description="使用 `sql_chunk` / `sql_done` / `result` / `error` 事件持续推送分析过程。",
    responses={200: {"content": {"text/event-stream": {"example": "event: sql_chunk\ndata: {\"content\":\"SELECT\"}\n\n"}}}},
)
def query_stream(payload: QueryRequest, request: Request) -> StreamingResponse:
    application = get_application()
    options = _resolve_options(payload)
    user = _user_context(request)

    def generate():
        if payload.force_complex or payload.conversation_context or application.is_complex(payload.question):
            yield _sse_event("status", {"stage": "planning", "message": "正在拆解复杂分析任务"})
            result = application.query(
                payload.question,
                options,
                user,
                True,
                payload.source_id,
                payload.conversation_context or "",
            )
            if result.get("plan"):
                yield _sse_event("plan", result["plan"])
            for step in result.get("step_results", []):
                yield _sse_event("step", step)
            yield _sse_event("result" if result.get("success") else "error", result)
            yield _sse_event("done", {})
        else:
            for item in application.system.run_stream(payload.question, options, user, payload.source_id):
                yield _sse_event(item["event"], item["data"])

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


static_dir = Path(__file__).with_name("static")
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
