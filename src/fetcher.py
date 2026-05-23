from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import requests

from src.config import (
    BACKFILL_NON_SEMVER,
    GITHUB_API_BASE,
    GITHUB_RETRY_MAX,
    GITHUB_TIMEOUT_S,
    MAX_RELEASES_PER_RUN,
)
from src.semver import parse_semver

logger = logging.getLogger(__name__)

_TRIVIAL_CHANGE_PATTERNS = [
    "update readme",
    "add contributors",
    "update contributors",
    "bump version",
    "bump changelog",
    "update changelog",
    "fix typo",
    "update docs",
    "update documentation",
    "formatting",
    "linting",
    "style:",
    "chore:",
    "ci:",
    "whitespace",
]

_PROD_BREAKING_BUG_PATTERNS = [
    "fix",
    "bug",
    "crash",
    "error",
    "broken",
    "regression",
    "exception",
    "fails",
    "failure",
    "incorrect",
    "wrong result",
    "typeerror",
    "attributeerror",
    "keyerror",
    "importerror",
    "null",
    "none type",
    "data loss",
    "silent",
    "incorrect result",
]

_BLACKLISTED_SECTIONS = [
    "migrating from <1.0.0 to >=1.0.0",
    "migrating from",
]


class GitHubFetchError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub API error {status}: {message}")
        self.status = status


def fetch_readme(owner: str, repo: str, token: str | None = None) -> str:
    """Fetch README content from GitHub API, return plain text (truncated to 3000 chars)."""
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/readme"
    try:
        resp = requests.get(
            url,
            headers={**_headers_base(token), "Accept": "application/vnd.github.raw+json"},
            timeout=GITHUB_TIMEOUT_S,
        )
        if resp.ok:
            return resp.text[:3000]
    except Exception as e:
        logger.warning("Could not fetch README for %s/%s: %s", owner, repo, e)
    return ""


def filter_trivial_changes(changes: list[str]) -> list[str]:
    """Remove trivial/cosmetic entries from a key_changes list."""
    result = []
    for c in changes:
        if not isinstance(c, str):
            continue
        low = c.lower()
        if any(p in low for p in _TRIVIAL_CHANGE_PATTERNS):
            continue
        if any(low.startswith(section) for section in _BLACKLISTED_SECTIONS):
            continue
        result.append(c)
    return result


def heuristic_dbt_analysis(
    release: dict[str, object],
    readme: str,
) -> dict[str, object]:
    """Rule-based dbt package analysis — no LLM required, used for testing."""
    from src.semver import parse_semver

    tag = str(release.get("tag_name", ""))
    body = str(release.get("body", "")).lower()
    name = str(release.get("name", tag))
    sv = parse_semver(tag)

    # Detect prod-breaking bug
    is_prod_breaking_bug = any(p in body for p in _PROD_BREAKING_BUG_PATTERNS) and sv.patch > 0

    # Determine severity
    if "data loss" in body or "corruption" in body or "silent" in body:
        severity = "critical"
    elif "crash" in body or "exception" in body or "typeerror" in body or "keyerror" in body:
        severity = "high"
    elif is_prod_breaking_bug:
        severity = "medium"
    elif sv.minor > 0 and sv.patch == 0:
        severity = "low"
    else:
        severity = "none"

    # Extract purpose from first non-empty README paragraph (strip HTML tags)
    purpose = ""
    for para in readme.split("\n\n"):
        clean = para.strip().lstrip("#").strip()
        clean = re.sub(r"<[^>]+>", "", clean).strip()  # strip HTML tags
        clean = re.sub(r"\s+", " ", clean)  # collapse whitespace
        if len(clean) > 40 and not clean.startswith("!"):
            purpose = clean[:300]
            break

    # Parse key changes from release body bullet points (skip markdown headers)
    raw_changes = []
    for line in str(release.get("body", "")).splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        stripped = stripped.lstrip("-*•").strip()
        if stripped and len(stripped) > 10:
            raw_changes.append(stripped)
    key_changes = filter_trivial_changes(raw_changes[:10])[:6]

    tags: list[str] = []
    if is_prod_breaking_bug:
        tags.append("bug-fix")
    if sv.patch == 0 and sv.minor == 0:
        tags.append("breaking")
    if not key_changes:
        tags.append("docs-only")
    if not tags:
        tags.append("feature" if sv.patch == 0 else "bug-fix")

    return {
        "purpose": purpose or f"{release.get('repo', '')} dbt package.",
        "summary": f"{name} — {'patch fix' if sv.patch > 0 else 'minor/major release'}.",
        "key_changes": key_changes,
        "is_prod_breaking_bug": is_prod_breaking_bug,
        "severity": severity,
        "tags": tags,
    }


