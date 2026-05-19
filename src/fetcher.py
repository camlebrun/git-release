from __future__ import annotations

import logging
import time
from datetime import datetime

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


class GitHubFetchError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub API error {status}: {message}")
        self.status = status


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


def backfill_releases(owner: str, repo: str, token: str | None = None) -> list[dict[str, object]]:
    all_releases = _all_pages(owner, repo, token)
    if not all_releases:
        return []

    semver_releases = [(r, parse_semver(str(r["tag_name"]))) for r in all_releases]
    valid = [(r, sv) for r, sv in semver_releases if sv.valid]

    if not valid:
        # Non-semver fallback: most recent N by published_at
        sorted_all = sorted(all_releases, key=lambda r: str(r["published_at"]))
        return sorted_all[-BACKFILL_NON_SEMVER:]

    max_major = max(sv.major for _, sv in valid)
    kept = [r for r, sv in valid if sv.major >= max_major - 1]
    kept.sort(key=lambda r: str(r["published_at"]))
    return kept
