# Plan — GitHub Release Digest

> Technical blueprint. Translate spec intent into architecture decisions, data models, and API contracts.

---

## 3.1 Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  GCP project: git-release-496817                                     │
│                                                                      │
│  ┌──────────────────┐   HTTP POST (daily)                           │
│  │ Cloud Scheduler  │──────────────────────────────────┐            │
│  │ 0 6 * * * UTC    │                                  │            │
│  └──────────────────┘                                  ▼            │
│                                          ┌─────────────────────┐    │
│  Browser / curl ──── GET /trigger ──────▶│                     │    │
│  Browser / curl ──── GET /digest  ──────▶│  Cloud Function     │    │
│  Browser / curl ──── GET /health  ──────▶│  (Python 3.12)      │    │
│                                          │  main()             │    │
│                                          └────────┬────────────┘    │
│                                                   │                  │
│                    ┌──────────────────────────────┼───────────────┐ │
│                    │   Cloud Storage bucket        │               │ │
│                    │   git-release-496817-releases │               │ │
│                    │                              ▼               │ │
│                    │  releases/{owner}/{repo}/{tag}.json (blobs)  │ │
│                    │  meta/cursor/{owner}/{repo}.json             │ │
│                    │  meta/run_status.json                        │ │
│                    └──────────────────────────────────────────────┘ │
│                                                                      │
│  ┌──────────────────────────────────────┐                           │
│  │  Secret Manager                      │                           │
│  │  GROQ_API_KEY / GITHUB_TOKEN /       │                           │
│  │  TRIGGER_SECRET                      │                           │
│  └──────────────────────────────────────┘                           │
└──────────────────────────────────────────────────────────────────────┘
                        │  GET /digest (CORS)
                        ▼
             ┌──────────────────────┐
             │  Cloudflare Pages    │
             │  index.html (bento)  │
             │  Vanilla JS fetch()  │
             └──────────────────────┘
```

**Cloud Function** (HTTP trigger, gen2) handles both the cron invocation from Cloud Scheduler and direct HTTP calls.  
**GCS** is the single storage layer — release blobs under `releases/`, metadata under `meta/`. No separate database needed.  
**Secret Manager** holds all credentials; the Cloud Function's service account has `secretmanager.secretAccessor` role.  
**Cloudflare Pages** serves the static bento frontend; it calls the Cloud Function URL directly (CORS enabled).

---

## 3.2 Repository Layout

```
git-release/
├── repos.json                  # Tracked repos ["owner/repo", ...]
├── pyproject.toml              # Python project config (black, ruff, mypy, pytest)
├── requirements.txt            # Runtime deps (groq, google-cloud-storage, ...)
├── requirements-dev.txt        # Dev deps (pytest, pytest-mock, functions-framework, ...)
├── src/
│   ├── main.py                 # Cloud Function entry: request router
│   ├── config.py               # Constants (limits, bucket name, project ID, etc.)
│   ├── secrets.py              # Google Secret Manager helpers
│   ├── fetcher.py              # GitHub API client
│   ├── semver.py               # Minimal semver parser (no external dep)
│   ├── analyser.py             # Groq API client + prompt call
│   ├── store.py                # GCS read/write helpers
│   ├── digest.py               # Digest aggregation logic
│   └── prompts/
│       └── release_analysis.py # LLM prompt template string
├── public/
│   ├── index.html              # Bento page shell
│   ├── app.js                  # Fetch + render logic
│   └── style.css               # Grid bento styles
└── tests/
    ├── test_fetcher.py
    ├── test_semver.py
    ├── test_analyser.py
    ├── test_store.py
    └── test_digest.py
```

---

## 3.3 Cloud Function Entry & Routing (`src/main.py`)

```python
import functions_framework
from flask import Request, Response

@functions_framework.http
def main(request: Request) -> Response:
    # OPTIONS preflight for CORS
    if request.method == "OPTIONS":
        return _cors_preflight()
    path = request.path.rstrip("/")
    if path == "/digest":
        return handle_digest(request)
    if path == "/health":
        return handle_health(request)
    if path == "/trigger":
        return handle_trigger(request)
    return Response("Not Found", status=404)
```

Routes:

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/digest` | none | Return paginated release records |
| GET | `/health` | none | Last run info + per-repo status |
| GET/POST | `/trigger` | `X-Trigger-Secret` header | Manually trigger or Cloud Scheduler call |

CORS: `Access-Control-Allow-Origin: *` on all routes — required so Cloudflare Pages (different origin) can call the function.

**Cloud Scheduler** sends a `POST /trigger` with the secret header from a service account — same code path as manual trigger.

---

## 3.4 GitHub Fetcher (`src/fetcher.py`)

Uses `requests` (simpler than `httpx` for sync Cloud Functions context).

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
from groq import Groq

