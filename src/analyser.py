from __future__ import annotations

import json
import logging

from mistralai.client import Mistral
from pydantic import BaseModel, ValidationError

from src.config import LLM_MAX_TOKENS, MISTRAL_MODEL
from src.prompts.dbt_package_analysis import DBT_PACKAGE_ANALYSIS_PROMPT
from src.prompts.release_analysis import RELEASE_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)


class DbtPackageAnalysisResult(BaseModel):
    purpose: str
    summary: str
    key_changes: list[str] = []
    is_prod_breaking_bug: bool
    severity: str
    tags: list[str]


class AnalysisResult(BaseModel):
    summary: str
    key_changes: list[str]
    breaking_changes: list[str] = []
    migration_notes: str = ""
    cve_references: list[str] = []
    severity: str
    tags: list[str]


class AuthError(Exception):
    """Raised on 401 — invalid API key, stops the pipeline."""


def _call_mistral(prompt: str, api_key: str) -> str:
    client = Mistral(api_key=api_key)
    response = client.chat.complete(
        model=MISTRAL_MODEL,
        messages=[{"role": "user", "content": prompt}],  # type: ignore[arg-type]
        temperature=0,
        max_tokens=LLM_MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    msg = response.choices[0].message
    return str(msg.content) if msg and msg.content else ""


def call_llm(prompt: str, api_key: str) -> str:
    """Public entry point — calls the configured LLM and returns a raw JSON string."""
    return _call_mistral(prompt, api_key)


def analyse_release(
    release: dict[str, object],
    api_key: str,
) -> tuple[dict[str, object] | None, str | None]:
    repo = str(release.get("repo", ""))
    tag = str(release.get("tag_name", ""))
    name = str(release.get("name", tag))
    body = str(release.get("body", ""))[:4000]

    prompt = RELEASE_ANALYSIS_PROMPT.format(repo=repo, tag=tag, name=name, body=body)
    try:
        data = json.loads(_call_mistral(prompt, api_key))
        result = AnalysisResult(**data)
        return result.model_dump(), None
    except ValidationError as e:
        logger.error("LLM response failed validation for %s@%s: %s", repo, tag, e)
        return None, str(e)
    except Exception as e:
        logger.error("LLM call failed for %s@%s: %s", repo, tag, e)
        return None, str(e)


def analyse_dbt_package_release(
    release: dict[str, object],
    readme: str,
    stale: bool = False,
    use_heuristics: bool = False,
    api_key: str = "",
) -> tuple[dict[str, object] | None, str | None]:
    """Analyse a dbt package release.

    stale=True: no release in >1 year — skip LLM, return README summary only.
    use_heuristics=True: rule-based analysis, no LLM call (for testing).
    """
    from src.fetcher import filter_trivial_changes, heuristic_dbt_analysis

    repo = str(release.get("repo", ""))
    tag = str(release.get("tag_name", ""))
    name = str(release.get("name", tag))
    body = str(release.get("body", ""))[:4000]

    if stale:
        purpose = ""
        for para in readme.split("\n\n"):
            clean = para.strip().lstrip("#").strip()
            if len(clean) > 40 and not clean.startswith("!"):
                purpose = clean[:300]
                break
        return {
            "purpose": purpose or f"{repo} dbt package.",
            "summary": f"No release in over a year. Last tag: {tag}.",
            "key_changes": [],
            "is_prod_breaking_bug": False,
            "severity": "none",
            "tags": ["docs-only"],
        }, None

    if use_heuristics:
        result = heuristic_dbt_analysis(release, readme)
        kc = result.get("key_changes", [])
        result["key_changes"] = filter_trivial_changes(kc if isinstance(kc, list) else [])
        return result, None

    prompt = DBT_PACKAGE_ANALYSIS_PROMPT.format(
        repo=repo, tag=tag, name=name, readme=readme[:2000], body=body
    )
    try:
        data = json.loads(_call_mistral(prompt, api_key))
        raw_kc = data.get("key_changes", [])
        data["key_changes"] = filter_trivial_changes(raw_kc if isinstance(raw_kc, list) else [])
        result_obj = DbtPackageAnalysisResult(**data)
        return result_obj.model_dump(), None
    except ValidationError as e:
        logger.error("LLM dbt validation failed for %s@%s: %s", repo, tag, e)
        return None, str(e)
    except Exception as e:
        logger.error("LLM dbt call failed for %s@%s: %s", repo, tag, e)
        return None, str(e)
