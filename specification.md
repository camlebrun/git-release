# Specification — GitHub Release Digest

> What the system does and why. No implementation details.
> Tests and acceptance criteria are defined here first.

---

## 1.1 Problem Statement

Developers following multiple open-source projects lose track of releases. Reading raw GitHub release notes is time-consuming and inconsistent. There is no single place that:
- Aggregates releases across repos
- Flags security issues (CVEs)
- Provides a plain-language summary
- Updates automatically every day

---

## 1.2 Users & Goals

| User | Goal |
|---|---|
| Developer / tech lead | Scan a digest every morning to stay current without reading every changelog |
| Security engineer | Spot CVE mentions quickly across all tracked repos |
| Non-technical stakeholder | Understand what changed in human language |

---

## 1.3 Scope

**In scope:**
- Fetching releases from a configurable list of public GitHub repos
- Storing raw release data as JSON (one record per release)
- Analysing each release with a Groq LLM: summary, key changes, CVE detection, severity tag
- A daily scheduled cloud function that only processes new releases (incremental)
- A static bento-style web page that displays the digest

**Out of scope (v1):**
- Private GitHub repos
- Non-GitHub sources (GitLab, npm, etc.)
- Email / Slack notifications
- User accounts or saved preferences
- Real-time updates (WebSocket / SSE)

---

## 1.4 Functional Requirements

### FR-01 — Repo configuration
- The operator configures a list of GitHub repos to track in `repos.json` (array of `"owner/repo"` strings).
- At least one repo must be configured for the function to run.

### FR-02 — Release fetch
- The function queries `GET /repos/:owner/:repo/releases` for each configured repo.
- Only releases with `published_at` strictly after the stored cursor are fetched.
- Releases are fetched in ascending `published_at` order so the cursor advances correctly.
- **First-run backfill (no cursor):** all releases are paginated from GitHub, semver-parsed, and filtered to the last 2 major versions (highest major `M` and `M-1`), including all their minor and patch releases. Non-semver tags fall back to the most recent 20 releases by date.
- Adding a new entry to `repos.json` automatically triggers the backfill on the next run (no code change needed).

### FR-03 — Release storage (raw)
- Each release is stored in **R2** as object `{owner}/{repo}/{tag}.json`.
- Cursors and run status are stored in **KV** (small, hot metadata only).
- The R2 object value is a JSON blob containing the full GitHub release payload plus metadata fields (see §1.6).
- If the R2 object already exists, the record is skipped (idempotent).

### FR-04 — LLM analysis
- For each newly stored release, one Groq API call is made.
- The prompt requests: **summary** (2–4 sentences), **key_changes** (bullet list ≤ 8 items), **cve_references** (array of CVE IDs found in the body), **severity** (`none | low | medium | high | critical`), **tags** (array of inferred labels: `breaking`, `security`, `performance`, `bug-fix`, `feature`, `deprecation`).
- The LLM response is parsed as JSON and merged into the stored release record.
- If LLM parsing fails, the release is stored with `analysis: null` and an `analysis_error` field.

### FR-05 — Cursor update
- After all releases for a repo are processed, the cursor key `cursor:{owner}/{repo}` is updated to the `published_at` of the latest release successfully stored.

### FR-06 — Scheduled trigger
- The cloud function runs automatically once per day at 06:00 UTC via a cron trigger.
- It can also be triggered manually via a `GET /trigger` HTTP endpoint (protected by a shared secret header `X-Trigger-Secret`).

### FR-07 — Digest API
- A `GET /digest` endpoint returns a JSON array of the most recent **N** analysed releases across all tracked repos (default N=20, max N=100, configurable via `?limit=`).
- Each item in the array is the full stored record (raw + analysis).
- Results are sorted by `published_at` descending.

### FR-08 — Frontend bento page
- A static HTML/JS/CSS page fetches `/digest` on load and renders cards in a CSS Grid bento layout.
- Each card shows: repo name, version tag, published date, severity badge, summary, key changes list, CVE references (if any), tags.
- Severity badge colour coding: `none`=grey, `low`=blue, `medium`=yellow, `high`=orange, `critical`=red.
- The page has a search/filter input that filters visible cards client-side by repo name or tag.
- Cards are responsive: full-width on mobile, 2-col on tablet, 3-col on desktop.

### FR-09 — Error resilience
- A single repo failure (GitHub API error, Groq error) must not abort the entire batch.
- Errors are logged with repo name and error message.
- A `GET /health` endpoint returns `200 OK` with last run timestamp and per-repo status.

---

## 1.5 Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-01 | Scheduled run completes in under 30 s for ≤ 10 repos with ≤ 5 new releases each |
| NFR-02 | Frontend page loads in under 2 s on a 4G connection |
| NFR-03 | No secrets in any committed file |
| NFR-04 | Worker must not exceed Cloudflare's 10 ms CPU time limit per request (subrequest I/O excluded) |
| NFR-05 | All stored JSON is valid UTF-8 and parseable |

---

## 1.6 Data Shape

### Stored release record (`release:{owner}/{repo}:{tag}`)
```json
{
  "id": 12345678,
  "repo": "owner/repo",
  "tag": "v1.2.3",
  "name": "Release 1.2.3",
  "body": "...raw markdown from GitHub...",
  "published_at": "2026-05-19T06:00:00Z",
  "html_url": "https://github.com/owner/repo/releases/tag/v1.2.3",
  "author": "octocat",
  "prerelease": false,
  "draft": false,
  "fetched_at": "2026-05-19T06:01:00Z",
  "analysis": {
    "summary": "This release adds...",
    "key_changes": ["Added X", "Fixed Y"],
    "cve_references": ["CVE-2026-12345"],
    "severity": "medium",
    "tags": ["security", "bug-fix"]
  },
  "analysis_error": null
}
```

### Cursor record (`cursor:{owner}/{repo}`)
```json
{
  "published_at": "2026-05-19T06:00:00Z",
  "updated_at": "2026-05-19T06:01:00Z"
}
```

---

## 1.7 Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-01 | Given a new release is published, when the daily function runs, then the release appears in `/digest` within 24 h |
| AC-02 | Given a release was already stored, when the function runs again, the existing record is not overwritten |
| AC-03 | Given a release body contains "CVE-2026-12345", when analysed, then `cve_references` includes that string |
| AC-04 | Given `repos.json` lists 3 repos, when repo #2 returns a 404, then repos #1 and #3 are still processed |
| AC-05 | Given the bento page loads, when filtered by a repo name, then only matching cards are visible |
| AC-06 | Given no prior cursor, when the function runs for the first time, then all releases for the last 2 major versions are fetched (e.g. v12.x.x and v11.x.x) |
| AC-06b | Given a repo with non-semver tags and no cursor, then the most recent 20 releases are fetched as backfill |
| AC-06c | Given `"owner/repo"` is added to `repos.json`, the next scheduled run backfills it without any code change |
| AC-07 | Given `/trigger` is called without the correct secret header, then a 401 is returned |
| AC-08 | Given 0 new releases since last run, when the function runs, then no Groq API calls are made |
