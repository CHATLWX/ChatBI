from __future__ import annotations

import re
from typing import Any, Protocol

import pymysql

from config import AppConfig, settings


class ResultStore(Protocol):
    backend: str

    def put(self, step_id: str, columns: list[str], rows: list[dict[str, Any]]) -> str: ...

    def get(self, reference: str) -> list[dict[str, Any]]: ...

    def cleanup(self) -> None: ...


class MemoryResultStore:
    backend = "memory"

    def __init__(self):
        self._data: dict[str, dict[str, Any]] = {}

    def put(self, step_id: str, columns: list[str], rows: list[dict[str, Any]]) -> str:
        reference = f"memory://{step_id}"
        self._data[reference] = {"columns": list(columns), "rows": [dict(row) for row in rows]}
        return reference

    def get(self, reference: str) -> list[dict[str, Any]]:
        if reference not in self._data:
            raise KeyError(f"中间结果不存在：{reference}")
        return [dict(row) for row in self._data[reference]["rows"]]

    def cleanup(self) -> None:
        self._data.clear()


class TempTableResultStore:
    backend = "temp_table"

    def __init__(self, config: AppConfig = settings):
        source = config.data_source
        self.connection = pymysql.connect(
            host=source.host,
            port=source.port,
            user=source.user,
            password=source.password,
            database=source.database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        self._tables: set[str] = set()

    @staticmethod
    def _identifier(value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", value)
        if not cleaned or cleaned[0].isdigit():
            cleaned = "c_" + cleaned
        return cleaned[:60]

    @staticmethod
    def _column_type(values: list[Any]) -> str:
        non_null = [value for value in values if value is not None]
        if non_null and all(isinstance(value, bool) for value in non_null):
            return "TINYINT"
        if non_null and all(isinstance(value, int) and not isinstance(value, bool) for value in non_null):
            return "BIGINT"
        if non_null and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in non_null):
            return "DOUBLE"
        return "TEXT"

    def put(self, step_id: str, columns: list[str], rows: list[dict[str, Any]]) -> str:
        table = self._identifier(f"tmp_agent_{step_id}")
        safe_columns = [self._identifier(column) for column in columns]
        if len(set(safe_columns)) != len(safe_columns):
            raise ValueError("中间结果列名清洗后发生冲突")
        definitions = []
        for original, safe in zip(columns, safe_columns):
            definitions.append(
                f"`{safe}` {self._column_type([row.get(original) for row in rows])} NULL"
            )
        with self.connection.cursor() as cursor:
            cursor.execute(f"DROP TEMPORARY TABLE IF EXISTS `{table}`")
            cursor.execute(f"CREATE TEMPORARY TABLE `{table}` ({', '.join(definitions)})")
            if rows:
                placeholders = ", ".join(["%s"] * len(columns))
                column_sql = ", ".join(f"`{column}`" for column in safe_columns)
                values = [tuple(row.get(column) for column in columns) for row in rows]
                cursor.executemany(
                    f"INSERT INTO `{table}` ({column_sql}) VALUES ({placeholders})",
                    values,
                )
        self._tables.add(table)
        return f"temp_table://{table}"

    def get(self, reference: str) -> list[dict[str, Any]]:
        prefix = "temp_table://"
        if not reference.startswith(prefix):
            raise ValueError(f"无效临时表引用：{reference}")
        table = self._identifier(reference[len(prefix) :])
        if table not in self._tables:
            raise KeyError(f"中间结果不存在：{reference}")
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT * FROM `{table}`")
            return list(cursor.fetchall())

    def cleanup(self) -> None:
        if not self.connection.open:
            return
        with self.connection.cursor() as cursor:
            for table in self._tables:
                cursor.execute(f"DROP TEMPORARY TABLE IF EXISTS `{table}`")
        self._tables.clear()
        self.connection.close()


def build_result_store(config: AppConfig = settings) -> ResultStore:
    if config.runtime.agent_storage_backend == "temp_table":
        return TempTableResultStore(config)
    return MemoryResultStore()
