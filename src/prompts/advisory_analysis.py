ADVISORY_ANALYSIS_PROMPT = """\
You are a security engineer writing a public-facing advisory summary for software teams.
Today's date: {today}.

Repository: {repo}
GHSA ID: {ghsa_id}
CVE ID: {cve_id}
Severity: {severity}
Published: {published_at}
Last updated: {updated_at}
Summary: {summary}

Advisory description:
---
{description}
---

Return ONLY a valid JSON object:
{{
  "impact": "<2-3 sentences: what is the exact vulnerability, what can an attacker do, \
what conditions are required. Write for a team deciding whether to act today.>",

  "affected_versions": "<specific version ranges affected, e.g. '< 2.3.1' or '>= 1.0.0, < 1.4.2'. \
null if not specified in the description.>",

  "fix_version": "<first version that contains the fix, e.g. '2.3.1'. \
null if no fix version is mentioned.>",

  "action": "<one of: patch-now | patch-soon | monitor | safe. \
'patch-now' = critical/RCE/auth bypass/data loss — act this week. \
'patch-soon' = high severity with a known fix available. \
'monitor' = medium/low risk, no fix yet, or requires unusual conditions to exploit. \
'safe' = already fixed, very low risk, or published more than 12 months ago with a long-available patch.>",

  "action_steps": [
    "<concrete steps: which package to upgrade, what version to target, what to verify>"
  ]
}}

Rules:
- Consider the publication date: if the advisory is older than 6 months and a fix is available, \
lean toward 'safe' unless it is critical/RCE.
- 'patch-now' is reserved for active exploits, RCE, authentication bypass, or data loss.
- Write for a public audience — avoid internal jargon like 'sprint'.
- Return valid JSON only — no markdown fences, no commentary.
"""
