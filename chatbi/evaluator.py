from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from database import DatabaseClient


class Evaluator:
    """第 8 课的独立 Text2SQL Execution Accuracy 评估器。"""

    def __init__(self, db: DatabaseClient):
        self.db = db

    @staticmethod
    def load_test_cases(path: str | Path = "test_cases.json") -> list[dict[str, Any]]:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def evaluate_one(self, case: dict[str, Any], generator: Callable[[str], str]) -> dict[str, Any]:
        result = {
            "id": case.get("id", "unknown"),
            "category": case.get("category", "unknown"),
            "question": case["question"],
            "expected_sql": case["expected_sql"],
            "generated_sql": None,
            "exact_match": False,
            "execution_match": False,
            "error": None,
            "detail": {},
        }
        try:
            generated_sql = generator(case["question"])
            result["generated_sql"] = generated_sql
            result["exact_match"] = self._normalize_sql(generated_sql) == self._normalize_sql(case["expected_sql"])
        except Exception as exc:
            result["error"] = f"SQL 生成失败：{exc}"
            return result

        try:
            expected_columns, expected_rows = self.db.execute(case["expected_sql"])
        except Exception as exc:
            result["error"] = f"预期 SQL 执行失败：{exc}"
            return result

        try:
            generated_columns, generated_rows = self.db.execute(generated_sql)
        except Exception as exc:
            result["error"] = f"生成 SQL 执行失败：{exc}"
            result["detail"] = {
                "expected_columns": expected_columns,
                "expected_row_count": len(expected_rows),
            }
            return result

        result["execution_match"] = self.results_equivalent(
            generated_columns,
            generated_rows,
            generated_sql,
            expected_columns,
            expected_rows,
            case["expected_sql"],
        )
        result["detail"] = {
            "expected_columns": expected_columns,
            "expected_row_count": len(expected_rows),
            "generated_columns": generated_columns,
            "generated_row_count": len(generated_rows),
        }
        return result

    def evaluate_all(self, cases: list[dict[str, Any]], generator: Callable[[str], str]) -> list[dict[str, Any]]:
        return [self.evaluate_one(case, generator) for case in cases]

    @staticmethod
    def _normalize_sql(sql: str) -> str:
        return " ".join(sql.lower().rstrip(";").split())

    @classmethod
    def results_equivalent(
        cls,
        generated_columns: list[str],
        generated_rows: list[dict[str, Any]],
        generated_sql: str,
        expected_columns: list[str],
        expected_rows: list[dict[str, Any]],
        expected_sql: str,
    ) -> bool:
        if len(generated_columns) != len(expected_columns) or len(generated_rows) != len(expected_rows):
            return False

        generated_checks = cls._column_name_checks(generated_sql)
        expected_checks = cls._column_name_checks(expected_sql)
        if len(generated_checks) == len(generated_columns) and len(expected_checks) == len(expected_columns):
            for index, (generated_column, expected_column) in enumerate(
                zip(generated_columns, expected_columns)
            ):
                if (generated_checks[index] or expected_checks[index]) and (
                    generated_column.lower() != expected_column.lower()
                ):
                    return False

        def normalize(columns: list[str], rows: list[dict[str, Any]]) -> list[tuple]:
            return sorted(
                [tuple(str(row.get(column)) for column in columns) for row in rows],
                key=str,
            )

        return normalize(generated_columns, generated_rows) == normalize(expected_columns, expected_rows)

    @staticmethod
    def _should_check_column_names(sql: str) -> bool:
        return any(Evaluator._column_name_checks(sql))

    @staticmethod
    def _column_name_checks(sql: str) -> list[bool]:
        match = re.search(r"select\s+(.*?)(?:\s+from\s+)", sql, re.I | re.S)
        if not match:
            return []
        select_clause = match.group(1).strip()
        items, current, depth = [], [], 0
        for char in select_clause:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            if char == "," and depth == 0:
                items.append("".join(current).strip())
                current = []
            else:
                current.append(char)
        if current:
            items.append("".join(current).strip())
        checks = []
        for item in items:
            clean = re.split(r"\s+as\s+", item, maxsplit=1, flags=re.I)[0].strip()
            if re.match(r"^(count|sum|avg|max|min)\s*\(", clean, re.I):
                checks.append(False)
                continue
            if re.match(r"^[+-]?\d*\.?\d+$", clean) or re.match(r"^(['\"]).*\1$", clean):
                checks.append(False)
                continue
            checks.append(True)
        return checks

    @staticmethod
    def generate_report(results: list[dict[str, Any]]) -> str:
        total = len(results)
        execution = sum(bool(item["execution_match"]) for item in results)
        exact = sum(bool(item["exact_match"]) for item in results)
        categories: dict[str, Counter] = {}
        for item in results:
            category = item["category"]
            if category not in categories:
                categories[category] = Counter(total=0, correct=0, error=0)
            categories[category]["total"] += 1
            categories[category]["correct"] += int(bool(item["execution_match"]))
            categories[category]["error"] += int(bool(item["error"]))
        lines = [
            "=" * 60,
            "ChatBI Text2SQL 评估报告",
            "=" * 60,
            f"总用例数：{total}",
            f"Execution Accuracy：{execution}/{total} = {execution / total:.1%}" if total else "Execution Accuracy：N/A",
            f"Exact Match Accuracy：{exact}/{total} = {exact / total:.1%}" if total else "Exact Match Accuracy：N/A",
            f"执行失败数：{sum(bool(item['error']) for item in results)}",
            "",
            "按难度分类统计：",
        ]
        for category in ("simple", "medium", "complex"):
            if category in categories:
                stat = categories[category]
                accuracy = stat["correct"] / stat["total"] if stat["total"] else 0
                lines.append(
                    f"  {category:8s}: {stat['correct']}/{stat['total']} = {accuracy:.1%} (失败 {stat['error']})"
                )
        lines.append("\n详细结果：")
        for item in results:
            status = "通过" if item["execution_match"] else "失败" if item["error"] else "不匹配"
            lines.append(f"[{item['id']}] {item['category']:8s} | {status} | {item['question']}")
            if item["error"]:
                lines.append(f"  错误：{item['error']}")
        return "\n".join(lines)

    report = generate_report
