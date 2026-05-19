from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from src.config import DIGEST_DEFAULT_LIMIT, DIGEST_MAX_LIMIT
from src.store import list_release_keys

logger = logging.getLogger(__name__)

_BATCH = 20


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

    records: list[dict[str, Any]] = []
    for i in range(0, len(keys), _BATCH):
        batch = keys[i : i + _BATCH]
        with ThreadPoolExecutor(max_workers=_BATCH) as executor:
            futures = {executor.submit(_fetch_one, s3, bucket, k): k for k in batch}
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    records.append(result)

    records.sort(key=lambda r: str(r.get("published_at", "")), reverse=True)
    return records[:limit]
