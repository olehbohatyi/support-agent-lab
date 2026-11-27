# Decisions

Short ADRs: context, decision, alternatives, consequences.

## ADR-001: Latest stable toolchain (B-01)

**Context.** The PRD assumed Python 3.12. The goal is to show a current stack, and the project has no legacy constraints.

**Decision.** Python 3.14, Django 6.1, DRF 3.18, PostgreSQL 19, managed with uv. The minimum versions in `pyproject.toml` are the latest at bootstrap, and `uv.lock` pins the exact resolved set.

**Alternatives.** Python 3.12/3.13 have wider ecosystem testing, but nothing in the dependency set needs them.

**Consequences.** Every dependency must support 3.14. When a new library is added, check that first.

## ADR-002: Postgres for everything, including KB search (B-01)

**Context.** The KB needs search in German and English; the PRD's non-goals exclude a vector database.

**Decision.** One PostgreSQL instance in docker compose. `django.contrib.postgres` is enabled now so full-text search is available in B-07. Tests run against real Postgres, not SQLite.

**Alternatives.** SQLite for tests is faster, but FTS and some constraints behave differently there. A vector DB (pgvector or a separate service) is P2.

**Consequences.** `docker compose up -d db` is needed before tests run.

## ADR-003: Deny-by-default API (B-01)

**Context.** Tenant-token authentication arrives in B-06.

**Decision.** DRF is configured with no authentication classes and `IsAuthenticated`, so any API view added before B-06 rejects every request.

**Consequences.** There is no window where an endpoint is accidentally public.
