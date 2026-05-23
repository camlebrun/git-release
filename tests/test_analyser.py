import json
from unittest.mock import MagicMock, patch

from src.analyser import (
    analyse_fusion_historical,
    analyse_fusion_release,
    analyse_release,
    call_llm,
)

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


# ── analyse_fusion_release ───────────────────────────────────────────────────

_FUSION_ANALYSIS = {
    **_VALID_ANALYSIS,
    "worth_tracking": True,
    "breaking_changes": [],
    "migration_notes": "",
}


def _make_fusion_release() -> dict[str, object]:
    return {
        "repo": "dbt-labs/dbt-fusion",
        "tag_name": "2.0.0-preview.177",
        "body": "Released January 20, 2026\n\n### Features\n\n- Add Snowflake adapter",
    }


def test_fusion_release_worth_tracking_true() -> None:
    mock_client = _mock_mistral_client(json.dumps(_FUSION_ANALYSIS))
    with patch("src.analyser.Mistral", return_value=mock_client):
        analysis, error = analyse_fusion_release(_make_fusion_release(), "fake-key")
    assert error is None
    assert analysis is not None
    assert analysis["worth_tracking"] is True


def test_fusion_release_worth_tracking_false() -> None:
    payload = {**_FUSION_ANALYSIS, "worth_tracking": False, "key_changes": []}
    mock_client = _mock_mistral_client(json.dumps(payload))
    with patch("src.analyser.Mistral", return_value=mock_client):
        analysis, error = analyse_fusion_release(_make_fusion_release(), "fake-key")
    assert error is None
    assert analysis is not None
    assert analysis["worth_tracking"] is False


def test_fusion_release_invalid_json_returns_none() -> None:
    with patch("src.analyser.Mistral", return_value=_mock_mistral_client("bad json")):
        analysis, error = analyse_fusion_release(_make_fusion_release(), "fake-key")
    assert analysis is None
    assert error is not None


def test_fusion_release_exception_returns_none() -> None:
    client = MagicMock()
    client.chat.complete.side_effect = Exception("network error")
    with patch("src.analyser.Mistral", return_value=client):
        analysis, error = analyse_fusion_release(_make_fusion_release(), "fake-key")
    assert analysis is None
    assert "network error" in (error or "")


# ── analyse_fusion_historical ────────────────────────────────────────────────


def _make_historical_release() -> dict[str, object]:
    return {
        "repo": "dbt-labs/dbt-fusion",
        "tag_name": "2.0.0-pre-2026",
        "body": "### 2.0.0-preview.4\nFirst release\n\n---\n\n### 2.0.0-preview.5\nBigQuery",
        "_historical_meta": {
            "version_count": 10,
            "first_version": "2.0.0-preview.4",
            "last_version": "2.0.0-preview.5",
            "version_list": "- 2.0.0-preview.4 (2025-10-01)\n- 2.0.0-preview.5 (2025-11-20)",
        },
    }


def test_fusion_historical_returns_worth_tracking_true() -> None:
    payload = {**_FUSION_ANALYSIS, "worth_tracking": True}
    mock_client = _mock_mistral_client(json.dumps(payload))
    with patch("src.analyser.Mistral", return_value=mock_client):
        analysis, error = analyse_fusion_historical(_make_historical_release(), "fake-key")
    assert error is None
    assert analysis is not None
    assert analysis["worth_tracking"] is True


def test_fusion_historical_invalid_json_returns_none() -> None:
    with patch("src.analyser.Mistral", return_value=_mock_mistral_client("not json")):
        analysis, error = analyse_fusion_historical(_make_historical_release(), "fake-key")
    assert analysis is None
    assert error is not None


def test_fusion_historical_bad_meta_does_not_crash() -> None:
    release = {**_make_historical_release(), "_historical_meta": "bad"}
    payload = {**_FUSION_ANALYSIS, "worth_tracking": True}
    mock_client = _mock_mistral_client(json.dumps(payload))
    with patch("src.analyser.Mistral", return_value=mock_client):
        analysis, error = analyse_fusion_historical(release, "fake-key")
    assert error is None
    assert analysis is not None
