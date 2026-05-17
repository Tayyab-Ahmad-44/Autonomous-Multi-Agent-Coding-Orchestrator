from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

from app.agents.base import AgentContext, AgentInput, AgentOutput, BaseAgent
from app.services.sandbox_service import SandboxResult, SandboxService


class ValidatorAgent(BaseAgent):
    agent_type = "validator"

    def __init__(self, sandbox_service: SandboxService | None = None) -> None:
        self._sandbox_service = sandbox_service or SandboxService()

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        if context.repo_path is None:
            raise ValueError("ValidatorAgent requires repo_path in AgentContext.")

        contract = _validation_contract_from_input(context, input)
        milestone = input.data.get("milestone")
        milestone_id = _milestone_id(milestone)
        required_tests = _required_tests(contract)

        results: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        artifact_ids: list[str] = []

        for test in required_tests:
            test_type = str(test.get("type", "")).strip().lower()
            command = str(test.get("command", "")).strip()
            if test_type not in _EXECUTABLE_TEST_TYPES:
                skipped.append(
                    {
                        "name": test.get("name"),
                        "type": test_type,
                        "reason": (
                            "Only shell, pytest, playwright, and semgrep tests are executable "
                            "in ValidatorAgent v1."
                        ),
                    }
                )
                continue
            if not command:
                result_data = _empty_command_result(context, test)
                results.append(result_data)
                issues.append(
                    {
                        "name": test.get("name"),
                        "type": test.get("type"),
                        "command": "",
                        "exit_code": -1,
                        "stdout": "",
                        "stderr": "Required test command is empty.",
                        "timed_out": False,
                    }
                )
                continue

            result = self._sandbox_service.run_command(
                repo_path=str(context.repo_path),
                command=command,
                timeout_seconds=int(test.get("timeout_seconds", 300)),
            )
            result_data = _validation_result_to_dict(test, result)
            if test_type == "playwright":
                playwright_artifact_ids = _store_playwright_artifacts(context)
                result_data["artifact_ids"] = playwright_artifact_ids
                artifact_ids.extend(playwright_artifact_ids)
            if test_type == "semgrep":
                semgrep_data = _parse_semgrep_output(result.stdout)
                semgrep_artifact_id = _store_semgrep_artifact(
                    context,
                    test=test,
                    result=result,
                    semgrep_data=semgrep_data,
                )
                result_data["semgrep"] = semgrep_data
                result_data["artifact_ids"] = [semgrep_artifact_id]
                artifact_ids.append(semgrep_artifact_id)
                semgrep_issues = _issues_from_semgrep_findings(
                    test,
                    result,
                    semgrep_data=semgrep_data,
                    artifact_id=semgrep_artifact_id,
                )
                issues.extend(semgrep_issues)
            results.append(result_data)

            if result.exit_code != 0:
                if test_type != "semgrep" or not semgrep_issues:
                    issues.append(_issue_from_result(test, result, artifact_ids=result_data.get("artifact_ids", [])))

        passed = all(result["exit_code"] == 0 for result in results) and not issues
        summary = _summary(passed=passed, results=results, skipped=skipped)
        report = _store_validation_report(
            context=context,
            milestone_id=milestone_id,
            passed=passed,
            summary=summary,
            issues=issues,
            raw_output={
                "results": results,
                "skipped": skipped,
                "artifact_ids": artifact_ids,
            },
        )

        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary=summary,
            data={
                "mission_id": str(context.mission_id),
                "milestone_id": str(milestone_id) if milestone_id else None,
                "validation_report_id": str(report.id),
                "passed": passed,
                "issues": issues,
                "results": results,
                "skipped": skipped,
                "artifact_ids": artifact_ids,
            },
        )


_EXECUTABLE_TEST_TYPES = {"shell", "pytest", "playwright", "semgrep"}
_PLAYWRIGHT_ARTIFACT_DIRS = ("test-results", "playwright-report")
_PLAYWRIGHT_MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".mov"}
_SEMGREP_FAILING_SEVERITIES = {"HIGH", "CRITICAL"}


def _validation_contract_from_input(context: AgentContext, input: AgentInput) -> dict[str, Any]:
    contract = input.data.get("validation_contract")
    if isinstance(contract, dict):
        return contract

    from app.services import missions as mission_service

    stored_contract = mission_service.get_latest_validation_contract(context.db, context.mission_id)
    if stored_contract is None:
        raise ValueError("ValidatorAgent requires a validation contract.")
    return {
        "id": str(stored_contract.id),
        "content": stored_contract.content,
        "assertions": stored_contract.assertions,
        "required_tests": stored_contract.required_tests,
    }


def _required_tests(contract: dict[str, Any]) -> list[dict[str, Any]]:
    required_tests = contract.get("required_tests", [])
    if not isinstance(required_tests, list):
        raise ValueError("Validation contract required_tests must be a list.")
    return [test for test in required_tests if isinstance(test, dict)]


def _milestone_id(milestone: Any) -> UUID | None:
    if not isinstance(milestone, dict):
        return None
    raw_milestone_id = milestone.get("id")
    if not raw_milestone_id:
        return None
    return UUID(str(raw_milestone_id))


def _validation_result_to_dict(test: dict[str, Any], result: SandboxResult) -> dict[str, Any]:
    data = asdict(result)
    data.update(
        {
            "name": test.get("name"),
            "type": test.get("type"),
        }
    )
    return data


