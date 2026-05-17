from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import TestCase

from app.core.config import Settings
from app.services.sandbox_service import E2BSandboxProvider, LocalSandboxProvider, SandboxService


class SandboxServiceTests(TestCase):
    def setUp(self) -> None:
        self.service = SandboxService()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name)
        (self.repo_path / "sample.txt").write_text("hello", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_can_run_pwd(self) -> None:
        command = "cd" if os.name == "nt" else "pwd"

        result = self.service.run_command(str(self.repo_path), command)

        self.assertEqual(result.exit_code, 0)
        self.assertIn(str(self.repo_path), result.stdout.strip())
        self.assertFalse(result.timed_out)

    def test_can_run_ls(self) -> None:
        command = "dir" if os.name == "nt" else "ls"

        result = self.service.run_command(str(self.repo_path), command)

        self.assertEqual(result.exit_code, 0)
        self.assertIn("sample.txt", result.stdout)

    def test_captures_exit_code(self) -> None:
        result = self.service.run_command(str(self.repo_path), "python -c \"import sys; sys.exit(7)\"")

        self.assertEqual(result.exit_code, 7)

    def test_timeout_works(self) -> None:
        result = self.service.run_command(
            str(self.repo_path),
            "python -c \"import time; time.sleep(2)\"",
            timeout_seconds=1,
        )

        self.assertEqual(result.exit_code, -1)
        self.assertTrue(result.timed_out)
        self.assertIn("timed out", result.stderr)

    def test_empty_command_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            self.service.run_command(str(self.repo_path), " ")

    def test_run_test_commands_returns_results_in_order(self) -> None:
        command = "dir" if os.name == "nt" else "ls"

        results = self.service.run_test_commands(str(self.repo_path), [command, command])

        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.exit_code == 0 for result in results))

    def test_uses_local_provider_from_settings(self) -> None:
        service = SandboxService(settings=Settings(sandbox_provider="local"))

        self.assertEqual(service.provider_name, "local")
        self.assertIsInstance(service.provider, LocalSandboxProvider)

    def test_can_select_e2b_provider_from_settings(self) -> None:
        service = SandboxService(settings=Settings(sandbox_provider="e2b", e2b_api_key="test-key"))

        self.assertEqual(service.provider_name, "e2b")
        self.assertIsInstance(service.provider, E2BSandboxProvider)

    def test_e2b_provider_requires_api_key_to_run(self) -> None:
        service = SandboxService(settings=Settings(sandbox_provider="e2b"))

        with self.assertRaisesRegex(RuntimeError, "E2B_API_KEY"):
            service.run_command(str(self.repo_path), "pwd")
