from config import settings
from agent_planner import AgentPlanner
from models import DecomposedTask, DecompositionPlan, ExecutionPlan, PlanStep, QueryOptions, QueryResult, UserContext
from result_store import MemoryResultStore
from step_executor import StepExecutor


def make_plan(dependent=True):
    return ExecutionPlan(
        question_type="profit",
        analysis_goal="分析利润",
        steps=[
            PlanStep(
                step_id="step_1",
                task_id="task_1",
                step_name="趋势",
                task_type="trend",
                question="查询趋势",
                description="查询趋势",
                expected_output="趋势结果",
            ),
            PlanStep(
                step_id="step_2",
                task_id="task_2",
                step_name="归因",
                task_type="cause",
                question="查询归因",
                description="查询归因",
                depends_on=["step_1"] if dependent else [],
                expected_output="归因结果",
            ),
        ],
    )


class FakeSystem:
    def __init__(self, results):
        self.results = iter(results)
        self.contexts = []

    def run(self, question, options, user, execution_context, source_id):
        self.contexts.append(execution_context)
        return next(self.results)


def config_with(**updates):
    runtime = settings.runtime.model_copy(update=updates)
    return settings.model_copy(update={"runtime": runtime})


def test_planner_maps_task_dependencies_to_step_dependencies():
    decomposition = DecompositionPlan(
        question_type="profit",
        analysis_goal="分析利润",
        subtasks=[
            DecomposedTask(task_id="task_1", task_name="趋势", task_type="trend", description="查询趋势"),
            DecomposedTask(task_id="task_2", task_name="归因", task_type="cause", description="查询归因", depends_on=["task_1"]),
        ],
    )
    plan = AgentPlanner().create_plan(decomposition)
    assert plan.steps[1].depends_on == ["step_1"]


def test_executor_retries_and_records_memory_reference():
    system = FakeSystem([
        QueryResult(success=False, question="查询趋势", error="失败", error_type="database_sql_syntax"),
        QueryResult(success=True, question="查询趋势", sql="SELECT 1", columns=["profit"], rows=[{"profit": 10}], formatted="profit=10"),
        QueryResult(success=True, question="查询归因", sql="SELECT 2", columns=["cause"], rows=[{"cause": "收入"}], formatted="cause=收入"),
    ])
    executor = StepExecutor(system, config_with(agent_max_retries=1), MemoryResultStore())
    results, context = executor.execute(make_plan(), "利润为什么下降", QueryOptions(), UserContext.demo_admin())
    assert results[0].attempts == 2
    assert results[0].result_reference == "memory://step_1"
    assert '"columns": ["profit"]' in system.contexts[2]
    assert '"rows": [{"profit": 10}]' in system.contexts[2]
    assert "memory://step_1" in context.memory


def test_executor_skips_dependency_after_failed_step():
    system = FakeSystem([
        QueryResult(success=False, question="查询趋势", error="失败", error_type="database_sql_syntax")
    ])
    executor = StepExecutor(system, config_with(agent_max_retries=0, agent_failure_policy="skip"), MemoryResultStore())
    results, _ = executor.execute(make_plan(), "利润为什么下降", QueryOptions(), UserContext.demo_admin())
    assert [result.status for result in results] == ["failed", "skipped"]
