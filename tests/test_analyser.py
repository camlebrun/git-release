import json
from unittest.mock import MagicMock, patch

from src.analyser import analyse_release, call_llm

_VALID_ANALYSIS = {
    "summary": "This release fixes several bugs.",
    "key_changes": ["Fixed bug A", "Fixed bug B"],
    "cve_references": [],
    "severity": "none",
    "tags": ["bug-fix"],
}


def _make_release(body: str = "Fixed bugs.") -> dict[str, object]:
    return {"repo": "owner/repo", "tag_name": "v1.0.0", "name": "Release 1.0.0", "body": body}


def _mock_mistral_client(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.complete.return_value = response
    return client


def test_happy_path() -> None:
    mock_client = _mock_mistral_client(json.dumps(_VALID_ANALYSIS))
    with patch("src.analyser.Mistral", return_value=mock_client):
        analysis, error = analyse_release(_make_release(), "fake-key")
    assert error is None
    assert analysis is not None
    assert analysis["summary"] == _VALID_ANALYSIS["summary"]
    assert analysis["severity"] == "none"


def test_invalid_json_returns_none() -> None:
    with patch("src.analyser.Mistral", return_value=_mock_mistral_client("not json }{")):
        analysis, error = analyse_release(_make_release(), "fake-key")
    assert analysis is None
    assert error is not None


def test_cve_detection() -> None:
    body = "Fixes CVE-2026-12345 and CVE-2026-99999."
    payload = {**_VALID_ANALYSIS, "cve_references": ["CVE-2026-12345"], "severity": "high"}
    with patch("src.analyser.Mistral", return_value=_mock_mistral_client(json.dumps(payload))):
        analysis, error = analyse_release(_make_release(body), "fake-key")
    assert error is None
    assert analysis is not None
    assert "CVE-2026-12345" in analysis["cve_references"]
    assert analysis["severity"] == "high"


def test_exception_returns_none() -> None:
    client = MagicMock()
    client.chat.complete.side_effect = Exception("timeout")
    with patch("src.analyser.Mistral", return_value=client):
        analysis, error = analyse_release(_make_release(), "fake-key")
    assert analysis is None
    assert "timeout" in (error or "")


def test_call_llm_returns_string() -> None:
    client = MagicMock()
    client.chat.complete.return_value.choices[0].message.content = '{"ok": true}'
    with patch("src.analyser.Mistral", return_value=client):
        result = call_llm("some prompt", "fake-key")
    assert result == '{"ok": true}'
