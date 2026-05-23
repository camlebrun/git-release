from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TEMPLATES = Path(__file__).parent / "templates"

_SEV_COLOR = {
    "critical": "#ef4444",
    "high": "#f97316",
    "medium": "#eab308",
    "low": "#22c55e",
    "none": "#6b7280",
}

_SEV_BG = {
    "critical": "#450a0a",
    "high": "#431407",
    "medium": "#422006",
    "low": "#052e16",
    "none": "#18181b",
}


def _render_card(r: dict[str, Any]) -> str:
    a = r.get("analysis") or {}
    sev = a.get("severity", "none")
    repo = r.get("repo", "")
    changes = a.get("key_changes", [])[:4]

    changes_block = ""
    if changes:
        items = "".join(
            f'<li style="margin:4px 0;color:#a1a1aa;font-size:13px;">{c}</li>'
            for c in changes
        )
        changes_block = f'<ul style="margin:0;padding-left:16px;">{items}</ul>'

    border = _SEV_COLOR.get(sev, "#3f3f46")
    tpl = (_TEMPLATES / "email_card.html").read_text()
    return tpl.replace("{{bg}}", _SEV_BG.get(sev, "#18181b")) \
              .replace("{{border}}", border) \
              .replace("{{border_alpha}}", border + "40") \
              .replace("{{sev_color}}", border) \
              .replace("{{severity}}", sev) \
              .replace("{{repo_owner}}", repo.split("/")[0]) \
              .replace("{{repo_name}}", repo.split("/")[-1]) \
              .replace("{{tag}}", str(r.get("tag", ""))) \
              .replace("{{summary}}", a.get("summary", "No summary available.")) \
              .replace("{{changes_block}}", changes_block) \
              .replace("{{url}}", str(r.get("html_url", "#")))


def _build_html(releases: list[dict[str, Any]]) -> str:
    count = len(releases)
    cards = "".join(_render_card(r) for r in releases)
    tpl = (_TEMPLATES / "email_digest.html").read_text()
    return tpl.replace("{{count}}", str(count)) \
              .replace("{{count_plural}}", "s" if count > 1 else "") \
              .replace("{{cards}}", cards)


def send_release_digest(
    releases: list[dict[str, Any]],
    gmail_address: str,
    gmail_app_password: str,
    to: str,
) -> None:
    if not releases:
        return

    count = len(releases)
    subject = f"⧆ {count} new release{'s' if count > 1 else ''} — StackRadar"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = to
    msg.attach(MIMEText(_build_html(releases), "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_app_password)
            server.sendmail(gmail_address, to, msg.as_string())
        logger.info("Mail sent: %d releases → %s", count, to)
    except Exception as e:
        logger.error("Failed to send mail: %s", e)
