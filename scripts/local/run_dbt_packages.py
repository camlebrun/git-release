"""Run pipeline locally for dbt packages only — heuristic analysis, no LLM."""
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")


def load_env(path: str = ".env.local") -> None:
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()


load_env()

from src.config import GCP_PROJECT, R2_BUCKET  # noqa: E402
from src.pipeline import load_repos, run_pipeline  # noqa: E402
from src.secrets import get_secret  # noqa: E402
from src.store import get_s3_client  # noqa: E402

# Temporarily override repos.json to only process dbt packages
_original_repos = load_repos()
_dbt_repos = [r for r in _original_repos if r.get("type") == "dbt_package"]
print(f"dbt packages to process: {[r['repo'] for r in _dbt_repos]}\n")

# Monkey-patch load_repos to return only dbt packages for this run
import src.pipeline as _pipeline  # noqa: E402

_pipeline._REPOS_PATH = Path("/dev/null")  # will be overridden below


def _dbt_only_load_repos():
    return _dbt_repos


_pipeline.load_repos = _dbt_only_load_repos  # type: ignore[assignment]

s3 = get_s3_client(
    access_key=get_secret(GCP_PROJECT, "R2_ACCESS_KEY_ID"),
    secret_key=get_secret(GCP_PROJECT, "R2_SECRET_ACCESS_KEY"),
    account_id=get_secret(GCP_PROJECT, "R2_ACCOUNT_ID"),
)
github_token = get_secret(GCP_PROJECT, "GITHUB_TOKEN")

llm_key = get_secret(GCP_PROJECT, "MISTRAL_API_KEY")
llm_delay_s = 1.2  # free tier ~1 req/s

print("Mode: Mistral LLM\n")
print("Starting dbt packages pipeline...\n")

result = run_pipeline(
    s3,
    R2_BUCKET,
    llm_key=llm_key,
    github_token=github_token,
    llm_provider="mistral",
    llm_delay_s=llm_delay_s,
    use_heuristics=False,
)

print("\nDone:")
for repo, status in result["repos"].items():
    if status["ok"]:
        print(f"  {repo}: {status['new_releases']} new releases stored")
    else:
        print(f"  {repo}: ERROR {status['error']}")
