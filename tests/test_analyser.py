import json
from unittest.mock import MagicMock, patch

import pytest

from src.analyser import analyse_release

_VALID_ANALYSIS = {
    "summary": "This release fixes several bugs.",
    "key_changes": ["Fixed bug A", "Fixed bug B"],
    "cve_references": [],
    "severity": "none",
    "tags": ["bug-fix"],
}


def _make_release(body: str = "Fixed bugs.") -> dict[str, object]:
    return {
        "repo": "owner/repo",
        "tag_name": "v1.0.0",
        "name": "Release 1.0.0",
        "body": body,
    }


def _mock_groq(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


def test_happy_path() -> None:
    client = _mock_groq(json.dumps(_VALID_ANALYSIS))
    with patch("src.analyser.Groq", return_value=client):
        analysis, error = analyse_release(_make_release(), "fake-key")
    assert error is None
    assert analysis is not None
    assert analysis["summary"] == _VALID_ANALYSIS["summary"]
    assert analysis["severity"] == "none"
    assert analysis["tags"] == ["bug-fix"]


def test_invalid_json_returns_none() -> None:
    client = _mock_groq("not json }{")
    with patch("src.analyser.Groq", return_value=client):
        analysis, error = analyse_release(_make_release(), "fake-key")
    assert analysis is None
    assert error is not None


def test_cve_detection() -> None:
    body = "Fixes CVE-2026-12345 and CVE-2026-99999."
    payload = {
        **_VALID_ANALYSIS,
        "cve_references": ["CVE-2026-12345", "CVE-2026-99999"],
        "severity": "high",
        "tags": ["security", "bug-fix"],
    }
    client = _mock_groq(json.dumps(payload))
    with patch("src.analyser.Groq", return_value=client):
        analysis, error = analyse_release(_make_release(body), "fake-key")
    assert error is None
    assert analysis is not None
    assert "CVE-2026-12345" in analysis["cve_references"]
    assert analysis["severity"] == "high"


def test_groq_exception_returns_none() -> None:
    client = MagicMock()
    client.chat.completions.create.side_effect = Exception("timeout")
    with patch("src.analyser.Groq", return_value=client):
        analysis, error = analyse_release(_make_release(), "fake-key")
    assert analysis is None
    assert error is not None
    assert "timeout" in error
