from __future__ import annotations

from typing import Any

from app.agents.base import AgentContext, AgentInput, AgentOutput, BaseAgent


class FixPlannerAgent(BaseAgent):
    agent_type = "fix_planner"

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        issues = _issues_from_input(input)
        fix_tasks = [_fix_task_from_issue(issue, index) for index, issue in enumerate(issues, start=1)]
        if not fix_tasks:
            fix_tasks = [
                {
                    "title": "Investigate failed validation",
                    "description": (
                        "Validation failed, but no structured issue was provided. "
                        "Inspect the latest validation report and repair the failing behavior."
                    ),
                    "task_type": "fix",
                    "assigned_agent_type": "worker",
                }
            ]

        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary=f"Created {len(fix_tasks)} deterministic fix task(s).",
            data={
                "mission_id": str(context.mission_id),
                "fix_tasks": fix_tasks,
            },
        )


def _issues_from_input(input: AgentInput) -> list[dict[str, Any]]:
    report = input.data.get("validation_report", {})
    issues = report.get("issues", []) if isinstance(report, dict) else []
    return [issue for issue in issues if isinstance(issue, dict)]


def _fix_task_from_issue(issue: dict[str, Any], index: int) -> dict[str, str]:
    name = str(issue.get("name") or f"validation issue {index}")
    command = str(issue.get("command") or "unknown command")
    exit_code = issue.get("exit_code", "unknown")
    stderr = str(issue.get("stderr") or "").strip()
    stdout = str(issue.get("stdout") or "").strip()
    output = stderr or stdout or "No command output captured."
    return {
        "title": f"Fix validation failure: {name}",
        "description": (
            f"Repair the behavior covered by validation command `{command}` "
            f"which exited with code {exit_code}. "
            f"Captured output: {output}"
        ),
        "task_type": "fix",
        "assigned_agent_type": "worker",
    }
