from __future__ import annotations

import queue
import threading
import time
from decimal import Decimal
from typing import Any, Callable

import pymysql

from config import AppConfig, settings
from models import UserContext
from security import QuerySecurityManager, SecurityError


class QueryExecutionError(RuntimeError):
    def __init__(self, error_type: str, message: str, metadata: dict[str, Any] | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.metadata = metadata or {}


class DatabaseConnectionPool:
    def __init__(self, factory: Callable[[], Any], pool_size: int, max_overflow: int, timeout: float):
        self.factory = factory
        self.pool_size = pool_size
        self.max_total = pool_size + max_overflow
        self.timeout = timeout
        self._idle: queue.LifoQueue = queue.LifoQueue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._total = 0

    def acquire(self) -> Any:
        try:
            connection = self._idle.get_nowait()
            connection.ping(reconnect=True)
            return connection
        except queue.Empty:
            pass
        except Exception:
            with self._lock:
                self._total = max(0, self._total - 1)
        with self._lock:
            if self._total < self.max_total:
                self._total += 1
                try:
                    return self.factory()
                except Exception:
                    self._total -= 1
                    raise
        try:
            connection = self._idle.get(timeout=self.timeout)
            connection.ping(reconnect=True)
            return connection
        except queue.Empty as exc:
            raise QueryExecutionError("pool_timeout", "数据库连接池等待超时") from exc

    def release(self, connection: Any) -> None:
        try:
            if self._idle.full():
                connection.close()
                with self._lock:
                    self._total = max(0, self._total - 1)
            else:
                self._idle.put_nowait(connection)
        except Exception:
            with self._lock:
                self._total = max(0, self._total - 1)

    def close(self) -> None:
        while not self._idle.empty():
            self._idle.get_nowait().close()
            with self._lock:
                self._total = max(0, self._total - 1)


class DatabaseClient:
    def __init__(
        self,
        config: AppConfig = settings,
        connection_factory: Callable[[], Any] | None = None,
        security: QuerySecurityManager | None = None,
        time_fn: Callable[[], float] = time.perf_counter,
    ):
        self.config = config
        self.security = security or QuerySecurityManager()
        self.time_fn = time_fn
        self.connection_factory = connection_factory or self._create_connection
        runtime = config.runtime
        self.connection_pool = DatabaseConnectionPool(
            self.connection_factory,
            runtime.pool_size,
            runtime.pool_max_overflow,
            runtime.pool_timeout,
        )
        self.last_query_info: dict[str, Any] = {}

    def _create_connection(self):
        source = self.config.data_source
        return pymysql.connect(
            host=source.host,
            port=source.port,
            user=source.user,
            password=source.password,
            database=source.database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=self.config.runtime.connect_timeout,
            read_timeout=self.config.runtime.read_timeout,
            write_timeout=self.config.runtime.write_timeout,
            autocommit=True,
        )

    def validate_connection(self) -> bool:
        try:
            connection = self.connection_pool.acquire()
            connection.ping(reconnect=True)
            self.connection_pool.release(connection)
            return True
        except Exception:
            return False

    def execute(
        self, sql: str, user: UserContext | None = None
    ) -> tuple[list[str], list[dict[str, Any]]]:
        user_context = user or UserContext.demo_admin()
        try:
            secured_sql = self.security.secure_sql(sql, user_context)
        except SecurityError as exc:
            raise QueryExecutionError("security", str(exc)) from exc
        started_at = self.time_fn()
        connection = None
        try:
            connection = self.connection_pool.acquire()
            with connection.cursor() as cursor:
                cursor.execute(f"SET SESSION MAX_EXECUTION_TIME={self.config.runtime.query_timeout_ms}")
                cursor.execute(secured_sql)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                raw_rows = cursor.fetchmany(self.config.runtime.query_max_rows)
                rows = [self._json_safe(row) for row in raw_rows]
                _, masked_rows = self.security.mask_result(columns, rows, user_context)
                duration_ms = round((self.time_fn() - started_at) * 1000, 2)
                explain_plan = self._explain(cursor, secured_sql) if duration_ms >= self.config.runtime.slow_query_threshold_ms else []
                self.last_query_info = {
                    "sql": secured_sql,
                    "duration_ms": duration_ms,
                    "row_count": len(masked_rows),
                    "slow_query": bool(explain_plan),
                    "explain_plan": explain_plan,
                }
                return columns, masked_rows
        except QueryExecutionError:
            raise
        except Exception as exc:
            duration_ms = round((self.time_fn() - started_at) * 1000, 2)
            raise self._translate_error(exc, duration_ms) from exc
        finally:
            if connection is not None:
                self.connection_pool.release(connection)

    @staticmethod
    def _json_safe(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: float(value) if isinstance(value, Decimal) else value.isoformat() if hasattr(value, "isoformat") else value
            for key, value in row.items()
        }

    @staticmethod
    def _explain(cursor: Any, sql: str) -> list[dict[str, Any]]:
        try:
            cursor.execute("EXPLAIN " + sql)
            return [DatabaseClient._json_safe(row) for row in cursor.fetchall()]
        except Exception:
            return []

    @staticmethod
    def _translate_error(exc: Exception, duration_ms: float) -> QueryExecutionError:
        code = exc.args[0] if getattr(exc, "args", None) and isinstance(exc.args[0], int) else None
        text = str(exc).lower()
        metadata = {"error_code": code, "duration_ms": duration_ms}
        if isinstance(exc, pymysql.err.ProgrammingError) or code in {1054, 1064, 1146}:
            return QueryExecutionError("sql_syntax", "SQL 语法、表名或字段不正确", metadata)
        if code in {1044, 1045, 1142, 1143, 1227}:
            return QueryExecutionError("permission_denied", "数据库权限不足", metadata)
        if code in {1205, 2013, 3024} or "timed out" in text:
            return QueryExecutionError("query_timeout", "查询执行超时", metadata)
        if code in {1049, 2003, 2006}:
            return QueryExecutionError("database_connection", "数据库连接失败", metadata)
        return QueryExecutionError("database_error", "数据库查询失败", metadata)
