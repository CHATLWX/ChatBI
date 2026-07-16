from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from application import ChatBIApplication
from config import AppConfig, settings
from index_builder import ensure_indexes
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
    description="Schema Linking + 指标 RAG + Plan-and-Execute 的企业级 ChatBI。",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    force_complex: bool = False
    source_id: str | None = None
    use_few_shot: bool | None = None
    use_rules: bool | None = None
    use_guards: bool | None = None
    use_indicator_knowledge: bool | None = None
    use_schema_linking: bool | None = None
    use_indicator_rag: bool | None = None


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


def _sse_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


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


@app.get("/health")
def health() -> dict[str, Any]:
    application = get_application()
    return {
        "status": "ok" if application.system.db.validate_connection() else "degraded",
        "database_connected": application.system.db.validate_connection(),
        "model": application.system.llm.model,
        "vector_store": "milvus",
        "collections": settings.milvus.collections,
    }


@app.post("/api/v1/query")
def query(payload: QueryRequest, request: Request) -> dict:
    result = get_application().query(
        payload.question,
        _resolve_options(payload),
        _user_context(request),
        payload.force_complex,
        payload.source_id,
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


@app.post("/api/v1/query/stream")
def query_stream(payload: QueryRequest, request: Request) -> StreamingResponse:
    application = get_application()
    options = _resolve_options(payload)
    user = _user_context(request)

    def generate():
        if payload.force_complex or application.is_complex(payload.question):
            yield _sse_event("status", {"stage": "planning", "message": "正在拆解复杂分析任务"})
            result = application.query(payload.question, options, user, True, payload.source_id)
            if result.get("plan"):
                yield _sse_event("plan", result["plan"])
            for step in result.get("step_results", []):
                yield _sse_event("step", step)
            yield _sse_event("result" if result.get("success") else "error", result)
            yield _sse_event("done", {})
        else:
            for item in application.system.run_stream(payload.question, options, user, payload.source_id):
                yield _sse_event(item["event"], item["data"])

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


static_dir = Path(__file__).with_name("static")
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
