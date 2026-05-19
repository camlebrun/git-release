"""Fetch + analyse releases and print JSON live — no R2 write."""
import json
import os
import sys
from pathlib import Path


def load_env(path: str = ".env.local") -> None:
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()

from src.analyser import analyse_release  # noqa: E402
from src.config import GCP_PROJECT  # noqa: E402
from src.fetcher import backfill_releases  # noqa: E402
from src.secrets import get_secret  # noqa: E402

github_token = get_secret(GCP_PROJECT, "GITHUB_TOKEN")
gemini_key = get_secret(GCP_PROJECT, "GEMINI_API_KEY")

repos = json.loads(Path("repos.json").read_text())

for repo_cfg in repos:
    repo = repo_cfg["repo"]
    min_version = repo_cfg.get("min_version")
    stable_only = repo_cfg.get("stable_only", False)
    owner, name = repo.split("/")

    print(f"\n{'='*60}", flush=True)
    print(f"  {repo}  (min={min_version}, stable={stable_only})", flush=True)
    print(f"{'='*60}", flush=True)

    releases = backfill_releases(owner, name, github_token, min_version, stable_only)
    print(f"  → {len(releases)} releases à analyser\n", flush=True)

    for i, release in enumerate(releases, 1):
        tag = str(release.get("tag_name", ""))
        print(f"[{i}/{len(releases)}] {repo}@{tag} ...", flush=True)

        analysis, error = analyse_release(
            {**release, "repo": repo}, gemini_key, provider="gemini"
        )

        record = {
            "repo": repo,
            "tag": tag,
            "name": release.get("name"),
            "published_at": release.get("published_at"),
            "html_url": release.get("html_url"),
            "analysis": analysis,
            "analysis_error": error,
        }

        print(json.dumps(record, indent=2, ensure_ascii=False), flush=True)
        print(flush=True)

print("\n✅ Done.", flush=True)
