from django.contrib import admin

from apps.tenants.models import AgentConfig, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "created_at"]
    search_fields = ["name", "slug"]
    # The hash is set by the token command (B-06), never typed in by hand.
    readonly_fields = ["api_token_hash", "created_at"]


@admin.register(AgentConfig)
class AgentConfigAdmin(admin.ModelAdmin):
    list_display = ["tenant", "name", "prompt_version", "provider", "model", "max_steps", "is_active"]
    list_filter = ["tenant", "provider", "is_active"]
    search_fields = ["name", "prompt_version"]
