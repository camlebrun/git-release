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
    "<Security advisory IDs explicitly written in the release body. Accept two formats: \
CVE-YYYY-NNNNN (CVE IDs) and GHSA-XXXX-XXXX-XXXX (GitHub Security Advisories). \
DO NOT infer, guess, or fabricate IDs. If none are written verbatim, return [].>"
  ],

  "severity": "<Upgrade urgency for the consuming team: none | low | medium | high | critical. \
'none' = no action needed — pure feature additions, performance improvements, patch/bug fixes with no behaviour change. \
'low' = minor behaviour change or optional deprecation warning; migration is trivial (1 config key, 1 flag). \
'medium' = breaking change that requires migration before upgrading — consumers must act. \
'high' = security fix (low/medium CVE), data integrity risk, or many breaking changes requiring significant refactor. \
'critical' = upgrade is urgent and complex: critical CVE / RCE / auth bypass / data loss, OR a major version release \
(X.0.0 or first stable release of a new major line e.g. v3.x after v2.x) with breaking changes requiring \
substantial migration effort across the codebase (e.g. Airflow 2→3, dbt-core 1→2). \
When in doubt between two levels, choose the higher one.>",

  "tags": [
    "<ONLY use values from this exact list — no others allowed: \
breaking | security | performance | bug-fix | feature | new-capability | \
deprecation | schema-change | config-change | dependency-update | refactor. \
Use 'new-capability' for significant new features that change what the tool can do (new API, new command, new integration). \
Use 'feature' for minor additions or improvements to existing functionality. \
Max 4 tags. No free-form values.>"
  ]
}}

Rules:
- summary: write as if briefing your team before a dependency upgrade decision
- key_changes: each entry must name the specific component, function, config key, or SQL object affected
- breaking_changes: when in doubt, include it — false positives are better than missing a breaking change
- Do not pad with filler. If the release is small, reflect that accurately.
- Return valid JSON only — no markdown fences, no commentary outside the JSON object
"""
