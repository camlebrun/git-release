# StackRadar

> Daily release intelligence for data & platform engineers.

StackRadar fetches GitHub release notes across your tracked repos, analyses them with a Mistral LLM, flags CVEs, and renders a bento-style digest — refreshed every morning at 06:00 UTC.

![CI](https://github.com/camlebrun/git-release/actions/workflows/ci.yml/badge.svg)

---

## What it does

- **Fetches** new releases incrementally (cursor-based, no duplicate processing)
- **Analyses** each release with `mistral-small-latest` via Mistral: summary, key changes, severity, CVE IDs, tags
- **Enriches** CVE IDs with CVSS scores from NIST NVD
- **Stores** one JSON blob per release in Cloudflare R2
- **Serves** a `/digest` API consumed by a static bento frontend on Cloudflare Pages

---

## Architecture

```
Cloud Scheduler (06:00 UTC)
    │  POST /trigger
    ▼
GCP Cloud Run Job (Python 3.12)
    ├── GitHub API     →  fetch new releases (incremental; 2-major backfill on first run)
    ├── Mistral LLM    →  summary, key changes, CVE IDs, severity, tags
    └── Cloudflare R2  →  store one JSON per release
         releases/{owner}/{repo}/{tag}.json
         meta/cursor/{owner}/{repo}.json

GCP Cloud Function (Python 3.12)
    └── /email-digest  →  send daily HTML digest email

Cloudflare Pages (static)
    └── fetch /digest  →  bento card grid + CVE table
```

---

## Tracked repos

Configured in [`repos.json`](repos.json):

```json
[
  "cli/cli",
  "vitejs/vite",
  "astral-sh/uv",
  "dbt-labs/dbt-core"
]
```

To add a repo: append `"owner/repo"` and deploy. The next run auto-backfills the last 2 major versions.

---

## Local development

```bash
# Python setup
pip install -r requirements-dev.txt

# Copy and fill in secrets
cp .env.local.example .env.local

# Run tests
make test

# Type check
make typecheck

# Start local function server
make dev
# → http://localhost:8080/digest
# → http://localhost:8080/health
# → curl -X POST -H "X-Trigger-Secret: <secret>" http://localhost:8080/trigger
```

---

## Environment variables (`.env.local`)

| Variable | Required | Description |
|---|---|---|
| `MISTRAL_API_KEY` | Yes | [Mistral](https://console.mistral.ai) API key |
| `GITHUB_TOKEN` | No | GitHub PAT — raises rate limit from 60 to 5 000 req/hr |
| `TRIGGER_SECRET` | Yes | Random string — protects the `/trigger` endpoint |
| `R2_ACCESS_KEY_ID` | Yes | Cloudflare R2 API token ID |
| `R2_SECRET_ACCESS_KEY` | Yes | Cloudflare R2 API token secret |
| `R2_ACCOUNT_ID` | Yes | Cloudflare account ID |

In production, these are stored in **GCP Secret Manager** and never in env files.

> `src/secrets.py` falls back to env vars automatically when Secret Manager is unavailable (local dev).

---

## API endpoints

| Endpoint | Auth | Description |
|---|---|---|
| `GET /digest?limit=N` | none | Latest N releases (default 20, max 100) |
| `GET /health` | none | Last run timestamp + per-repo status |
| `POST /trigger` | `X-Trigger-Secret` header | Run the pipeline immediately |

---

## Frontend

- **Digest tab** — bento grid of release cards: severity badge, LLM summary, key changes, CVE chips
- **CVE tab** — aggregated CVE table across all releases, sorted by severity + CVSS score, linked to NVD
- Live search filters both tabs simultaneously
- Dark mode, responsive (mobile → desktop)

---

## Project docs

| Document | Description |
|---|---|
| [`docs/sdd.md`](docs/sdd.md) | Specification-Driven Development methodology used in this project |
| [`docs/constitution.md`](docs/constitution.md) | Immutable architectural principles |
| [`docs/specification.md`](docs/specification.md) | Functional & non-functional requirements |
| [`docs/plan.md`](docs/plan.md) | Technical blueprint and API contracts |

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).
