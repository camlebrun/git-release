from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.analyser import AuthError, analyse_release
from src.digest import get_digest
from src.fetcher import backfill_releases, get_new_releases
from src.security_advisories import analyse_advisory, fetch_advisories
from src.store import (
    get_advisory_cursor,
    get_cursor,
    put_release,
    read_all_advisories,
    release_exists,
    set_advisory_cursor,
    set_cursor,
    set_run_status,
    write_digest_json,
    write_repo_advisories,
)

logger = logging.getLogger(__name__)

_REPOS_PATH = Path(__file__).parent.parent / "repos.json"


def load_repos() -> list[dict[str, str]]:
    raw = json.loads(_REPOS_PATH.read_text())
    result = []
    for item in raw:
        if isinstance(item, str):
            result.append({"repo": item})
        else:
            result.append(item)
    return result


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
    llm_key: str,
    github_token: str | None = None,
    llm_provider: str = "groq",
    llm_delay_s: float = 0.0,
) -> dict[str, Any]:
    repos = load_repos()
    repo_status: dict[str, Any] = {}

    for repo_cfg in repos:
        repo = repo_cfg["repo"]
        min_version = repo_cfg.get("min_version")
        stable_only = repo_cfg.get("stable_only", False)
        owner, name = repo.split("/", 1)
        try:
            cursor = get_cursor(s3, bucket, owner, name)
            if cursor is None:
                releases = backfill_releases(
                    owner, name, github_token, min_version, bool(stable_only)
                )
                logger.info("[%s] backfill %d releases (min=%s)", repo, len(releases), min_version)
            else:
                releases = get_new_releases(owner, name, cursor, github_token)
                logger.info("[%s] incremental: %d new since %s", repo, len(releases), cursor)

            new_count = 0
            latest_published_at = cursor

            for release in releases:
                tag = str(release.get("tag_name", ""))
                if release_exists(s3, bucket, owner, name, tag):
                    continue

                if llm_delay_s > 0 and new_count > 0:
                    time.sleep(llm_delay_s)
                try:
                    analysis, error = analyse_release(
                        {**release, "repo": repo}, llm_key, llm_provider
                    )
                except AuthError as e:
                    logger.error("❌ Auth error — stopping pipeline: %s", e)
                    raise  # propagate up, stop everything

                record = _build_record(release, repo, analysis, error, [])
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

    # Fetch + analyse + store advisories per repo
    logger.info("Fetching security advisories...")
    for repo_cfg in repos:
        repo = repo_cfg["repo"]
        owner, name = repo.split("/", 1)
        all_repo_advisories = fetch_advisories(owner, name, github_token)

        # Load existing stored advisories to merge (cursor-based update)
        existing = {
            a["ghsa_id"]: a
            for a in (read_all_advisories(s3, bucket) or [])
            if a.get("repo") == repo
        }
        cursor = get_advisory_cursor(s3, bucket, owner, name)

        updated = False
        for adv in all_repo_advisories:
            ghsa = adv.get("ghsa_id", "")
            updated_at = adv.get("updated_at") or ""
            # Skip if already analysed and not updated since cursor
            if ghsa in existing and cursor and updated_at <= cursor:
                adv["analysis"] = existing[ghsa].get("analysis")
                continue
            # Run LLM analysis on new/updated advisories
            adv["analysis"] = analyse_advisory(adv, llm_key, llm_provider)
            updated = True
            logger.info("[%s] advisory analysed: %s", repo, ghsa)

        write_repo_advisories(s3, bucket, owner, name, all_repo_advisories)
        if updated and all_repo_advisories:
            latest = max((a.get("updated_at") or "" for a in all_repo_advisories), default="")
            if latest:
                set_advisory_cursor(s3, bucket, owner, name, latest)
        logger.info("[%s] %d advisories stored", repo, len(all_repo_advisories))

    # Read all per-repo advisories and build master digest.json
    all_advisories = read_all_advisories(s3, bucket)
    all_records = get_digest(s3, bucket, limit=500)
    write_digest_json(s3, bucket, all_records, all_advisories)
    logger.info("digest.json: %d releases, %d advisories", len(all_records), len(all_advisories))

    logger.info("Pipeline complete: %s", repo_status)
    return run_status
