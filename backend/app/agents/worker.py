from __future__ import annotations

import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentOutput, BaseAgent
from app.core.config import Settings, get_settings
from app.models import FeatureTaskStatus
from app.services.codex_service import CodexResult, CodexService
from app.services.git_service import GitService, GitServiceError
from app.services.llm_service import LLMService
from app.services.sandbox_service import SandboxResult, SandboxService


logger = logging.getLogger(__name__)

# Codex's CLI stdout has no guaranteed structure (see CodexService/CodexResult), so decisions
# are extracted with a dedicated LLM call rather than by parsing Codex's own output.
_MAX_DECISION_DIFF_CHARS = 6000


class MissionDecisionEntry(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=500)


class MissionDecisionExtraction(BaseModel):
    decisions: list[MissionDecisionEntry] = Field(default_factory=list)


class DecisionExtractionLLMService(Protocol):
    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_hint: dict[str, Any],
    ) -> dict[str, Any]:
        pass


class WorkerAgent(BaseAgent):
    agent_type = "worker"

    def __init__(
        self,
        sandbox_service: SandboxService | None = None,
        codex_service: CodexService | None = None,
        git_service: GitService | None = None,
        settings: Settings | None = None,
        decision_llm_service: DecisionExtractionLLMService | None = None,
    ) -> None:
        self._sandbox_service = sandbox_service or SandboxService()
        self._settings = settings or get_settings()
        self._codex_service = codex_service or CodexService(settings=self._settings)
        self._git_service = git_service or GitService()
        self._decision_llm_service = decision_llm_service or LLMService()

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        if context.repo_path is None:
            raise ValueError(
                "Repository workspace is not initialized. "
                "Clone the repository before running the mission."
            )
        if context.feature_task_id is None:
            raise ValueError("WorkerAgent requires feature_task_id in AgentContext.")

        repo_path = context.repo_path
        if not repo_path.exists():
            raise ValueError(
                f"Repository workspace does not exist on disk: {repo_path}. "
                "Clone the repository before running the mission."
            )

        validation_contract = _load_validation_contract(context)
        feature_task = input.data
        if self._settings.codex_enabled:
            return await self._run_codex_worker(
                context=context,
                repo_path=repo_path,
                feature_task=feature_task,
                validation_contract=validation_contract,
            )

        # Non-codex path: inspect repo, setup branch, capture git state.
        branch_name = _task_branch_name(context)
        git_state = _prepare_git_branch(self._git_service, repo_path, branch_name)
        git_status_before = _capture_git_status(self._git_service, repo_path, git_state)

        inspection_results = self._inspect_repository(repo_path)
        artifact_ids = _store_inspection_artifacts(context, inspection_results)

        git_diff = _capture_git_diff(self._git_service, repo_path, git_state)
        git_status_after = _capture_git_status(self._git_service, repo_path, git_state)
        changed_files = _parse_changed_files(git_status_after)

        diff_artifact_id = _store_git_diff_artifact(
            context,
            branch_name=branch_name,
            git_state=git_state,
            git_diff=git_diff,
            git_status=git_status_after,
            commit_output=None,
            latest_commit=None,
        )
        if diff_artifact_id is not None:
            artifact_ids.append(diff_artifact_id)

        _mark_feature_task_status(context, FeatureTaskStatus.completed)

        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary="Worker inspected the repository and produced a no-edit implementation report.",
            data={
                "mission_id": str(context.mission_id),
                "feature_task_id": str(context.feature_task_id),
                "repo_path": str(repo_path),
                "worker_report": _worker_report(feature_task, validation_contract),
                "repo_inspection": [_inspection_result_to_dict(result) for result in inspection_results],
                "artifact_ids": artifact_ids,
                "changed_files": changed_files,
                "git": {
                    "branch_name": branch_name,
                    "is_git_repo": git_state["is_git_repo"],
                    "branch_ready": git_state.get("branch_ready", False),
                    "status_before": git_status_before,
                    "diff": git_diff,
                    "has_changes": bool(git_diff.strip()),
                },
            },
        )

    async def _run_codex_worker(
        self,
        *,
        context: AgentContext,
        repo_path: Path,
        feature_task: dict[str, Any],
        validation_contract: dict[str, Any] | None,
    ) -> AgentOutput:
        mission_goal = _load_mission_goal(context)
        mission_decisions = _load_mission_decisions(context)
        branch_name = _task_branch_name(context)
        git_state = _prepare_git_branch(self._git_service, repo_path, branch_name)
        task_prompt = _codex_task_prompt(
            mission_goal=mission_goal,
            feature_task=feature_task,
            validation_contract=validation_contract,
            allow_commits=self._settings.codex_allow_commits,
            mission_decisions=mission_decisions,
        )
        result = self._codex_service.run_codex_task(
            repo_path=str(repo_path),
            task_prompt=task_prompt,
        )
        artifact_id = _store_codex_artifact(context, result=result, task_prompt=task_prompt)
        git_diff = _capture_git_diff(self._git_service, repo_path, git_state)
        git_status = _capture_git_status(self._git_service, repo_path, git_state)
        git_has_changes = bool(git_diff.strip() or git_status.strip())
        commit_output = None
        latest_commit = None
        if git_has_changes and self._settings.auto_commit:
            commit_output = self._git_service.commit_all(
                str(repo_path),
                f"Task: {feature_task.get('title', 'Untitled task')}",
            )
            latest_commit = self._git_service.get_latest_commit(str(repo_path))
        diff_artifact_id = _store_git_diff_artifact(
            context,
            branch_name=branch_name,
            git_state=git_state,
            git_diff=git_diff,
            git_status=git_status,
            commit_output=commit_output,
            latest_commit=latest_commit,
        )
        artifact_ids = [artifact_id]
        if diff_artifact_id is not None:
            artifact_ids.append(diff_artifact_id)
        task_status = FeatureTaskStatus.completed if result.exit_code == 0 else FeatureTaskStatus.failed
        _mark_feature_task_status(context, task_status)

        if task_status == FeatureTaskStatus.completed and git_has_changes:
            await self._extract_and_store_decisions(
                context=context,
                feature_task=feature_task,
                diff_text=git_diff or git_status,
            )

        status = "completed" if result.exit_code == 0 else "failed"
        summary = (
            "Codex CLI completed the worker task."
            if result.exit_code == 0
            else f"Codex CLI failed with exit code {result.exit_code}."
        )
        return AgentOutput(
            agent_type=self.agent_type,
            status=status,
            summary=summary,
            data={
                "mission_id": str(context.mission_id),
                "feature_task_id": str(context.feature_task_id),
                "repo_path": str(repo_path),
                "codex_enabled": True,
                "codex_result": asdict(result),
                "git": {
                    "branch_name": branch_name,
                    "is_git_repo": git_state["is_git_repo"],
                    "branch_ready": git_state["branch_ready"],
                    "diff_captured": diff_artifact_id is not None,
                    "has_changes": git_has_changes,
                    "auto_commit": self._settings.auto_commit,
                    "commit_output": commit_output,
                    "latest_commit": latest_commit,
                },
                "artifact_ids": artifact_ids,
            },
        )

    async def _extract_and_store_decisions(
        self,
        *,
        context: AgentContext,
        feature_task: dict[str, Any],
        diff_text: str,
    ) -> None:
        from app.services import missions as mission_service

        try:
            raw_extraction = await self._decision_llm_service.generate_json(
                system_prompt=_decision_extraction_system_prompt(),
                user_prompt=_decision_extraction_user_prompt(feature_task, diff_text),
                schema_hint=_decision_extraction_schema_hint(),
            )
            extraction = MissionDecisionExtraction.model_validate(raw_extraction)
        except Exception:
            logger.warning(
                "Mission decision extraction failed for feature_task=%s",
                context.feature_task_id,
                exc_info=True,
            )
            return

        for entry in extraction.decisions:
            mission_service.create_mission_decision(
                context.db,
                mission_id=context.mission_id,
                key=entry.key,
                value=entry.value,
                source_task_id=context.feature_task_id,
            )

    def _inspect_repository(self, repo_path: Path) -> list[tuple[str, SandboxResult]]:
        commands = _inspection_commands(repo_path)
        return [
            (
                logical_command,
                self._sandbox_service.run_command(
                    repo_path=str(repo_path),
                    command=actual_command,
                    timeout_seconds=30,
                ),
            )
            for logical_command, actual_command in commands
        ]


