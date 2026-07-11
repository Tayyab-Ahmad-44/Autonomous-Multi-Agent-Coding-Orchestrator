from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentOutput, BaseAgent
from app.services.llm_service import LLMService


PlannerTaskType = Literal["backend", "frontend", "database", "test", "docs", "research"]


class PlanFeature(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    task_type: PlannerTaskType


class PlanMilestone(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    order_index: int = Field(ge=1)
    features: list[PlanFeature] = Field(min_length=1, max_length=5)


class PlannerPlan(BaseModel):
    milestones: list[PlanMilestone] = Field(min_length=1, max_length=4)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class PlannerLLMService(Protocol):
    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_hint: dict[str, Any],
    ) -> dict[str, Any]:
        pass


class PlannerAgent(BaseAgent):
    agent_type = "planner"

    def __init__(self, llm_service: PlannerLLMService | None = None) -> None:
        self._llm_service = llm_service or LLMService()

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        title = str(input.data.get("title", "")).strip()
        goal = str(input.data.get("goal", "")).strip()
        if not title or not goal:
            raise ValueError("PlannerAgent requires mission title and goal in AgentInput.data.")

        repo_profile = input.data.get("repo_profile")
        mission_decisions = input.data.get("mission_decisions")
        raw_plan = await self._llm_service.generate_json(
            system_prompt=_system_prompt(),
            user_prompt=_user_prompt(
                title=title,
                goal=goal,
                repo_profile=repo_profile,
                mission_decisions=mission_decisions,
            ),
            schema_hint=_schema_hint(),
        )
        plan = PlannerPlan.model_validate(raw_plan)
        plan_data = plan.model_dump()

        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary=f"Created a plan with {len(plan.milestones)} milestone(s).",
            data=plan_data,
        )


def _system_prompt() -> str:
    return """Mission planner
You are the planning agent for a factory-style coding orchestrator.
Create a small MVP implementation plan for one software mission.

Rules:
- Keep MVP tasks small.
- Do not create more than 4 milestones.
- Do not create more than 5 features per milestone.
- Every feature must be independently implementable.
- Include testing tasks where relevant.
- Use only these feature task_type values: backend, frontend, database, test, docs, research.
- Return only valid JSON."""


def _user_prompt(
    *,
    title: str,
    goal: str,
    repo_profile: dict | None = None,
    mission_decisions: list | None = None,
) -> str:
    repo_section = _format_repo_profile(repo_profile)
    decisions_section = _format_mission_decisions(mission_decisions)
    return f"""Plan this mission.

Mission title:
{title}

Mission goal:
{goal}{repo_section}{decisions_section}"""


def _format_mission_decisions(mission_decisions: list | None) -> str:
    if not mission_decisions:
        return ""
    lines = ["\n\nPrior decisions in this mission (stay consistent with these):"]
    for decision in mission_decisions:
        if not isinstance(decision, dict):
            continue
        key = decision.get("key", "")
        value = decision.get("value", "")
        if key or value:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _format_repo_profile(profile: dict | None) -> str:
    if not profile:
        return ""
    lines = ["\n\nRepository profile:"]
    if profile.get("language"):
        lines.append(f"- Language: {profile['language']}")
    if profile.get("frontend_framework"):
        lines.append(f"- Frontend: {profile['frontend_framework']}")
    if profile.get("backend_framework"):
        lines.append(f"- Backend: {profile['backend_framework']}")
    if profile.get("package_manager"):
        lines.append(f"- Package manager: {profile['package_manager']}")
    if profile.get("test_commands"):
        lines.append(f"- Test commands: {', '.join(profile['test_commands'])}")
    if profile.get("build_commands"):
        lines.append(f"- Build commands: {', '.join(profile['build_commands'])}")
    if profile.get("important_dirs"):
        lines.append(f"- Key directories: {', '.join(profile['important_dirs'])}")
    if profile.get("has_docker"):
        lines.append("- Docker: yes")
    if profile.get("has_ci"):
        lines.append("- CI: yes")
    if profile.get("readme_summary"):
        lines.append(f"- README excerpt: {profile['readme_summary'][:300]}")
    return "\n".join(lines)


def _schema_hint() -> dict[str, Any]:
    return {
        "milestones": [
            {
                "name": "string",
                "description": "string",
                "order_index": 1,
                "features": [
                    {
                        "title": "string",
                        "description": "string",
                        "task_type": "backend|frontend|database|test|docs|research",
                    }
                ],
            }
        ],
        "assumptions": ["string"],
        "risks": ["string"],
    }
