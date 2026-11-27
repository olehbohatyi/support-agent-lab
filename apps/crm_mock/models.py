"""Mock CRM of a utility provider. Synthetic data only."""

from decimal import Decimal

from django.db import models

from apps.tenants.models import TenantScopedModel


class Customer(TenantScopedModel):
    customer_number = models.CharField(max_length=20)
    full_name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    language = models.CharField(max_length=2, default="de")

    class Meta:
        ordering = ["tenant", "customer_number"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "customer_number"], name="uniq_customer_number"),
        ]

    def __str__(self) -> str:
        return f"{self.customer_number} {self.full_name}"


class Contract(TenantScopedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ENDED = "ended", "Ended"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="contracts")
    contract_number = models.CharField(max_length=20)
    meter_number = models.CharField(max_length=30)
    tariff = models.CharField(max_length=100)
    billing_address = models.TextField()
    status = models.CharField(max_length=10, choices=Status, default=Status.ACTIVE)

    class Meta:
        ordering = ["tenant", "contract_number"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "contract_number"], name="uniq_contract_number"),
        ]

    def __str__(self) -> str:
        return self.contract_number


class MeterReading(TenantScopedModel):
    """Written by the submit_meter_reading tool (B-04)."""

    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="readings")
    value_kwh = models.PositiveIntegerField()
    read_on = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tenant", "-read_on"]

    def __str__(self) -> str:
        return f"{self.contract_id}: {self.value_kwh} kWh on {self.read_on}"


class Invoice(TenantScopedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"

    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="invoices")
    invoice_number = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="EUR")
    status = models.CharField(max_length=10, choices=Status, default=Status.OPEN)
    issued_on = models.DateField()
    due_on = models.DateField()

    class Meta:
        ordering = ["tenant", "-issued_on"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "invoice_number"], name="uniq_invoice_number"),
        ]

    def __str__(self) -> str:
        return self.invoice_number
