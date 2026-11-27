from django.db import models

from apps.crm_mock.models import Customer
from apps.tenants.models import TenantScopedModel


class Conversation(TenantScopedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        # A write tool is waiting for the customer's explicit "yes" (confirm gate, B-08).
        AWAITING_CONFIRMATION = "awaiting_confirmation", "Awaiting confirmation"
        HANDED_OFF = "handed_off", "Handed off to a human"
        CLOSED = "closed", "Closed"

    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="conversations"
    )
    status = models.CharField(max_length=30, choices=Status, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Conversation {self.pk} ({self.status})"

    @property
    def handed_off(self) -> bool:
        return self.status == self.Status.HANDED_OFF


class Message(TenantScopedModel):
    """One turn of the conversation. ``tenant`` is repeated so messages can be scoped directly."""

    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        ASSISTANT = "assistant", "Assistant"
        HUMAN_AGENT = "human_agent", "Human agent"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20, choices=Role)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # "conversation_id", not "conversation": a FK name sorts by Conversation's ordering via a join.
        ordering = ["conversation_id", "created_at", "id"]

    def __str__(self) -> str:
        return f"{self.role}: {self.content[:40]}"
