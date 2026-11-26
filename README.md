# Agent Orchestrator

Factory-style multi-agent coding orchestrator for turning a software goal into planned work, validation contracts, agent jobs, validation reports, and fix tasks — all against a real GitHub repository.

The project is currently an MVP. The backend is the main product surface. The frontend is a Next.js UI for creating missions, reviewing plans, and watching live execution.

## Core Idea

A user submits a mission:

```text
Build email/password auth in this repo
```

The system then moves through a controlled workflow:

```text
Mission
  -> clone repository
  -> analyze repository
  -> plan (milestones + tasks)
  -> validation contract
  -> human approval
  -> worker tasks (one per feature task)
  -> validation
  -> fix task if validation fails
  -> next milestone
  -> completed
  -> open GitHub PR
```

The orchestrator is the only component that decides the next step.

Agents do not talk freely to each other. Communication is:

```text
Orchestrator -> Agent -> Orchestrator
```

## Current Tech Stack

- Backend: FastAPI
- Database: PostgreSQL
- ORM: SQLAlchemy
- Migrations: Alembic
- Queue: Redis + Celery
- Orchestration: LangGraph
- Frontend: Next.js App Router + Tailwind
- Sandbox MVP: local subprocess execution behind a provider interface
- Validation: shell, pytest, Playwright, Semgrep
- Optional coding engine: Codex CLI
- GitHub: REST API via httpx for push + PR creation

## Architecture Rules

- Orchestrator controls the mission lifecycle.
- Every agent run is stored in the database.
- Every mission must have a validation contract before workers start.
- Workers only complete tasks.
- Validators only create reports.
- Validators do not fix code.
- FixPlanner creates fix tasks from failed validation reports.
- If retry or validation-loop limits are exceeded, the mission becomes `failed` and requires human intervention.
- Decision extraction is best-effort: a failed extraction never fails the feature task it ran alongside.

## Main Concepts

### Mission

Top-level user goal. A mission has status:

```text
draft
planning
waiting_for_approval
running
validating
failed
completed
```

### Milestone

Ordered phase of a mission. A milestone has feature tasks and is validated as a unit.

### FeatureTask

An implementable task assigned to a worker-like agent. Task types include:

```text
planning
research
backend
frontend
database
test
docs
fix
```

### ValidationContract

A structured contract created before workers start. It includes:

- Markdown contract text
- Concrete assertions
- Required tests
- Definition of done

### AgentRun

A stored execution record for any agent. Agent runs move through:

```text
queued -> running -> completed
queued -> running -> failed
```

### ValidationReport

Validator output for a mission or milestone. Failed reports produce fix tasks.

### MissionEvent

Structured internal event log used by the API and frontend timeline.

### Repository

A GitHub (or local) repository attached to a mission. After cloning, the workspace lives at:

```text
{WORKSPACE_ROOT}/missions/{mission_id}/repo
```

The mission branch is:

```text
mission/{mission_id_short}
```

Worker task branches are:

```text
mission/{mission_id_short}/task/{task_id_short}
```

### MissionDecision

