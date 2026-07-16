from __future__ import annotations

from indicator_metadata import INDICATOR_BY_NAME, INDICATOR_DEFINITIONS


class IndicatorKnowledge:
    """第 9 课的关键词指标知识；第 20 课作为指标 RAG 的降级路径。"""

    def __init__(self):
        self.indicators = INDICATOR_BY_NAME
        self.alias_map: dict[str, str] = {}
        for indicator in INDICATOR_DEFINITIONS:
            self.alias_map[indicator["name"].lower()] = indicator["name"]
            for alias in indicator.get("aliases", []):
                self.alias_map[alias.lower()] = indicator["name"]

    def detect_indicators(self, question: str) -> list[str]:
        detected = []
        question_lower = question.lower()
        for alias, standard_name in self.alias_map.items():
            if alias in question_lower and standard_name not in detected:
                detected.append(standard_name)
        return detected

    def get_indicator_text(self, indicator_name: str) -> str:
        indicator = self.indicators.get(indicator_name)
        if not indicator:
            return ""
        lines = [
            f"指标：{indicator['name']}",
            f"  定义：{indicator['definition']}",
            f"  计算公式：{indicator['formula']}",
            f"  数据来源：{', '.join(indicator['data_source'])}",
        ]
        if indicator.get("depends_on"):
            lines.append(f"  依赖指标：{', '.join(indicator['depends_on'])}")
        if indicator.get("filters"):
            lines.append(f"  强制过滤：{' AND '.join(indicator['filters'])}")
        return "\n".join(lines)

    def get_indicator_context(self, question: str) -> dict:
        detected = self.detect_indicators(question)
        if not detected:
            return {"detected_indicators": [], "indicator_block": ""}
        blocks = ["【指标知识】"]
        injected: set[str] = set()
        for name in detected:
            if name not in injected:
                blocks.append(self.get_indicator_text(name))
                injected.add(name)
            indicator = self.indicators.get(name)
            for dependency in indicator.get("depends_on", []) if indicator else []:
                if dependency not in injected:
                    blocks.append(self.get_indicator_text(dependency))
                    injected.add(dependency)
        return {
            "detected_indicators": list(injected),
            "indicator_block": "\n\n".join(blocks),
        }
