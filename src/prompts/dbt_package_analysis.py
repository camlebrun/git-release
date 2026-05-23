DBT_PACKAGE_ANALYSIS_PROMPT = """\
You are a senior analytics engineer reviewing a dbt package release for a team \
that uses this package in production dbt projects.

Repository: {repo}
Tag: {tag}
Release name: {name}

Package README (truncated):
---
{readme}
---

Release notes:
---
{body}
---

Return ONLY a valid JSON object with this exact schema:

{{
  "purpose": "<2-3 sentences. For whom is this package built, how does it work \
(macros? tests? models?), and why would a team use it over alternatives. \
Extract this from the README, not the release notes.>",

  "summary": "<2-3 sentences. What changed in this specific release and why it matters \
for a team running this package in prod. Skip cosmetic/doc-only changes.>",

  "key_changes": [
    "<Relevant changes only. Format: '[Area] What changed and impact.' \
Include: macro signature changes, new tests/assertions, breaking model changes, \
SQL dialect fixes, dbt version compatibility changes, new dependencies. \
EXCLUDE: README updates, contributor additions, changelog formatting, \
version bumps without functional change, migration guides for old versions. \
Max 6 items. Empty array if no meaningful functional change.>"
  ],

  "is_prod_breaking_bug": <true if this release fixes a bug that could silently produce wrong results, \
cause a dbt run to crash, or cause data loss in a production pipeline. \
false for feature additions, docs, refactors, or minor fixes. true/false>,

  "severity": "<none | low | medium | high | critical. \
'critical' = data corruption or silent wrong results in prod. \
'high' = dbt run crash or test false-negatives masking data issues. \
'medium' = broken edge case or unexpected behaviour requiring workaround. \
'low' = cosmetic or minor fix. 'none' = no functional change.>",

  "tags": [
    "<One or more of: breaking | bug-fix | new-test | macro-change | \
dbt-compatibility | sql-fix | feature | deprecation | docs-only>"
  ]
}}

Rules:
- is_prod_breaking_bug must be true ONLY if a team running this in prod today would be affected
- key_changes must be empty array if release is docs/contributor/formatting only
- Do not mention migration guides for versions older than the last major release
- Return valid JSON only — no markdown fences, no commentary
"""
