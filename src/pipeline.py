from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests as _http

from src.analyser import (
    analyse_dbt_package_release,
    analyse_fusion_historical,
    analyse_fusion_release,
    analyse_release,
)
from src.digest import get_digest
from src.fetcher import (
    HISTORICAL_TAG,
    backfill_releases,
    fetch_changelog_releases,
    fetch_readme,
    get_new_releases,
)
from src.security_advisories import analyse_advisory, fetch_advisories
from src.semver import parse_semver
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


def _call_email_function(url: str, payload: dict[str, Any]) -> None:
    """POST to the email Cloud Function with OIDC token for service-to-service auth."""
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token

        auth_req = google.auth.transport.requests.Request()
        token = google.oauth2.id_token.fetch_id_token(auth_req, url)  # type: ignore[no-untyped-call]
        _http.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=20)
    except Exception as e:
        logger.error("Email function call failed: %s", e)


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
    group: str | None = None,
    deprecated: bool = False,
    deprecated_notice: str | None = None,
) -> dict[str, Any]:
    return {
        "id": release.get("id"),
        "repo": repo,
        "group": group,
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
        "deprecated": deprecated,
        "deprecated_notice": deprecated_notice,
    }


def _is_stale(releases: list[dict[str, Any]]) -> bool:
    """True if the most recent release is older than 1 year."""
    if not releases:
        return True
    latest = max((str(r.get("published_at", "")) for r in releases), default="")
    if not latest:
        return True
    try:
        pub = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - pub).days > 365
    except ValueError:
        return False


def _should_store_dbt_release(
    analysis: dict[str, Any], release: dict[str, Any], all_patches: bool = False
) -> bool:
    """For dbt packages: store patches only if prod-breaking; always store minor/major."""
    sv = parse_semver(str(release.get("tag_name", "")))
    if sv.valid and sv.patch > 0 and not all_patches:
        return bool(analysis.get("is_prod_breaking_bug", False))
    return True


def _process_repos(
    s3: Any,
    bucket: str,
    repos: list[dict[str, str]],
    llm_key: str,
    github_token: str | None,
    llm_delay_s: float,
    email_function_url: str | None,
    use_heuristics: bool,
) -> dict[str, Any]:
    """Phase 1 — fetch, analyse, and store releases for every configured repo."""
    repo_status: dict[str, Any] = {}

    for repo_cfg in repos:
        repo = repo_cfg["repo"]
        group = repo_cfg.get("group")
        min_version = repo_cfg.get("min_version")
        stable_only = repo_cfg.get("stable_only", False)
        minor_only = repo_cfg.get("minor_only", False)
        repo_type = repo_cfg.get("type", "release")
        is_dbt_package = repo_type == "dbt_package"
        all_patches = bool(repo_cfg.get("all_patches", False))
        is_deprecated = bool(repo_cfg.get("deprecated", False))
        deprecated_notice = repo_cfg.get("deprecated_notice")
        owner, name = repo.split("/", 1)

        try:
            source = repo_cfg.get("source", "github")
            cursor = get_cursor(s3, bucket, owner, name)

            if source == "changelog":
                releases = fetch_changelog_releases(owner, name, github_token, since=cursor)
                logger.info("[%s] changelog: %d releases", repo, len(releases))
            elif cursor is None:
                releases = backfill_releases(
                    owner,
                    name,
                    github_token,
                    min_version,
                    bool(stable_only),
                    minor_only=False if is_dbt_package else bool(minor_only),
                )
                logger.info("[%s] backfill %d releases (min=%s)", repo, len(releases), min_version)
            else:
                releases = get_new_releases(owner, name, cursor, github_token)
                if minor_only and not is_dbt_package:
                    releases = [
                        r for r in releases if parse_semver(str(r.get("tag_name", ""))).patch == 0
                    ]
                logger.info("[%s] incremental: %d new since %s", repo, len(releases), cursor)

            readme = fetch_readme(owner, name, github_token) if is_dbt_package else ""
            stale = _is_stale(releases) if is_dbt_package else False

            new_count = 0
            latest_published_at = cursor

            for release in releases:
                tag = str(release.get("tag_name", ""))
                if release_exists(s3, bucket, owner, name, tag):
                    continue

                if llm_delay_s > 0 and new_count > 0:
                    time.sleep(llm_delay_s)

                is_historical = tag == HISTORICAL_TAG
                if is_historical:
                    analysis, error = analyse_fusion_historical({**release, "repo": repo}, llm_key)
                elif source == "changelog":
                    analysis, error = analyse_fusion_release({**release, "repo": repo}, llm_key)
                elif is_dbt_package:
                    analysis, error = analyse_dbt_package_release(
                        {**release, "repo": repo},
                        readme,
                        stale=stale,
                        use_heuristics=use_heuristics,
                        api_key=llm_key,
                    )
                else:
                    analysis, error = analyse_release({**release, "repo": repo}, llm_key)

                if analysis is None:
                    logger.warning("[%s] skipping %s — LLM analysis failed: %s", repo, tag, error)
                    continue

                if source == "changelog" and not is_historical:
                    if not analysis.get("worth_tracking", True):
                        logger.info("[%s] skipping %s — not worth tracking", repo, tag)
                        latest_published_at = str(release.get("published_at", ""))
                        continue

                if is_dbt_package and not _should_store_dbt_release(analysis, release, all_patches):
                    logger.info("[%s] skipping patch %s — not prod-breaking", repo, tag)
                    latest_published_at = str(release.get("published_at", ""))
                    continue

                record = _build_record(
                    release, repo, analysis, error, [], group, is_deprecated, deprecated_notice
                )
                put_release(s3, bucket, record)
                new_count += 1
                latest_published_at = str(release.get("published_at", ""))

            if latest_published_at and latest_published_at != cursor:
                set_cursor(s3, bucket, owner, name, latest_published_at)

            repo_status[repo] = {"ok": True, "new_releases": new_count}

        except Exception as e:
            logger.error("[%s] pipeline error: %s", repo, e)
            repo_status[repo] = {"ok": False, "error": str(e)}
            if email_function_url:
                _call_email_function(
                    email_function_url.rstrip("/") + "/fail",
                    {"error": str(e), "repo": repo},
                )

    return repo_status


