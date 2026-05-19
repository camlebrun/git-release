"""Run the pipeline locally — loads .env.local for secrets."""
import logging
import os
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)


def load_env(path: str = ".env.local") -> None:
    """Always overwrite — so updating .env.local is picked up on restart."""
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()


load_env()

from src.config import GCP_PROJECT, R2_BUCKET  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402
from src.secrets import get_secret  # noqa: E402
from src.store import get_s3_client  # noqa: E402

s3 = get_s3_client(
    access_key=get_secret(GCP_PROJECT, "R2_ACCESS_KEY_ID"),
    secret_key=get_secret(GCP_PROJECT, "R2_SECRET_ACCESS_KEY"),
    account_id=get_secret(GCP_PROJECT, "R2_ACCOUNT_ID"),
)

github_token = get_secret(GCP_PROJECT, "GITHUB_TOKEN")

llm_key = get_secret(GCP_PROJECT, "OPENAI_API_KEY")
llm_provider = "openai"
llm_delay_s = 0.3  # 500 RPM — quasi pas besoin de délai
print("🤖 Provider: OpenAI gpt-4o-mini (~$0.06 pour 116 releases)\n")

print("🚀 Starting pipeline...\n")
result = run_pipeline(s3, R2_BUCKET, llm_key, github_token, llm_provider, llm_delay_s)

print("\n✅ Done:")
for repo, status in result["repos"].items():
    if status["ok"]:
        print(f"  {repo}: {status['new_releases']} new releases")
    else:
        print(f"  {repo}: ❌ {status['error']}")
