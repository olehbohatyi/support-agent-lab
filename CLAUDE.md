# support-agent-lab: rules for Claude Code

## Context
Learning/portfolio project by Oleh. Goal: a Django service showing an AI support agent
(agent loop, tool calling, context management, multi-provider LLM gateway, evals).
The PRD is the source of truth (scope P0/P1/P2, issues B-01..B-15). Do not add features
beyond the PRD without asking. Data is synthetic only. Never claim production use.

Tracking: Linear project "Interview Prep — Lime Connect (AI Engineer)", team OLE.
Issue titles carry the PRD key, e.g. "[B-05] Agent loop" (OLE-56).

## Workflow
- One Linear issue = one branch `b-XX-short-name`; small commits; reference the issue key.
- Before each commit: `uv run ruff check`, `uv run ruff format`, `uv run pytest` must pass.
- Work in dependency order from the PRD. If blocked or the spec is ambiguous, STOP and ask.
- Mark acceptance criteria in the issue when done; do not mark done without a test or a manual check.
- Move the Linear issue: In Progress when starting, In Review when the diff is ready, Done after Oleh's review.

## Teach mode (mandatory)
After each issue, append to `docs/LEARNING.md` (in Russian):
1. What was built and why this design.
2. The 3 questions an interviewer may ask about it, with short answers.
3. What would change in production.
Explain non-obvious Python/Django parts in code comments sparingly, in English.
Oleh reviews the diff and must be able to explain every file.

## Architecture rules
- Python 3.14 (latest stable), type hints everywhere, pydantic v2 for DTOs and tool schemas.
- Always use the latest stable versions of libraries, frameworks and images; check before adding.
- Views are thin; logic lives in services (apps/agent/*). Agent runtime has no HTTP dependency.
- Hand-written agent loop. No LangChain, LlamaIndex or agent frameworks.
- Every data access goes through `for_tenant(tenant)`. No cross-tenant queries.
- Write tools require a confirm gate stored in conversation state. Tools are idempotent.
- LLM access only through the LLMProvider interface. Tests use FakeProvider, no network.
- Secrets only via env; keep `.env.example` current; never commit keys.
- Logs and fixtures contain no real personal data.

## Commands
- `docker compose up -d db` — Postgres
- `uv sync` — install
- `uv run python manage.py migrate`
- `uv run pytest`
- `uv run ruff check . && uv run ruff format --check .`

## Decisions
Record non-trivial choices in `docs/DECISIONS.md` (context, decision, alternatives, consequences).

## Do not
- Overengineer (no Celery, no vector DB, no streaming in P0).
- Invent facts about Lime Connect internals.
- Skip tests for guardrails, tenancy or idempotency.
