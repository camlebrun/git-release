from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.security_advisories import analyse_advisory, fetch_advisories


def _mock_response(ok: bool, data: object, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


def _make_advisory(
    severity: str = "high", ghsa_id: str = "GHSA-0000-0000-0000"
) -> dict[str, object]:
    return {
        "ghsa_id": ghsa_id,
        "cve_id": "CVE-2026-12345",
        "severity": severity,
        "summary": "Remote code execution.",
        "description": "Attacker can execute arbitrary code.",
        "published_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "html_url": "https://github.com/owner/repo/security/advisories/GHSA-0000-0000-0000",
    }


# ── fetch_advisories ────────────────────────────────────────────────────────


def test_fetch_returns_normalised_advisories() -> None:
    raw = [_make_advisory()]
    with patch("src.security_advisories.requests.get", return_value=_mock_response(True, raw)):
        result = fetch_advisories("owner", "repo")
    assert len(result) == 1
    assert result[0]["repo"] == "owner/repo"
    assert result[0]["ghsa_id"] == "GHSA-0000-0000-0000"
    assert result[0]["severity"] == "high"


def test_fetch_sorts_by_severity() -> None:
    raw = [
        _make_advisory(severity="low", ghsa_id="GHSA-low"),
        _make_advisory(severity="critical", ghsa_id="GHSA-crit"),
        _make_advisory(severity="medium", ghsa_id="GHSA-med"),
    ]
    with patch("src.security_advisories.requests.get", return_value=_mock_response(True, raw)):
        result = fetch_advisories("owner", "repo")
    assert result[0]["ghsa_id"] == "GHSA-crit"
    assert result[1]["ghsa_id"] == "GHSA-med"
    assert result[2]["ghsa_id"] == "GHSA-low"


def test_fetch_http_error_returns_empty() -> None:
    with patch(
        "src.security_advisories.requests.get",
        return_value=_mock_response(False, {}, status_code=404),
    ):
        result = fetch_advisories("owner", "repo")
    assert result == []


def test_fetch_network_error_returns_empty() -> None:
    with patch("src.security_advisories.requests.get", side_effect=ConnectionError("timeout")):
        result = fetch_advisories("owner", "repo")
    assert result == []


def test_fetch_adds_auth_header_when_token_provided() -> None:
    mock_resp = _mock_response(True, [])
    with patch("src.security_advisories.requests.get", return_value=mock_resp) as mock_get:
        fetch_advisories("owner", "repo", token="ghp_test")
    headers = mock_get.call_args.kwargs["headers"]
    assert headers.get("Authorization") == "Bearer ghp_test"


def test_fetch_no_auth_header_without_token() -> None:
    mock_resp = _mock_response(True, [])
    with patch("src.security_advisories.requests.get", return_value=mock_resp) as mock_get:
        fetch_advisories("owner", "repo")
    headers = mock_get.call_args.kwargs["headers"]
    assert "Authorization" not in headers


# ── analyse_advisory ────────────────────────────────────────────────────────

_VALID_ANALYSIS = {"action": "upgrade-immediately", "impact": "RCE possible.", "notes": ""}


def test_analyse_returns_parsed_dict() -> None:
    adv = _make_advisory()
    with patch("src.analyser.call_llm", return_value=json.dumps(_VALID_ANALYSIS)):
        result = analyse_advisory(adv, "fake-key")
    assert result is not None
    assert result["action"] == "upgrade-immediately"


def test_analyse_returns_none_on_invalid_json() -> None:
    adv = _make_advisory()
    with patch("src.analyser.call_llm", return_value="not json {"):
        result = analyse_advisory(adv, "fake-key")
    assert result is None


def test_analyse_returns_none_on_exception() -> None:
    adv = _make_advisory()
    with patch("src.analyser.call_llm", side_effect=RuntimeError("network down")):
        result = analyse_advisory(adv, "fake-key")
    assert result is None
