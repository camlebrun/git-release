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
            f'<li style="margin:4px 0;color:#6b7280;font-size:13px;">{c}</li>' for c in changes
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


def _send_raw(
    gmail_address: str, gmail_app_password: str, to: str, subject: str, html: str
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, to, msg.as_string())


def _fail_html(error: str, repo: str | None) -> str:
    context = (
        f"<p style='margin:0 0 8px;color:#6b7280;font-size:13px;'>Repo: <strong>{repo}</strong></p>"
        if repo
        else ""
    )
    return f"""<!DOCTYPE html><html><body style="margin:0;padding:0;background:linear-gradient(135deg,#f5f3ff 0%,#ede9fe 100%);font-family:-apple-system,sans-serif;">
  <div style="max-width:600px;margin:0 auto;padding:32px 16px;">
    <div style="margin-bottom:20px;">
      <span style="font-size:16px;font-weight:700;background:linear-gradient(135deg,#5b5fc7,#8b5cf6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">⬡ StackRadar</span>
    </div>
    <div style="background:white;border-radius:20px;border:1px solid #fee2e2;border-left:3px solid #dc2626;padding:20px 24px;">
      <h2 style="margin:0 0 12px;color:#dc2626;font-size:16px;font-weight:700;">⚠ Pipeline failure</h2>
      {context}
      <pre style="margin:0;background:#fef2f2;border-radius:8px;padding:12px;font-size:12px;color:#7f1d1d;overflow:auto;white-space:pre-wrap;">{error}</pre>
    </div>
    <p style="margin:20px 0 0;color:#9ca3af;font-size:11px;">Sent by StackRadar</p>
  </div>
</body></html>"""


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

        path = request.path.rstrip("/")

        if path == "/fail":
            error = body.get("error", "Unknown error")
            repo = body.get("repo")
            subject = "⚠ StackRadar — Pipeline failure"
            _send_raw(
                gmail_address, gmail_app_password, notify_email, subject, _fail_html(error, repo)
            )
            logger.info("Fail email sent")
            return Response(json.dumps({"sent": "fail"}), status=200, mimetype="application/json")

        count = len(releases)
        subject = f"⬡ {count} new release{'s' if count > 1 else ''} — StackRadar"
        _send_raw(gmail_address, gmail_app_password, notify_email, subject, _build_html(releases))

        logger.info("Email sent: %d releases", count)
        return Response(json.dumps({"sent": count}), status=200, mimetype="application/json")

    except Exception as e:
        logger.error("Email failed: %s", e)
        return Response(str(e), status=500)
