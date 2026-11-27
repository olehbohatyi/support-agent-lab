"""Tenant isolation (B-02 acceptance): tenant B never sees tenant A's data."""

from collections.abc import Callable
from contextlib import AbstractContextManager as ContextManager
from dataclasses import dataclass
from datetime import date

import pytest
from django.apps import apps
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.conversations.models import Conversation, Message
from apps.crm_mock.models import Contract, Customer, Invoice, MeterReading
from apps.knowledge.models import KnowledgeDoc
from apps.tenants.models import AgentConfig, Tenant, TenantMismatchError, TenantScopedModel
from apps.tenants.seed import seed_demo


@dataclass
class TenantData:
    tenant: Tenant
    customer: Customer
    contract: Contract
    doc: KnowledgeDoc
    conversation: Conversation
    message: Message


def _make_tenant(slug: str) -> TenantData:
    tenant = Tenant.objects.create(name=slug.title(), slug=slug)
    AgentConfig.objects.create(tenant=tenant, system_prompt="You help customers.")
    customer = Customer.objects.create(tenant=tenant, customer_number=f"{slug}-1", full_name="Test Person")
    contract = Contract.objects.create(
        tenant=tenant,
        customer=customer,
        contract_number=f"{slug}-c1",
        meter_number="M-1",
        tariff="Basis",
        billing_address="Musterstraße 1",
    )
    Invoice.objects.create(
        tenant=tenant,
        contract=contract,
        invoice_number=f"{slug}-i1",
        issued_on=date(2026, 11, 1),
        due_on=date(2026, 11, 15),
    )
    doc = KnowledgeDoc.objects.create(tenant=tenant, title="Zählerstand", body="...", language="de")
    conversation = Conversation.objects.create(tenant=tenant, customer=customer)
    message = Message.objects.create(
        tenant=tenant, conversation=conversation, role=Message.Role.CUSTOMER, content="Hallo"
    )
    return TenantData(tenant, customer, contract, doc, conversation, message)


@pytest.fixture
def tenant_a(db: None) -> TenantData:
    return _make_tenant("alpha")


@pytest.fixture
def tenant_b(db: None) -> TenantData:
    return _make_tenant("beta")


@pytest.mark.parametrize(
    "model",
    [Customer, Contract, Invoice, KnowledgeDoc, Conversation, Message, AgentConfig],
)
def test_for_tenant_returns_only_own_rows(
    model: type[TenantScopedModel], tenant_a: TenantData, tenant_b: TenantData
) -> None:
    rows_b = model.objects.for_tenant(tenant_b.tenant)

    assert rows_b.exists()
    assert not rows_b.filter(tenant=tenant_a.tenant).exists()
    assert set(rows_b.values_list("tenant_id", flat=True)) == {tenant_b.tenant.pk}


def test_tenant_b_cannot_fetch_tenant_a_row_by_id(tenant_a: TenantData, tenant_b: TenantData) -> None:
    for model, row in [
        (Customer, tenant_a.customer),
        (KnowledgeDoc, tenant_a.doc),
        (Conversation, tenant_a.conversation),
    ]:
        with pytest.raises(model.DoesNotExist):
            model.objects.for_tenant(tenant_b.tenant).get(pk=row.pk)


def test_row_cannot_reference_another_tenants_row(tenant_a: TenantData, tenant_b: TenantData) -> None:
    with pytest.raises(TenantMismatchError):
        Contract.objects.create(
            tenant=tenant_b.tenant,
            customer=tenant_a.customer,
            contract_number="x",
            meter_number="M",
            tariff="T",
            billing_address="A",
        )
    with pytest.raises(TenantMismatchError):
        Message.objects.create(
            tenant=tenant_b.tenant, conversation=tenant_a.conversation, role="customer", content="hi"
        )


def test_moving_a_row_to_another_tenant_is_rejected(tenant_a: TenantData, tenant_b: TenantData) -> None:
    contract = tenant_a.contract
    contract.tenant = tenant_b.tenant

    with pytest.raises(TenantMismatchError):
        contract.save()


