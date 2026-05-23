"""Preview releases that would be fetched — no R2 write, no Groq call."""
import json
import os
from pathlib import Path


def load_env(path: str = ".env.local") -> None:
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()

from src.config import GCP_PROJECT  # noqa: E402
from src.fetcher import backfill_releases  # noqa: E402
from src.secrets import get_secret  # noqa: E402

github_token = get_secret(GCP_PROJECT, "GITHUB_TOKEN")

repos = json.loads(Path("repos.json").read_text())

for repo_cfg in repos:
    repo = repo_cfg["repo"]
    min_version = repo_cfg.get("min_version")
    owner, name = repo.split("/", 1)

    print(f"\n{'='*60}")
    print(f"  {repo}  (min_version={min_version})")
    print(f"{'='*60}")

    releases = backfill_releases(owner, name, github_token, min_version)
    print(f"  → {len(releases)} releases\n")

    for r in releases:
        print(json.dumps({
            "tag":          r.get("tag_name"),
            "name":         r.get("name"),
            "published_at": r.get("published_at"),
            "prerelease":   r.get("prerelease"),
        }, indent=2))
