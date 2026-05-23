from unittest.mock import MagicMock, patch

import pytest

from src.fetcher import (
    HISTORICAL_TAG,
    GitHubFetchError,
    backfill_releases,
    fetch_changelog_releases,
    filter_trivial_changes,
    get_new_releases,
)


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


def test_backfill_min_version_filters_below() -> None:
    releases = [
        _release("v1.5.0", "2026-05-01T00:00:00Z"),
        _release("v1.0.0", "2026-03-01T00:00:00Z"),
        _release("v0.9.0", "2026-01-01T00:00:00Z"),
    ]
    with patch("src.fetcher.requests.get", side_effect=[_make_resp(releases), _make_resp([])]):
        result = backfill_releases("owner", "repo", min_version="1.0.0")
    tags = {r["tag_name"] for r in result}
    assert "v1.5.0" in tags
    assert "v1.0.0" in tags
    assert "v0.9.0" not in tags


def test_backfill_min_version_exact_match_included() -> None:
    releases = [_release("v1.0.0", "2026-01-01T00:00:00Z")]
    with patch("src.fetcher.requests.get", side_effect=[_make_resp(releases), _make_resp([])]):
        result = backfill_releases("owner", "repo", min_version="1.0.0")
    assert len(result) == 1


# ── filter_trivial_changes ───────────────────────────────────────────────────


def test_filter_removes_trivial_entries() -> None:
    changes = ["Fix typo in README", "Add new feature", "chore: bump version"]
    result = filter_trivial_changes(changes)
    assert result == ["Add new feature"]


def test_filter_keeps_all_non_trivial() -> None:
    changes = ["Improve query performance", "Support Python 3.12"]
    assert filter_trivial_changes(changes) == changes


def test_filter_skips_non_string_entries() -> None:
    changes = ["Fix typo", 42, None, "Real change"]  # type: ignore[list-item]
    result = filter_trivial_changes(changes)
    assert result == ["Real change"]


# ── fetch_changelog_releases ─────────────────────────────────────────────────

_SAMPLE_CHANGELOG = """\
# dbt Fusion changelog

## 2.0.0-preview-nightly.5

Released January 15, 2026

### Features

- Nightly build, should be ignored

## 2.0.0-preview.10

Released January 20, 2026

### Features

- [dbt-fusion] Add Snowflake adapter support

## 2.0.0-preview.9

Released January 05, 2026

### Fixes

- [dbt-fusion] Fix manifest regression

## dbt-fusion 2.0.0-beta.3

Released December 10, 2025

### Features

- Old beta format, should be ignored

## 2.0.0-preview.5

Released November 20, 2025

### Features

- [dbt-fusion] Initial BigQuery support

## 2.0.0-preview.4

Released October 01, 2025

### Features

- [dbt-fusion] First preview release
"""


def _make_raw_resp(text: str) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.text = text
    return resp


def test_changelog_excludes_nightly_and_beta() -> None:
    with patch("src.fetcher.requests.get", return_value=_make_raw_resp(_SAMPLE_CHANGELOG)):
        result = fetch_changelog_releases("owner", "repo")
    tags = [r["tag_name"] for r in result]
    assert "2.0.0-preview-nightly.5" not in tags
    assert not any("beta" in str(t) for t in tags)


def test_changelog_creates_historical_entry_for_pre_2026() -> None:
    with patch("src.fetcher.requests.get", return_value=_make_raw_resp(_SAMPLE_CHANGELOG)):
        result = fetch_changelog_releases("owner", "repo")
    assert result[0]["tag_name"] == HISTORICAL_TAG
    meta = result[0]["_historical_meta"]
    assert isinstance(meta, dict)
    assert meta["version_count"] == 2
    assert meta["first_version"] == "2.0.0-preview.4"
    assert meta["last_version"] == "2.0.0-preview.5"


def test_changelog_2026_releases_returned_separately() -> None:
    with patch("src.fetcher.requests.get", return_value=_make_raw_resp(_SAMPLE_CHANGELOG)):
        result = fetch_changelog_releases("owner", "repo")
    tags_2026 = [r["tag_name"] for r in result if r["tag_name"] != HISTORICAL_TAG]
    assert "2.0.0-preview.9" in tags_2026
    assert "2.0.0-preview.10" in tags_2026


def test_changelog_2026_releases_ascending_order() -> None:
    with patch("src.fetcher.requests.get", return_value=_make_raw_resp(_SAMPLE_CHANGELOG)):
        result = fetch_changelog_releases("owner", "repo")
    dates = [r["published_at"] for r in result if r["tag_name"] != HISTORICAL_TAG]
    assert dates == sorted(dates)


def test_changelog_since_skips_historical_and_old_releases() -> None:
    with patch("src.fetcher.requests.get", return_value=_make_raw_resp(_SAMPLE_CHANGELOG)):
        result = fetch_changelog_releases("owner", "repo", since="2026-01-10T00:00:00+00:00")
    tags = [r["tag_name"] for r in result]
    assert HISTORICAL_TAG not in tags
    assert "2.0.0-preview.9" not in tags
    assert "2.0.0-preview.10" in tags


def test_changelog_raises_on_api_error() -> None:
    resp = MagicMock()
    resp.ok = False
    resp.status_code = 404
    resp.text = "Not Found"
    with patch("src.fetcher.requests.get", return_value=resp):
        with pytest.raises(GitHubFetchError) as exc:
            fetch_changelog_releases("owner", "repo")
    assert exc.value.status == 404
