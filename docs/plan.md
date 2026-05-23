# Plan — StackRadar

> Technical blueprint. Translate spec intent into architecture decisions, data models, and API contracts.

---

## 3.1 Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  GCP project: git-release-496817                                     │
│                                                                      │
│  ┌──────────────────┐   triggers Job (daily)                        │
│  │ Cloud Scheduler  │──────────────────────────────────┐            │
│  │ 0 6 * * * UTC    │                                  │            │
│  └──────────────────┘                                  ▼            │
│                                          ┌─────────────────────┐    │
│                                          │  Cloud Run Job      │    │
│                                          │  (Python 3.12)      │    │
│                                          │  src/main.py        │    │
│                                          └────────┬────────────┘    │
│                                                   │                  │
│                    ┌──────────────────────────────┼───────────────┐ │
│                    │   Cloudflare R2               │               │ │
│                    │   git-release-releases        │               │ │
│                    │                              ▼               │ │
│                    │  releases/{owner}/{repo}/{tag}.json (blobs)  │ │
│                    │  meta/cursor/{owner}/{repo}.json             │ │
│                    │  meta/run_status.json                        │ │
│                    └──────────────────────────────────────────────┘ │
│                                                                      │
│  ┌──────────────────────────────────────────────┐                   │
│  │  Secret Manager                              │                   │
│  │  MISTRAL_API_KEY / GITHUB_TOKEN /            │                   │
│  │  EMAIL_FUNCTION_URL / R2 credentials         │                   │
│  └──────────────────────────────────────────────┘                   │
│                                                                      │
│  ┌──────────────────────────────────────┐                           │
│  │  Cloud Function gen2 (email)         │                           │
│  │  functions/email/main.py             │                           │
│  └──────────────────────────────────────┘                           │
└──────────────────────────────────────────────────────────────────────┘
                        │  reads public R2 URL
                        ▼
             ┌──────────────────────┐
             │  Cloudflare Pages    │
             │  index.html (bento)  │
             │  Vanilla JS fetch()  │
             └──────────────────────┘
```

**Cloud Run Job** is the pipeline compute — triggered daily by Cloud Scheduler, runs to completion, scales to zero.  
**Cloudflare R2** is the single storage layer (S3-compatible via boto3) — release blobs under `releases/`, metadata under `meta/`. No separate database needed.  
**Secret Manager** holds all credentials; the Cloud Run Job's service account has `secretmanager.secretAccessor` role.  
**Cloud Function gen2** (email) is a separate lightweight HTTP-triggered unit that sends the daily digest email.  
**Cloudflare Pages** serves the static bento frontend; it reads release data directly from the public R2 bucket URL.

---

## 3.2 Repository Layout

```
git-release/
├── repos.json                  # Tracked repos ["owner/repo", ...]
├── pyproject.toml              # Python project config (black, ruff, mypy, pytest)
├── requirements.txt            # Runtime deps (mistralai, boto3, ...)
├── requirements-dev.txt        # Dev deps (pytest, pytest-mock, pytest-cov, pip-audit, ...)
├── Dockerfile                  # Cloud Run Job container image
├── src/
│   ├── main.py                 # Cloud Run Job entry point
│   ├── config.py               # Constants (limits, bucket name, project ID, etc.)
│   ├── secrets.py              # GCP Secret Manager helpers
│   ├── fetcher.py              # GitHub API client
│   ├── semver.py               # Minimal semver parser (no external dep)
│   ├── analyser.py             # Mistral API client + prompt call
│   ├── store.py                # R2/boto3 read/write helpers
│   ├── pipeline.py             # Orchestration: fetch → analyse → store
│   ├── digest.py               # Digest aggregation logic
│   ├── security_advisories.py  # GitHub Security Advisories fetch + analyse
│   └── prompts/
│       ├── release_analysis.py    # LLM prompt: release summary
│       ├── dbt_package_analysis.py# LLM prompt: dbt package
│       └── advisory_analysis.py   # LLM prompt: security advisory
├── functions/
│   └── email/
│       ├── main.py             # Cloud Function gen2: send daily digest email
│       └── requirements.txt
├── public/
│   ├── index.html              # Main bento page
│   ├── app.js                  # Fetch + render logic
│   ├── style.css               # Grid bento styles
│   └── dbt-packages/           # dbt packages sub-page
└── tests/
    ├── test_fetcher.py
    ├── test_semver.py
    ├── test_analyser.py
    ├── test_store.py
    ├── test_digest.py
    ├── test_pipeline.py
    └── test_security_advisories.py
