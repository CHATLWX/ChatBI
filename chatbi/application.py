from __future__ import annotations

from config import AppConfig, settings
from main import ChatBISystem
from models import QueryOptions, UserContext
from plan_execute_agent import PlanAndExecuteAgent


COMPLEX_MARKERS = ("为什么", "原因", "下降", "下滑", "归因", "影响因素", "深入分析")


class ChatBIApplication:
    def __init__(self, config: AppConfig = settings):
        self.config = config
        self.system = ChatBISystem(config)
        self.agent = PlanAndExecuteAgent(self.system, config)

    @staticmethod
    def is_complex(question: str) -> bool:
        return any(marker in question for marker in COMPLEX_MARKERS)

    def query(
        self,
        question: str,
        options: QueryOptions,
        user: UserContext,
        force_complex: bool = False,
        source_id: str | None = None,
        conversation_context: str = "",
    ) -> dict:
        if force_complex or conversation_context or (self.config.features.agent_planning and self.is_complex(question)):
            result = self.agent.run(question, options, user, source_id, conversation_context)
            payload = {"mode": "agent", **result.model_dump()}
            payload["duration_ms"] = payload.get("metadata", {}).get("duration_ms", 0)
            return payload
        result = self.system.run(question, options, user, source_id=source_id)
        payload = {"mode": "text2sql", **result.model_dump()}
        payload["duration_ms"] = payload.get("metadata", {}).get("duration_ms", 0)
        return payload

    def close(self) -> None:
        self.agent.close()
        self.system.close()
