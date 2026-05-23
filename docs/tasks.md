# Tasks — GitHub Release Digest

> Atomic, testable work chunks. Each task targets a single PR, ~1–4 h.
> Stack: Python 3.12 · GCP Cloud Functions gen2 · GCS · Cloudflare Pages
> Status: `[ ]` todo · `[~]` in progress · `[x]` done

---

## Phase 1 — Project Scaffold

### T-01 — Repo init & toolchain
**Est.:** 30 min  
**Depends on:** nothing

- [ ] `git init`, create `.gitignore` (`__pycache__/`, `*.pyc`, `.env.local`, `.venv/`)
- [ ] `pyproject.toml`: configure `black`, `ruff`, `mypy` (strict), `pytest`
- [ ] `requirements.txt`: `functions-framework`, `boto3`, `google-cloud-secret-manager`, `mistralai`, `requests`, `pydantic`
- [ ] `requirements-dev.txt`: `pytest`, `pytest-mock`, `black`, `ruff`, `mypy`
- [ ] `src/__init__.py`, `tests/__init__.py`
- [ ] `Makefile` targets: `dev`, `test`, `lint`, `typecheck`, `deploy`

**Acceptance:** `python -m pytest` runs (0 tests, no errors); `functions-framework --target=main --port=8080` starts on an empty `src/main.py`.

---

### T-02 — Config, types & repo list
**Est.:** 20 min  
**Depends on:** T-01

- [ ] Create `src/config.py` with all constants from plan §3.11
- [ ] Create `repos.json` with 2–3 example repos (e.g. `"cli/cli"`, `"vitejs/vite"`)
- [ ] Create `src/types.py`: `TypedDict` definitions for `GitHubRelease`, `ReleaseRecord`, `Analysis`, `CursorRecord`, `RunStatus`

**Acceptance:** `mypy --strict src/config.py src/types.py` passes.

---

## Phase 2 — Core Python Logic

### T-03 — Secret Manager helper
**Est.:** 30 min  
**Depends on:** T-02

- [ ] Implement `src/secrets.py` per plan §3.12
- [ ] Module-level cache so secrets are fetched once per warm instance
- [ ] Write `tests/test_secrets.py` (mock `SecretManagerServiceClient`):
  - Happy path: returns decoded string
  - Caches on second call (SDK not called twice)

**Acceptance:** `pytest tests/test_secrets.py` passes (2+ tests green).

---

### T-04 — Semver parser
**Est.:** 45 min  
**Depends on:** T-02

- [ ] Implement `src/semver.py`: `parse_semver(tag: str) -> SemVer`
  - Strip leading `v`, split on `-` to discard pre-release suffix, split on `.`
  - Return `SemVer(valid=False)` for anything not matching `\d+\.\d+\.\d+`
- [ ] Write `tests/test_semver.py`:
  - `"v12.3.1"` → `SemVer(major=12, minor=3, patch=1, valid=True)`
  - `"v12.3.1-rc2"` → `SemVer(major=12, minor=3, patch=1, valid=True)`
  - `"20240501"` → `SemVer(valid=False)`
  - `"1.0.0"` (no v prefix) → `SemVer(major=1, ..., valid=True)`
  - `"v2.0.0-beta.1"` → `SemVer(major=2, ..., valid=True)`

**Acceptance:** `pytest tests/test_semver.py` passes (5+ tests green).

---

### T-05 — GitHub fetcher
**Est.:** 1.5 h  
**Depends on:** T-04

- [ ] Implement `src/fetcher.py` per plan §3.4:
  - `get_new_releases(owner, repo, since, token=None)`: paginate, stop when `published_at <= since`, cap at `MAX_RELEASES_PER_RUN`
  - `backfill_releases(owner, repo, token=None)`: paginate ALL, semver-filter to majors M and M-1, fallback `BACKFILL_NON_SEMVER` for non-semver repos
  - `GitHubFetchError(status, message)` custom exception
- [ ] Write `tests/test_fetcher.py` (mock `requests.get`):
  - Correct URL and headers for owner/repo
  - `since` filter stops pagination early
  - Backfill: v12.x and v11.x kept, v10.x dropped
  - Backfill fallback: all non-semver tags → returns 20 most recent
  - Non-2xx → raises `GitHubFetchError`

**Acceptance:** `pytest tests/test_fetcher.py` passes (5+ tests green).

---

### T-06 — Mistral analyser
**Est.:** 1.5 h  
**Depends on:** T-02

- [ ] Write prompt template in `src/prompts/release_analysis.py` (plain string, f-string ready):
  - Includes repo, tag, release name, body truncated to 4 000 chars
  - Instructs strict JSON output matching spec §1.6 schema