def _inspection_commands(repo_path: Path) -> list[tuple[str, str]]:
    if os.name == "nt":
        commands = [("pwd", "cd"), ("ls", "dir")]
    else:
        commands = [("pwd", "pwd"), ("ls", "ls")]

    if (repo_path / ".git").exists():
        commands.append(("git status", "git status --short"))
    return commands


def _load_validation_contract(context: AgentContext) -> dict[str, Any] | None:
    from app.services import missions as mission_service

    contract = mission_service.get_latest_validation_contract(context.db, context.mission_id)
    if contract is None:
        return None
    return {
        "id": str(_safe_getattr(contract, "id", "")),
        "content": _safe_getattr(contract, "content", ""),
        "assertions": _safe_getattr(contract, "assertions", []),
        "required_tests": _safe_getattr(contract, "required_tests", []),
    }


def _load_mission_goal(context: AgentContext) -> str:
    from app.services import missions as mission_service

    mission = mission_service.get_mission(context.db, context.mission_id)
    if mission is None:
        return ""
    return str(_safe_getattr(mission, "goal", ""))


def _load_mission_decisions(context: AgentContext) -> list[dict[str, str]]:
    from app.services import missions as mission_service

    decisions = mission_service.list_mission_decisions(context.db, context.mission_id)
    return [{"key": decision.key, "value": decision.value} for decision in decisions]


