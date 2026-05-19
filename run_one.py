"""Test pipeline on a single release — fetch + analyse + store to R2.

Usage:
    python3.12 run_one.py dagster-io/dagster 1.11.0
    python3.12 run_one.py dbt-labs/dbt-core v1.10.0
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)


def load_env(path: str = ".env.local") -> None:
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()


load_env()

import requests  # noqa: E402

from src.analyser import analyse_release  # noqa: E402
from src.config import GCP_PROJECT, R2_BUCKET  # noqa: E402
from src.secrets import get_secret  # noqa: E402
from src.store import get_s3_client, put_release, release_exists  # noqa: E402

if len(sys.argv) != 3:
    print("Usage: python3.12 run_one.py <owner/repo> <tag>")
    print("  e.g: python3.12 run_one.py dagster-io/dagster 1.11.0")
    sys.exit(1)

repo = sys.argv[1]
tag = sys.argv[2].lstrip("v")
owner, name = repo.split("/")

# ── Secrets ────────────────────────────────────────────────────────────────
s3 = get_s3_client(
    access_key=get_secret(GCP_PROJECT, "R2_ACCESS_KEY_ID"),
    secret_key=get_secret(GCP_PROJECT, "R2_SECRET_ACCESS_KEY"),
    account_id=get_secret(GCP_PROJECT, "R2_ACCOUNT_ID"),
)
openai_key = get_secret(GCP_PROJECT, "OPENAI_API_KEY")
github_token = get_secret(GCP_PROJECT, "GITHUB_TOKEN")

# ── Check if already in R2 ─────────────────────────────────────────────────
full_tag = f"v{tag}" if not tag.startswith("v") else tag
if release_exists(s3, R2_BUCKET, owner, name, full_tag):
    print(f"⏭  {repo}@{full_tag} already in R2 — nothing to do")
    sys.exit(0)

# ── Fetch from GitHub (try both v-prefix and without) ─────────────────────
headers = {
    "Accept": "application/vnd.github+json",
    **({"Authorization": f"Bearer {github_token}"} if github_token else {}),
}
release = None
for try_tag in [full_tag, full_tag.lstrip("v")]:
    log.info("Fetching %s@%s from GitHub...", repo, try_tag)
    resp = requests.get(
        f"https://api.github.com/repos/{repo}/releases/tags/{try_tag}",
        headers=headers, timeout=10,
    )
    if resp.ok:
        full_tag = try_tag
        release = resp.json()
        break

if release is None:
    print(f"❌ GitHub 404: tag '{full_tag}' not found in {repo}")
    sys.exit(1)

log.info("Got release: %s", release.get("name"))

# ── Analyse ────────────────────────────────────────────────────────────────
log.info("Analysing with gpt-4o-mini...")
analysis, error = analyse_release({**release, "repo": repo}, openai_key, provider="openai")

if error:
    print(f"❌ Analysis failed: {error}")
    sys.exit(1)

# ── Store to R2 ────────────────────────────────────────────────────────────
record = {
    "id": release.get("id"),
    "repo": repo,
    "tag": full_tag,
    "name": release.get("name"),
    "body": release.get("body", ""),
    "published_at": release.get("published_at"),
    "html_url": release.get("html_url"),
    "author": (release.get("author") or {}).get("login"),
    "prerelease": release.get("prerelease", False),
    "draft": release.get("draft", False),
    "fetched_at": datetime.now(timezone.utc).isoformat(),
    "analysis": analysis,
    "analysis_error": None,
    "cve_details": [],
}

put_release(s3, R2_BUCKET, record)
log.info("✅ Stored in R2: releases/%s/%s/%s.json", owner, name, full_tag)

print("\n── Analysis ──────────────────────────────────────────")
print(json.dumps(analysis, indent=2, ensure_ascii=False))
