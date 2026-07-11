from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from app.agents import AgentContext, AgentInput, build_default_registry
from app.core.database import get_session_local
from app.services import missions as mission_service
from app.workers.celery_app import celery_app


def _advance_mission(db, mission_id) -> None:
    from app.orchestration.mission_graph import run_mission_until_blocked

    try:
        asyncio.run(run_mission_until_blocked(db, mission_id))
    except Exception as exc:
        mission_service.log_mission_event(
            db,
            mission_id=mission_id,
            event_type="orchestration_error",
            message=f"Auto-advance failed: {exc}",
            payload={},
        )


@celery_app.task(name="app.workers.tasks.run_agent_task")
def run_agent_task(agent_run_id: str) -> dict[str, str]:
    db = get_session_local()()
    try:
        agent_run = mission_service.get_agent_run(db, UUID(agent_run_id))
        if agent_run is None:
            raise ValueError(f"AgentRun not found: {agent_run_id}")

        mission_service.mark_agent_run_running(db, agent_run)
        try:
            registry = build_default_registry()
            agent = registry.get(agent_run.agent_type)
            repository = mission_service.get_repository(db, agent_run.mission_id)
            repo_path = Path(repository.local_path) if repository and repository.local_path else None
            output = asyncio.run(
                agent.run(
                    AgentContext(
                        mission_id=agent_run.mission_id,
                        feature_task_id=agent_run.feature_task_id,
                        agent_run_id=agent_run.id,
                        db=db,
                        repo_path=repo_path,
                    ),
                    AgentInput(
                        instructions=str(agent_run.input.get("instructions", "")),
                        data=dict(agent_run.input.get("data", {})),
                    ),
                )
            )
            output_payload = {
                "status": output.status,
                "summary": output.summary,
                "data": output.data,
            }
            output_error = output.summary if output.status == "failed" else None
            mission_service.complete_agent_run(
                db,
                agent_run,
                output=output_payload,
                error=output_error,
            )
            _advance_mission(db, agent_run.mission_id)
            return {"agent_run_id": agent_run_id, "status": output.status}
        except Exception as exc:
            mission_service.complete_agent_run(db, agent_run, error=str(exc))
            _advance_mission(db, agent_run.mission_id)
            return {"agent_run_id": agent_run_id, "status": "failed"}
    finally:
        db.close()
