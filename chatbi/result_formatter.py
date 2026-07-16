from __future__ import annotations

from typing import Any


class ResultFormatter:
    def format(self, columns: list[str], rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "查询结果为空"
        widths = {
            column: min(40, max(len(str(column)), *(len(str(row.get(column, ""))) for row in rows[:50])))
            for column in columns
        }
        header = " | ".join(column.ljust(widths[column]) for column in columns)
        separator = "-+-".join("-" * widths[column] for column in columns)
        body = [" | ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns) for row in rows[:50]]
        suffix = f"\n... 共 {len(rows)} 行" if len(rows) > 50 else ""
        return "\n".join([header, separator, *body]) + suffix

    @staticmethod
    def format_error(message: str) -> str:
        return f"查询失败：{message}"
