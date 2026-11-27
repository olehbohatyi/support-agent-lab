import pytest
from django.test import Client


@pytest.mark.django_db
def test_health_reports_ok_and_reaches_database(client: Client) -> None:
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_denies_by_default() -> None:
    """Until tenant auth lands (B-06), DRF must not allow anonymous access."""
    from django.conf import settings

    permissions = settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]
    assert permissions == ["rest_framework.permissions.IsAuthenticated"]