- [ ] Implement `src/analyser.py` per plan §3.6:
  - `analyse_release(release: dict, api_key: str) -> dict | None`
  - Pydantic `AnalysisResult` model for validation
  - On `ValidationError` or JSON decode error: log + return `None`
- [ ] Write `tests/test_analyser.py` (mock `mistralai.client.Mistral`):
  - Happy path: valid JSON parsed into `AnalysisResult`
  - Invalid JSON from model: returns `None`
  - Body with `"CVE-2026-12345"` → `cve_references` contains that string

**Acceptance:** `pytest tests/test_analyser.py` passes (3+ tests green).

---

### T-07 — R2 store (boto3)
**Est.:** 1.5 h  
**Depends on:** T-02

- [ ] Implement `src/store.py` per plan §3.7:
  - `get_s3_client(access_key, secret_key, account_id)` — boto3 with R2 endpoint
  - All helper functions: `get_release`, `put_release`, `release_exists`, `list_release_keys`
  - Cursor helpers: `get_cursor`, `set_cursor`
  - Run status helpers: `get_run_status`, `set_run_status`
- [ ] Write `tests/test_store.py` (mock `boto3.client`):
  - `put_release` is idempotent (`head_object` check prevents overwrite)
  - `get_cursor` returns `None` when key missing (ClientError NoSuchKey)
  - `set_cursor` writes correct JSON to correct R2 key
  - `list_release_keys` uses correct prefix and paginates

**Acceptance:** `pytest tests/test_store.py` passes (4+ tests green).

---

### T-08 — Digest aggregation
**Est.:** 45 min  
**Depends on:** T-07

- [ ] Implement `src/digest.py` per plan §3.8
- [ ] Write `tests/test_digest.py` (mock GCS blobs):
  - Returns records sorted by `published_at` desc
  - Respects `limit` param
  - `body` field is stripped from output

**Acceptance:** `pytest tests/test_digest.py` passes (3+ tests green).

---

### T-09 — Pipeline orchestration
**Est.:** 1 h  
**Depends on:** T-05, T-06, T-07

- [ ] Implement `run_pipeline(bucket, mistral_key, github_token)` in `src/main.py` per plan §3.9
- [ ] Load `repos.json` from function directory at startup
- [ ] Branch per repo: no cursor → `backfill_releases`, cursor exists → `get_new_releases`
- [ ] Error isolation: per-repo try/except, logs error, continues
- [ ] `set_run_status` after all repos processed

**Acceptance:** local run with mocked GCS + GitHub (real Mistral skipped) completes without raising; `run_status` dict returned.

---

## Phase 3 — HTTP Routes

### T-10 — HTTP router (`src/main.py`)
**Est.:** 45 min  
**Depends on:** T-08, T-09

- [ ] Implement `main(request)` with `functions_framework.http` decorator
- [ ] `GET /digest`: parse `limit` query param (default 20, max 100), return JSON + CORS headers
- [ ] `GET /health`: return run status JSON from GCS
- [ ] `GET|POST /trigger`: validate `X-Trigger-Secret` header → `run_pipeline()` → return JSON summary
- [ ] `OPTIONS *`: return CORS preflight 204
- [ ] 404 for unknown paths

**Acceptance:**
```bash
functions-framework --target=main --port=8080
curl localhost:8080/digest                           # → JSON array
curl localhost:8080/trigger                          # → 401
curl -H "X-Trigger-Secret: dev" localhost:8080/trigger  # → 200 JSON
```

---

## Phase 4 — Frontend

### T-11 — Bento page HTML/CSS
**Est.:** 1.5 h  
**Depends on:** T-10

- [ ] `public/index.html`:
  - `<meta name="api-url" content="https://...cloudfunctions.net/git-release">` (set at deploy)
  - `<input id="search">`, `<div id="grid">`, loading spinner
- [ ] `public/style.css`:
  - CSS custom properties for severity colours (`--sev-none`, `--sev-low`, ..., `--sev-critical`)
  - Grid bento: `grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))`
  - Card: border-radius, shadow, hover lift (`translateY(-2px)`)
  - Severity badge pill
  - Responsive: 1-col ≤ 480px, 2-col ≤ 900px, 3-col above
  - Dark mode: `@media (prefers-color-scheme: dark)`

**Acceptance:** page renders in browser with hardcoded placeholder card data; responsive at 375px, 768px, 1280px.

---

### T-12 — Frontend JS
**Est.:** 1.5 h  
**Depends on:** T-11