def _store_inspection_artifacts(
    context: AgentContext,
    inspection_results: list[tuple[str, SandboxResult]],
) -> list[str]:
    from app.services import missions as mission_service

    artifact_ids: list[str] = []
    for logical_command, result in inspection_results:
        artifact = mission_service.create_artifact(
            context.db,
            mission_id=context.mission_id,
            agent_run_id=context.agent_run_id,
            artifact_type="repo_inspection",
            path=logical_command,
            metadata={
                "logical_command": logical_command,
                "result": asdict(result),
            },
        )
        artifact_ids.append(str(artifact.id))
    return artifact_ids


def _store_codex_artifact(
    context: AgentContext,
    *,
    result: CodexResult,
    task_prompt: str,
) -> str:
    from app.services import missions as mission_service

    artifact = mission_service.create_artifact(
        context.db,
        mission_id=context.mission_id,
        agent_run_id=context.agent_run_id,
        artifact_type="codex_run",
        path=f"codex://agent-runs/{context.agent_run_id or 'untracked'}",
        metadata={
            "task_prompt": task_prompt,
            "result": asdict(result),
        },
    )
    return str(artifact.id)


def _store_git_diff_artifact(
    context: AgentContext,
    *,
    branch_name: str,
    git_state: dict[str, Any],
    git_diff: str,
    git_status: str,
    commit_output: str | None,
    latest_commit: str | None,
) -> str | None:
    if not git_state["is_git_repo"]:
        return None

    from app.services import missions as mission_service

    artifact = mission_service.create_artifact(
        context.db,
        mission_id=context.mission_id,
        agent_run_id=context.agent_run_id,
        artifact_type="git_diff",
        path=f"git://branches/{branch_name}/diff",
        metadata={
            "branch_name": branch_name,
            "git_state": git_state,
            "status": git_status,
            "diff": git_diff,
            "commit_output": commit_output,
            "latest_commit": latest_commit,
        },
    )
    return str(artifact.id)


def _mark_feature_task_status(context: AgentContext, status: FeatureTaskStatus) -> None:
    from app.services import missions as mission_service

    feature_task = mission_service.get_feature_task(context.db, context.feature_task_id)
    if feature_task is None:
        raise ValueError(f"FeatureTask not found: {context.feature_task_id}")
    mission_service.set_feature_task_status(context.db, feature_task, status)


def _worker_report(
    feature_task: dict[str, Any],
    validation_contract: dict[str, Any] | None,
) -> str:
    task_title = feature_task.get("title", "Untitled task")
    task_description = feature_task.get("description", "")
    contract_note = (
        "Validation contract is present and will guide implementation."
        if validation_contract
        else "No validation contract was found."
    )
    return (
        f"Would implement feature task '{task_title}'. "
        f"Task description: {task_description}. "
        f"{contract_note} No code edits were made in this MVP worker."
    )


def _task_branch_name(context: AgentContext) -> str:
    mission_short = str(context.mission_id).split("-")[0]
    task_short = str(context.feature_task_id).split("-")[0]
    # Must not be a prefix of (or nested under) the mission's own branch,
    # "mission/{mission_short}" (created on clone) - git can't have a ref
    # that is both a leaf and a directory in the same path, e.g.
    # "mission/f6aef04a" and "mission/f6aef04a/task/2e158265" collide.
    return f"task/{mission_short}/{task_short}"


def _prepare_git_branch(
    git_service: GitService,
    repo_path: Path,
    branch_name: str,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "is_git_repo": False,
        "branch_name": branch_name,
        "branch_ready": False,
        "starting_branch": None,
        "checkout_action": None,
    }
    if not git_service.is_git_repo(str(repo_path)):
        return state

    state["is_git_repo"] = True
    state["starting_branch"] = git_service.current_branch(str(repo_path))
    try:
        git_service.checkout_branch(str(repo_path), branch_name)
        state["checkout_action"] = "checkout_existing"
    except GitServiceError:
        git_service.create_branch(str(repo_path), branch_name)
        state["checkout_action"] = "create_branch"

    state["current_branch"] = git_service.current_branch(str(repo_path))
    state["branch_ready"] = state["current_branch"] == branch_name
    return state


def _capture_git_diff(
    git_service: GitService,
    repo_path: Path,
    git_state: dict[str, Any],
) -> str:
    if not git_state["is_git_repo"]:
        return ""
    return git_service.diff(str(repo_path))


