from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.analyser import analyse_release
from src.cve_enricher import enrich_cve_list
from src.fetcher import backfill_releases, get_new_releases
from src.store import get_cursor, put_release, release_exists, set_cursor, set_run_status

logger = logging.getLogger(__name__)

_REPOS_PATH = Path(__file__).parent.parent / "repos.json"


def load_repos() -> list[str]:
    return json.loads(_REPOS_PATH.read_text())  # type: ignore[no-any-return]


def _build_record(
    release: dict[str, Any],
    repo: str,
    analysis: dict[str, Any] | None,
    analysis_error: str | None,
    cve_details: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": release.get("id"),
        "repo": repo,
        "tag": release.get("tag_name"),
        "name": release.get("name"),
        "body": release.get("body", ""),
        "published_at": release.get("published_at"),
        "html_url": release.get("html_url"),
        "author": (release.get("author") or {}).get("login"),
        "prerelease": release.get("prerelease", False),
        "draft": release.get("draft", False),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "analysis": analysis,
        "analysis_error": analysis_error,
        "cve_details": cve_details,
    }


def run_pipeline(
    s3: Any,
    bucket: str,
    groq_key: str,
    github_token: str | None = None,
) -> dict[str, Any]:
    repos = load_repos()
    repo_status: dict[str, Any] = {}

    for repo in repos:
        owner, name = repo.split("/", 1)
        try:
            cursor = get_cursor(s3, bucket, owner, name)
            if cursor is None:
                releases = backfill_releases(owner, name, github_token)
                logger.info("[%s] backfill: %d releases", repo, len(releases))
            else:
                releases = get_new_releases(owner, name, cursor, github_token)
                logger.info("[%s] incremental: %d new releases since %s", repo, len(releases), cursor)

            new_count = 0
            latest_published_at = cursor

            for release in releases:
                tag = str(release.get("tag_name", ""))
                if release_exists(s3, bucket, owner, name, tag):
                    continue

                analysis, error = analyse_release({**release, "repo": repo}, groq_key)

                cve_ids: list[str] = (analysis or {}).get("cve_references", [])  # type: ignore[assignment]
                cve_details = enrich_cve_list(cve_ids) if cve_ids else []

                record = _build_record(release, repo, analysis, error, cve_details)
                put_release(s3, bucket, record)
                new_count += 1
                latest_published_at = str(release.get("published_at", ""))

            if latest_published_at and latest_published_at != cursor:
                set_cursor(s3, bucket, owner, name, latest_published_at)

            repo_status[repo] = {"ok": True, "new_releases": new_count}

        except Exception as e:
            logger.error("[%s] pipeline error: %s", repo, e)
            repo_status[repo] = {"ok": False, "error": str(e)}

    run_status = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "repos": repo_status,
    }
    set_run_status(s3, bucket, run_status)
    logger.info("Pipeline complete: %s", repo_status)
    return run_status
