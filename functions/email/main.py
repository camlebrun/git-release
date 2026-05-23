"""Cloud Function — email digest sender.
Called by Cloud Run at end of pipeline with a JSON body: {"releases": [...]}
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import functions_framework
from flask import Request, Response
from google.cloud import secretmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GCP_PROJECT = "git-release-496817"

_SEV_BG = {
    "critical": "#fee2e2",
    "high": "#fff4ed",
    "medium": "#fffbeb",
    "low": "#eff6ff",
    "none": "#f3f4f6",
}
_SEV_FG = {
    "critical": "#dc2626",
    "high": "#ea580c",
    "medium": "#d97706",
    "low": "#2563eb",
    "none": "#6b7280",
}

_TEMPLATES = Path(__file__).parent / "templates"


def _get_secret(name: str) -> str:
    client = secretmanager.SecretManagerServiceClient()
    path = f"projects/{GCP_PROJECT}/secrets/{name}/versions/latest"
    return client.access_secret_version(name=path).payload.data.decode()


def _render_card(r: dict[str, Any]) -> str:
    a = r.get("analysis") or {}
    sev = a.get("severity", "none")
    repo = r.get("repo", "")
    changes = a.get("key_changes", [])[:4]
    changes_block = ""
    if changes:
        items = "".join(
            f'<li style="margin:4px 0;color:#6b7280;font-size:13px;">{c}</li>'
            for c in changes
        )
        changes_block = f'<ul style="margin:0;padding-left:16px;">{items}</ul>'

    tpl = (_TEMPLATES / "email_card.html").read_text()
    return (
        tpl.replace("{{sev_bg}}", _SEV_BG.get(sev, "#f3f4f6"))
        .replace("{{sev_fg}}", _SEV_FG.get(sev, "#6b7280"))
        .replace("{{severity}}", sev)
        .replace("{{repo_owner}}", repo.split("/")[0])
        .replace("{{repo_name}}", repo.split("/")[-1])
        .replace("{{tag}}", str(r.get("tag", "")))
        .replace("{{summary}}", a.get("summary", "No summary available."))
        .replace("{{changes_block}}", changes_block)
        .replace("{{url}}", str(r.get("html_url", "#")))
    )


def _build_html(releases: list[dict[str, Any]]) -> str:
    count = len(releases)
    cards = "".join(_render_card(r) for r in releases)
    tpl = (_TEMPLATES / "email_digest.html").read_text()
    return (
        tpl.replace("{{count}}", str(count))
        .replace("{{count_plural}}", "s" if count > 1 else "")
        .replace("{{cards}}", cards)
    )


@functions_framework.http
def send_email(request: Request) -> Response:
    try:
        body = request.get_json(silent=True) or {}
        releases = body.get("releases", [])
        if not releases:
            return Response("no releases", status=200)

        gmail_address = _get_secret("GMAIL_ADDRESS")
        gmail_app_password = _get_secret("GMAIL_APP_PASSWORD")
        notify_email = _get_secret("NOTIFY_EMAIL")

        count = len(releases)
        subject = f"⬡ {count} new release{'s' if count > 1 else ''} — StackRadar"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = gmail_address
        msg["To"] = notify_email
        msg.attach(MIMEText(_build_html(releases), "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_app_password)
            server.sendmail(gmail_address, notify_email, msg.as_string())

        logger.info("Email sent: %d releases", count)
        return Response(json.dumps({"sent": count}), status=200, mimetype="application/json")

    except Exception as e:
        logger.error("Email failed: %s", e)
        return Response(str(e), status=500)