def _process_advisories(
    s3: Any,
    bucket: str,
    repos: list[dict[str, str]],
    llm_key: str,
    github_token: str | None,
) -> None:
    """Phase 2 — fetch and LLM-analyse security advisories for every repo."""
    logger.info("Fetching security advisories...")
    for repo_cfg in repos:
        repo = repo_cfg["repo"]
        owner, name = repo.split("/", 1)
        all_repo_advisories = fetch_advisories(owner, name, github_token)

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
            if ghsa in existing and cursor and updated_at <= cursor:
                adv["analysis"] = existing[ghsa].get("analysis")
                continue
            adv["analysis"] = analyse_advisory(adv, llm_key)
            updated = True
            logger.info("[%s] advisory analysed: %s", repo, ghsa)

        write_repo_advisories(s3, bucket, owner, name, all_repo_advisories)
        if updated and all_repo_advisories:
            latest = max((a.get("updated_at") or "" for a in all_repo_advisories), default="")
            if latest:
                set_advisory_cursor(s3, bucket, owner, name, latest)
        logger.info("[%s] %d advisories stored", repo, len(all_repo_advisories))


def _build_and_clean_digest(s3: Any, bucket: str) -> tuple[list[dict[str, Any]], str]:
    """Phase 3 — write versioned digest JSON and remove stale digest files."""
    all_advisories = read_all_advisories(s3, bucket)
    all_records = get_digest(s3, bucket, limit=500)
    digest_key = write_digest_json(s3, bucket, all_records, all_advisories)
    logger.info("%s: %d releases, %d advisories", digest_key, len(all_records), len(all_advisories))

    paginator = s3.get_paginator("list_objects_v2")
    old_digests = []
    for page in paginator.paginate(Bucket=bucket, Prefix="digest-"):
        for obj in page.get("Contents", []):
            if obj["Key"] != digest_key:
                old_digests.append({"Key": obj["Key"]})
    if old_digests:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": old_digests})
        logger.info("Cleaned %d old digest(s)", len(old_digests))

    return all_records, digest_key


def run_pipeline(
    s3: Any,
    bucket: str,
    llm_key: str,
    github_token: str | None = None,
    llm_delay_s: float = 0.0,
    email_function_url: str | None = None,
    use_heuristics: bool = False,
) -> dict[str, Any]:
    run_start = datetime.now(timezone.utc).isoformat()
    repos = load_repos()

    repo_status = _process_repos(
        s3, bucket, repos, llm_key, github_token, llm_delay_s, email_function_url, use_heuristics
    )
    set_run_status(
        s3, bucket, {"ran_at": datetime.now(timezone.utc).isoformat(), "repos": repo_status}
    )

    _process_advisories(s3, bucket, repos, llm_key, github_token)

    all_records, _ = _build_and_clean_digest(s3, bucket)

    if email_function_url:
        # ISO8601 sorts lexicographically — valid comparison for UTC timestamps
        new_records = [r for r in all_records if str(r.get("fetched_at", "")) >= run_start]
        if new_records:
            _call_email_function(email_function_url, {"releases": new_records})
            logger.info("Email function called: %d releases", len(new_records))

    logger.info("Pipeline complete: %s", repo_status)
    return {"ran_at": run_start, "repos": repo_status}