- [ ] `public/app.js`:
  - Read `CLOUD_FUNCTION_URL` from `<meta name="api-url">` on load
  - `fetch(CLOUD_FUNCTION_URL + '/digest?limit=50')` → render cards
  - `renderCard(record)` → HTML string, uses `data-repo` and `data-tags` attributes
  - CVE chips: red pill, hidden when `cve_references` is empty
  - Tags: grey pills
  - Search input: live filter (case-insensitive, repo name + tags)
  - Empty state: "No releases found"
  - Error state: top banner if fetch fails

**Acceptance:**
- Page loaded against `functions-framework` dev server shows real release cards
- Filter by repo name hides non-matching cards
- A release with a CVE shows the red CVE chip

---

## Phase 5 — Integration & Hardening

### T-13 — End-to-end smoke test with real Mistral + GCS
**Est.:** 30 min  
**Depends on:** T-12

- [ ] Create `.env.local` (gitignored) with real secrets for local dev
- [ ] Run `functions-framework --target=main --port=8080`, hit `/trigger`:
  - GCS objects created under `releases/`
  - First-run backfill scoped to 2 major versions (inspect GCS object names)
  - `analysis` fields populated (not null)
  - At least one CVE detected on a known security release
- [ ] Fix any prompt / parsing issues found

**Acceptance:** ≥ 3 GCS objects with non-null `analysis`; backfill respects 2-major constraint.

---

### T-14 — Rate limit & timeout hardening
**Est.:** 45 min  
**Depends on:** T-13

- [ ] Add retry with exponential backoff (max 3 attempts) on GitHub 429 / 5xx in `src/fetcher.py`
- [ ] Add `timeout=MISTRAL_TIMEOUT_S` to Mistral SDK call; catch timeout error → return `None`
- [ ] Add `timeout=GITHUB_TIMEOUT_S` to `requests.get` calls
- [ ] `tests/test_fetcher.py`: mock 429 → assert retry → success
- [ ] `tests/test_analyser.py`: mock timeout → assert returns `None`

**Acceptance:** retry + timeout test cases pass; function does not hang indefinitely on slow upstream.

---

### T-15 — GCP deployment
**Est.:** 45 min  
**Depends on:** T-14

- [ ] Create GCS bucket: `gcloud storage buckets create gs://git-release-496817-releases ...`
- [ ] Create service account `git-release-sa`, grant `storage.objectAdmin` + `secretmanager.secretAccessor`
- [ ] Create secrets in Secret Manager: `MISTRAL_API_KEY`, `GITHUB_TOKEN`, `TRIGGER_SECRET`
- [ ] Deploy Cloud Function (commands from plan §3.13)
- [ ] Create Cloud Scheduler job (commands from plan §3.13)
- [ ] Manual trigger via `curl -H "X-Trigger-Secret: ..." https://...cloudfunctions.net/git-release/trigger`
- [ ] Deploy Cloudflare Pages: update `<meta name="api-url">`, `npx wrangler pages deploy public/ --project-name=git-release`

**Acceptance:** `/digest` returns real data from production GCS; Pages bento page loads and renders cards.

---

## Phase 6 — Polish

### T-16 — README
**Est.:** 20 min  
**Depends on:** T-15

- [ ] `README.md`: purpose, architecture diagram link, setup steps (clone → GCP setup → deploy), `repos.json` format, secret names, local dev instructions (`functions-framework`)

---

### T-17 — Observability
**Est.:** 30 min  
**Depends on:** T-15

- [ ] Replace `print()` with `logging.getLogger(__name__)` calls throughout (GCP Cloud Logging picks these up automatically)
- [ ] Structured log fields: `repo`, `tag`, `new_releases`, `mistral_duration_ms`, `error`
- [ ] `/health` response includes `last_run_at`, `total_blobs` (from GCS list count), per-repo `{ last_fetched, new_count, error? }`
- [ ] View logs: `gcloud functions logs read git-release --region=us-central1 --limit=50`

---

## Dependency Graph

```
T-01 → T-02 → T-03
         └──── T-04 → T-05 ──┐
         └──── T-06 ──────────┤
         └──── T-07 → T-08 ──┴── T-09 → T-10 → T-12
                                              │
                                         T-11 ┘
                                              │
                                   T-13 → T-14 → T-15 → T-16
                                                        └── T-17
```

---

## Effort Summary

| Phase | Tasks | Est. Total |
|---|---|---|
| 1 — Scaffold | T-01, T-02 | ~50 min |
| 2 — Core logic | T-03 – T-09 | ~7.5 h |
| 3 — HTTP | T-10 | ~45 min |
| 4 — Frontend | T-11, T-12 | ~3 h |
| 5 — Integration | T-13 – T-15 | ~2 h |
| 6 — Polish | T-16, T-17 | ~50 min |
| **Total** | | **~15 h** |
