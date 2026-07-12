from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentOutput, BaseAgent
from app.services.llm_service import LLMService


class PromotedMemoryEntry(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=500)


class MemoryPromotion(BaseModel):
    promotions: list[PromotedMemoryEntry] = Field(default_factory=list)


class MemoryPromoterLLMService(Protocol):
    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_hint: dict[str, Any],
    ) -> dict[str, Any]:
        pass


class MemoryPromoterAgent(BaseAgent):
    """Decides which of a mission's decisions are durable repo knowledge.

    Runs once per milestone that passes validation - the earliest point at which the work has
    actually been vetted. It sees the mission's decisions and the repo's current memory together,
    so promotion and supersession are a single judgement: reusing an existing key retires the old
    value, and inventing a new key spends a slot in a small permanent budget.
    """

    agent_type = "memory_promoter"

    def __init__(self, llm_service: MemoryPromoterLLMService | None = None) -> None:
        self._llm_service = llm_service or LLMService()

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        mission_goal = str(input.data.get("mission_goal", "")).strip()
        mission_decisions = input.data.get("mission_decisions") or []
        if not mission_decisions:
            return AgentOutput(
                agent_type=self.agent_type,
                status="completed",
                summary="No mission decisions to promote.",
                data={"promotions": []},
            )

        raw = await self._llm_service.generate_json(
            system_prompt=_system_prompt(),
            user_prompt=_user_prompt(
                mission_goal=mission_goal,
                milestone_name=str(input.data.get("milestone_name", "")),
                mission_decisions=mission_decisions,
                repo_memories=input.data.get("repo_memories") or [],
            ),
            schema_hint=_schema_hint(),
        )
        promotion = MemoryPromotion.model_validate(raw)

        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary=f"Promoted {len(promotion.promotions)} fact(s) to repo memory.",
            data=promotion.model_dump(),
        )


def _system_prompt() -> str:
    return """Repo memory promoter
You decide which decisions from a completed milestone are durable knowledge about the REPOSITORY
that future, unrelated missions on this repo should know.

Promote a fact only if it:
- describes the repository itself: architecture, conventions, library and framework choices,
  recurring failure patterns and how they were resolved.
- would still be true and useful months from now, to someone building an unrelated feature.

Do not promote:
- anything specific to this mission's feature or this milestone's tasks.
- restatements of what the code plainly shows (file names, function names).
- one-off details a future mission could not act on.

Repo memory is a small, permanent, shared budget, and every fact in it is injected into every
future prompt for this repo. Most milestones should promote ZERO or ONE fact. An empty list is a
good and common answer. Be stingy.

Superseding:
- If a fact updates something already in repo memory, REUSE THAT EXACT KEY. The old value is
  retired and replaced. This is how the repo learns that, say, JWT auth was migrated to OAuth.
- Invent a new key only when no existing key covers the fact.

Rules:
- Each key is a short lowercase snake_case slug (e.g. "auth_scheme").
- Each value is a short, concrete phrase (e.g. "OAuth2 via Auth0; replaced the earlier JWT scheme").
- Return only valid JSON."""


def _user_prompt(
    *,
    mission_goal: str,
    milestone_name: str,
    mission_decisions: list,
    repo_memories: list,
) -> str:
    return f"""Decide what to promote into this repo's long-term memory.

Mission goal:
{mission_goal or "No mission goal was provided."}

Milestone that just passed validation:
{milestone_name or "Unnamed milestone"}

Decisions made during this mission:
{_format_entries(mission_decisions) or "- None."}

Repo memory as it stands today (reuse one of these keys to supersede it):
{_format_entries(repo_memories) or "- Empty. This repo has no long-term memory yet."}"""


def _format_entries(entries: list) -> str:
    lines: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key", "")
        value = entry.get("value", "")
        if key or value:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _schema_hint() -> dict[str, Any]:
    return {
        "promotions": [
            {"key": "string", "value": "string"},
        ],
    }
