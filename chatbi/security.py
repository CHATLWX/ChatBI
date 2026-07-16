from __future__ import annotations

import re
from typing import Any

from models import UserContext


class SecurityError(RuntimeError):
    pass


class QuerySecurityManager:
    _banned = re.compile(
        r"\b(insert|update|delete|drop|alter|create|replace|truncate|grant|revoke|call|load|outfile|dumpfile|sleep|benchmark)\b",
        re.I,
    )
    _sensitive_markers = ("phone", "mobile", "email", "id_card", "password", "secret")
    _amount_markers = ("amount", "revenue", "cost", "profit", "expense", "收入", "成本", "利润", "费用")

    def secure_sql(self, sql: str, user: UserContext | None = None) -> str:
        user = user or UserContext.demo_admin()
        cleaned = re.sub(r"--.*?$|/\*.*?\*/", "", sql, flags=re.M | re.S).strip()
        if not re.match(r"^(select|with)\b", cleaned, re.I):
            raise SecurityError("仅允许执行 SELECT/CTE 只读查询")
        if self._banned.search(cleaned) or ";" in cleaned.rstrip(";"):
            raise SecurityError("SQL 包含危险操作或多条语句")
        if user.role not in {"admin", "finance", "analyst", "sales"}:
            raise SecurityError("当前角色无数据查询权限")
        if user.role == "sales":
            if not user.region:
                raise SecurityError("销售角色缺少区域权限范围")
            cleaned = self._inject_region_filter(cleaned, user.region)
        return cleaned.rstrip(";")

    def _inject_region_filter(self, sql: str, region: str) -> str:
        if "dim_customers" not in sql.lower():
            raise SecurityError("销售角色的查询必须关联 dim_customers 以实施区域过滤")
        alias_match = re.search(r"\bdim_customers\s+(?:as\s+)?([a-zA-Z_]\w*)", sql, re.I)
        alias = alias_match.group(1) if alias_match else "dim_customers"
        safe_region = region.replace("'", "''")
        condition = f"{alias}.region = '{safe_region}'"
        boundary = re.search(r"\b(group\s+by|order\s+by|having|limit)\b", sql, re.I)
        head, tail = (sql[: boundary.start()], sql[boundary.start() :]) if boundary else (sql, "")
        conjunction = " AND " if re.search(r"\bwhere\b", head, re.I) else " WHERE "
        return f"{head.rstrip()}{conjunction}{condition} {tail.lstrip()}".strip()

    def mask_result(
        self, columns: list[str], rows: list[dict[str, Any]], user: UserContext | None = None
    ) -> tuple[list[str], list[dict[str, Any]]]:
        user = user or UserContext.demo_admin()
        if user.role in {"admin", "finance"}:
            return columns, rows
        masked = []
        for row in rows:
            item = dict(row)
            for column in columns:
                name = column.lower()
                if any(marker in name for marker in self._sensitive_markers):
                    item[column] = "***"
                elif user.role == "sales" and any(marker in name for marker in self._amount_markers):
                    value = item.get(column)
                    item[column] = round(float(value), -3) if isinstance(value, (int, float)) else value
            masked.append(item)
        return columns, masked
