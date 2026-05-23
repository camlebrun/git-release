"""Cloud Function — email digest sender (internal, requires OIDC auth from Cloud Run)."""

from __future__ import annotations

import json
import logging
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

# Module-level secret cache — loaded once per cold start
_secrets: dict[str, str] = {}


def _get_secret(name: str) -> str:
    if name not in _secrets:
        client = secretmanager.SecretManagerServiceClient()
        path = f"projects/{GCP_PROJECT}/secrets/{name}/versions/latest"
        _secrets[name] = client.access_secret_version(name=path).payload.data.decode()
    return _secrets[name]


def _safe_text(s: str) -> str:
    """Normalize common non-ASCII lookalikes from LLM output to plain UTF-8."""
    return (
        s.replace("\xa0", " ")  # non-breaking space → regular space
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )


def _render_card(r: dict[str, Any]) -> str:
    a = r.get("analysis") or {}
    sev = a.get("severity", "none")
    repo = r.get("repo", "")
    changes = a.get("key_changes", [])[:4]
    changes_block = ""
    if changes:
        items = "".join(
            f'<li style="margin:6px 0;color:#6b7280;-webkit-text-fill-color:#6b7280;font-size:13px;line-height:1.5;">'
            f'<span style="color:#8b5cf6;-webkit-text-fill-color:#8b5cf6;font-weight:700;margin-right:8px;">&rsaquo;</span>'
            f"{_safe_text(str(c))}</li>"
            for c in changes
        )
        changes_block = f'<ul style="margin:0;padding:0;list-style:none;">{items}</ul>'

    tpl = (_TEMPLATES / "email_card.html").read_text()
    return (
        tpl.replace("{{sev_bg}}", _SEV_BG.get(sev, "#f3f4f6"))
        .replace("{{sev_fg}}", _SEV_FG.get(sev, "#6b7280"))
        .replace("{{severity}}", sev)
        .replace("{{repo_owner}}", repo.split("/")[0])
        .replace("{{repo_name}}", repo.split("/")[-1])
        .replace("{{tag}}", str(r.get("tag", "")))
        .replace("{{summary}}", _safe_text(a.get("summary", "No summary available.")))
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


def _fail_html(error: str, repo: str | None) -> str:
    context = (
        f"<p style='margin:0 0 8px;color:#6b7280;font-size:13px;'>"
        f"Repo: <strong>{repo}</strong></p>"
        if repo
        else ""
    )
    return (
        '<!DOCTYPE html><html><head><meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark"></head><body style="margin:0;padding:0;'
        "background-color:#f5f3ff;"
        'font-family:-apple-system,sans-serif;">'
        '<div style="max-width:600px;margin:0 auto;padding:32px 16px;">'
        '<div style="margin-bottom:20px;">'
        '<span style="font-size:16px;font-weight:700;color:#5b5fc7;display:flex;align-items:center;gap:8px;">'
        "📡 StackRadar</span></div>"
        '<div style="background:white;border-radius:20px;border:1px solid #fee2e2;'
        'border-left:3px solid #dc2626;padding:20px 24px;">'
        '<h2 style="margin:0 0 12px;color:#dc2626;font-size:16px;font-weight:700;">'
        "⚠ Pipeline failure</h2>"
        f"{context}"
        f'<pre style="margin:0;background:#fef2f2;border-radius:8px;padding:12px;'
        f'font-size:12px;color:#7f1d1d;overflow:auto;white-space:pre-wrap;">{error}</pre>'
        "</div>"
        '<p style="margin:20px 0 0;color:#9ca3af;font-size:11px;">Sent by StackRadar</p>'
        "</div></body></html>"
    )


def _send(subject: str, html: str) -> None:
    gmail_address = _get_secret("GMAIL_ADDRESS")
    gmail_app_password = _get_secret("GMAIL_APP_PASSWORD")
    notify_email = _get_secret("NOTIFY_EMAIL")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = notify_email
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, notify_email, msg.as_bytes())


@functions_framework.http
def send_email(request: Request) -> Response:
    try:
        body = request.get_json(silent=True) or {}
        path = request.path.rstrip("/")

        if path == "/fail":
            error = body.get("error", "Unknown error")
            repo = body.get("repo")
            _send("[StackRadar] Pipeline failure", _fail_html(error, repo))
            logger.info("Fail email sent for repo=%s", repo)
            return Response(json.dumps({"sent": "fail"}), status=200, mimetype="application/json")

        releases = body.get("releases", [])
        if not releases:
            return Response(json.dumps({"sent": 0}), status=200, mimetype="application/json")

        count = len(releases)
        _send(
            f"[StackRadar] {count} new release{'s' if count > 1 else ''}",
            _build_html(releases),
        )
        logger.info("Digest email sent: %d releases", count)
        return Response(json.dumps({"sent": count}), status=200, mimetype="application/json")

    except Exception as e:
        logger.error("Email failed: %s", e)
        return Response(json.dumps({"error": str(e)}), status=500, mimetype="application/json")
