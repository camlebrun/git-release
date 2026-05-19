# Constitution — GitHub Release Digest

> Immutable principles for all AI operations on this project.
> Any change here requires explicit team sign-off.

---

## 0.1 Project Identity

**Name:** GitHub Release Digest  
**Purpose:** Automatically fetch, analyse, and surface GitHub release notes as a daily structured digest — with LLM-generated summaries, CVE flags, and a bento-style web UI.

---

## 0.2 Tech Stack (locked)

| Layer | Choice | Rationale |
|---|---|---|
| Runtime | **Python 3.12** | full pip ecosystem, groq SDK, functions-framework |
| Cloud function | **GCP Cloud Functions gen2** (project `git-release-496817`) | managed, scales to zero, HTTP + Cloud Scheduler cron |
| Blob storage | **Cloudflare R2** via S3-compatible API | 10 GB free, no egress fees — better than GCS 5 GB free |
| Metadata | **R2** (`meta/` prefix in same bucket) | cursors + run status as JSON blobs — no separate DB |
| Secrets | **GCP Secret Manager** | GROQ_API_KEY, GITHUB_TOKEN, TRIGGER_SECRET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY |
| R2 client | **boto3** with custom endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` | standard S3-compatible API |
| LLM | **Groq API** (`llama-3.3-70b-versatile`) | fast inference, generous free tier, `pip install groq` |
| GitHub data | GitHub REST API v3 (`/repos/:owner/:repo/releases`) | stable, no auth needed for public repos |
| Frontend | Vanilla JS + CSS Grid (bento layout) | zero build toolchain, static HTML |
| Hosting | **Cloudflare Pages** | free CDN, easy deploy, calls GCP Cloud Function via CORS |

---

## 0.3 Coding Standards

- **Language:** Python 3.12 for Cloud Function; plain JS for frontend.
- **Formatting:** `black` (88-char line length) + `isort`.
- **Linting:** `ruff`.
- **Type hints:** all function signatures annotated; `mypy --strict` must pass.
- **No framework bloat:** no React, no Vue, no bundler for the frontend.
- **Secrets** go in GCP Secret Manager — never in source, never in `.env.local` committed to git.
- **All LLM prompts** live in `src/prompts/` as named Python string templates — never inline.
- **Error handling:** every external call (GitHub API, Groq API, R2/boto3) must have a try/except with structured logging.
- **No magic numbers:** durations, limits, and thresholds go in `src/config.py`.

---

## 0.4 Data Rules

- One JSON file per release, stored in GCS as `releases/{owner}/{repo}/{tag}.json`.
- A cursor file per repo at `meta/cursor/{owner}/{repo}.json` stores `published_at` of the last fetched release — the incremental watermark.
- Run status stored at `meta/run_status.json`.
- Raw GitHub release payload is stored untouched alongside the LLM analysis in the same JSON blob.
- Releases are **append-only**; existing GCS objects are never overwritten unless `--force` flag is passed.

---

## 0.5 Security Rules

- GitHub API token (if used) scoped to `public_repo` read-only.
- Groq API key never logged, never surfaced in responses.
- Frontend receives only pre-computed digest data; no secrets are exposed to the browser.
- CVE references extracted by the LLM are informational only — no automated remediation.
- Rate limits: respect GitHub's 60 req/hr unauthenticated / 5 000 req/hr authenticated; back off on 429.

---

## 0.6 Operational Rules

- Scheduled function runs **once per day at 06:00 UTC**.
- Incremental fetch: only releases with `published_at > cursor` are fetched and analysed.
- Maximum **50 releases per repo per run** to stay within Groq and Worker CPU limits.
- LLM analysis cost per release: 1 Groq call, capped at 1 024 output tokens.
- Failures are logged to Cloudflare logpush; the run does not crash the whole batch on a single-repo error.

---

## 0.7 Definition of Done

A feature is done when:
1. `mypy --strict src/` passes with no errors.
2. Unit tests pass (`pytest`).
3. `functions-framework --target=main --port=8080` runs locally without errors.
4. The bento page renders correctly in Chrome, Firefox, and Safari.
5. A new release in a tracked repo appears on the digest within 24 hours.
