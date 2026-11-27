from django.contrib import admin

from apps.crm_mock.models import Contract, Customer, Invoice, MeterReading


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["customer_number", "full_name", "tenant", "language"]
    list_filter = ["tenant", "language"]
    search_fields = ["customer_number", "full_name"]


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ["contract_number", "customer", "tenant", "tariff", "status"]
    list_filter = ["tenant", "status"]
    search_fields = ["contract_number", "meter_number"]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["invoice_number", "contract", "tenant", "amount", "status", "due_on"]
    list_filter = ["tenant", "status"]
    search_fields = ["invoice_number"]


@admin.register(MeterReading)
class MeterReadingAdmin(admin.ModelAdmin):
    list_display = ["contract", "tenant", "value_kwh", "read_on", "created_at"]
    list_filter = ["tenant"]
