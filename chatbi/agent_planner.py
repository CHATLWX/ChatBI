from __future__ import annotations

from models import DecompositionPlan, ExecutionPlan, PlanStep


class AgentPlanner:
    def create_plan(self, decomposition: DecompositionPlan) -> ExecutionPlan:
        task_to_step = {task.task_id: f"step_{index}" for index, task in enumerate(decomposition.subtasks, 1)}
        steps = []
        for index, task in enumerate(decomposition.subtasks, 1):
            dimensions = "、".join(task.dimensions) or "无指定维度"
            metrics = "、".join(task.metrics) or "按问题识别指标"
            question = f"{task.description}。分析指标：{metrics}；分析维度：{dimensions}。"
            steps.append(
                PlanStep(
                    step_id=f"step_{index}",
                    task_id=task.task_id,
                    step_name=task.task_name,
                    task_type=task.task_type,
                    question=question,
                    description=task.description,
                    depends_on=[task_to_step[item] for item in task.depends_on],
                    metrics=task.metrics,
                    dimensions=task.dimensions,
                    expected_output=f"返回支撑“{task.task_name}”的结构化查询结果",
                )
            )
        return ExecutionPlan(
            question_type=decomposition.question_type,
            analysis_goal=decomposition.analysis_goal,
            steps=steps,
        )
