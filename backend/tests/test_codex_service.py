from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app.core.config import Settings
from app.services.codex_service import CodexService


class CodexServiceTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_run_codex_task_invokes_codex_exec_from_repo_path(self) -> None:
        service = CodexService(settings=Settings(codex_command="codex-test"))
        completed = subprocess.CompletedProcess(
            args=["codex-test", "exec", "do work"],
            returncode=0,
            stdout="done",
            stderr="",
        )

        with patch("app.services.codex_service.subprocess.run", return_value=completed) as run:
            result = service.run_codex_task(str(self.repo_path), "do work")

        command = run.call_args.args[0]
        self.assertEqual(command, ["codex-test", "exec", "--sandbox", "workspace-write", "do work"])
        self.assertEqual(Path(run.call_args.kwargs["cwd"]), self.repo_path.resolve())
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout, "done")
        self.assertFalse(result.timed_out)

    def test_run_codex_task_reuses_exec_when_configured(self) -> None:
        service = CodexService(settings=Settings(codex_command="codex-test exec --sandbox workspace-write"))
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="done",
            stderr="",
        )

        with patch("app.services.codex_service.subprocess.run", return_value=completed) as run:
            service.run_codex_task(str(self.repo_path), "do work")

        command = run.call_args.args[0]
        self.assertEqual(command, ["codex-test", "exec", "--sandbox", "workspace-write", "do work"])

    def test_run_codex_task_timeout_is_captured(self) -> None:
        service = CodexService(settings=Settings(codex_command="codex-test"))

        with patch(
            "app.services.codex_service.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                cmd=["codex-test", "exec", "do work"],
                timeout=1,
                output="partial",
                stderr="",
            ),
        ):
            result = service.run_codex_task(str(self.repo_path), "do work", timeout_seconds=1)

        self.assertEqual(result.exit_code, -1)
        self.assertTrue(result.timed_out)
        self.assertIn("timed out", result.stderr)

    def test_run_codex_task_rejects_empty_prompt(self) -> None:
        service = CodexService(settings=Settings(codex_command="codex-test"))

        with self.assertRaisesRegex(ValueError, "prompt must not be empty"):
            service.run_codex_task(str(self.repo_path), " ")


def test_codex_command_adds_model_and_effort_overrides():
    from app.services.codex_service import _codex_command

    command = _codex_command(
        "codex",
        "do work",
        sandbox="workspace-write",
        model="gpt-5.4",
        reasoning_effort="medium",
    )

    assert command == [
        "codex", "exec", "--sandbox", "workspace-write",
        "--model", "gpt-5.4", "-c", "model_reasoning_effort=medium", "do work",
    ]


def test_api_key_auth_passes_key_only_to_codex(tmp_path):
    from unittest.mock import patch
    import subprocess as sp
    from app.core.config import Settings
    from app.services.codex_service import CodexService

    service = CodexService(settings=Settings(codex_auth="api_key", openai_api_key="sk-test"))
    done = sp.CompletedProcess(["codex"], 0, stdout="ok", stderr="")
    with patch("app.services.codex_service.subprocess.run", return_value=done) as run:
        service.run_codex_task(str(tmp_path), "do work")
    assert run.call_args.kwargs["env"]["CODEX_API_KEY"] == "sk-test"
    assert "sk-test" not in " ".join(run.call_args.args[0])


def test_chatgpt_auth_does_not_inject_key(tmp_path):
    from unittest.mock import patch
    import subprocess as sp
    from app.core.config import Settings
    from app.services.codex_service import CodexService

    service = CodexService(settings=Settings(codex_auth="chatgpt", openai_api_key="sk-test"))
    done = sp.CompletedProcess(["codex"], 0, stdout="ok", stderr="")
    with patch("app.services.codex_service.subprocess.run", return_value=done) as run:
        service.run_codex_task(str(tmp_path), "do work")
    env = run.call_args.kwargs["env"]
    assert env is None or "CODEX_API_KEY" not in env