def _capture_git_status(
    git_service: GitService,
    repo_path: Path,
    git_state: dict[str, Any],
) -> str:
    if not git_state["is_git_repo"]:
        return ""
    return git_service.status(str(repo_path))


def _codex_task_prompt(
    *,
    mission_goal: str,
    feature_task: dict[str, Any],
    validation_contract: dict[str, Any] | None,
    allow_commits: bool,
    mission_decisions: list[dict[str, str]] | None = None,
) -> str:
    assertions = _format_assertions(validation_contract)
    required_tests = _format_required_tests(validation_contract)
    decisions_section = _format_mission_decisions(mission_decisions)
    commit_rule = (
        "Commits are allowed by configuration, but only commit if this task explicitly requires it."
        if allow_commits
        else "Do not commit unless asked."
    )
    return f"""You are a coding worker in a controlled multi-agent orchestrator.

Mission goal:
{mission_goal or "No mission goal was provided."}{decisions_section}

Feature task:
Title: {feature_task.get("title", "Untitled task")}
Description: {feature_task.get("description", "")}
Task type: {feature_task.get("task_type", "unknown")}

Relevant validation contract assertions:
{assertions}

Required tests from validation contract:
{required_tests}

Rules:
- Modify only files needed for this task.
- Run tests if available.
- Do not delete unrelated code.
- Summarize changes and tests run in your final output.
- {commit_rule}
"""


def _format_mission_decisions(mission_decisions: list[dict[str, str]] | None) -> str:
    if not mission_decisions:
        return ""
    lines = ["\n\nPrior decisions in this mission (stay consistent with these):"]
    for decision in mission_decisions:
        key = decision.get("key", "")
        value = decision.get("value", "")
        if key or value:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _format_assertions(validation_contract: dict[str, Any] | None) -> str:
    if not validation_contract:
        return "- No validation contract assertions were found."
    assertions = validation_contract.get("assertions", [])
    if not isinstance(assertions, list) or not assertions:
        return "- No validation contract assertions were found."

    lines: list[str] = []
    for assertion in assertions:
        if not isinstance(assertion, dict):
            continue
        assertion_id = assertion.get("id", "assertion")
        description = assertion.get("description", "")
        validation_method = assertion.get("validation_method", "unspecified")
        lines.append(f"- {assertion_id}: {description} (method: {validation_method})")
    return "\n".join(lines) if lines else "- No validation contract assertions were found."


def _format_required_tests(validation_contract: dict[str, Any] | None) -> str:
    if not validation_contract:
        return "- No required tests were found."
    required_tests = validation_contract.get("required_tests", [])
    if not isinstance(required_tests, list) or not required_tests:
        return "- No required tests were found."

    lines: list[str] = []
    for test in required_tests:
        if not isinstance(test, dict):
            continue
        name = test.get("name", "unnamed test")
        test_type = test.get("type", "unknown")
        command = test.get("command", "")
        lines.append(f"- {name} [{test_type}]: {command}")
    return "\n".join(lines) if lines else "- No required tests were found."


def _decision_extraction_system_prompt() -> str:
    return """Mission decision extractor
You read a completed coding task's description and code diff, and extract concrete
implementation decisions that other tasks in the same mission should stay consistent with.

Rules:
- Only extract decisions that would affect how OTHER tasks in the same mission should be
  implemented (e.g. auth scheme, error response shape, naming conventions, library choices).
- Do not invent decisions that are not evidenced by the diff or task description.
- If nothing decision-worthy happened, return an empty list.
- Each key must be a short lowercase snake_case slug (e.g. "auth_scheme").
- Each value must be a short, concrete phrase (e.g. "JWT with refresh tokens").
- Return only valid JSON."""


def _decision_extraction_user_prompt(feature_task: dict[str, Any], diff_text: str) -> str:
    truncated_diff = diff_text[:_MAX_DECISION_DIFF_CHARS].strip()
    return f"""Extract key decisions from this completed task.

Task title:
{feature_task.get("title", "Untitled task")}

Task description:
{feature_task.get("description", "")}

Code diff or status (may be truncated):
{truncated_diff or "No diff was captured."}"""


def _decision_extraction_schema_hint() -> dict[str, Any]:
    return {
        "decisions": [
            {"key": "string", "value": "string"},
        ],
    }


def _parse_changed_files(git_status: str) -> list[str]:
    """Parse `git status --short` output into a list of file paths."""
    files: list[str] = []
    for line in git_status.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            files.append(parts[1])
    return files


def _safe_getattr(value: Any, name: str, default: Any) -> Any:
    try:
        return getattr(value, name)
    except AttributeError:
        return default


def _inspection_result_to_dict(result: tuple[str, SandboxResult]) -> dict[str, Any]:
    logical_command, sandbox_result = result
    data = asdict(sandbox_result)
    data["logical_command"] = logical_command
    data["executed_command"] = sandbox_result.command
    return data
