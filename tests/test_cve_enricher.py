from unittest.mock import MagicMock, patch

from src.cve_enricher import enrich_cve, enrich_cve_list

_NVD_RESPONSE = {
    "vulnerabilities": [
        {
            "cve": {
                "id": "CVE-2026-12345",
                "descriptions": [{"lang": "en", "value": "A critical buffer overflow."}],
                "metrics": {
                    "cvssMetricV31": [{"cvssData": {"baseScore": 9.8, "baseSeverity": "CRITICAL"}}]
                },
                "references": [{"url": "https://example.com/advisory"}],
            }
        }
    ]
}

_OSV_RESPONSE = {
    "id": "CVE-2026-99999",
    "summary": "A moderate vulnerability in package X.",
    "references": [{"url": "https://osv.dev/CVE-2026-99999"}],
    "severity": [{"score": "5.4"}],
}


def _resp(data: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.ok = status < 400
    r.status_code = status
    r.json.return_value = data
    return r


def test_enrich_cve_nvd_happy_path() -> None:
    with patch("src.cve_enricher.requests.get", return_value=_resp(_NVD_RESPONSE)):
        result = enrich_cve("CVE-2026-12345")
    assert result["id"] == "CVE-2026-12345"
    assert result["cvss_score"] == 9.8
    assert result["cvss_severity"] == "CRITICAL"
    assert "buffer overflow" in (result["description"] or "")
    assert result["source"] == "nvd"


def test_enrich_cve_falls_back_to_osv_on_nvd_failure() -> None:
    nvd_fail = _resp({}, status=404)
    osv_ok = _resp(_OSV_RESPONSE)
    with patch("src.cve_enricher.requests.get", side_effect=[nvd_fail, osv_ok]):
        result = enrich_cve("CVE-2026-99999")
    assert result["source"] == "osv"
    assert "moderate" in (result["description"] or "")


def test_enrich_cve_returns_minimal_on_both_failures() -> None:
    fail = _resp({}, status=500)
    with patch("src.cve_enricher.requests.get", side_effect=[fail, fail]):
        result = enrich_cve("CVE-2026-00000")
    assert result["id"] == "CVE-2026-00000"
    assert result["description"] is None
    assert result["cvss_score"] is None


def test_enrich_cve_list_returns_one_per_id() -> None:
    with patch("src.cve_enricher.requests.get", return_value=_resp(_NVD_RESPONSE)):
        with patch("src.cve_enricher.time.sleep"):  # skip rate-limit delay
            results = enrich_cve_list(["CVE-2026-12345", "CVE-2026-12345"])
    assert len(results) == 2


def test_enrich_cve_nvd_empty_vulnerabilities_falls_back() -> None:
    nvd_empty = _resp({"vulnerabilities": []})
    osv_ok = _resp(_OSV_RESPONSE)
    with patch("src.cve_enricher.requests.get", side_effect=[nvd_empty, osv_ok]):
        result = enrich_cve("CVE-2026-99999")
    assert result["source"] == "osv"