A key/value fact recorded mid-mission (e.g. `auth_scheme = JWT with refresh tokens`) so later tasks in the same mission stay consistent with earlier ones. See [Mission Decision Memory](#mission-decision-memory).

### RepoProfile

Automatic analysis of the cloned repository, run before planning. Detects:

- Frontend framework (Next.js, React, Vue, Angular, Svelte)
- Backend framework (FastAPI, Django, Flask, Express, Fastify)
- Package manager (pnpm, yarn, npm, poetry, pip)
- Language (Python, JavaScript/TypeScript)
- Test commands
- Build commands
- Key directories
- Docker and CI presence
- README excerpt

The planner includes the repo profile in its prompt to generate more accurate tasks.

## Agents

### PlannerAgent

Creates milestones and feature tasks from the mission title, goal, (when available) repo profile, and prior mission decisions recorded so far.

### SpecAgent

Creates the validation contract from the mission goal, milestones, and feature tasks.

### WorkerAgent

Executes one feature task against the cloned repository.

Current behavior:

- Creates or checks out a task branch.
- If `CODEX_ENABLED=false`, inspects the repository and produces a no-edit report.
- If `CODEX_ENABLED=true`, calls the Codex CLI to perform code changes, with prior mission decisions included in the prompt.
- Captures git diff and status as an Artifact.
- Commits if `AUTO_COMMIT=true` and there are changes.
- Marks the feature task completed or failed.
- If the task completed with real changes, extracts and records mission decisions for later tasks. See [Mission Decision Memory](#mission-decision-memory).

### ValidatorAgent

Runs required tests from the validation contract and creates a validation report.

Supported test types:

- `shell`
- `pytest`
- `playwright`
- `semgrep`

### FixPlannerAgent

Creates targeted fix tasks from a failed validation report.

## Codex CLI vs WorkerAgent

`WorkerAgent` is the orchestrator-controlled backend component.

`Codex CLI` is an optional external coding engine that the worker can call.

```text
Orchestrator -> WorkerAgent -> optional Codex CLI
```

When Codex is enabled, Codex writes code. The worker prepares the prompt, runs Codex, records output, captures diffs, and updates database state.

When Codex is disabled, the worker only performs safe repository inspection.

## Environment Variables

Create a backend `.env` file in `backend/.env` if you run backend commands from `backend/`.

You can start from the root example:

```powershell
cd backend
copy ..\.env.example .env
```

Backend variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/agent_orchestrator` | SQLAlchemy database URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker and result backend |
| `OPENAI_API_KEY` | empty | Required for real LLM-backed planner/spec agents |
| `DEFAULT_LLM_MODEL` | `gpt-4.1-mini` | Default OpenAI model for LLM service |
| `CELERY_TASK_ALWAYS_EAGER` | `false` | Runs Celery tasks inline when true |
| `CODEX_ENABLED` | `false` | Enables Codex CLI-backed worker execution |
| `CODEX_COMMAND` | `codex` | Codex CLI command name |
| `CODEX_SANDBOX` | `workspace-write` | Codex sandbox mode; `exec` defaults to read-only, which blocks edits |
| `CODEX_MODEL` | empty | Optional model override (else `~/.codex/config.toml`) |
| `CODEX_REASONING_EFFORT` | empty | Optional reasoning effort override |
| `CODEX_AUTH` | `chatgpt` | `api_key` passes `OPENAI_API_KEY` to Codex (as `CODEX_API_KEY`) for orchestrator runs only, billed per token |
| `MISSION_ENV_ENABLED` | `true` | Create a per-mission virtualenv with the repo's requirements before running tests/Codex |
| `MISSION_PYTHON_VERSION` | `3.12` | Python version for mission virtualenvs (via `uv`) |
| `CODEX_ALLOW_COMMITS` | `false` | Tells Codex whether commits are allowed in prompt rules |
| `AUTO_COMMIT` | `false` | Worker commits changes after Codex if true |
| `WORKSPACE_ROOT` | `/workspaces` | Root directory for cloned mission repositories |
| `GITHUB_TOKEN` | empty | GitHub personal access token for push and PR creation |
| `SANDBOX_PROVIDER` | `local` | Sandbox provider: `local` or `e2b` |
| `E2B_API_KEY` | empty | Required only for future E2B provider execution |
| `MAX_AGENT_RETRIES` | `2` | Failed worker retry limit per task |
| `MAX_VALIDATION_LOOPS` | `3` | Failed validation/fix loop limit per milestone |

Frontend variables go in `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Run in Docker (recommended)

The API and the Celery worker run in containers that share a `workspaces`
volume. The container is the sandbox: Codex runs there with full access to the
mission workspace, and test commands from validation contracts never run on
your machine. (`SANDBOX_PROVIDER=e2b` is the planned hosted equivalent and is
not implemented yet.)

1. Fill in `backend/.env` (start from `.env.example`). Container-specific
   values (database/Redis hosts, `WORKSPACE_ROOT`, `CODEX_COMMAND`,
   `CODEX_SANDBOX`) are set by `docker-compose.yml` and override the file.
2. Codex auth inside the container: set `CODEX_AUTH=api_key` (uses
   `OPENAI_API_KEY`), since the container has no ChatGPT login.
3. Set `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME` and
   `GIT_COMMITTER_EMAIL` so worker commits are attributed to you.
4. Start everything:

```powershell
docker compose --profile app up --build
```

5. Run the frontend on the host (`cd frontend; npm.cmd run dev`) and open
   http://localhost:3000/missions.

`docker compose up` without the profile still starts only Postgres and Redis,
for running the backend directly on the host.

Inspect a mission's workspace:

```powershell
docker compose exec worker ls /workspaces/missions
```

## Run Dependencies

Start PostgreSQL and Redis:

```powershell
docker compose up
```

This exposes:

- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

## Run Backend

From another terminal:

```powershell
cd backend

uv venv env
uv pip install --python env\Scripts\python.exe -r requirements.txt
copy ..\.env.example .env

env\Scripts\alembic.exe upgrade head
env\Scripts\uvicorn.exe app.main:app --reload
```

Backend runs at:

```text
http://localhost:8000
```

## Run Celery Worker

Run this in a separate terminal:

```powershell
cd backend
env\Scripts\celery.exe -A app.workers.celery_app.celery_app worker --loglevel=info --pool=solo
```

`--pool=solo` is recommended on Windows.

The orchestrator queues worker jobs through Celery. Without the Celery worker, queued worker tasks will not execute asynchronously.

For tests, tasks are usually run directly or mocked.

## Run Frontend

```powershell
cd frontend

copy .env.example .env.local
npm.cmd install
npm.cmd run dev
```

Frontend runs at:

```text
http://localhost:3000/missions
```

## Example Mission Flow

1. Create a mission (`POST /missions`).
2. Clone the repository (`POST /missions/{id}/repository/clone`).
3. Analyze the repository (`POST /missions/{id}/analyze-repo`) — optional, auto-runs before planning.
4. Generate plan (`POST /missions/{id}/plan`).
5. Generate validation contract (`POST /missions/{id}/validation-contract`).
6. Approve plan (`POST /missions/{id}/approve-plan`).
7. Call `/tick` — worker task queued.
8. Celery worker executes the task on the cloned repo.
9. Call `/tick` again — validation runs.
10. If validation fails, fix tasks are created.
11. Run fix tasks via further ticks.
12. If validation passes, next milestone starts.
13. Repeat until mission is completed.
14. Open PR (`POST /missions/{id}/open-pr`).

## Validation Support

### Shell and Pytest

Validation contract required tests can include:

```json
{
  "name": "Run backend tests",
  "type": "pytest",
  "command": "pytest"
}
```

or:

```json
{
  "name": "Smoke command",
  "type": "shell",
  "command": "python -c \"print('ok')\""
}
```

### Playwright

Playwright commands run inside the cloned repository path.

Install Playwright in the target repository:

```powershell
cd path\to\target\repo
npm.cmd install -D @playwright/test
npx playwright install
```

In Linux containers or CI images:

```bash
npx playwright install --with-deps
```

The validator stores screenshots and videos found under:

```text
test-results/
playwright-report/
```

### Semgrep

Example validation test:

```json
{
  "name": "Semgrep scan",
  "type": "semgrep",
  "command": "semgrep --config auto . --json"
}
```

High or critical findings fail validation.

## Sandbox Providers

The sandbox service is provider-based.

### Local

```env
SANDBOX_PROVIDER=local
```

Runs commands with Python subprocess in the cloned repository path.

### E2B

```env
SANDBOX_PROVIDER=e2b
E2B_API_KEY=...
```

The E2B provider is currently a placeholder. It can be selected, but remote execution is not implemented yet.

## Codex Worker Integration

Enable Codex:

```env
CODEX_ENABLED=true
CODEX_COMMAND=codex
```

When enabled, `WorkerAgent` calls the Codex CLI from the task branch with a prompt containing:

- mission goal
- feature task title and description
- validation contract assertions
- required tests
- implementation rules

Worker rules include:

- modify only files needed for the task
- run tests if available
- do not delete unrelated code
- summarize changes
- do not commit unless asked

After Codex runs, the worker captures the git diff as an artifact.

If `AUTO_COMMIT=true`, the worker commits changes with:

```text
Task: {feature_task.title}
```

## Mission Decision Memory

Feature tasks in the same mission run as independent Worker jobs, potentially far apart in time. Without shared memory, task 3 has no way to know that task 1 already picked JWT-with-refresh-tokens for auth, or settled on a particular error response shape. Mission decision memory closes that gap.

Flow:

1. When a codex-enabled Worker task completes successfully and produced a real diff, the worker makes one extra LLM call (separate from Codex itself) that reads the task title, description, and diff, and extracts a short list of `{key, value}` decisions — e.g. `auth_scheme = JWT with refresh tokens`. This runs only when there is an actual diff, so it never fires for no-edit or Codex-disabled task runs.
2. Each decision is stored as a `MissionDecision` row scoped to the mission, tagged with the source feature task.
3. Every later Planner and codex-enabled Worker prompt in the same mission includes a "Prior decisions in this mission" section listing all decisions recorded so far, so subsequent tasks stay consistent with earlier ones.

Notes:

- Decision extraction is best-effort. If the extraction call fails or returns nothing useful, the feature task itself still completes normally — extraction failures are logged and swallowed, never propagated.
- All decisions recorded for a mission are included in later prompts; there is currently no summarization, deduplication, or cap. A mission that accumulates a very large number of decisions would need that handling added later.

## GitHub Integration

### Clone

`POST /missions/{id}/repository/clone` clones the repository into:

```text
{WORKSPACE_ROOT}/missions/{mission_id}/repo
```

The mission branch is checked out or created. The local path is saved to the repository record.

### Push and PR

`POST /missions/{id}/open-pr` requires `GITHUB_TOKEN` in `.env`.

```env
GITHUB_TOKEN=ghp_...
```

The endpoint:

1. Detects GitHub owner and repo from the repository URL.
2. Pushes the current mission branch to the remote.
3. Opens a pull request against the default branch.
4. Stores the PR URL as an artifact.
5. Returns `{ "pr_url": "...", "branch": "..." }`.

If a PR for the branch already exists, the existing PR URL is returned.

## Testing

Run all backend tests with pytest:

```powershell
cd backend
env\Scripts\pytest.exe -q
```

Run Python compile check:

```powershell
env\Scripts\python.exe -m compileall app tests
```

Current tests cover:

- mission CRUD
- planning
- validation contract generation
- approval flow
- LangGraph tick lifecycle
- Celery worker execution
- repository support
- sandbox providers
- Codex service wrapper
- Git service (clone, fetch, checkout, pull, branch, diff, status, commit)
- GitHub service (URL parsing, push, PR creation, duplicate PR handling)
- validator support for shell, pytest, Playwright, and Semgrep
- full lifecycle with failed validation, fix task creation, passing validation, milestone completion, and mission completion
- mission decision memory: extraction after a successful worker run, prompt injection for later Planner/Worker tasks, and non-fatal handling of extraction failures

## Database Migrations

Run migrations:

```powershell
cd backend
env\Scripts\alembic.exe upgrade head
```

Show current migration head:

```powershell
env\Scripts\alembic.exe heads
```

Migration history:

| Revision | Description |
| --- | --- |
| `0001_core_mission_system` | missions, milestones, feature tasks, agent runs, validation contracts, validation reports, artifacts |
| `0002_repositories` | repositories table |
| `0003_mission_events` | mission events table |
| `0004_repo_profiles` | repo profiles table |
| `0005_mission_decisions` | mission decisions table |

## Current Limitations

- E2B sandbox execution is only a skeleton.
- Worker code edits require Codex CLI and `CODEX_ENABLED=true`.
- Without Codex, workers only inspect repositories and mark tasks completed.
- Validators execute commands from the validation contract — use trusted repositories and commands.
- The Pause/Resume buttons in the run dashboard are placeholders (no backend support yet).
- Mission decision memory has no summarization, deduplication, or cap yet — every recorded decision is included in later prompts as-is.

## Troubleshooting

### Backend cannot connect to Postgres

Make sure Docker Compose is running:

```powershell
docker compose up
```

Check that `DATABASE_URL` points to:

```text
postgresql+psycopg2://postgres:postgres@localhost:5432/agent_orchestrator
```

### Worker tasks stay queued

Start Celery:

```powershell
cd backend
env\Scripts\celery.exe -A app.workers.celery_app.celery_app worker --loglevel=info --pool=solo
```

### Planner or Spec fails with missing API key

Set:

```env
OPENAI_API_KEY=...
```

Or use tests with fake planner/spec agents.

### Frontend cannot reach backend

Check `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Then restart the frontend dev server.

### Clone fails with authentication error

For private repositories, embed a token in the URL:

```text
https://x-access-token:{GITHUB_TOKEN}@github.com/org/repo.git
```

Or set `GITHUB_TOKEN` in `.env` — the clone service does not use it automatically; provide an authenticated URL directly.

### Codex reports "sandbox helper not found" on Windows

If `~/.codex/config.toml` sets `[windows] sandbox = "elevated"` but the helper
(`codex-windows-sandbox-setup.exe`) is missing, Codex can't run any command and
the worker task fails with "Codex CLI exited without changing any files". Use
the unelevated sandbox for orchestrator runs. Config overrides must come
**after** `exec`, or Codex ignores them:

```env
CODEX_COMMAND=codex exec -c windows.sandbox="unelevated"
```

### Codex says the model is not supported with a ChatGPT account

Set `CODEX_MODEL` to a model your account can use (see `~/.codex/models_cache.json`).

### Open PR fails with "GITHUB_TOKEN is not configured"

Set in `backend/.env`:

```env
GITHUB_TOKEN=ghp_...
```

### `pip` is missing in the uv-created env

Use uv directly:

```powershell
uv pip install --python env\Scripts\python.exe -r requirements.txt
```
