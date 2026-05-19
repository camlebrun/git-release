from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

_NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_OSV_URL = "https://api.osv.dev/v1/vulns"
_TIMEOUT = 8


def enrich_cve(cve_id: str) -> dict[str, object]:
    """Return NVD data for a CVE ID, falling back to OSV.dev.

    Returns a dict with: id, description, cvss_score, cvss_severity, references.
    Returns minimal dict on any failure (never raises).
    """
    result = _fetch_nvd(cve_id)
    if result:
        return result
    return _fetch_osv(cve_id) or {"id": cve_id, "description": None, "cvss_score": None, "cvss_severity": None, "references": []}


def enrich_cve_list(cve_ids: list[str]) -> list[dict[str, object]]:
    """Enrich a list of CVE IDs. Respects NVD rate limit (1 req/6s without API key)."""
    results = []
    for i, cve_id in enumerate(cve_ids):
        if i > 0:
            time.sleep(6)  # NVD free tier: max 5 req/30s
        results.append(enrich_cve(cve_id))
    return results


def _fetch_nvd(cve_id: str) -> dict[str, object] | None:
    try:
        resp = requests.get(_NVD_URL, params={"cveId": cve_id}, timeout=_TIMEOUT)
        if not resp.ok:
            return None
        data = resp.json()
        vulns = data.get("vulnerabilities", [])
        if not vulns:
            return None
        cve = vulns[0]["cve"]
        description = next(
            (d["value"] for d in cve.get("descriptions", []) if d["lang"] == "en"),
            None,
        )
        metrics = cve.get("metrics", {})
        cvss_score: float | None = None
        cvss_severity: str | None = None
        for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            if key in metrics and metrics[key]:
                m = metrics[key][0]
                cvss_data = m.get("cvssData", {})
                cvss_score = cvss_data.get("baseScore")
                cvss_severity = cvss_data.get("baseSeverity") or m.get("baseSeverity")
                break
        references = [r["url"] for r in cve.get("references", [])[:5]]
        return {
            "id": cve_id,
            "description": description,
            "cvss_score": cvss_score,
            "cvss_severity": cvss_severity,
            "references": references,
            "source": "nvd",
        }
    except Exception as e:
        logger.warning("NVD fetch failed for %s: %s", cve_id, e)
        return None


def _fetch_osv(cve_id: str) -> dict[str, object] | None:
    try:
        resp = requests.get(f"{_OSV_URL}/{cve_id}", timeout=_TIMEOUT)
        if not resp.ok:
            return None
        data = resp.json()
        summary = data.get("summary") or data.get("details", "")
        refs = [r["url"] for r in data.get("references", [])[:5]]
        severity = data.get("severity", [{}])
        score = severity[0].get("score") if severity else None
        return {
            "id": cve_id,
            "description": summary[:500] if summary else None,
            "cvss_score": score,
            "cvss_severity": None,
            "references": refs,
            "source": "osv",
        }
    except Exception as e:
        logger.warning("OSV fetch failed for %s: %s", cve_id, e)
        return None
