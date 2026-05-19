RELEASE_ANALYSIS_PROMPT = """\
You are a senior software engineer analysing a GitHub release note.

Repository: {repo}
Tag: {tag}
Release name: {name}

Release body (markdown):
---
{body}
---

Return ONLY a valid JSON object with this exact schema:
{{
  "summary": "<2-4 sentence plain-English summary of what changed>",
  "key_changes": ["<change 1>", "<change 2>", ...],
  "cve_references": ["CVE-YYYY-NNNNN", ...],
  "severity": "<one of: none | low | medium | high | critical>",
  "tags": ["<zero or more of: breaking | security | performance | bug-fix | feature | deprecation>"]
}}

Rules:
- key_changes: at most 8 items, each under 100 chars
- cve_references: extract ONLY CVE IDs explicitly written in the body (format CVE-YYYY-NNNNN)
- severity: reflect security impact — none if no CVEs or breaking changes, critical if RCE/auth bypass
- tags: include "security" whenever cve_references is non-empty; "breaking" for breaking API changes
- Return valid JSON only — no markdown fences, no commentary outside the JSON object
"""
