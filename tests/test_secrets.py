from unittest.mock import MagicMock, patch

import pytest

from src.secrets import clear_cache, get_secret


@pytest.fixture(autouse=True)
def reset_cache() -> None:
    clear_cache()


def _mock_client(value: str) -> MagicMock:
    payload = MagicMock()
    payload.data = value.encode()
    response = MagicMock()
    response.payload = payload
    client = MagicMock()
    client.access_secret_version.return_value = response
    return client


def test_get_secret_returns_value() -> None:
    with patch(
        "src.secrets.secretmanager.SecretManagerServiceClient",
        return_value=_mock_client("my-api-key"),
    ):
        result = get_secret("my-project", "MY_SECRET")
    assert result == "my-api-key"


def test_get_secret_caches_on_second_call() -> None:
    client = _mock_client("cached-value")
    with patch(
        "src.secrets.secretmanager.SecretManagerServiceClient",
        return_value=client,
    ):
        get_secret("my-project", "MY_SECRET")
        get_secret("my-project", "MY_SECRET")
    assert client.access_secret_version.call_count == 1


def test_env_var_fallback_skips_secret_manager() -> None:
    client = _mock_client("should-not-be-used")
    with patch("src.secrets.secretmanager.SecretManagerServiceClient", return_value=client):
        with patch.dict("os.environ", {"MY_SECRET": "from-env"}):
            result = get_secret("my-project", "MY_SECRET")
    assert result == "from-env"
    assert client.access_secret_version.call_count == 0


def test_clear_cache_forces_refetch() -> None:
    client = _mock_client("value")
    with patch(
        "src.secrets.secretmanager.SecretManagerServiceClient",
        return_value=client,
    ):
        get_secret("my-project", "MY_SECRET")
        clear_cache()
        get_secret("my-project", "MY_SECRET")
    assert client.access_secret_version.call_count == 2