```

---

## 3.3 Cloud Run Job Entry Point (`src/main.py`)

```python
def main() -> None:
    llm_key = get_secret(GCP_PROJECT, "MISTRAL_API_KEY")
    github_token = get_secret(GCP_PROJECT, "GITHUB_TOKEN")   # optional
    email_function_url = get_secret(GCP_PROJECT, "EMAIL_FUNCTION_URL")  # optional
    s3 = get_s3_client(...)
    run_pipeline(s3, R2_BUCKET, llm_key, github_token, email_function_url)

if __name__ == "__main__":
    main()
```

The Cloud Run Job is invoked by **Cloud Scheduler** (`0 6 * * * UTC`). It runs to completion and exits. There are no HTTP routes on the job itself.

The **email Cloud Function** (`functions/email/main.py`) is a separate gen2 HTTP-triggered function that reads the digest from R2 and sends the daily email. It is called by the pipeline at the end of a successful run via `EMAIL_FUNCTION_URL`.

---

## 3.4 GitHub Fetcher (`src/fetcher.py`)

Uses `requests` (simpler than `httpx` for sync Cloud Run context).

### Incremental fetch (cursor exists)
```python
def get_new_releases(owner: str, repo: str, since: str, token: str | None = None) -> list[dict]:
```
- Paginates `GET /repos/{owner}/{repo}/releases?per_page=100&page=N`.
- Stops when `published_at <= since` or no more pages.
- Returns ascending by `published_at`, capped at `MAX_RELEASES_PER_RUN`.

### First-run backfill (no cursor)
```python
def backfill_releases(owner: str, repo: str, token: str | None = None) -> list[dict]:
```
1. Paginate ALL releases (all pages, no early stop).
2. Call `parse_semver(tag)` from `src/semver.py` on each tag.
3. `M` = max valid major found.
4. Keep releases where major ∈ `{M, M-1}`.
5. Non-semver fallback: return 20 most recent by `published_at`.
6. Return ascending by `published_at`.

Raises `GitHubFetchError(status, message)` on non-2xx responses.

## 3.5 Semver Parser (`src/semver.py`)

```python
from dataclasses import dataclass

@dataclass
class SemVer:
    major: int
    minor: int
    patch: int
    valid: bool

def parse_semver(tag: str) -> SemVer:
    # strips leading 'v', splits on '-' to discard pre-release suffix,
    # then splits on '.' — returns SemVer(valid=False) if not \d+\.\d+\.\d+
```

No external dependency — stdlib `re` only.

---

## 3.6 Analyser (`src/analyser.py`)

```python
from mistralai import Mistral

def call_llm(prompt: str, api_key: str) -> str:
    """Single public entry point for all LLM calls."""

def analyse_release(release: dict, api_key: str) -> tuple[dict | None, str | None]:
```
- Instantiates `Mistral(api_key=api_key)`.
- Calls `client.chat.complete(model=MISTRAL_MODEL, response_format={"type": "json_object"}, ...)`.
- `MISTRAL_MODEL = "mistral-small-latest"`, `LLM_MAX_TOKENS = 4096`.
- Prompt template from `src/prompts/release_analysis.py` — injects `repo`, `tag`, `name`, `body[:4000]`.
- Expected JSON output:
  ```json
  {
    "summary": "2-4 sentences",
    "key_changes": ["...", "..."],
    "cve_references": ["CVE-YYYY-NNNNN"],
    "severity": "none|low|medium|high|critical",
    "tags": ["breaking|security|performance|bug-fix|feature|deprecation"]
  }
  ```
- Validates with a `pydantic` model (`AnalysisResult`); on `ValidationError` returns `(None, error_str)` and logs `analysis_error`.

---

## 3.7 R2 Store via boto3 (`src/store.py`)

R2 exposes an S3-compatible API. We use `boto3` with a custom endpoint — no Cloudflare Workers needed.

```python
import boto3

