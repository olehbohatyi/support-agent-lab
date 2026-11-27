"""Test-wide guards."""

import socket
from collections.abc import Iterator

import pytest

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Tests may reach the local Postgres, nothing else. A real LLM call in a test fails loudly."""
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: object) -> object:
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in _LOCAL_HOSTS and not host.startswith("/"):
            raise RuntimeError(f"external network access in tests is not allowed: {address!r}")
        return real_connect(self, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    yield