def _headers_base(token: str | None) -> dict[str, str]:
    h: dict[str, str] = {"X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _headers(token: str | None) -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get_page(url: str, token: str | None, params: dict[str, int | str]) -> list[dict[str, object]]:
    for attempt in range(GITHUB_RETRY_MAX):
        resp = requests.get(url, headers=_headers(token), params=params, timeout=GITHUB_TIMEOUT_S)
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = 2**attempt
            logger.warning(
                "GitHub %s, retrying in %ss (attempt %s)", resp.status_code, wait, attempt + 1
            )  # noqa: E501
            time.sleep(wait)
            continue
        if not resp.ok:
            raise GitHubFetchError(resp.status_code, resp.text[:200])
        return resp.json()  # type: ignore[no-any-return]
    raise GitHubFetchError(429, "Max retries exceeded")


def _all_pages(owner: str, repo: str, token: str | None) -> list[dict[str, object]]:
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases"
    releases: list[dict[str, object]] = []
    page = 1
    while True:
        page_data = _get_page(url, token, {"per_page": 100, "page": page})
        if not page_data:
            break
        releases.extend(page_data)
        page += 1
    return releases


def get_new_releases(
    owner: str, repo: str, since: str, token: str | None = None
) -> list[dict[str, object]]:
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases"
    result: list[dict[str, object]] = []
    page = 1
    done = False
    while not done:
        page_data = _get_page(url, token, {"per_page": 100, "page": page})
        if not page_data:
            break
        for release in page_data:
            pub = datetime.fromisoformat(str(release["published_at"]).replace("Z", "+00:00"))
            if pub <= since_dt:
                done = True
                break
            result.append(release)
            if len(result) >= MAX_RELEASES_PER_RUN:
                done = True
                break
        page += 1

    result.sort(key=lambda r: str(r["published_at"]))
    return result


def backfill_releases(
    owner: str,
    repo: str,
    token: str | None = None,
    min_version: str | None = None,
    stable_only: bool = False,
    minor_only: bool = False,
) -> list[dict[str, object]]:
    all_releases = _all_pages(owner, repo, token)
    if not all_releases:
        return []

    semver_releases = [(r, parse_semver(str(r["tag_name"]))) for r in all_releases]
    valid = [(r, sv) for r, sv in semver_releases if sv.valid]

    if not valid:
        sorted_all = sorted(all_releases, key=lambda r: str(r["published_at"]))
        return sorted_all[-BACKFILL_NON_SEMVER:]

    if min_version:
        min_sv = parse_semver(min_version)
        if min_sv.valid:
            valid = [
                (r, sv)
                for r, sv in valid
                if (sv.major, sv.minor, sv.patch) >= (min_sv.major, min_sv.minor, min_sv.patch)
            ]
    else:
        max_major = max(sv.major for _, sv in valid)
        valid = [(r, sv) for r, sv in valid if sv.major >= max_major - 1]

    if stable_only:
        valid = [(r, sv) for r, sv in valid if not r.get("prerelease")]
    if minor_only:
        valid = [(r, sv) for r, sv in valid if sv.patch == 0]
    valid.sort(key=lambda x: str(x[0]["published_at"]))
    return [r for r, _ in valid]


# ---------------------------------------------------------------------------
# Changelog-based fetcher (for repos with no GitHub releases, e.g. dbt-fusion)
# ---------------------------------------------------------------------------

_CHANGELOG_VERSION_RE = re.compile(r"^(\d+\.\d+\.\d+-preview\.\d+)$")
_CHANGELOG_DATE_RE = re.compile(r"Released\s+(\w+ \d+, \d{4})")
_HISTORICAL_CUTOFF = "2026-01-01T00:00:00+00:00"
_HISTORICAL_TAG = "2.0.0-pre-2026"
HISTORICAL_TAG = _HISTORICAL_TAG


def _parse_changelog_date(text: str) -> str | None:
    m = _CHANGELOG_DATE_RE.search(text)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%B %d, %Y").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return None


def _changelog_anchor(version: str) -> str:
    anchor = version.replace(".", "")
    return f"https://github.com/dbt-labs/dbt-fusion/blob/main/CHANGELOG.md#{anchor}"


def _build_historical_record(
    pre_releases: list[dict[str, object]],
    owner: str,
    repo: str,
) -> dict[str, object]:
    """Merge all pre-2026 releases into one consolidated synthetic record."""
    pre_releases_sorted = sorted(pre_releases, key=lambda r: str(r["published_at"]))
    first = str(pre_releases_sorted[0]["tag_name"])
    last = str(pre_releases_sorted[-1]["tag_name"])
    published_at = str(pre_releases_sorted[-1]["published_at"])

    version_list = "\n".join(
        f"- {r['tag_name']} ({str(r['published_at'])[:10]})" for r in pre_releases_sorted
    )

    # Sample: first 2 + last 2 versions for LLM context
    sample_releases = pre_releases_sorted[:2] + pre_releases_sorted[-2:]
    body_sample = "\n\n---\n\n".join(
        f"### {r['tag_name']}\n{str(r['body'])[:600]}" for r in sample_releases
    )

    return {
        "tag_name": _HISTORICAL_TAG,
        "name": f"dbt-fusion — Historical snapshot ({first} → {last})",
        "body": body_sample,
        "published_at": published_at,
        "html_url": f"https://github.com/{owner}/{repo}/blob/main/CHANGELOG.md",
        "prerelease": True,
        "draft": False,
        "id": None,
        "author": None,
        "_historical_meta": {
            "version_count": len(pre_releases),
            "first_version": first,
            "last_version": last,
            "version_list": version_list,
        },
    }


def fetch_changelog_releases(
    owner: str,
    repo: str,
    token: str | None = None,
    since: str | None = None,
) -> list[dict[str, object]]:
    """Parse CHANGELOG.md and return release-like records.

    Pre-2026 versions are merged into a single historical entry.
    2026+ versions matching X.Y.Z-preview.N are returned individually.
    Patch versions (Z > 0), nightly, and beta entries are excluded.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/CHANGELOG.md"
    headers = {**_headers_base(token), "Accept": "application/vnd.github.raw+json"}
    resp = requests.get(url, headers=headers, timeout=GITHUB_TIMEOUT_S)
    if not resp.ok:
        raise GitHubFetchError(resp.status_code, resp.text[:200])

    raw = resp.text
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else None
    cutoff_dt = datetime.fromisoformat(_HISTORICAL_CUTOFF)

    sections = re.split(r"^## ", raw, flags=re.MULTILINE)
    pre_releases: list[dict[str, object]] = []
    releases: list[dict[str, object]] = []

    for section in sections:
        lines = section.strip().splitlines()
        if not lines:
            continue
        header = lines[0].strip()
        if not _CHANGELOG_VERSION_RE.match(header):
            continue

        sv = parse_semver(header)
        if sv.valid and sv.patch > 0:
            continue

        body = "\n".join(lines[1:]).strip()
        published_at = _parse_changelog_date(body)
        if published_at is None:
            continue

        pub_dt = datetime.fromisoformat(published_at)

        if pub_dt < cutoff_dt:
            pre_releases.append({"tag_name": header, "body": body, "published_at": published_at})
            continue

        if since_dt and pub_dt <= since_dt:
            continue

        releases.append(
            {
                "tag_name": header,
                "name": header,
                "body": body,
                "published_at": published_at,
                "html_url": _changelog_anchor(header),
                "prerelease": True,
                "draft": False,
                "id": None,
                "author": None,
            }
        )

    result: list[dict[str, object]] = []

    # Include historical entry only on first backfill (no cursor yet)
    historical_already_stored = since_dt is not None
    if pre_releases and not historical_already_stored:
        result.append(_build_historical_record(pre_releases, owner, repo))

    result.extend(sorted(releases, key=lambda r: str(r["published_at"])))
    return result
