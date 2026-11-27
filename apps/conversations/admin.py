from django.contrib import admin

from apps.conversations.models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ["role", "content", "created_at"]
    readonly_fields = ["created_at"]


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["id", "tenant", "customer", "status", "created_at"]
    list_filter = ["tenant", "status"]
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["conversation", "tenant", "role", "created_at"]
    list_filter = ["tenant", "role"]
