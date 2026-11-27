"""Synthetic demo data: two fictional utility providers with a few customers each.

Idempotent: running it twice updates the same rows instead of duplicating them.
All names, addresses and contacts are placeholders (Musterstadt, example.com).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.crm_mock.models import Contract, Customer, Invoice
from apps.tenants.models import AgentConfig, Tenant

DEFAULT_TOOLS = [
    "get_contract_info",
    "submit_meter_reading",
    "get_invoice_status",
    "change_billing_address",
    "handoff_to_human",
]

# Prompt v1 is deliberately naive; v2 (B-12) adds explicit rules, and evals compare them.
PROMPT_V1 = (
    "You are the customer support assistant of {tenant}. "
    "Answer the customer's questions about their contract, meter readings and invoices. "
    "Reply in the customer's language."
)


@dataclass(frozen=True)
class _CustomerSeed:
    number: str
    name: str
    language: str
    contract: str
    meter: str
    tariff: str
    address: str
    invoice: str
    amount: str
    status: str


_TENANTS: dict[str, tuple[str, list[_CustomerSeed]]] = {
    "stadtwerke-musterstadt": (
        "Stadtwerke Musterstadt (demo)",
        [
            _CustomerSeed(
                "SM-1001",
                "Erika Mustermann",
                "de",
                "SM-V-5001",
                "MZ-000101",
                "Strom Basis",
                "Musterstraße 1, 12345 Musterstadt",
                "SM-R-9001",
                "84.20",
                Invoice.Status.OPEN,
            ),
            _CustomerSeed(
                "SM-1002",
                "Max Mustermann",
                "de",
                "SM-V-5002",
                "MZ-000102",
                "Strom Öko",
                "Beispielweg 7, 12345 Musterstadt",
                "SM-R-9002",
                "112.75",
                Invoice.Status.OVERDUE,
            ),
            _CustomerSeed(
                "SM-1003",
                "Alex Example",
                "en",
                "SM-V-5003",
                "MZ-000103",
                "Gas Komfort",
                "Probeplatz 3, 12345 Musterstadt",
                "SM-R-9003",
                "63.10",
                Invoice.Status.PAID,
            ),
        ],
    ),
    "beispiel-energie": (
        "Beispiel Energie (demo)",
        [
            _CustomerSeed(
                "BE-2001",
                "Jana Beispiel",
                "de",
                "BE-V-6001",
                "MZ-000201",
                "Strom Flex",
                "Testallee 12, 54321 Beispielhausen",
                "BE-R-8001",
                "95.00",
                Invoice.Status.OPEN,
            ),
            _CustomerSeed(
                "BE-2002",
                "Sam Sample",
                "en",
                "BE-V-6002",
                "MZ-000202",
                "Strom Basis",
                "Demostraße 4, 54321 Beispielhausen",
                "BE-R-8002",
                "47.35",
                Invoice.Status.PAID,
            ),
        ],
    ),
}


@dataclass(frozen=True)
class SeedResult:
    tenants: int
    customers: int


@transaction.atomic
def seed_demo() -> SeedResult:
    customers = 0
    for slug, (name, people) in _TENANTS.items():
        tenant, _ = Tenant.objects.update_or_create(slug=slug, defaults={"name": name})
        AgentConfig.objects.update_or_create(
            tenant=tenant,
            name="support",
            prompt_version="v1",
            defaults={
                "system_prompt": PROMPT_V1.format(tenant=name),
                "provider": AgentConfig.Provider.FAKE,
                "enabled_tools": DEFAULT_TOOLS,
            },
        )
        for p in people:
            customer, _ = Customer.objects.update_or_create(
                tenant=tenant,
                customer_number=p.number,
                defaults={
                    "full_name": p.name,
                    "language": p.language,
                    "email": f"{p.number.lower()}@example.com",
                    "phone": "+49 000 " + p.number[-4:],
                },
            )
            contract, _ = Contract.objects.update_or_create(
                tenant=tenant,
                contract_number=p.contract,
                defaults={
                    "customer": customer,
                    "meter_number": p.meter,
                    "tariff": p.tariff,
                    "billing_address": p.address,
                },
            )
            Invoice.objects.update_or_create(
                tenant=tenant,
                invoice_number=p.invoice,
                defaults={
                    "contract": contract,
                    "amount": Decimal(p.amount),
                    "status": p.status,
                    "issued_on": date(2026, 11, 1),
                    "due_on": date(2026, 11, 15),
                },
            )
            customers += 1
    return SeedResult(tenants=len(_TENANTS), customers=customers)
