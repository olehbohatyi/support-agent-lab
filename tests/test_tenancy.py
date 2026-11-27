"""Tenant isolation (B-02 acceptance): tenant B never sees tenant A's data."""

from dataclasses import dataclass
from datetime import date

import pytest
from django.apps import apps

from apps.conversations.models import Conversation, Message
from apps.crm_mock.models import Contract, Customer, Invoice
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
