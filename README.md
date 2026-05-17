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

## Project Structure

```text
agent-orchestrator/
  backend/
    app/
      main.py
      core/
        config.py
        database.py
      models/
      schemas/
      api/
        routes/
      services/
        git_service.py
        github_service.py
        repo_analysis_service.py
        missions.py
      agents/
      orchestration/
      workers/
    alembic/
      versions/
        0001_core_mission_system.py
        0002_repositories.py
        0003_mission_events.py
        0004_repo_profiles.py
    tests/
    requirements.txt
    Dockerfile
  frontend/
    app/
      missions/
        new/           <- creation wizard
        [id]/
          review/      <- plan approval
          run/         <- live execution dashboard
    lib/
      api.ts
    package.json
  docker-compose.yml
  .env.example
  README.md
```

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

Creates milestones and feature tasks from the mission title, goal, and (when available) repo profile.

### SpecAgent

Creates the validation contract from the mission goal, milestones, and feature tasks.

### WorkerAgent

Executes one feature task against the cloned repository.

Current behavior:

- Creates or checks out a task branch.
- If `CODEX_ENABLED=false`, inspects the repository and produces a no-edit report.
- If `CODEX_ENABLED=true`, calls the Codex CLI to perform code changes.
- Captures git diff and status as an Artifact.
- Commits if `AUTO_COMMIT=true` and there are changes.
- Marks the feature task completed or failed.

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
cd agent-orchestrator/backend
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

## Run Dependencies

Start PostgreSQL and Redis:

```powershell
cd agent-orchestrator
docker compose up
```

This exposes:

- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

## Run Backend

From another terminal:

```powershell
cd agent-orchestrator/backend

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

Health check:

```powershell
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

API docs:

```text
http://localhost:8000/docs
```

## Run Celery Worker

Run this in a separate terminal:

```powershell
cd agent-orchestrator/backend
env\Scripts\celery.exe -A app.workers.celery_app.celery_app worker --loglevel=info --pool=solo
```

`--pool=solo` is recommended on Windows.

The orchestrator queues worker jobs through Celery. Without the Celery worker, queued worker tasks will not execute asynchronously.

For tests, tasks are usually run directly or mocked.

## Run Frontend

```powershell
cd agent-orchestrator/frontend

copy .env.example .env.local
npm.cmd install
npm.cmd run dev
```

Frontend runs at:

```text
http://localhost:3000/missions
```

## Frontend Screens

### /missions/new — Creation wizard

Four-step wizard:

1. **Mission details** — title and goal.
2. **Repository** — GitHub URL and default branch.
3. **Clone** — auto-triggers clone, shows local path and mission branch on success.
4. **Next steps** — optionally generate plan and validation contract before heading to the review screen.

### /missions/{id}/review — Plan review

Shows the mission goal, repository info, repo profile (when analyzed), plan milestones and tasks, and validation contract side by side.

Action bar adapts to current state:

- No plan → **Generate plan** (primary).
- Plan + no contract → **Generate validation contract** (primary) + Regenerate plan (ghost).
- Plan + contract → **Approve plan** (primary, redirects to run dashboard) + regenerate buttons.
- Repository cloned → **Analyze repo** / **Re-analyze repo** (ghost).

### /missions/{id}/run — Live execution dashboard

Live SSE updates (every 2 seconds). Shows:

- Progress bar (completed tasks / total tasks).
- Milestone and task status with failure highlighting.
- Latest validation report and issues.
- Event timeline (last 20 events).
- Toolbar: **Tick** (advance orchestrator), **Validate**, **Open PR** (when completed), **Refresh**.
- PR banner with link after a pull request is opened.

## Main API Endpoints

### Health

```http
GET /health
```

### Missions

```http
POST /missions
GET /missions
GET /missions/{mission_id}
PATCH /missions/{mission_id}/status
DELETE /missions/{mission_id}
```

### Repository Endpoints

```http
POST /missions/{mission_id}/repository/clone
GET /missions/{mission_id}/repository
POST /missions/{mission_id}/repository         (manual attach)
```

`/repository/clone` clones the GitHub repo into the workspace, checks out the default branch, creates the mission branch, and saves the local path.

### Repository Analysis

```http
POST /missions/{mission_id}/analyze-repo
```

Inspects the cloned repository and saves a `RepoProfile`. Automatically runs before planning if the repo is cloned and no profile exists.

### Planning and Contract

```http
POST /missions/{mission_id}/plan
POST /missions/{mission_id}/validation-contract
POST /missions/{mission_id}/orchestrate
```

`/orchestrate` generates a plan and validation contract, then sets the mission to `waiting_for_approval`.

### Approval

```http
POST /missions/{mission_id}/approve-plan
POST /missions/{mission_id}/reject-plan
```

Approval requires:

- milestones
- feature tasks
- validation contract

### Tick Loop

```http
POST /missions/{mission_id}/tick
```

Advances the mission by one orchestrator decision.

Tick behavior:

- If no plan exists, create one (and auto-analyze repo if needed).
- If no validation contract exists, create one.
- If waiting for approval, stop.
- If agent runs are queued/running, stop.
- If a task failed and retries remain, queue retry.
- If a task failed and retries are exhausted, fail mission.
- If a pending task exists, queue worker.
- If all current milestone tasks are complete, run validation.
- If validation fails, create fix tasks.
- If validation passes, advance milestone.
- If all milestones pass, complete mission.

### Validation

```http
POST /missions/{mission_id}/validate
```

Runs the current validation contract against the cloned repository.

### GitHub PR

```http
POST /missions/{mission_id}/open-pr
```

Pushes the mission branch to GitHub and opens a pull request. Returns the PR URL. Requires `GITHUB_TOKEN` to be set. If a PR already exists for the branch, returns the existing PR URL.

### Server-Sent Events

```http
GET /missions/{mission_id}/events
```

Streams the mission detail snapshot every 2 seconds. The frontend uses this to auto-refresh mission status, tasks, validation reports, and timeline events.

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
cd agent-orchestrator/backend
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

## Database Migrations

Run migrations:

```powershell
cd agent-orchestrator/backend
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

## Current Limitations

- E2B sandbox execution is only a skeleton.
- Worker code edits require Codex CLI and `CODEX_ENABLED=true`.
- Without Codex, workers only inspect repositories and mark tasks completed.
- Validators execute commands from the validation contract — use trusted repositories and commands.
- The Pause/Resume buttons in the run dashboard are placeholders (no backend support yet).

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
cd agent-orchestrator/backend
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
