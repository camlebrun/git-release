from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from src.config import DIGEST_DEFAULT_LIMIT, DIGEST_MAX_LIMIT
from src.store import list_release_keys

logger = logging.getLogger(__name__)

_BATCH = 20
_REPOS_PATH = Path(__file__).parent.parent / "repos.json"


def _load_repo_overrides() -> dict[str, dict[str, Any]]:
    """Build repo → override fields (deprecated, notice…) from repos.json at digest time."""
    try:
        raw = json.loads(_REPOS_PATH.read_text())
        overrides: dict[str, dict[str, Any]] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            fields: dict[str, Any] = {}
            if item.get("deprecated"):
                fields["deprecated"] = True
                fields["deprecated_notice"] = item.get("deprecated_notice")
            if item.get("notice"):
                fields["notice"] = item["notice"]
            if fields:
                overrides[item["repo"]] = fields
        return overrides
    except Exception:
        return {}


def _fetch_one(s3: Any, bucket: str, key: str) -> dict[str, Any] | None:
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        record = json.loads(resp["Body"].read())
        record.pop("body", None)
        return record  # type: ignore[no-any-return]
    except Exception as e:
        logger.warning("Failed to fetch digest record %s: %s", key, e)
        return None


def get_digest(s3: Any, bucket: str, limit: int = DIGEST_DEFAULT_LIMIT) -> list[dict[str, Any]]:
    limit = min(limit, DIGEST_MAX_LIMIT)
    keys = list_release_keys(s3, bucket)
    deprecated_map = _load_repo_overrides()

    records: list[dict[str, Any]] = []
    for i in range(0, len(keys), _BATCH):
        batch = keys[i : i + _BATCH]
        with ThreadPoolExecutor(max_workers=_BATCH) as executor:
            futures = {executor.submit(_fetch_one, s3, bucket, k): k for k in batch}
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    # Inject deprecated status from repos.json (overrides stale R2 records)
                    repo = result.get("repo", "")
                    if repo in deprecated_map:
                        result.update(deprecated_map[repo])
                    records.append(result)

    records.sort(key=lambda r: str(r.get("published_at", "")), reverse=True)
    return records[:limit]
