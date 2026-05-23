# Constitution — StackRadar

> Immutable principles for all AI operations on this project.
> Any change here requires explicit team sign-off.

---

## 0.1 Project Identity

**Name:** StackRadar
**Purpose:** Automatically fetch, analyse, and surface GitHub release notes as a daily structured digest — with LLM-generated summaries, CVE flags, security advisories, and a bento-style web UI.

---

## 0.2 Tech Stack (locked)

| Layer | Choice | Rationale |
|---|---|---|
| Runtime | **Python 3.12** | full pip ecosystem, mistralai SDK, pydantic |
| Pipeline compute | **GCP Cloud Run Job** (project `git-release-496817`) | managed, scales to zero, triggered by Cloud Scheduler |
| Email compute | **GCP Cloud Function gen2** | lightweight HTTP trigger, separate deployment unit |
| Blob storage | **Cloudflare R2** via S3-compatible API (boto3) | 10 GB free, no egress fees |
| Metadata | **R2** (`meta/` prefix in same bucket) | cursors + run status as JSON blobs — no separate DB |
| Secrets | **GCP Secret Manager** | `MISTRAL_API_KEY`, `GITHUB_TOKEN`, `EMAIL_FUNCTION_URL`, R2 credentials |
| R2 client | **boto3** with custom endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` | standard S3-compatible API |
| LLM | **Mistral API** (`mistral-small-latest`) | JSON mode, fast inference, no rate limit issues at this scale |
| GitHub data | GitHub REST API v3 (`/repos/:owner/:repo/releases`) | stable, no auth needed for public repos |
| Frontend | Vanilla JS + CSS Grid (bento layout) | zero build toolchain, static HTML served from Cloudflare Pages |
| Hosting | **Cloudflare Pages** | free CDN, direct R2 read via public bucket URL |

---

## 0.3 Coding Standards

- **Language:** Python 3.12 for backend; plain JS for frontend.
- **Formatting:** `black` (88-char line length) + `isort`.
- **Linting:** `ruff`.
- **Type hints:** all function signatures annotated; `mypy --strict` must pass.
- **No framework bloat:** no React, no Vue, no bundler for the frontend.
- **Secrets** go in GCP Secret Manager — never in source, never in `.env.local` committed to git.
- **All LLM prompts** live in `src/prompts/` as named Python string templates — never inline.
- **Error handling:** every external call (GitHub API, Mistral API, R2/boto3) must have a try/except with structured logging.
- **No magic numbers:** durations, limits, and thresholds go in `src/config.py`.

---

## 0.4 Data Rules

- One JSON file per release, stored in R2 as `releases/{owner}/{repo}/{tag}.json`.
- A cursor file per repo at `meta/cursor/{owner}/{repo}.json` stores `published_at` of the last fetched release — the incremental watermark.
- Run status stored at `meta/run_status.json`.
- Raw GitHub release payload is stored untouched alongside the LLM analysis in the same JSON blob.
- Releases are **append-only**; existing R2 objects are never overwritten.

---

## 0.5 Security Rules

- GitHub API token (if used) scoped to `public_repo` read-only.
- Mistral API key never logged, never surfaced in responses.
- Frontend reads only from a public R2 bucket URL; no secrets are exposed to the browser.
- CVE references extracted by the LLM are informational only — no automated remediation.
- Rate limits: respect GitHub's 60 req/hr unauthenticated / 5 000 req/hr authenticated; back off on 429.

---

## 0.6 Operational Rules

- Cloud Run Job runs **once per day at 06:00 UTC** via Cloud Scheduler.
- Incremental fetch: only releases with `published_at > cursor` are fetched and analysed.
- Maximum **50 releases per repo per run** to stay within Mistral rate limits.
- LLM analysis cost per release: 1 Mistral call, capped at 4 096 output tokens.
- Failures are logged to GCP Cloud Logging; a single repo error does not abort the whole batch.

---

## 0.7 Definition of Done

A feature is done when:
1. `mypy --strict src/` passes with no errors.
2. Unit tests pass (`pytest`) with coverage ≥ 65%.
3. `python -m src.main` runs locally without errors (with `.env.local`).
4. The bento page renders correctly in Chrome, Firefox, and Safari.
5. A new release in a tracked repo appears on the digest within 24 hours.
