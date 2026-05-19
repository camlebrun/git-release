from __future__ import annotations

import json
import logging

import functions_framework
from flask import Request, Response

from src.config import (
    DIGEST_DEFAULT_LIMIT,
    DIGEST_MAX_LIMIT,
    GCP_PROJECT,
    R2_BUCKET,
)
from src.digest import get_digest
from src.pipeline import run_pipeline
from src.secrets import get_secret
from src.store import get_run_status, get_s3_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Trigger-Secret",
}


def _json(data: object, status: int = 200) -> Response:
    return Response(
        json.dumps(data, default=str),
        status=status,
        mimetype="application/json",
        headers=_CORS,
    )


def _get_s3() -> object:
    return get_s3_client(
        access_key=get_secret(GCP_PROJECT, "R2_ACCESS_KEY_ID"),
        secret_key=get_secret(GCP_PROJECT, "R2_SECRET_ACCESS_KEY"),
        account_id=get_secret(GCP_PROJECT, "R2_ACCOUNT_ID"),
    )


@functions_framework.http
def main(request: Request) -> Response:
    if request.method == "OPTIONS":
        return Response("", status=204, headers=_CORS)

    path = request.path.rstrip("/") or "/"

    if path == "/digest":
        return _handle_digest(request)
    if path == "/health":
        return _handle_health(request)
    if path == "/trigger":
        return _handle_trigger(request)

    return _json({"error": "Not Found"}, status=404)


def _handle_digest(request: Request) -> Response:
    try:
        limit = int(request.args.get("limit", DIGEST_DEFAULT_LIMIT))
    except ValueError:
        limit = DIGEST_DEFAULT_LIMIT
    limit = min(limit, DIGEST_MAX_LIMIT)
    s3 = _get_s3()
    records = get_digest(s3, R2_BUCKET, limit)
    return _json(records)


def _handle_health(request: Request) -> Response:
    s3 = _get_s3()
    status = get_run_status(s3, R2_BUCKET) or {"ran_at": None, "repos": {}}
    return _json(status)


def _handle_trigger(request: Request) -> Response:
    expected = get_secret(GCP_PROJECT, "TRIGGER_SECRET")
    provided = request.headers.get("X-Trigger-Secret", "")
    if provided != expected:
        return _json({"error": "Unauthorized"}, status=401)

    s3 = _get_s3()
    groq_key = get_secret(GCP_PROJECT, "GROQ_API_KEY")
    try:
        github_token: str | None = get_secret(GCP_PROJECT, "GITHUB_TOKEN")
    except Exception:
        github_token = None

    result = run_pipeline(s3, R2_BUCKET, groq_key, github_token)
    return _json(result)