def get_s3_client(access_key: str, secret_key: str, account_id: str):
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
```

### R2 object paths (in bucket `git-release-releases`)

| Purpose | R2 key |
|---|---|
| Release blob | `releases/{owner}/{repo}/{tag}.json` |
| Cursor | `meta/cursor/{owner}/{repo}.json` |
| Run status | `meta/run_status.json` |

### Helper functions

```python
def get_release(s3, bucket: str, owner: str, repo: str, tag: str) -> dict | None
def put_release(s3, bucket: str, record: dict) -> None     # no-op if key exists
def release_exists(s3, bucket: str, owner: str, repo: str, tag: str) -> bool
def list_release_keys(s3, bucket: str) -> list[str]        # paginated, prefix="releases/"

def get_cursor(s3, bucket: str, owner: str, repo: str) -> str | None
def set_cursor(s3, bucket: str, owner: str, repo: str, published_at: str) -> None

def get_run_status(s3, bucket: str) -> dict | None
def set_run_status(s3, bucket: str, status: dict) -> None
```

`release_exists` uses `s3.head_object` (cheaper than GET). All blobs stored with `ContentType="application/json"`.

---

## 3.8 Digest Aggregation (`src/digest.py`)

```python
def get_digest(bucket, limit: int = DIGEST_DEFAULT_LIMIT) -> list[dict]:
```
- Lists all blobs with prefix `releases/`.
- Downloads in parallel using `ThreadPoolExecutor` (batches of 20).
- Parses each blob's JSON, drops the `body` field (raw markdown — saves ~80% payload).
- Sorts by `published_at` descending, returns first `limit` items.

---

## 3.9 Pipeline Orchestration (`src/pipeline.py`)

Runs as the Cloud Run Job's main workload:

```python
def run_pipeline(
    s3: S3Client,
    bucket: str,
    llm_key: str,
    github_token: str | None = None,
    email_function_url: str | None = None,
) -> dict:
    repos = load_repos()       # reads repos.json
    repo_results = _process_repos(s3, bucket, repos, llm_key, github_token, ...)
    _process_advisories(s3, bucket, repos, llm_key, github_token)
    digest, digest_key = _build_and_clean_digest(s3, bucket)
    if email_function_url and digest:
        _send_email_notification(email_function_url, digest[:5])
    run_status = {"ran_at": utcnow_iso(), "repos": repo_results}
    set_run_status(s3, bucket, run_status)
    return run_status
```

Three private helpers keep the orchestrator thin:
- `_process_repos` — per-repo fetch / analyse / store loop
- `_process_advisories` — GitHub Security Advisories fetch + LLM analyse
- `_build_and_clean_digest` — aggregate, sort, write `digest.json` to R2

---

## 3.10 Frontend Architecture (`public/`)

- `index.html`: minimal shell with a `<div id="grid">` and a `<input id="search">`.
- `app.js`:
  - Reads `CLOUD_FUNCTION_URL` from a `<meta name="api-url">` tag set at deploy time.
  - On load: `fetch(CLOUD_FUNCTION_URL + '/digest?limit=50')` → render cards.
  - `renderCard(record)` → returns an HTML string injected via `innerHTML` (data is trusted — from our own function).
  - Search input filters `document.querySelectorAll('.card')` by `data-repo` and `data-tags` attributes.
- `style.css`:
  - CSS Grid: `grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))`.
  - Severity badge: coloured pill using CSS custom properties.
  - Card hover: subtle lift (`box-shadow` transition).

---

## 3.11 Configuration (`src/config.py`)

```python
GCP_PROJECT      = "git-release-496817"
GCP_REGION       = "europe-west9"
R2_BUCKET        = "git-release-releases"

MAX_RELEASES_PER_RUN   = 50
BACKFILL_NON_SEMVER    = 20    # fallback count for repos without semver tags
DIGEST_DEFAULT_LIMIT   = 20
DIGEST_MAX_LIMIT       = 100
LLM_MAX_TOKENS         = 4096
MISTRAL_MODEL          = "mistral-small-latest"
GITHUB_API_BASE        = "https://api.github.com"
GITHUB_TIMEOUT_S       = 10
GITHUB_RETRY_MAX       = 3
```

---

## 3.12 Secrets (`src/secrets.py`)

Secrets live in **GCP Secret Manager** — never in env vars or committed files.

```python
from google.cloud import secretmanager

