# support-agent-lab

A learning project: a multi-tenant Django service with an AI customer-support agent.
It has a hand-written agent loop, tool calling over a mock CRM, guardrails, a knowledge base
on Postgres full-text search, and an eval system that compares prompt versions.

> Work in progress. The full README (diagram, demo, API contract, and what is not here)
> lands in B-14. All data is synthetic.

## Quick start

```bash
cp .env.example .env          # then set DJANGO_SECRET_KEY and POSTGRES_PASSWORD
docker compose up -d db
uv sync
uv run python manage.py migrate
uv run pytest
```

Requires Docker, [uv](https://docs.astral.sh/uv/) and Python 3.14 (uv installs it if missing).

## Stack

Python 3.14 · Django 6.1 · Django REST Framework 3.18 · PostgreSQL 19 · pydantic 2 · httpx ·
Anthropic SDK · pytest · ruff.
