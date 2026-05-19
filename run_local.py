"""Run the pipeline locally — loads .env.local for secrets."""
import os
from pathlib import Path


def load_env(path: str = ".env.local") -> None:
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


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

# Use Gemini if GEMINI_API_KEY is set, otherwise fall back to Groq
try:
    llm_key = get_secret(GCP_PROJECT, "GEMINI_API_KEY")
    llm_provider = "gemini"
    print("🤖 Provider: Google Gemini 2.0 Flash\n")
except Exception:
    llm_key = get_secret(GCP_PROJECT, "GROQ_API_KEY")
    llm_provider = "groq"
    print("🤖 Provider: Groq llama-3.3-70b\n")

print("🚀 Starting pipeline...\n")
result = run_pipeline(s3, R2_BUCKET, llm_key, github_token, llm_provider)

print("\n✅ Done:")
for repo, status in result["repos"].items():
    if status["ok"]:
        print(f"  {repo}: {status['new_releases']} new releases")
    else:
        print(f"  {repo}: ❌ {status['error']}")
