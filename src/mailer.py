from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TEMPLATES = Path(__file__).parent / "templates"

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
        li_style = (
            "margin:6px 0;color:#6b7280;-webkit-text-fill-color:#6b7280;"
            "font-size:13px;line-height:1.5;"
        )
        bullet_style = (
            "color:#8b5cf6;-webkit-text-fill-color:#8b5cf6;" "font-weight:700;margin-right:8px;"
        )
        items = "".join(
            f'<li style="{li_style}">'
            f'<span style="{bullet_style}">&rsaquo;</span>'
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
    msg.attach(MIMEText(_build_html(releases), "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_app_password)
            server.sendmail(gmail_address, to, msg.as_bytes())
        logger.info("Mail sent: %d releases → %s", count, to)
    except Exception as e:
        logger.error("Failed to send mail: %s", e)
