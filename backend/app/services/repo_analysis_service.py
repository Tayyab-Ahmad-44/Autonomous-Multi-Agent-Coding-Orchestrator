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

        # Collect file presence. Manifests at the root win; if a manifest type is
        # missing at the root, fall back to common monorepo subfolders
        # (e.g. backend/requirements.txt + frontend/package.json).
        js_dir = _find_manifest_dir(root, ("package.json",))
        py_dir = _find_manifest_dir(root, ("pyproject.toml", "requirements.txt"))
        raw["js_manifest_dir"] = _rel_dir(root, js_dir)
        raw["py_manifest_dir"] = _rel_dir(root, py_dir)

        package_json = _read_json(js_dir / "package.json") if js_dir else None
        pyproject = _read_text(py_dir / "pyproject.toml") if py_dir else None
        requirements = _read_text(py_dir / "requirements.txt") if py_dir else None
        poetry_lock = bool(py_dir) and (py_dir / "poetry.lock").exists()
        pnpm_lock = bool(js_dir) and (js_dir / "pnpm-lock.yaml").exists()
        package_lock = bool(js_dir) and (js_dir / "package-lock.json").exists()
        yarn_lock = bool(js_dir) and (js_dir / "yarn.lock").exists()
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
        if (pyproject or requirements) and package_json:
            profile.language = "Python + JavaScript/TypeScript"
        elif pyproject or requirements:
            profile.language = "Python"
        elif package_json:
            profile.language = "JavaScript/TypeScript"

        js_prefix = _cd_prefix(root, js_dir)
        py_prefix = _cd_prefix(root, py_dir)

        # Test commands
        if package_json:
            scripts = package_json.get("scripts", {})
            test_script = scripts.get("test")
            if test_script:
                profile.test_commands.append(f"{js_prefix}npm test")
        if pyproject or requirements:
            # pytest is always installed into the mission environment, so a
            # Python project can be tested with it even if it doesn't list it.
            profile.test_commands.append(f"{py_prefix}pytest")

        # Build commands
        if package_json:
            scripts = package_json.get("scripts", {})
            if "build" in scripts:
                js_mgr = "pnpm" if pnpm_lock else "yarn" if yarn_lock else "npm"
                profile.build_commands.append(f"{js_prefix}{js_mgr} run build")

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


_MONOREPO_SUBDIRS = ("backend", "frontend", "server", "client", "api", "web", "app", "src")


def _find_manifest_dir(root: Path, names: tuple[str, ...]) -> Path | None:
    for directory in (root, *(root / sub for sub in _MONOREPO_SUBDIRS)):
        if any((directory / name).is_file() for name in names):
            return directory
    return None


def _rel_dir(root: Path, directory: Path | None) -> str | None:
    if directory is None:
        return None
    rel = directory.relative_to(root).as_posix()
    return "." if rel in ("", ".") else rel


def _cd_prefix(root: Path, directory: Path | None) -> str:
    rel = _rel_dir(root, directory)
    return "" if rel in (None, ".") else f"cd {rel} && "


def _read_text(path: Path) -> str | None:
    """Read a repo file as text, handling UTF-16/UTF-8 BOMs.

    Files written by Windows tools (e.g. PowerShell `>` redirects) are often
    UTF-16. Decoding those as UTF-8 leaves NUL bytes that PostgreSQL rejects.
    """
    try:
        data = path.read_bytes()
    except (OSError, PermissionError):
        return None
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16", errors="replace")
    elif data.startswith(b"\xef\xbb\xbf"):
        text = data[3:].decode("utf-8", errors="replace")
    else:
        text = data.decode("utf-8", errors="replace")
    return text.replace("\x00", "")


def _read_json(path: Path) -> dict | None:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