def test_for_tenant_rejects_unsaved_tenant(db: None) -> None:
    with pytest.raises(ValueError, match="saved tenant"):
        Customer.objects.for_tenant(Tenant(name="x", slug="x"))


def test_every_tenant_scoped_model_exposes_for_tenant() -> None:
    """Guard: a new model that forgets the base class or the manager fails here."""
    scoped = [m for m in apps.get_models() if issubclass(m, TenantScopedModel)]

    assert {m.__name__ for m in scoped} >= {
        "AgentConfig",
        "KnowledgeDoc",
        "Customer",
        "Contract",
        "Invoice",
        "MeterReading",
        "Conversation",
        "Message",
    }
    for model in scoped:
        assert hasattr(model.objects, "for_tenant"), model.__name__


@pytest.mark.django_db
def test_seed_demo_creates_two_tenants_and_is_idempotent() -> None:
    first = seed_demo()
    second = seed_demo()

    assert first == second
    assert Tenant.objects.count() == 2
    for tenant in Tenant.objects.all():
        assert Customer.objects.for_tenant(tenant).exists()
        assert AgentConfig.objects.for_tenant(tenant).filter(prompt_version="v1").exists()
    assert Customer.objects.count() == first.customers


# --- Constraints and query cost (review of PR #3) ---------------------------------------


def test_meter_reading_is_unique_per_contract_and_day(tenant_a: TenantData) -> None:
    MeterReading.objects.create(
        tenant=tenant_a.tenant, contract=tenant_a.contract, value_kwh=100, read_on=date(2026, 11, 20)
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        MeterReading.objects.create(
            tenant=tenant_a.tenant, contract=tenant_a.contract, value_kwh=100, read_on=date(2026, 11, 20)
        )


def test_api_token_hash_is_unique_but_blank_is_allowed_for_many(db: None) -> None:
    Tenant.objects.create(name="One", slug="one")
    Tenant.objects.create(name="Two", slug="two")  # both blank: fine
    Tenant.objects.create(name="Three", slug="three", api_token_hash="a" * 64)

    with pytest.raises(IntegrityError), transaction.atomic():
        Tenant.objects.create(name="Four", slug="four", api_token_hash="a" * 64)


def test_only_one_active_agent_config_per_tenant_and_name(tenant_a: TenantData) -> None:
    # tenant_a already has an active "support" v1.
    AgentConfig.objects.create(
        tenant=tenant_a.tenant, prompt_version="v2", system_prompt="v2", is_active=False
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        AgentConfig.objects.create(tenant=tenant_a.tenant, prompt_version="v3", system_prompt="v3")


def test_same_tenant_check_costs_at_most_one_query_per_fk(
    tenant_a: TenantData, django_assert_num_queries: Callable[..., ContextManager[None]]
) -> None:
    # Only the id is set, so the related row is not loaded: 1 SELECT tenant_id + 1 INSERT.
    with django_assert_num_queries(2):
        Conversation.objects.create(tenant=tenant_a.tenant, customer_id=tenant_a.customer.pk)

    # The related object is already loaded: no extra query, just the INSERT.
    with django_assert_num_queries(1):
        Conversation.objects.create(tenant=tenant_a.tenant, customer=tenant_a.customer)


def test_default_ordering_does_not_join_the_tenant_table(tenant_a: TenantData) -> None:
    for model in [Customer, Contract, Invoice, KnowledgeDoc, Conversation, Message, AgentConfig]:
        sql = str(model.objects.for_tenant(tenant_a.tenant).query)
        assert "tenants_tenant" not in sql, model.__name__
    assert "conversations_conversation" not in str(Message.objects.for_tenant(tenant_a.tenant).query)


@pytest.mark.django_db
def test_seeded_overdue_invoices_are_past_due() -> None:
    seed_demo()
    today = timezone.localdate()

    for invoice in Invoice.objects.filter(status=Invoice.Status.OVERDUE):
        assert invoice.due_on < today
    for invoice in Invoice.objects.filter(status=Invoice.Status.OPEN):
        assert invoice.due_on >= today
