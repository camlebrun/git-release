RELEASE_ANALYSIS_PROMPT = """\
You are a principal software engineer reviewing a release for a tech lead audience.
Your analysis must be technical, precise, and actionable — not a marketing summary.

Repository: {repo}
Tag: {tag}
Release name: {name}

Release notes (markdown):
---
{body}
---

Return ONLY a valid JSON object with this exact schema:

{{
  "summary": "<3-5 sentences. Cover: what problem this release solves, the \
technical approach taken, and the impact on downstream consumers. \
Mention deprecations, architectural shifts, or performance characteristics if present. \
Write for an engineer who owns services that depend on this repo.>",

  "key_changes": [
    "<Each item must be specific and technical. Format: '[Component/Area] What changed and why it matters.' \
Include: API changes, config changes, new CLI flags, SQL/schema changes, dependency bumps with implications, \
performance improvements with measured gains, behaviour changes that affect idempotency/correctness. \
Max 8 items. No vague entries like 'bug fixes' — be precise about what was broken and what changed.>"
  ],

  "breaking_changes": [
    "<List every change that requires action from consumers: deprecated config keys removed, \
renamed CLI args, changed return types, removed endpoints, new required parameters, \
changed default behaviours. Empty array if none.>"
  ],

  "migration_notes": "<If breaking_changes is non-empty: concrete steps to migrate. \
What files to update, what commands to run, what to test. \
Empty string if no migration needed.>",

  "cve_references": [
    "<ONLY CVE IDs that appear verbatim in the release body, exact format CVE-YYYY-NNNNN \
where YYYY is a 4-digit year and NNNNN is at least 4 digits. \
DO NOT infer, guess, or fabricate CVE IDs. If none are explicitly written, return [].>"
  ],

  "severity": "<Security/stability impact: none | low | medium | high | critical. \
Base on: CVEs present, breaking changes, data-loss risk, auth changes. \
'none' = pure feature/perf. 'low' = minor behaviour change. 'medium' = breaking change requiring migration. \
'high' = security fix or data integrity risk. 'critical' = RCE, auth bypass, data loss.>",

  "tags": [
    "<One or more of: breaking | security | performance | bug-fix | feature | deprecation | \
schema-change | config-change | dependency-update | refactor>"
  ]
}}

Rules:
- summary: write as if briefing your team before a dependency upgrade decision
- key_changes: each entry must name the specific component, function, config key, or SQL object affected
- breaking_changes: when in doubt, include it — false positives are better than missing a breaking change
- Do not pad with filler. If the release is small, reflect that accurately.
- Return valid JSON only — no markdown fences, no commentary outside the JSON object
"""
