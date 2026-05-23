"""Delete all R2 records for a given repo (releases + cursor).

Usage:
    python scripts/purge_repo_r2.py calogica/dbt-expectations
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.secrets import get_secrets  # noqa: E402
from src.store import get_s3_client  # noqa: E402


def purge(owner: str, repo: str) -> None:
    secrets = get_secrets()
    s3 = get_s3_client(
        secrets["R2_ACCESS_KEY"],
        secrets["R2_SECRET_KEY"],
        secrets["R2_ACCOUNT_ID"],
    )
    bucket = secrets["R2_BUCKET"]

    # 1. Delete release records
    prefix = f"releases/{owner}/{repo}/"
    paginator = s3.get_paginator("list_objects_v2")
    to_delete: list[dict] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            to_delete.append({"Key": obj["Key"]})

    if to_delete:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})
        print(f"Deleted {len(to_delete)} release(s): {prefix}")
    else:
        print(f"No releases found under {prefix}")

    # 2. Delete cursor
    cursor_key = f"meta/cursor/{owner}/{repo}.json"
    try:
        s3.delete_object(Bucket=bucket, Key=cursor_key)
        print(f"Deleted cursor: {cursor_key}")
    except Exception:
        print(f"No cursor found: {cursor_key}")

    print("Done — next pipeline run will backfill from scratch.")


if __name__ == "__main__":
    if len(sys.argv) != 2 or "/" not in sys.argv[1]:
        print("Usage: python scripts/purge_repo_r2.py owner/repo")
        sys.exit(1)
    owner, repo = sys.argv[1].split("/", 1)
    purge(owner, repo)
