from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession
from app.models import FeatureTaskStatus
from app.schemas import AgentRunRead
from app.services import missions as mission_service
from app.workers.tasks import run_agent_task


router = APIRouter(prefix="/feature-tasks", tags=["feature-tasks"])


@router.post("/{task_id}/run", response_model=AgentRunRead, status_code=status.HTTP_202_ACCEPTED)
def run_feature_task(task_id: UUID, db: DbSession) -> AgentRunRead:
    feature_task = mission_service.get_feature_task(db, task_id)
    if feature_task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature task not found")

    mission = mission_service.get_mission_with_details(db, feature_task.mission_id)
    if mission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found")

    active_run = mission_service.get_active_agent_run_for_feature_task(mission, feature_task.id)
    if active_run is not None:
        return active_run

    agent_run = mission_service.create_agent_run_for_feature_task(db, feature_task)
    mission_service.set_feature_task_status(db, feature_task, FeatureTaskStatus.running)
    run_agent_task.delay(str(agent_run.id))

    db.expire(agent_run)
    refreshed = mission_service.get_agent_run(db, agent_run.id)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    return refreshed
