from __future__ import annotations

import re
from dataclasses import dataclass


class SemanticPolicyError(ValueError):
    """The requested metric cannot be represented at the requested grain."""


_PROFIT_PATTERN = re.compile(r"(?<!毛)(经营利润率|经营利润|净利润率|净利润|净利率|利润率|利润)")
_DIMENSION_MARKERS = {
    "客户类型": ("客户类型", "客户"),
    "大区": ("大区", "区域", "欧洲", "北美", "亚太"),
    "国家": ("国家", "country"),
    "行业": ("行业", "industry"),
    "产品线": ("产品线", "业务线", "product_line"),
    "产品类别": ("产品类别", "品类", "category"),
    "技术路线": ("技术路线", "tech_route"),
    "部门": ("部门", "department"),
}
_SALES_DIMENSIONS = {
    "客户类型",
    "大区",
    "国家",
    "行业",
    "产品线",
    "产品类别",
    "技术路线",
}


@dataclass(frozen=True)
class SemanticPolicyResult:
    original_question: str
    effective_question: str
    dimensions: tuple[str, ...] = ()
    original_metric: str | None = None
    effective_metric: str | None = None
    reason: str = ""

    @property
    def adjusted(self) -> bool:
        return self.original_question != self.effective_question

    def metadata(self) -> dict:
        return {
            "adjusted": self.adjusted,
            "original_metric": self.original_metric,
            "effective_metric": self.effective_metric,
            "dimensions": list(self.dimensions),
            "reason": self.reason,
        }


def apply_semantic_policy(question: str) -> SemanticPolicyResult:
    """Apply deterministic metric-grain rules before Schema Linking and RAG."""
    dimensions = tuple(
        name
        for name, markers in _DIMENSION_MARKERS.items()
        if any(marker.lower() in question.lower() for marker in markers)
    )
    profit_match = _PROFIT_PATTERN.search(question)
    if not profit_match or not dimensions:
        return SemanticPolicyResult(question, question, dimensions)

    if "部门" in dimensions:
        raise SemanticPolicyError(
            "利润不支持部门维度：销售事实没有部门字段，且期间费用没有销售维度分摊规则。"
            "请查询部门费用，或仅按月份查询利润。"
        )

    incompatible_sales_dimensions = tuple(
        dimension for dimension in dimensions if dimension in _SALES_DIMENSIONS
    )
    if not incompatible_sales_dimensions:
        return SemanticPolicyResult(question, question, dimensions)

    original_metric = profit_match.group(0)

    def replace_metric(match: re.Match[str]) -> str:
        return "毛利率" if match.group(0).endswith("率") else "毛利"

    effective_question = _PROFIT_PATTERN.sub(replace_metric, question)
    effective_metric = "毛利率" if original_metric.endswith("率") else "毛利"
    return SemanticPolicyResult(
        original_question=question,
        effective_question=effective_question,
        dimensions=incompatible_sales_dimensions,
        original_metric=original_metric,
        effective_metric=effective_metric,
        reason=(
            "finance_expenses 只有月份和部门粒度，未定义客户、产品或区域费用分摊规则；"
            f"已将{original_metric}回退为{effective_metric}。"
        ),
    )
