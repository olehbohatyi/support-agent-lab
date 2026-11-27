from django.contrib import admin

from apps.knowledge.models import KnowledgeDoc


@admin.register(KnowledgeDoc)
class KnowledgeDocAdmin(admin.ModelAdmin):
    list_display = ["title", "tenant", "language", "source_path", "updated_at"]
    list_filter = ["tenant", "language"]
    search_fields = ["title", "body"]