def _empty_command_result(context: AgentContext, test: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": "",
        "repo_path": str(context.repo_path),
        "stdout": "",
        "stderr": "Required test command is empty.",
        "exit_code": -1,
        "duration_seconds": 0.0,
        "timed_out": False,
        "name": test.get("name"),
        "type": test.get("type"),
    }


def _issue_from_result(
    test: dict[str, Any],
    result: SandboxResult,
    *,
    artifact_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": test.get("name"),
        "type": test.get("type"),
        "command": result.command,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timed_out": result.timed_out,
        "artifact_ids": artifact_ids or [],
    }


def _summary(
    *,
    passed: bool,
    results: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> str:
    status = "passed" if passed else "failed"
    return (
        f"Validation {status}: {len(results)} executable test(s) run, "
        f"{len(skipped)} unsupported test(s) skipped."
    )


def _store_validation_report(
    *,
    context: AgentContext,
    milestone_id: UUID | None,
    passed: bool,
    summary: str,
    issues: list[dict[str, Any]],
    raw_output: dict[str, Any],
) -> Any:
    from app.services import missions as mission_service

    return mission_service.create_validation_report(
        context.db,
        mission_id=context.mission_id,
        milestone_id=milestone_id,
        validator_type=ValidatorAgent.agent_type,
        passed=passed,
        summary=summary,
        issues=issues,
        raw_output=raw_output,
    )


def _store_playwright_artifacts(context: AgentContext) -> list[str]:
    if context.repo_path is None:
        return []

    from app.services import missions as mission_service

    repo_path = context.repo_path.resolve()
    artifact_ids: list[str] = []
    for artifact_path in _find_playwright_artifacts(repo_path):
        artifact = mission_service.create_artifact(
            context.db,
            mission_id=context.mission_id,
            agent_run_id=context.agent_run_id,
            artifact_type="playwright_artifact",
            path=_relative_path(repo_path, artifact_path),
            metadata={
                "absolute_path": str(artifact_path),
                "source": "playwright",
                "suffix": artifact_path.suffix.lower(),
            },
        )
        artifact_ids.append(str(artifact.id))
    return artifact_ids


def _find_playwright_artifacts(repo_path: Path) -> list[Path]:
    artifacts: list[Path] = []
    for directory_name in _PLAYWRIGHT_ARTIFACT_DIRS:
        directory = repo_path / directory_name
        if not directory.exists() or not directory.is_dir():
            continue
        artifacts.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in _PLAYWRIGHT_MEDIA_EXTENSIONS
        )
    return sorted(artifacts)


def _relative_path(repo_path: Path, artifact_path: Path) -> str:
    try:
        return artifact_path.relative_to(repo_path).as_posix()
    except ValueError:
        return str(artifact_path)


def _parse_semgrep_output(stdout: str) -> dict[str, Any]:
    if not stdout.strip():
        return {
            "parsed": None,
            "parse_error": "Semgrep stdout was empty.",
            "high_or_critical_findings": [],
        }
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {
            "parsed": None,
            "parse_error": f"Semgrep stdout was not valid JSON: {exc}",
            "high_or_critical_findings": [],
        }

    findings = _high_or_critical_semgrep_findings(parsed)
    return {
        "parsed": parsed,
        "parse_error": None,
        "high_or_critical_findings": findings,
    }


def _high_or_critical_semgrep_findings(parsed: Any) -> list[dict[str, Any]]:
    if not isinstance(parsed, dict):
        return []
    raw_results = parsed.get("results", [])
    if not isinstance(raw_results, list):
        return []

    findings: list[dict[str, Any]] = []
    for finding in raw_results:
        if not isinstance(finding, dict):
            continue
        severity = _semgrep_severity(finding)
        if severity in _SEMGREP_FAILING_SEVERITIES:
            findings.append(finding)
    return findings


def _semgrep_severity(finding: dict[str, Any]) -> str:
    extra = finding.get("extra", {})
    if not isinstance(extra, dict):
        return ""
    return str(extra.get("severity", "")).strip().upper()


def _issues_from_semgrep_findings(
    test: dict[str, Any],
    result: SandboxResult,
    *,
    semgrep_data: dict[str, Any],
    artifact_id: str,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    findings = semgrep_data.get("high_or_critical_findings", [])
    if not isinstance(findings, list):
        return issues

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        extra = finding.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}
        issues.append(
            {
                "name": test.get("name"),
                "type": "semgrep",
                "command": result.command,
                "exit_code": result.exit_code,
                "severity": _semgrep_severity(finding),
                "check_id": finding.get("check_id"),
                "path": finding.get("path"),
                "start": finding.get("start"),
                "message": extra.get("message"),
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timed_out": result.timed_out,
                "artifact_ids": [artifact_id],
            }
        )
    return issues


def _store_semgrep_artifact(
    context: AgentContext,
    *,
    test: dict[str, Any],
    result: SandboxResult,
    semgrep_data: dict[str, Any],
) -> str:
    from app.services import missions as mission_service

    artifact = mission_service.create_artifact(
        context.db,
        mission_id=context.mission_id,
        agent_run_id=context.agent_run_id,
        artifact_type="semgrep_output",
        path=f"semgrep://{_artifact_slug(str(test.get('name') or 'semgrep'))}",
        metadata={
            "test_name": test.get("name"),
            "command": result.command,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "semgrep": semgrep_data,
        },
    )
    return str(artifact.id)


def _artifact_slug(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in slug.split("-") if part) or "semgrep"
