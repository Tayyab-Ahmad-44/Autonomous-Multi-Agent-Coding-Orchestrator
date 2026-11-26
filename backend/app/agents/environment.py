from __future__ import annotations

import logging

from app.agents.base import AgentContext
from app.services.mission_environment import EnvironmentResult, MissionEnvironmentService

logger = logging.getLogger(__name__)


def prepare_mission_environment(
    context: AgentContext,
    service: MissionEnvironmentService | None = None,
) -> EnvironmentResult | None:
    """Create or reuse the mission's virtualenv before running repo commands.

    Best-effort: a failed install is logged as a mission event (so it shows in
    the UI timeline) but never fails the agent; the repo's tests will surface
    the real problem.
    """
    if context.repo_path is None:
        return None
    try:
        result = (service or MissionEnvironmentService()).ensure(context.repo_path)
    except Exception as exc:  # noqa: BLE001 - environment setup must not crash agents
        logger.exception("Mission environment setup crashed")
        result = EnvironmentResult(status="failed", log=[f"crashed: {exc}"])

    if result.status in {"ready", "failed"}:
        from app.services import missions as mission_service

        message = (
            f"Python environment ready ({result.manifest_dir} requirements, {result.duration_seconds:.0f}s)."
            if result.status == "ready"
            else "Python environment setup failed; tests will run without the repo's dependencies."
        )
        mission_service.log_mission_event(
            context.db,
            mission_id=context.mission_id,
            event_type=f"environment_{result.status}",
            message=message,
            payload={
                "venv_path": result.venv_path,
                "manifest_dir": result.manifest_dir,
                "log_tail": "\n".join(result.log)[-3000:],
            },
        )
    return result
