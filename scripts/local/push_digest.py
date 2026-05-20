"""Build and push digest.json to R2 — releases + security advisories (no LLM)."""
import logging
import os
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

log.info("Loading .env.local...")
for line in Path(".env.local").read_text().splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()
log.info(".env.local loaded")

log.info("Importing modules...")
from src.config import GCP_PROJECT, R2_BUCKET
from src.digest import get_digest
from src.pipeline import load_repos
from src.secrets import get_secret
from src.security_advisories import fetch_advisories
from src.store import get_s3_client, read_all_advisories, write_digest_json, write_repo_advisories
log.info("Modules imported")

log.info("Connecting to R2...")
s3 = get_s3_client(
    access_key=get_secret(GCP_PROJECT, "R2_ACCESS_KEY_ID"),
    secret_key=get_secret(GCP_PROJECT, "R2_SECRET_ACCESS_KEY"),
    account_id=get_secret(GCP_PROJECT, "R2_ACCOUNT_ID"),
)
log.info("R2 connected — bucket: %s", R2_BUCKET)

github_token = get_secret(GCP_PROJECT, "GITHUB_TOKEN")
log.info("GitHub token loaded: %s...", github_token[:10])

repos = load_repos()
log.info("Repos to process: %s", [r["repo"] for r in repos])

# ── Fetch advisories per repo ──────────────────────────────────────────────
for repo_cfg in repos:
    repo = repo_cfg["repo"]
    owner, name = repo.split("/", 1)
    log.info("[%s] Fetching security advisories from GitHub API...", repo)
    advisories = fetch_advisories(owner, name, github_token)
    log.info("[%s] Got %d advisories", repo, len(advisories))
    for a in advisories:
        log.info("  → %s | %s | %s", a.get("ghsa_id"), a.get("cve_id"), a.get("severity"))
    log.info("[%s] Writing to R2: advisories/%s/%s/advisories.json...", repo, owner, name)
    write_repo_advisories(s3, R2_BUCKET, owner, name, advisories)
    log.info("[%s] ✓ Written", repo)

# ── Read all advisories from R2 ────────────────────────────────────────────
log.info("Reading all advisories from R2...")
all_advisories = read_all_advisories(s3, R2_BUCKET)
log.info("Total advisories in R2: %d", len(all_advisories))

# ── Read all releases from R2 ──────────────────────────────────────────────
log.info("Reading releases from R2...")
records = get_digest(s3, R2_BUCKET, limit=500)
log.info("Total releases: %d", len(records))

# ── Write master digest.json ───────────────────────────────────────────────
log.info("Writing digest.json to R2...")
write_digest_json(s3, R2_BUCKET, records, all_advisories)
log.info("✅ digest.json written: %d releases, %d advisories", len(records), len(all_advisories))
