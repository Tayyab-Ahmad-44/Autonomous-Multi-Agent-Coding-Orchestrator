"""Keep the test suite independent of the developer's local backend/.env.

pydantic-settings gives real environment variables priority over .env, so
pinning them here stops a local CODEX_ENABLED=true (or real API keys) from
leaking into tests that expect the stub worker.
"""
import os

_TEST_ENV = {
    "CODEX_ENABLED": "false",
    "CODEX_COMMAND": "codex",
    "CODEX_SANDBOX": "workspace-write",
    "CODEX_MODEL": "",
    "CODEX_AUTH": "chatgpt",
    "CODEX_REASONING_EFFORT": "",
    "AUTO_COMMIT": "false",
    "CODEX_ALLOW_COMMITS": "false",
    "CELERY_TASK_ALWAYS_EAGER": "false",
    "SANDBOX_PROVIDER": "local",
    "MISSION_ENV_ENABLED": "false",
    "OPENAI_API_KEY": "",
    "GITHUB_TOKEN": "",
    "MAX_AGENT_RETRIES": "2",
    "MAX_VALIDATION_LOOPS": "3",
}
os.environ.update(_TEST_ENV)

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()
