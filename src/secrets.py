from __future__ import annotations

from google.cloud import secretmanager

_cache: dict[str, str] = {}


def get_secret(project: str, name: str) -> str:
    key = f"{project}/{name}"
    if key not in _cache:
        client = secretmanager.SecretManagerServiceClient()
        path = f"projects/{project}/secrets/{name}/versions/latest"
        response = client.access_secret_version(name=path)
        _cache[key] = response.payload.data.decode("utf-8")
    return _cache[key]


def clear_cache() -> None:
    _cache.clear()
