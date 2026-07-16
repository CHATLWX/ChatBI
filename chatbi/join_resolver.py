from __future__ import annotations

from collections import defaultdict, deque

from schema_metadata import JOIN_RELATIONS


class JoinResolver:
    def __init__(self):
        self.graph: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for left_table, left_field, right_table, right_field in JOIN_RELATIONS:
            condition = f"{left_table}.{left_field} = {right_table}.{right_field}"
            self.graph[left_table].append((right_table, condition))
            self.graph[right_table].append((left_table, condition))

    @staticmethod
    def select_anchor(query: str, tables: list[str]) -> str:
        metric_markers = ("收入", "销售额", "成本", "毛利", "利润", "订单", "销量", "客单价")
        if "sales_orders" in tables and any(marker in query for marker in metric_markers):
            return "sales_orders"
        if "finance_expenses" in tables and any(marker in query for marker in ("费用", "研发", "管理费用")):
            return "finance_expenses"
        if "客户" in query and "dim_customers" in tables:
            return "dim_customers"
        if "产品" in query and "dim_products" in tables:
            return "dim_products"
        return tables[0] if tables else ""

    def resolve(self, query: str, tables: list[str]) -> dict:
        anchor = self.select_anchor(query, tables)
        joins, connected = [], {anchor}
        for target in tables:
            if target in connected:
                continue
            path = self._bfs(anchor, target)
            for next_table, condition in path:
                if next_table not in connected:
                    joins.append({"table": next_table, "condition": condition})
                    connected.add(next_table)
        return {"anchor_table": anchor, "joins": joins, "connected_tables": list(connected)}

    def _bfs(self, start: str, target: str) -> list[tuple[str, str]]:
        queue = deque([(start, [])])
        seen = {start}
        while queue:
            node, path = queue.popleft()
            if node == target:
                return path
            for neighbor, condition in self.graph[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, path + [(neighbor, condition)]))
        return []
