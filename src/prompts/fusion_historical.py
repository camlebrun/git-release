FUSION_HISTORICAL_PROMPT = """\
You are a principal software engineer writing a historical snapshot of dbt-fusion \
for a tech lead audience.

dbt-fusion is a Rust rewrite of dbt-core by dbt Labs, currently in preview.
This entry covers the entire pre-2026 development period (beta + early previews).

Versions in this period ({version_count} releases, {first_version} → {last_version}):
{version_list}

Sample changelog entries from this period:
---
{body_sample}
---

Write a concise historical snapshot that covers:
- What dbt-fusion set out to do (the rewrite rationale)
- The major capabilities shipped during this period (adapters, commands, key features)
- The state of the product at the end of 2025 / entry into 2026

Return ONLY a valid JSON object with this exact schema:

{{
  "worth_tracking": true,

  "summary": "<4-6 sentences. Historical arc: why fusion exists, what was built, \
where it stood at end of 2025. Write for an engineer deciding whether to evaluate fusion.>",

  "key_changes": [
    "<Major capability shipped during this period. Format: '[Area] What was built.' \
Include: adapters added, commands shipped, key architectural decisions. Max 8 items.>"
  ],

  "breaking_changes": [],
  "migration_notes": "",
  "cve_references": [],
  "severity": "none",
  "tags": ["feature"]
}}

Return valid JSON only — no markdown fences, no commentary.
"""
