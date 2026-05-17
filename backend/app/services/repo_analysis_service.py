from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RepoProfileData:
    frontend_framework: str | None = None
    backend_framework: str | None = None
    package_manager: str | None = None
    language: str | None = None
    test_commands: list[str] = field(default_factory=list)
    build_commands: list[str] = field(default_factory=list)
    important_dirs: list[str] = field(default_factory=list)
    has_docker: bool = False
    has_ci: bool = False
    readme_summary: str | None = None
    raw_data: dict = field(default_factory=dict)


class RepoAnalysisService:
    def analyze_repo(self, local_path: str) -> RepoProfileData:
        root = Path(local_path)
        profile = RepoProfileData()
        raw: dict = {}

        # Collect file presence
        package_json = _read_json(root / "package.json")
        pyproject = _read_text(root / "pyproject.toml")
        requirements = _read_text(root / "requirements.txt")
        poetry_lock = (root / "poetry.lock").exists()
        pnpm_lock = (root / "pnpm-lock.yaml").exists()
        package_lock = (root / "package-lock.json").exists()
        yarn_lock = (root / "yarn.lock").exists()
        has_dockerfile = (root / "Dockerfile").exists() or (root / "dockerfile").exists()
        has_compose = (root / "docker-compose.yml").exists() or (root / "docker-compose.yaml").exists()
        readme_text = _read_text(root / "README.md") or _read_text(root / "readme.md")

        raw["has_package_json"] = package_json is not None
        raw["has_pyproject"] = pyproject is not None
        raw["has_requirements"] = requirements is not None

        # Package manager
        if pnpm_lock:
            profile.package_manager = "pnpm"
        elif yarn_lock:
            profile.package_manager = "yarn"
        elif package_lock:
            profile.package_manager = "npm"
        elif poetry_lock:
            profile.package_manager = "poetry"
        elif pyproject and "poetry" in pyproject:
            profile.package_manager = "poetry"
        elif requirements:
            profile.package_manager = "pip"

        # Frontend framework
        if package_json:
            deps = {**package_json.get("dependencies", {}), **package_json.get("devDependencies", {})}
            if "next" in deps:
                profile.frontend_framework = "Next.js"
            elif "react" in deps and "vue" not in deps:
                profile.frontend_framework = "React"
            elif "vue" in deps:
                profile.frontend_framework = "Vue"
            elif "@angular/core" in deps:
                profile.frontend_framework = "Angular"
            elif "svelte" in deps:
                profile.frontend_framework = "Svelte"
            raw["npm_deps"] = list(deps.keys())[:30]

        # Backend framework
        if pyproject or requirements:
            text = (pyproject or "") + (requirements or "")
            if "fastapi" in text.lower():
                profile.backend_framework = "FastAPI"
            elif "django" in text.lower():
                profile.backend_framework = "Django"
            elif "flask" in text.lower():
                profile.backend_framework = "Flask"

        if package_json and not profile.backend_framework:
            deps = {**package_json.get("dependencies", {}), **package_json.get("devDependencies", {})}
            if "express" in deps:
                profile.backend_framework = "Express"
            elif "fastify" in deps:
                profile.backend_framework = "Fastify"

        # Language
        if pyproject or requirements:
            profile.language = "Python"
        elif package_json and not profile.language:
            profile.language = "JavaScript/TypeScript"

        # Test commands
        if package_json:
            scripts = package_json.get("scripts", {})
            test_script = scripts.get("test")
            if test_script:
                profile.test_commands.append(f"npm test")
        if pyproject and "pytest" in pyproject:
            profile.test_commands.append("pytest")
        elif requirements and "pytest" in requirements:
            profile.test_commands.append("pytest")

        # Build commands
        if package_json:
            scripts = package_json.get("scripts", {})
            if "build" in scripts:
                mgr = profile.package_manager or "npm"
                profile.build_commands.append(f"{mgr} run build")

        # Docker / CI
        profile.has_docker = has_dockerfile or has_compose
        ci_dirs = [".github/workflows", ".circleci", ".gitlab-ci.yml", "Jenkinsfile"]
        profile.has_ci = any((root / d).exists() for d in ci_dirs)

        # Important directories
        candidate_dirs = ["src", "app", "pages", "backend", "frontend", "tests", "test", "lib", "api"]
        profile.important_dirs = [d for d in candidate_dirs if (root / d).is_dir()]

        # README summary (first 500 chars)
        if readme_text:
            profile.readme_summary = readme_text[:500].strip()

        raw["important_dirs"] = profile.important_dirs
        raw["has_docker"] = profile.has_docker
        raw["has_ci"] = profile.has_ci
        profile.raw_data = raw

        return profile


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return None


def _read_json(path: Path) -> dict | None:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