def get_secret(project: str, name: str) -> str:
    client = secretmanager.SecretManagerServiceClient()
    path = f"projects/{project}/secrets/{name}/versions/latest"
    return client.access_secret_version(name=path).payload.data.decode()
```

Secrets accessed at job startup:
- `MISTRAL_API_KEY` — Mistral account API key
- `GITHUB_TOKEN` — GitHub PAT, `public_repo` read-only (optional, raises rate limit 60→5000 req/hr)
- `EMAIL_FUNCTION_URL` — URL of the email Cloud Function (optional; email skipped if absent)
- `R2_ACCESS_KEY_ID` — R2 API token ID (create in Cloudflare dashboard → R2 → Manage API Tokens)
- `R2_SECRET_ACCESS_KEY` — R2 API token secret
- `R2_ACCOUNT_ID` — Cloudflare account ID (found in dashboard URL)

The Cloud Run Job's service account needs `roles/secretmanager.secretAccessor`.

---

## 3.13 Deployment

```bash
# 1. Create R2 bucket in Cloudflare dashboard
# Dashboard → R2 → Create bucket → name: git-release-releases
# Then create R2 API token: Dashboard → R2 → Manage API Tokens → Create token (Object Read & Write)

# 2. Store secrets in GCP Secret Manager
echo -n "..." | gcloud secrets create MISTRAL_API_KEY --data-file=- --project=git-release-496817
echo -n "ghp_..." | gcloud secrets create GITHUB_TOKEN --data-file=- --project=git-release-496817
echo -n "https://..." | gcloud secrets create EMAIL_FUNCTION_URL --data-file=- --project=git-release-496817
echo -n "<r2-access-key-id>" | gcloud secrets create R2_ACCESS_KEY_ID --data-file=- --project=git-release-496817
echo -n "<r2-secret-access-key>" | gcloud secrets create R2_SECRET_ACCESS_KEY --data-file=- --project=git-release-496817
echo -n "<cloudflare-account-id>" | gcloud secrets create R2_ACCOUNT_ID --data-file=- --project=git-release-496817

# 3. Build and push Docker image (or use Cloud Build)
gcloud builds submit --config=cloudbuild.yaml --project=git-release-496817

# 4. Deploy Cloud Run Job
gcloud run jobs deploy stackradar-pipeline \
  --image=europe-west9-docker.pkg.dev/git-release-496817/git-release/stackradar:latest \
  --region=europe-west9 \
  --service-account=git-release-sa@git-release-496817.iam.gserviceaccount.com \
  --project=git-release-496817

# 5. Create Cloud Scheduler job
gcloud scheduler jobs create http stackradar-daily \
  --schedule="0 6 * * *" \
  --uri="https://europe-west9-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/git-release-496817/jobs/stackradar-pipeline:run" \
  --http-method=POST \
  --oauth-service-account-email=git-release-sa@git-release-496817.iam.gserviceaccount.com \
  --time-zone="UTC" \
  --project=git-release-496817

# 6. Deploy email Cloud Function
gcloud functions deploy email-digest \
  --gen2 \
  --runtime=python312 \
  --region=europe-west9 \
  --source=functions/email \
  --entry-point=send_digest \
  --trigger-http \
  --service-account=git-release-sa@git-release-496817.iam.gserviceaccount.com \
  --project=git-release-496817

# 7. Frontend deploys automatically via Cloudflare Pages on push to main
```

---

## 3.14 Testing Strategy

- **Unit tests** (`pytest` + `pytest-mock`, coverage gate ≥ 65%):
  - `test_semver.py`: tag parsing edge cases
  - `test_fetcher.py`: mock `requests.get`, assert URL construction, pagination, backfill filter
  - `test_analyser.py`: mock Mistral SDK, assert pydantic validation + fallback
  - `test_store.py`: mock boto3 S3 client, assert idempotency, cursor read/write
  - `test_digest.py`: assert sort order, limit, body stripping
  - `test_pipeline.py`: mock all I/O, assert orchestration (backfill vs incremental, error isolation)
  - `test_security_advisories.py`: mock GitHub advisory API + LLM, assert normalisation and severity sort
- **Local run**: `python -m src.main` with `.env.local` for secrets (never committed)
- **Security scan**: `bandit -r src functions` + `pip-audit` in CI
- **No E2E browser automation in v1** — manual visual check of bento page
