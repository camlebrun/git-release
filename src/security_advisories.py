from __future__ import annotations

import json
import logging
from typing import Any

import requests

from src.config import GITHUB_API_BASE, GITHUB_TIMEOUT_S

logger = logging.getLogger(__name__)

_SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def fetch_advisories(owner: str, repo: str, token: str | None = None) -> list[dict[str, Any]]:
    """Fetch published security advisories for a repo via GitHub API."""
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    advisories: list[dict[str, Any]] = []
    try:
        # Single request — repos have few advisories, no pagination needed
        resp = requests.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/security-advisories",
            headers=headers,
            params={"per_page": 100, "state": "published"},
            timeout=GITHUB_TIMEOUT_S,
        )
        if resp.ok:
            advisories = resp.json()
            if not isinstance(advisories, list):
                advisories = []
        else:
            logger.warning("Security advisories %s/%s: HTTP %s", owner, repo, resp.status_code)
    except Exception as e:
        logger.error("Failed to fetch advisories for %s/%s: %s", owner, repo, e)

    result = []
    for a in advisories:
        result.append(
            {
                "ghsa_id": a.get("ghsa_id"),
                "cve_id": a.get("cve_id"),
                "severity": a.get("severity", "unknown"),
                "summary": a.get("summary", ""),
                "description": (a.get("description") or "")[:500],
                "published_at": a.get("published_at"),
                "updated_at": a.get("updated_at"),
                "html_url": a.get("html_url"),
                "repo": f"{owner}/{repo}",
            }
        )

    result.sort(
        key=lambda x: (_SEV_ORDER.get(x["severity"], 9), x.get("published_at") or ""), reverse=False
    )
    return result


def analyse_advisory(
    advisory: dict[str, Any], api_key: str, provider: str = "openai"
) -> dict[str, Any] | None:
    """Run LLM analysis on an advisory. Returns analysis dict or None on failure."""
    from src.analyser import _call_openai  # noqa: PLC0415
    from src.prompts.advisory_analysis import ADVISORY_ANALYSIS_PROMPT

    prompt = ADVISORY_ANALYSIS_PROMPT.format(
        repo=advisory.get("repo", ""),
        ghsa_id=advisory.get("ghsa_id", ""),
        cve_id=advisory.get("cve_id", "N/A"),
        severity=advisory.get("severity", ""),
        summary=advisory.get("summary", ""),
        description=(advisory.get("description") or "")[:3000],
    )
    try:
        raw = _call_openai(prompt, api_key)
        return json.loads(raw)
    except Exception as e:
        logger.error("Advisory analysis failed for %s: %s", advisory.get("ghsa_id"), e)
        return None
