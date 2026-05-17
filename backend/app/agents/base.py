from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(slots=True)
class AgentInput:
    instructions: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentOutput:
    agent_type: str
    status: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentContext:
    mission_id: UUID
    db: Session
    feature_task_id: UUID | None = None
    agent_run_id: UUID | None = None
    repo_path: Path | None = None
    shared_files: dict[str, str] = field(default_factory=dict)


class BaseAgent(ABC):
    agent_type: ClassVar[str]

    @abstractmethod
    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        raise NotImplementedError
