from __future__ import annotations

import json
import logging
import os

from flask import Flask, Request, Response, request

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

app = Flask(__name__)

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


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "OPTIONS"])
def handle(path: str) -> Response:
    if request.method == "OPTIONS":
        return Response("", status=204, headers=_CORS)

    route = "/" + path.rstrip("/")

    if route == "/digest":
        return _handle_digest(request)
    if route == "/health":
        return _handle_health(request)
    if route == "/trigger":
        return _handle_trigger(request)

    return _json({"error": "Not Found"}, status=404)


def _handle_digest(req: Request) -> Response:
    try:
        limit = int(req.args.get("limit", DIGEST_DEFAULT_LIMIT))
    except ValueError:
        limit = DIGEST_DEFAULT_LIMIT
    limit = min(limit, DIGEST_MAX_LIMIT)
    s3 = _get_s3()
    records = get_digest(s3, R2_BUCKET, limit)
    return _json(records)


def _handle_health(req: Request) -> Response:
    s3 = _get_s3()
    status = get_run_status(s3, R2_BUCKET) or {"ran_at": None, "repos": {}}
    return _json(status)


def _handle_trigger(req: Request) -> Response:
    expected = get_secret(GCP_PROJECT, "TRIGGER_SECRET")
    provided = req.headers.get("X-Trigger-Secret", "")
    if provided != expected:
        return _json({"error": "Unauthorized"}, status=401)

    s3 = _get_s3()
    mistral_key = get_secret(GCP_PROJECT, "MISTRAL_API_KEY")
    try:
        github_token: str | None = get_secret(GCP_PROJECT, "GITHUB_TOKEN")
    except Exception:
        github_token = None
    try:
        email_function_url: str | None = get_secret(GCP_PROJECT, "EMAIL_FUNCTION_URL")
    except Exception:
        email_function_url = None

    result = run_pipeline(
        s3,
        R2_BUCKET,
        mistral_key,
        github_token,
        llm_provider="mistral",
        llm_delay_s=1.2,
        email_function_url=email_function_url,
    )
    return _json(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
