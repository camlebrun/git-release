# git-release

Daily GitHub release digest — fetches releases, analyses them with Groq LLM, enriches CVEs via NIST NVD, and renders a bento-style web page.

## Architecture

```
Cloud Scheduler (06:00 UTC)
    │  POST /trigger
    ▼
GCP Cloud Function (Python 3.12)
    ├── GitHub API  →  fetch new releases (incremental, 2-major backfill)
    ├── Groq LLM   →  summary, key changes, CVE IDs, severity, tags
    ├── NIST NVD   →  enrich CVE IDs with CVSS score + description
    └── Cloudflare R2  →  store one JSON per release
         releases/{owner}/{repo}/{tag}.json
         meta/cursor/{owner}/{repo}.json

Cloudflare Pages (static)
    └── fetch /digest  →  bento card grid + CVE table
```

## Tracked repos

Configured in `repos.json`:

```json
[
  "cli/cli",
  "vitejs/vite",
  "astral-sh/uv",
  "dbt-labs/dbt-core",
  "starburstdata/dbt-trino",
  "dagster-io/dagster"
]
```

To add a repo: add `"owner/repo"` to `repos.json` and deploy. The next run auto-backfills the last 2 major versions.

## Local development

```bash
# Install deps
pip install -r requirements-dev.txt

# Run tests
make test

# Type check
make typecheck

# Local function server (needs .env.local with secrets)
cp .env.local.example .env.local   # fill in your keys
make dev
# → http://localhost:8080/digest
# → http://localhost:8080/health
# → curl -X POST -H "X-Trigger-Secret: <secret>" http://localhost:8080/trigger
```

### `.env.local` (never commit)

```
GROQ_API_KEY=gsk_...
GITHUB_TOKEN=ghp_...          # optional
TRIGGER_SECRET=your-secret
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_ACCOUNT_ID=...             # Cloudflare account ID
```

> For local dev, `src/secrets.py` falls back to env vars when Secret Manager is unavailable.

## Deploy

```bash
chmod +x deploy.sh
./deploy.sh
```

The script:
1. Prompts for secrets → stores in GCP Secret Manager
2. Creates service account with `secretmanager.secretAccessor` + `storage.objectAdmin`
3. Deploys Cloud Function gen2 (Python 3.12)
4. Creates Cloud Scheduler job (`0 6 * * * UTC`)
5. Injects function URL into `public/index.html` and deploys to Cloudflare Pages

## Secrets (GCP Secret Manager)

| Secret name | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Groq API key |
| `GITHUB_TOKEN` | No | GitHub PAT — raises rate limit from 60 to 5000 req/hr |
| `TRIGGER_SECRET` | Yes | Random string — protects `/trigger` endpoint |
| `R2_ACCESS_KEY_ID` | Yes | Cloudflare R2 API token ID |
| `R2_SECRET_ACCESS_KEY` | Yes | Cloudflare R2 API token secret |
| `R2_ACCOUNT_ID` | Yes | Cloudflare account ID |

## API endpoints

| Endpoint | Auth | Description |
|---|---|---|
| `GET /digest?limit=N` | none | Latest N releases (default 20, max 100) |
| `GET /health` | none | Last run status |
| `POST /trigger` | `X-Trigger-Secret` header | Run pipeline immediately |

## Frontend

- **Digest tab**: bento grid of release cards — severity badge, summary, key changes, CVE chips (→ NVD)
- **CVE tab**: table of all CVEs across releases, sorted by severity then CVSS score, linked to NVD
- Live search filters both tabs simultaneously
- Dark mode, responsive (mobile → desktop)
