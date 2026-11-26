# Full (non-slim) image: already ships git, ca-certificates and libstdc++, so
# the build needs no apt step (large apt downloads stalled inside BuildKit on
# Docker Desktop for Windows).
FROM python:3.12-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

# Node from the official image, then the Codex CLI the worker calls.
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install -g @openai/codex@0.144.1 \
    && npm cache clean --force \
    && codex --version \
    && git --version

# uv: per-mission virtualenvs.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/

WORKDIR /app

COPY requirements.txt .
RUN UV_HTTP_TIMEOUT=120 uv pip install --system --no-cache -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
