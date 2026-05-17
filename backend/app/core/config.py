from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/agent_orchestrator"
    redis_url: str = "redis://localhost:6379/0"
    openai_api_key: str = ""
    default_llm_model: str = "gpt-4.1-mini"
    celery_task_always_eager: bool = False
    codex_enabled: bool = False
    codex_command: str = "codex"
    codex_allow_commits: bool = False
    auto_commit: bool = False
    sandbox_provider: Literal["local", "e2b"] = "local"
    e2b_api_key: str | None = None
    max_agent_retries: int = Field(default=2, ge=0)
    max_validation_loops: int = Field(default=3, ge=0)
    workspace_root: str = "/workspaces"
    github_token: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
