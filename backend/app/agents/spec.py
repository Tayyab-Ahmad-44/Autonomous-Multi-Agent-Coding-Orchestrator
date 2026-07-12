from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentOutput, BaseAgent
from app.agents.memory_prompt import format_memory_sections
from app.services.llm_service import LLMService


ValidationMethod = Literal[
    "unit_test",
    "integration_test",
    "browser_test",
    "manual_review",
    "security_scan",
]
RequiredTestType = Literal["pytest", "playwright", "shell", "semgrep", "manual"]


class ContractAssertion(BaseModel):
    id: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1)
    validation_method: ValidationMethod


class RequiredTest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: RequiredTestType
    command: str = Field(min_length=1)


class ValidationContractPlan(BaseModel):
    contract_markdown: str = Field(min_length=1)
    assertions: list[ContractAssertion] = Field(min_length=1)
    required_tests: list[RequiredTest] = Field(min_length=1)
    definition_of_done: list[str] = Field(default_factory=list)


class SpecLLMService(Protocol):
    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_hint: dict[str, Any],
    ) -> dict[str, Any]:
        pass


class SpecAgent(BaseAgent):
    agent_type = "spec"

    def __init__(self, llm_service: SpecLLMService | None = None) -> None:
        self._llm_service = llm_service or LLMService()

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        goal = str(input.data.get("goal", "")).strip()
        milestones = input.data.get("milestones")
        feature_tasks = input.data.get("feature_tasks")
        if not goal or not milestones or not feature_tasks:
            raise ValueError(
                "SpecAgent requires mission goal, milestones, and feature_tasks in AgentInput.data."
            )

        raw_contract = await self._llm_service.generate_json(
            system_prompt=_system_prompt(),
            user_prompt=_user_prompt(
                goal=goal,
                milestones=milestones,
                feature_tasks=feature_tasks,
                repo_memories=input.data.get("repo_memories"),
                user_preferences=input.data.get("user_preferences"),
            ),
            schema_hint=_schema_hint(),
        )
        contract = ValidationContractPlan.model_validate(raw_contract)
        contract_data = contract.model_dump()

        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary=f"Created validation contract with {len(contract.assertions)} assertion(s).",
            data=contract_data,
        )


def _system_prompt() -> str:
    return """Validation contract spec agent
You create validation contracts for a factory-style coding orchestrator.
The contract will be used by validator agents later.

Rules:
- Define observable behavior.
- Avoid vague checks.
- Workers should not start until this contract exists.
- Assertions must be concrete enough for a validator to evaluate.
- Include required tests where relevant.
- Use only these validation_method values: unit_test, integration_test, browser_test, manual_review, security_scan.
- Use only these required test type values: pytest, playwright, shell, semgrep, manual.
- Return only valid JSON."""


def _user_prompt(
    *,
    goal: str,
    milestones: Any,
    feature_tasks: Any,
    repo_memories: list | None = None,
    user_preferences: list | None = None,
) -> str:
    # Repo memory and user preferences matter here specifically because they constrain
    # required_tests: a contract demanding unittest for a repo that standardised on pytest
    # produces tests the worker cannot satisfy.
    memory_section = format_memory_sections(
        repo_memories=repo_memories,
        user_preferences=user_preferences,
    )
    return f"""Create a validation contract for this mission.

Mission goal:
{goal}

Generated milestones:
{milestones}

Generated feature tasks:
{feature_tasks}{memory_section}"""


def _schema_hint() -> dict[str, Any]:
    return {
        "contract_markdown": "string",
        "assertions": [
            {
                "id": "A1",
                "description": "string",
                "validation_method": (
                    "unit_test|integration_test|browser_test|manual_review|security_scan"
                ),
            }
        ],
        "required_tests": [
            {
                "name": "string",
                "type": "pytest|playwright|shell|semgrep|manual",
                "command": "string",
            }
        ],
        "definition_of_done": ["string"],
    }
