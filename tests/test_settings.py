import pytest

from config.settings import env_list


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("localhost,127.0.0.1", ["localhost", "127.0.0.1"]),
        ("localhost, 127.0.0.1", ["localhost", "127.0.0.1"]),
        (" a.example ,, b.example ,", ["a.example", "b.example"]),
        ("", []),
    ],
)
def test_env_list_strips_spaces_and_drops_empty_items(
    raw: str, expected: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SAL_TEST_LIST", raw)

    assert env_list("SAL_TEST_LIST") == expected
