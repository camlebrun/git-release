from unittest.mock import MagicMock, patch

import pytest

from src.fetcher import GitHubFetchError, backfill_releases, get_new_releases


def _release(tag: str, published_at: str) -> dict:
    return {"tag_name": tag, "published_at": published_at, "id": hash(tag)}


def _mock_get(*pages: list[dict]) -> MagicMock:
    responses = []
    for page in pages:
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json.return_value = page
    responses = [*(_make_resp(page) for page in pages)]
    mock = MagicMock()
    mock.side_effect = responses
    return mock


def _make_resp(data: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.return_value = data
    return resp


# --- get_new_releases ---


def test_get_new_releases_filters_by_since() -> None:
    releases = [
        _release("v3.0.0", "2026-05-10T00:00:00Z"),
        _release("v2.0.0", "2026-04-01T00:00:00Z"),
        _release("v1.0.0", "2026-01-01T00:00:00Z"),
    ]
    with patch("src.fetcher.requests.get", side_effect=[_make_resp(releases), _make_resp([])]):
        result = get_new_releases("owner", "repo", since="2026-03-01T00:00:00Z")
    tags = [r["tag_name"] for r in result]
    assert "v3.0.0" in tags
    assert "v2.0.0" in tags
    assert "v1.0.0" not in tags


def test_get_new_releases_returns_ascending_order() -> None:
    releases = [
        _release("v3.0.0", "2026-05-10T00:00:00Z"),
        _release("v2.0.0", "2026-04-01T00:00:00Z"),
    ]
    with patch("src.fetcher.requests.get", side_effect=[_make_resp(releases), _make_resp([])]):
        result = get_new_releases("owner", "repo", since="2026-01-01T00:00:00Z")
    assert result[0]["tag_name"] == "v2.0.0"
    assert result[1]["tag_name"] == "v3.0.0"


def test_get_new_releases_raises_on_error() -> None:
    resp = MagicMock()
    resp.ok = False
    resp.status_code = 404
    resp.text = "Not Found"
    with patch("src.fetcher.requests.get", return_value=resp):
        with pytest.raises(GitHubFetchError) as exc:
            get_new_releases("owner", "repo", since="2026-01-01T00:00:00Z")
    assert exc.value.status == 404


# --- backfill_releases ---


def test_backfill_keeps_last_two_majors() -> None:
    releases = [
        _release("v12.1.0", "2026-05-01T00:00:00Z"),
        _release("v12.0.0", "2026-04-01T00:00:00Z"),
        _release("v11.5.0", "2026-03-01T00:00:00Z"),
        _release("v11.0.0", "2026-02-01T00:00:00Z"),
        _release("v10.9.0", "2026-01-01T00:00:00Z"),
    ]
    with patch("src.fetcher.requests.get", side_effect=[_make_resp(releases), _make_resp([])]):
        result = backfill_releases("owner", "repo")
    tags = {r["tag_name"] for r in result}
    assert "v12.1.0" in tags
    assert "v12.0.0" in tags
    assert "v11.5.0" in tags
    assert "v11.0.0" in tags
    assert "v10.9.0" not in tags


def test_backfill_non_semver_fallback() -> None:
    releases = [_release(f"nightly-{i}", f"2026-0{(i % 9) + 1}-01T00:00:00Z") for i in range(1, 25)]
    with patch("src.fetcher.requests.get", side_effect=[_make_resp(releases), _make_resp([])]):
        result = backfill_releases("owner", "repo")
    assert len(result) == 20


def test_backfill_returns_ascending_order() -> None:
    releases = [
        _release("v2.0.0", "2026-05-01T00:00:00Z"),
        _release("v1.0.0", "2026-01-01T00:00:00Z"),
    ]
    with patch("src.fetcher.requests.get", side_effect=[_make_resp(releases), _make_resp([])]):
        result = backfill_releases("owner", "repo")
    assert result[0]["tag_name"] == "v1.0.0"
    assert result[1]["tag_name"] == "v2.0.0"
