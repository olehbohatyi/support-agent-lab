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

## ADR-004: Tenant isolation in the model layer (B-02)

**Context.** Every query must be limited to one tenant, and a bug in one view must not leak another customer's data.

**Decision.** All tenant-owned models inherit `TenantScopedModel`. It adds a `tenant` FK and a queryset with `for_tenant(tenant)`. There is no "unscoped" helper. On save, every FK to another tenant-scoped row is checked to belong to the same tenant (`TenantMismatchError`). `Message` repeats `tenant` (instead of only reaching it through `conversation`) so it can be scoped directly. A test asserts every scoped model exposes `for_tenant`.

**Alternatives.** Postgres row-level security is stronger, but needs per-request DB roles or session variables, which is too much for this project. Schema-per-tenant (django-tenants) is heavy for tens of thousands of small tenants. A thread-local "current tenant" in the default manager hides the scoping and is easy to bypass by accident in background jobs.

**Consequences.** Django's default `objects.all()` still exists, so the rule is enforced by convention and tests, not by the database. Admin intentionally sees all tenants. Bulk operations (`bulk_create`, `update()`) skip `save()` and so skip the FK check. Don't use them for cross-entity writes.
