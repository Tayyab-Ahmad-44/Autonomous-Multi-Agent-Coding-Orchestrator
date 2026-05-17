from app.agents.base import BaseAgent
from app.agents.fix_planner import FixPlannerAgent
from app.agents.planner import PlannerAgent
from app.agents.research import ResearchAgent
from app.agents.spec import SpecAgent
from app.agents.validator import ValidatorAgent
from app.agents.worker import WorkerAgent


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        self._agents[agent.agent_type] = agent

    def get(self, agent_type: str) -> BaseAgent:
        try:
            return self._agents[agent_type]
        except KeyError as exc:
            raise KeyError(f"Agent type is not registered: {agent_type}") from exc

    def types(self) -> list[str]:
        return sorted(self._agents)


def build_default_registry() -> AgentRegistry:
    registry = AgentRegistry()
    for agent in (
        PlannerAgent(),
        SpecAgent(),
        ResearchAgent(),
        WorkerAgent(),
        ValidatorAgent(),
        FixPlannerAgent(),
    ):
        registry.register(agent)
    return registry
