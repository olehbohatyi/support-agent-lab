"""Tenancy: the isolation root and the base class every tenant-owned model inherits.

Rules (CLAUDE.md):
- every data query goes through ``Model.objects.for_tenant(tenant)``;
- there is no "unscoped" helper — reading across tenants is not part of the API;
- a row can only reference rows of its own tenant (checked on save).
"""

from __future__ import annotations

from typing import Any, Self

from django.db import models


class TenantMismatchError(ValueError):
    """Raised when a row would reference data that belongs to another tenant."""


class Tenant(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=64, unique=True)
    # sha256 of the API token; the token itself is never stored (issued in B-06).
    api_token_hash = models.CharField(max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return self.name


class TenantQuerySet(models.QuerySet):
    def for_tenant(self, tenant: Tenant) -> Self:
        if tenant.pk is None:
            raise ValueError("for_tenant() needs a saved tenant")
        return self.filter(tenant=tenant)


class TenantScopedModel(models.Model):
    """Abstract base: adds ``tenant`` and the ``for_tenant`` manager."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="+")

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.check_same_tenant()
        super().save(*args, **kwargs)

    def check_same_tenant(self) -> None:
        """Every FK to another tenant-scoped row must point inside this tenant."""
        for field in self._meta.concrete_fields:
            if not isinstance(field, models.ForeignKey) or field.name == "tenant":
                continue
            if not issubclass(field.related_model, TenantScopedModel):
                continue
            related = getattr(self, field.name)
            if related is not None and related.tenant_id != self.tenant_id:
                raise TenantMismatchError(
                    f"{type(self).__name__}.{field.name} belongs to tenant {related.tenant_id}, "
                    f"not {self.tenant_id}"
                )


class AgentConfig(TenantScopedModel):
    """Per-tenant agent settings. Prompts are versioned so evals can compare them."""

    class Provider(models.TextChoices):
        FAKE = "fake", "Fake (tests, no network)"
        ANTHROPIC = "anthropic", "Anthropic"

    name = models.CharField(max_length=100, default="support")
    prompt_version = models.CharField(max_length=20, default="v1")
    system_prompt = models.TextField()
    provider = models.CharField(max_length=20, choices=Provider, default=Provider.FAKE)
    model = models.CharField(max_length=100, blank=True)
    enabled_tools = models.JSONField(default=list, blank=True)
    max_steps = models.PositiveSmallIntegerField(default=8)
    token_budget = models.PositiveIntegerField(default=20_000)
    handoff_rules = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tenant", "name", "prompt_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name", "prompt_version"], name="uniq_agentconfig_version"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} {self.prompt_version}"
