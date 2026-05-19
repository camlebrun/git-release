"""Build and push digest.json to R2 from existing release records."""
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

for line in Path(".env.local").read_text().splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

from src.config import GCP_PROJECT, R2_BUCKET
from src.digest import get_digest
from src.secrets import get_secret
from src.store import get_s3_client, write_digest_json

s3 = get_s3_client(
    access_key=get_secret(GCP_PROJECT, "R2_ACCESS_KEY_ID"),
    secret_key=get_secret(GCP_PROJECT, "R2_SECRET_ACCESS_KEY"),
    account_id=get_secret(GCP_PROJECT, "R2_ACCOUNT_ID"),
)

records = get_digest(s3, R2_BUCKET, limit=500)
write_digest_json(s3, R2_BUCKET, records)
print(f"✅ digest.json written to R2 ({len(records)} records)")
