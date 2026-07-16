from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class UserContext(BaseModel):
    user_id: str
    role: str = "admin"
    region: str | None = None

    @classmethod
    def demo_admin(cls) -> "UserContext":
        return cls(user_id="demo_admin", role="admin")


class QueryOptions(BaseModel):
    use_few_shot: bool = True
    use_rules: bool = True
    use_guards: bool = True
    use_indicator_knowledge: bool = True
    use_schema_linking: bool = True
    use_indicator_rag: bool = True


class DecomposedTask(BaseModel):
    task_id: str
    task_name: str
    task_type: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)


class DecompositionPlan(BaseModel):
    question_type: str
    analysis_goal: str
    subtasks: list[DecomposedTask]


class PlanStep(BaseModel):
    step_id: str
    task_id: str
    step_name: str
    task_type: str
    action: str = "text2sql"
    question: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    expected_output: str


class ExecutionPlan(BaseModel):
    question_type: str
    analysis_goal: str
    steps: list[PlanStep]


class StepExecutionResult(BaseModel):
    step_id: str
    task_id: str
    step_name: str
    success: bool
    status: Literal["completed", "failed", "skipped"] = "completed"
    attempts: int = 1
    question: str
    depends_on: list[str] = Field(default_factory=list)
    context_used: str = ""
    storage_backend: str | None = None
    result_reference: str | None = None
    sql: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    formatted: str = ""
    error: str | None = None
    error_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionContext(BaseModel):
    original_question: str
    results: dict[str, StepExecutionResult] = Field(default_factory=dict)
    memory: dict[str, dict[str, Any]] = Field(default_factory=dict)


class AnalysisSummary(BaseModel):
    completed_steps: int
    total_steps: int
    key_findings: list[str] = Field(default_factory=list)
    text: str = ""


class AnalysisReport(BaseModel):
    title: str
    executive_summary: str
    key_findings: list[str] = Field(default_factory=list)
    root_causes: list[str] = Field(default_factory=list)
    trend_judgment: str
    action_suggestions: list[str] = Field(default_factory=list)
    markdown: str = ""


class QueryResult(BaseModel):
    success: bool
    question: str
    sql: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    formatted: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    error_type: str | None = None


class AgentResult(BaseModel):
    success: bool
    question: str
    plan: ExecutionPlan | None = None
    step_results: list[StepExecutionResult] = Field(default_factory=list)
    summary: AnalysisSummary | None = None
    report: AnalysisReport | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    error_type: str | None = None
