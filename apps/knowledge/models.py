from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from apps.tenants.models import TenantScopedModel


class Language(models.TextChoices):
    DE = "de", "Deutsch"
    EN = "en", "English"


class KnowledgeDoc(TenantScopedModel):
    """A knowledge-base article the agent may quote. Loaded by `load_kb` (B-07)."""

    title = models.CharField(max_length=300)
    body = models.TextField()
    language = models.CharField(max_length=2, choices=Language)
    source_path = models.CharField(max_length=300, blank=True)
    # Filled by B-07 with a language-specific tsvector; GIN index keeps FTS fast.
    search_vector = SearchVectorField(null=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        indexes = [GinIndex(fields=["search_vector"], name="kb_search_vector_gin")]
        constraints = [
            # load_kb upserts by file path; docs without a path are not deduplicated.
            models.UniqueConstraint(
                fields=["tenant", "source_path"],
                condition=~models.Q(source_path=""),
                name="uniq_kb_source_path",
            ),
        ]

    def __str__(self) -> str:
        return self.title
