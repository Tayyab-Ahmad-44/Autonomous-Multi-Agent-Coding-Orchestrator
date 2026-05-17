from celery import Celery

from app.core.config import get_settings


settings = get_settings()

celery_app = Celery(
    "agent_orchestrator",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    accept_content=["json"],
    result_serializer="json",
    task_always_eager=settings.celery_task_always_eager,
    task_serializer="json",
    timezone="UTC",
)
