from app.services.repo_analysis_service import _read_text


def test_read_text_decodes_utf16_readme_without_nul_bytes(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_bytes("# Ticket Agent\nFastAPI app".encode("utf-16"))

    text = _read_text(readme)

    assert text == "# Ticket Agent\nFastAPI app"
    assert "\x00" not in text


def test_read_text_strips_utf8_bom(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_bytes(b"\xef\xbb\xbffastapi\n")

    assert _read_text(req) == "fastapi\n"


def test_read_text_missing_file_returns_none(tmp_path):
    assert _read_text(tmp_path / "nope.md") is None


def test_analyze_repo_detects_monorepo_subfolders(tmp_path):
    from app.services.repo_analysis_service import RepoAnalysisService

    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements.txt").write_bytes("fastapi==0.110\npytest\n".encode("utf-16"))
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(
        '{"dependencies": {"react": "18"}, "scripts": {"build": "vite build"}}'
    )
    (tmp_path / "frontend" / "package-lock.json").write_text("{}")

    profile = RepoAnalysisService().analyze_repo(str(tmp_path))

    assert profile.backend_framework == "FastAPI"
    assert profile.frontend_framework == "React"
    assert profile.language == "Python + JavaScript/TypeScript"
    assert "cd backend && pytest" in profile.test_commands
    assert profile.build_commands == ["cd frontend && npm run build"]
    assert profile.raw_data["py_manifest_dir"] == "backend"


def test_python_project_gets_pytest_command_even_if_unlisted(tmp_path):
    from app.services.repo_analysis_service import RepoAnalysisService

    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements.txt").write_text("fastapi\n")

    assert RepoAnalysisService().analyze_repo(str(tmp_path)).test_commands == ["cd backend && pytest"]


def test_spec_prompt_includes_repo_test_commands():
    from app.agents.spec import _system_prompt, _user_prompt

    prompt = _user_prompt(
        goal="g", milestones=[], feature_tasks=[],
        repo_profile={"test_commands": ["cd backend && pytest"], "backend_framework": "FastAPI"},
    )
    assert "cd backend && pytest" in prompt
    assert "import app" in _system_prompt()  # the rule forbidding ad-hoc import checks
