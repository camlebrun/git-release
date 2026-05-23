from __future__ import annotations

import os

from google.cloud import secretmanager

_cache: dict[str, str] = {}


def get_secret(project: str, name: str) -> str:
    key = f"{project}/{name}"
    if key not in _cache:
        # Fall back to environment variable for local development
        env_val = os.environ.get(name)
        if env_val is not None:
            _cache[key] = env_val
        else:
            client = secretmanager.SecretManagerServiceClient()
            path = f"projects/{project}/secrets/{name}/versions/latest"
            response = client.access_secret_version(name=path)
            _cache[key] = response.payload.data.decode("utf-8")
    return _cache[key]


def clear_cache() -> None:
    _cache.clear()
