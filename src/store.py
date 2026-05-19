from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def get_s3_client(access_key: str, secret_key: str, account_id: str) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )


def _release_key(owner: str, repo: str, tag: str) -> str:
    return f"releases/{owner}/{repo}/{tag}.json"


def _cursor_key(owner: str, repo: str) -> str:
    return f"meta/cursor/{owner}/{repo}.json"


_RUN_STATUS_KEY = "meta/run_status.json"


def _get_json(s3: Any, bucket: str, key: str) -> dict[str, Any] | None:
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(resp["Body"].read())  # type: ignore[no-any-return]
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def _put_json(s3: Any, bucket: str, key: str, data: dict[str, Any]) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False).encode(),
        ContentType="application/json",
    )


def release_exists(s3: Any, bucket: str, owner: str, repo: str, tag: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=_release_key(owner, repo, tag))
        return True
    except ClientError:
        return False


def get_release(s3: Any, bucket: str, owner: str, repo: str, tag: str) -> dict[str, Any] | None:
    return _get_json(s3, bucket, _release_key(owner, repo, tag))


def put_release(s3: Any, bucket: str, record: dict[str, Any]) -> None:
    owner_repo = str(record["repo"])
    owner, repo = owner_repo.split("/", 1)
    tag = str(record["tag"])
    if release_exists(s3, bucket, owner, repo, tag):
        logger.debug("Skipping existing release %s@%s", owner_repo, tag)
        return
    _put_json(s3, bucket, _release_key(owner, repo, tag), record)


def list_release_keys(s3: Any, bucket: str) -> list[str]:
    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="releases/"):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def get_cursor(s3: Any, bucket: str, owner: str, repo: str) -> str | None:
    data = _get_json(s3, bucket, _cursor_key(owner, repo))
    return str(data["published_at"]) if data else None


def set_cursor(s3: Any, bucket: str, owner: str, repo: str, published_at: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _put_json(
        s3, bucket, _cursor_key(owner, repo), {"published_at": published_at, "updated_at": now}
    )  # noqa: E501


def get_advisory_cursor(s3: Any, bucket: str, owner: str, repo: str) -> str | None:
    key = f"meta/advisory-cursor/{owner}/{repo}.json"
    data = _get_json(s3, bucket, key)
    return str(data["updated_at"]) if data else None


def set_advisory_cursor(s3: Any, bucket: str, owner: str, repo: str, updated_at: str) -> None:
    key = f"meta/advisory-cursor/{owner}/{repo}.json"
    _put_json(s3, bucket, key, {"updated_at": updated_at})


def get_run_status(s3: Any, bucket: str) -> dict[str, Any] | None:
    return _get_json(s3, bucket, _RUN_STATUS_KEY)


def set_run_status(s3: Any, bucket: str, status: dict[str, Any]) -> None:
    _put_json(s3, bucket, _RUN_STATUS_KEY, status)


def write_repo_advisories(
    s3: Any, bucket: str, owner: str, repo: str, advisories: list[dict[str, Any]]
) -> None:
    """Store advisories per repo: advisories/{owner}/{repo}/advisories.json"""
    _put_json(s3, bucket, f"advisories/{owner}/{repo}/advisories.json", advisories)


def read_all_advisories(s3: Any, bucket: str) -> list[dict[str, Any]]:
    """Read all per-repo advisory files and merge into one list."""
    all_advisories: list[dict[str, Any]] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="advisories/"):
        for obj in page.get("Contents", []):
            data = _get_json(s3, bucket, obj["Key"])
            if data:
                all_advisories.extend(data)
    return all_advisories


def write_digest_json(
    s3: Any,
    bucket: str,
    records: list[dict[str, Any]],
    advisories: list[dict[str, Any]] | None = None,
) -> None:
    """Write digest.json = { releases, advisories } to R2 root for public fetch."""
    slim = [{k: v for k, v in r.items() if k != "body"} for r in records]
    slim.sort(key=lambda r: str(r.get("published_at", "")), reverse=True)
    payload: dict[str, Any] = {"releases": slim, "advisories": advisories or []}
    s3.put_object(
        Bucket=bucket,
        Key="digest.json",
        Body=json.dumps(payload, ensure_ascii=False).encode(),
        ContentType="application/json",
        CacheControl="public, max-age=3600",
    )
