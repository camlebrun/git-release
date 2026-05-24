FUSION_RELEASE_ANALYSIS_PROMPT = """\
You are a principal software engineer reviewing a dbt-fusion preview release for a tech lead audience.
dbt-fusion is a Rust rewrite of dbt-core, currently in preview. It ships weekly preview builds.

Repository: {repo}
Tag: {tag}

Release notes (markdown):
---
{body}
---

Determine if this release is worth tracking — it qualifies if it contains at least one of:
- A significant new feature (new adapter support, new command, new config capability, major UX change)
- A prod-breaking bug fix (incorrect results, crash, data loss, state:modified false positive, manifest regression)

Releases that are NOT worth tracking: internal refactors, CI changes, documentation, \
dependency bumps, code reorganisation, minor type-system changes with no user impact.

Return ONLY a valid JSON object with this exact schema:

{{
  "worth_tracking": <true if qualifies by the criteria above, false otherwise>,

  "summary": "<3-4 sentences. What changed, why it matters to a dbt user evaluating fusion. \
Skip internal details. If worth_tracking is false, one sentence is enough.>",

  "key_changes": [
    "<Specific, technical. Format: '[Component] What changed and why it matters.' \
Only user-facing changes. Max 6 items. Empty array if worth_tracking is false.>"
  ],

  "breaking_changes": [
    "<Changes requiring action from consumers. Empty array if none.>"
  ],

  "migration_notes": "<Concrete migration steps if breaking_changes non-empty, else empty string.>",

  "cve_references": [],

  "severity": "<none | low | medium | high | critical — based on CVEs, breaking changes, data-loss risk.>",

  "tags": [
    "<ONLY use values from this exact list — no others allowed: \
breaking | security | performance | bug-fix | feature | new-capability | \
deprecation | schema-change | config-change | dependency-update | refactor. \
Use 'new-capability' for significant new features (new adapter, new command, major UX change). \
Use 'feature' for minor additions. Max 4 tags. No free-form values.>"
  ]
}}

Return valid JSON only — no markdown fences, no commentary.
"""
