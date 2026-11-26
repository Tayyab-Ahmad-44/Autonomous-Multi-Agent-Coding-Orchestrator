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
    # Codex defaults to a read-only sandbox in `exec` mode, which makes the
    # worker unable to edit files. workspace-write limits writes to the repo.
    codex_sandbox: str = "workspace-write"
    # Optional overrides for ~/.codex/config.toml (e.g. when the global model
    # isn't available for the logged-in account).
    codex_model: str = ""
    # "chatgpt": use the CLI's own login. "api_key": pass OPENAI_API_KEY to
    # Codex as CODEX_API_KEY for orchestrator runs only (billed per token),
    # leaving the user's global Codex login untouched.
    codex_auth: Literal["chatgpt", "api_key"] = "chatgpt"
    codex_reasoning_effort: str = ""
    codex_allow_commits: bool = False
    auto_commit: bool = False
    sandbox_provider: Literal["local", "e2b"] = "local"
    # Per-mission virtualenv with the target repo's requirements installed, so
    # validators and Codex run the repo's tests with its real dependencies.
    mission_env_enabled: bool = True
    mission_python_version: str = "3.12"
    mission_env_install_timeout_seconds: int = Field(default=900, ge=30)
    e2b_api_key: str | None = None
    max_agent_retries: int = Field(default=2, ge=0)
    max_validation_loops: int = Field(default=3, ge=0)
    workspace_root: str = "/workspaces"
    github_token: str | None = None
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=60, ge=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
