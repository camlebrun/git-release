from __future__ import annotations

import json
import logging
import time

import requests
from mistralai.client import Mistral
from pydantic import BaseModel, ValidationError

from src.config import (
    GEMINI_BASE_URL,
    GEMINI_MODEL,
    GROQ_BASE_URL,
    GROQ_MODEL,
    GROQ_TIMEOUT_S,
    LLM_MAX_TOKENS,
    MISTRAL_MODEL,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)
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


def _call_gemini(prompt: str, api_key: str, retries: int = 5) -> str:
    url = f"{GEMINI_BASE_URL}/{GEMINI_MODEL}:generateContent"
    for attempt in range(retries):
        resp = requests.post(
            url,
            headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "maxOutputTokens": LLM_MAX_TOKENS,
                    "temperature": 0,
                },
            },
            timeout=30,
        )
        if resp.status_code == 429:
            wait = 4 * (2**attempt)  # 4s, 8s, 16s, 32s, 64s
            logger.warning("Gemini 429 — wait %ss (attempt %s/%s)", wait, attempt + 1, retries)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return str(resp.json()["candidates"][0]["content"]["parts"][0]["text"])
    raise RuntimeError(f"Gemini 429 after {retries} retries")


class AuthError(Exception):
    """Raised on 401 — invalid API key, must stop the pipeline."""


def _call_openai_compat(
    prompt: str, api_key: str, base_url: str, model: str, timeout: float
) -> str:
    from openai import AuthenticationError, OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=LLM_MAX_TOKENS,
        )
    except AuthenticationError as e:
        raise AuthError(f"Invalid API key — update your key and restart: {e}") from e
    return response.choices[0].message.content or ""


def _call_groq(prompt: str, api_key: str) -> str:
    return _call_openai_compat(prompt, api_key, GROQ_BASE_URL, GROQ_MODEL, float(GROQ_TIMEOUT_S))


def _call_openai(prompt: str, api_key: str) -> str:
    return _call_openai_compat(prompt, api_key, OPENAI_BASE_URL, OPENAI_MODEL, 30.0)


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


def analyse_release(
    release: dict[str, object],
    api_key: str,
    provider: str = "groq",
) -> tuple[dict[str, object] | None, str | None]:
    repo = str(release.get("repo", ""))
    tag = str(release.get("tag_name", ""))
    name = str(release.get("name", tag))
    body = str(release.get("body", ""))[:4000]

    prompt = RELEASE_ANALYSIS_PROMPT.format(repo=repo, tag=tag, name=name, body=body)

    try:
        if provider == "gemini":
            raw = _call_gemini(prompt, api_key)
        elif provider == "openai":
            raw = _call_openai(prompt, api_key)
        elif provider == "mistral":
            raw = _call_mistral(prompt, api_key)
        else:
            raw = _call_groq(prompt, api_key)

        data = json.loads(raw)
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
    provider: str = "mistral",
) -> tuple[dict[str, object] | None, str | None]:
    """Analyse a dbt package release.

    stale=True: repo has no release in >1 year — skip LLM, return README summary only.
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
        if provider == "mistral":
            raw = _call_mistral(prompt, api_key)
        elif provider == "openai":
            raw = _call_openai(prompt, api_key)
        elif provider == "gemini":
            raw = _call_gemini(prompt, api_key)
        else:
            raw = _call_groq(prompt, api_key)

        data = json.loads(raw)
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
