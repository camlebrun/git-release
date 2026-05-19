from __future__ import annotations

import json
import logging
import time

import requests
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from src.config import (
    GEMINI_BASE_URL,
    GEMINI_MODEL,
    GROQ_BASE_URL,
    GROQ_MODEL,
    GROQ_TIMEOUT_S,
    LLM_MAX_TOKENS,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)
from src.prompts.release_analysis import RELEASE_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)


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
    from openai import AuthenticationError

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