def analyse_release(release: dict, api_key: str) -> dict | None:
```
- Instantiates `Groq(api_key=api_key)`.
- Calls `client.chat.completions.create(model=GROQ_MODEL, response_format={"type": "json_object"}, ...)`.
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
- Validates with a `pydantic` model (`AnalysisResult`); on `ValidationError` returns `None` and logs `analysis_error`.

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

## 3.9 Pipeline Orchestration

Runs on `/trigger` (from Cloud Scheduler or manual call):

```python
def run_pipeline(bucket, groq_key: str, github_token: str | None) -> dict:
    repos = load_repos()          # reads repos.json bundled with the function
    status = {}
    for repo in repos:
        owner, name = repo.split("/")
        try:
            cursor = get_cursor(bucket, owner, name)
            if cursor is None:
                releases = backfill_releases(owner, name, github_token)
            else:
                releases = get_new_releases(owner, name, cursor, github_token)
            new_count = 0
            latest_published_at = cursor
            for release in releases:          # ascending published_at
                if release_exists(bucket, owner, name, release["tag_name"]):
                    continue
                analysis = analyse_release(release, groq_key)
                record = build_record(release, analysis)
                put_release(bucket, record)
                new_count += 1
                latest_published_at = release["published_at"]
            if latest_published_at and latest_published_at != cursor:
                set_cursor(bucket, owner, name, latest_published_at)
            status[repo] = {"ok": True, "new": new_count}
        except Exception as e:
            logging.error("repo %s failed: %s", repo, e)
            status[repo] = {"ok": False, "error": str(e)}
    run_status = {"ran_at": utcnow_iso(), "repos": status}
    set_run_status(bucket, run_status)
    return run_status
```

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
GCS_BUCKET       = "git-release-496817-releases"
GCP_REGION       = "us-central1"

MAX_RELEASES_PER_RUN   = 50
BACKFILL_NON_SEMVER    = 20    # fallback count for repos without semver tags
DIGEST_DEFAULT_LIMIT   = 20
DIGEST_MAX_LIMIT       = 100
LLM_MAX_TOKENS         = 1024
GROQ_MODEL             = "llama-3.3-70b-versatile"
GITHUB_API_BASE        = "https://api.github.com"
GROQ_TIMEOUT_S         = 10
GITHUB_TIMEOUT_S       = 10
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

Secrets accessed at function startup (cached in module scope for warm instances):
- `GROQ_API_KEY` — Groq account API key
- `GITHUB_TOKEN` — GitHub PAT, `public_repo` read-only (optional, raises rate limit 60→5000 req/hr)
- `TRIGGER_SECRET` — random string validated on `/trigger` requests
- `R2_ACCESS_KEY_ID` — R2 API token ID (create in Cloudflare dashboard → R2 → Manage API Tokens)
- `R2_SECRET_ACCESS_KEY` — R2 API token secret
- `R2_ACCOUNT_ID` — Cloudflare account ID (found in dashboard URL)

The Cloud Function's service account needs `roles/secretmanager.secretAccessor`.

---

## 3.13 Deployment

```bash
# 1. Create R2 bucket in Cloudflare dashboard (or via Wrangler CLI if available)
# Dashboard → R2 → Create bucket → name: git-release-releases
# Then create R2 API token: Dashboard → R2 → Manage API Tokens → Create token (Object Read & Write)

# 2. Store secrets in GCP Secret Manager
echo -n "gsk_..." | gcloud secrets create GROQ_API_KEY --data-file=- --project=git-release-496817
echo -n "ghp_..." | gcloud secrets create GITHUB_TOKEN --data-file=- --project=git-release-496817
echo -n "$(openssl rand -hex 32)" | gcloud secrets create TRIGGER_SECRET --data-file=- --project=git-release-496817
echo -n "<r2-access-key-id>" | gcloud secrets create R2_ACCESS_KEY_ID --data-file=- --project=git-release-496817
echo -n "<r2-secret-access-key>" | gcloud secrets create R2_SECRET_ACCESS_KEY --data-file=- --project=git-release-496817
echo -n "<cloudflare-account-id>" | gcloud secrets create R2_ACCOUNT_ID --data-file=- --project=git-release-496817

# 3. Deploy Cloud Function (gen2)
gcloud functions deploy git-release \
  --gen2 \
  --runtime=python312 \
  --region=us-central1 \
  --source=. \
  --entry-point=main \
  --trigger-http \
  --allow-unauthenticated \
  --service-account=git-release-sa@git-release-496817.iam.gserviceaccount.com \
  --project=git-release-496817

# 4. Create Cloud Scheduler job
gcloud scheduler jobs create http git-release-daily \
  --schedule="0 6 * * *" \
  --uri="https://us-central1-git-release-496817.cloudfunctions.net/git-release/trigger" \
  --http-method=POST \
  --headers="X-Trigger-Secret=$(gcloud secrets versions access latest --secret=TRIGGER_SECRET --project=git-release-496817)" \
  --time-zone="UTC" \
  --project=git-release-496817

# 5. Deploy frontend to Cloudflare Pages
# Set the Cloud Function URL in public/index.html meta tag, then:
npx wrangler pages deploy public/ --project-name=git-release
```

---

## 3.14 Testing Strategy

- **Unit tests** (`pytest` + `pytest-mock`):
  - `test_semver.py`: tag parsing edge cases
  - `test_fetcher.py`: mock `requests.get`, assert URL construction, pagination, backfill filter
  - `test_analyser.py`: mock Groq SDK, assert pydantic validation + fallback
  - `test_store.py`: mock `google-cloud-storage` client, assert idempotency, cursor read/write
  - `test_digest.py`: assert sort order, limit, body stripping
- **Local integration**: `functions-framework --target=main --port=8080` with `.env.local` for secrets (never committed)
- **No E2E browser automation in v1** — manual visual check of bento page
