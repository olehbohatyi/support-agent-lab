from django.core.management.base import BaseCommand

from apps.tenants.seed import seed_demo


class Command(BaseCommand):
    help = (
        "Create or reset the two synthetic demo tenants with customers, contracts and invoices. "
        "Re-running overwrites admin edits to the seeded rows (e.g. the v1 system prompt)."
    )

    def handle(self, *args: object, **options: object) -> None:
        result = seed_demo()
        self.stdout.write(
            self.style.SUCCESS(f"Seeded {result.tenants} tenants, {result.customers} customers.")
        )
