GCP_PROJECT = "git-release-496817"
GCP_REGION = "europe-west9"

R2_BUCKET = "git-release-releases"

MAX_RELEASES_PER_RUN = 50
BACKFILL_NON_SEMVER = 20
DIGEST_DEFAULT_LIMIT = 20
DIGEST_MAX_LIMIT = 100
LLM_MAX_TOKENS = 4096
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

GEMINI_MODEL = "gemini-flash-latest"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

OPENAI_MODEL = "gpt-4o-mini"
OPENAI_BASE_URL = "https://api.openai.com/v1"

MISTRAL_MODEL = "mistral-small-latest"

GITHUB_API_BASE = "https://api.github.com"
GROQ_TIMEOUT_S = 10
GITHUB_TIMEOUT_S = 10
GITHUB_RETRY_MAX = 3
