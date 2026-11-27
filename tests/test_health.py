import pytest
from django.db import OperationalError
from django.test import Client


@pytest.mark.django_db
def test_health_reports_ok_and_reaches_database(client: Client) -> None:
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_returns_503_when_database_is_down(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenConnection:
        def cursor(self) -> None:
            raise OperationalError("connection refused")

    monkeypatch.setattr("config.urls.connection", BrokenConnection())

    response = client.get("/health/")

    assert response.status_code == 503
    assert response.json() == {"status": "error"}


def test_health_rejects_non_get(client: Client) -> None:
    response = client.post("/health/")

    assert response.status_code == 405
