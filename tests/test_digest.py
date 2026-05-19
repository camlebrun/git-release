import json
from unittest.mock import MagicMock

from src.digest import get_digest

BUCKET = "test-bucket"


def _blob(tag: str, published_at: str, with_body: bool = True) -> bytes:
    record: dict = {
        "repo": "owner/repo",
        "tag": tag,
        "published_at": published_at,
        "analysis": None,
    }  # noqa: E501
    if with_body:
        record["body"] = "raw markdown — should be stripped"
    return json.dumps(record).encode()


def _mock_s3(blobs: dict[str, bytes]) -> MagicMock:
    s3 = MagicMock()
    page = {"Contents": [{"Key": k} for k in blobs]}
    paginator = MagicMock()
    paginator.paginate.return_value = [page]
    s3.get_paginator.return_value = paginator

    def get_object(Bucket: str, Key: str) -> dict:
        body = MagicMock()
        body.read.return_value = blobs[Key]
        return {"Body": body}

    s3.get_object.side_effect = get_object
    return s3


def test_sorted_descending() -> None:
    blobs = {
        "releases/owner/repo/v1.json": _blob("v1", "2026-01-01T00:00:00Z"),
        "releases/owner/repo/v3.json": _blob("v3", "2026-03-01T00:00:00Z"),
        "releases/owner/repo/v2.json": _blob("v2", "2026-02-01T00:00:00Z"),
    }
    result = get_digest(_mock_s3(blobs), BUCKET, limit=10)
    assert [r["tag"] for r in result] == ["v3", "v2", "v1"]


def test_respects_limit() -> None:
    blobs = {
        f"releases/owner/repo/v{i}.json": _blob(f"v{i}", f"2026-0{i}-01T00:00:00Z")
        for i in range(1, 6)
    }
    result = get_digest(_mock_s3(blobs), BUCKET, limit=3)
    assert len(result) == 3


def test_body_stripped() -> None:
    blobs = {"releases/owner/repo/v1.json": _blob("v1", "2026-01-01T00:00:00Z", with_body=True)}
    result = get_digest(_mock_s3(blobs), BUCKET)
    assert "body" not in result[0]
