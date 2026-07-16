from __future__ import annotations

import re
from typing import Any


class ErrorAnalyzer:
    """第 7 课的离线 SQL 错误分类器，不接入生产查询主链路。"""

    FIELD_ERROR = "field_error"
    JOIN_ERROR = "join_error"
    TIME_ERROR = "time_error"
    FILTER_ERROR = "filter_error"
    AGGREGATION_ERROR = "aggregation_error"
    SYNTAX_ERROR = "syntax_error"
    UNKNOWN = "unknown"

    def categorize_error(self, sql: str, question: str | None = None) -> dict[str, Any]:
        detected = self.detect_all(sql, question)
        error_type = detected[0] if detected else self.UNKNOWN
        return {
            "error_type": error_type,
            "all_error_types": detected,
            "reason": self._reason(error_type),
            "suggestion": self._suggestion(error_type),
        }

    def detect_all(self, sql: str, question: str | None = None) -> list[str]:
        sql_lower = sql.lower()
        question = question or ""
        detected = []
        if ("收入" in question or "销售额" in question) and "gross_amount" in sql_lower and "net_amount" not in sql_lower:
            detected.append(self.FIELD_ERROR)
        if "成本" in question and "standard_cost" in sql_lower and "material_cost" not in sql_lower:
            detected.append(self.FIELD_ERROR)
        if ("收入" in question or "销售额" in question) and "exchange_rates" not in sql_lower:
            detected.append(self.JOIN_ERROR)
        if ("大区" in question or "区域" in question) and "dim_customers" not in sql_lower:
            detected.append(self.JOIN_ERROR)
        if ("产品线" in question or "产品" in question) and "dim_products" not in sql_lower:
            detected.append(self.JOIN_ERROR)
        if any(marker in question for marker in ("最近", "上个月", "本月")) and not any(
            marker in sql_lower for marker in ("date_sub", "curdate", "current_date")
        ):
            detected.append(self.TIME_ERROR)
        if any(marker in question for marker in ("收入", "销售额", "订单", "销量")) and "order_status" not in sql_lower:
            detected.append(self.FILTER_ERROR)
        select_match = re.search(r"select\s+(.*?)\s+from\s+", sql_lower, re.S)
        if select_match and re.search(r"\b(sum|avg|count|max|min)\s*\(", select_match.group(1)):
            non_aggregate = re.sub(r"\b(sum|avg|count|max|min)\s*\([^)]*\)", "", select_match.group(1))
            if re.search(r"\b[a-z_]\w*\.[a-z_]\w*\b", non_aggregate) and "group by" not in sql_lower:
                detected.append(self.AGGREGATION_ERROR)
        if not re.match(r"^\s*(select|with)\b", sql_lower):
            detected.append(self.SYNTAX_ERROR)
        return list(dict.fromkeys(detected))

    @classmethod
    def analyze_batch(cls, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        analyzer = cls()
        return [
            {
                "id": case.get("id"),
                "question": case.get("question"),
                **analyzer.categorize_error(case.get("generated_sql", ""), case.get("question")),
            }
            for case in cases
        ]

    @staticmethod
    def _reason(error_type: str) -> str:
        return {
            "field_error": "金额或成本字段与问题中的业务口径不一致",
            "join_error": "缺少问题所需的维度表或汇率表关联",
            "time_error": "动态时间问题没有使用日期边界函数",
            "filter_error": "遗漏订单状态等强制业务过滤",
            "aggregation_error": "聚合函数与非聚合维度缺少匹配的 GROUP BY",
            "syntax_error": "输出不是可执行的 SELECT/CTE 查询",
        }.get(error_type, "未匹配到已知错误模式")

    @staticmethod
    def _suggestion(error_type: str) -> str:
        return {
            "field_error": "在 RULES 中强化字段语义并增加字段选择负例",
            "join_error": "在 ERROR_GUARDS 中补充 Join 检查并增加多表 Few-shot",
            "time_error": "增加时间边界 Few-shot，明确动态时间 SQL 写法",
            "filter_error": "在 RULES 中明确强制过滤条件",
            "aggregation_error": "强调 SELECT 非聚合字段必须出现在 GROUP BY 中",
            "syntax_error": "检查 Prompt 和模型输出是否完整",
        }.get(error_type, "人工审查并补充到测试集")
