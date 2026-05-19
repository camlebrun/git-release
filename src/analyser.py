from __future__ import annotations

import json
import logging

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from src.config import (
    GEMINI_BASE_URL,
    GEMINI_MODEL,
    GROQ_BASE_URL,
    GROQ_MODEL,
    GROQ_TIMEOUT_S,
    LLM_MAX_TOKENS,
)
from src.prompts.release_analysis import RELEASE_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)


class AnalysisResult(BaseModel):
    summary: str
    key_changes: list[str]
    cve_references: list[str]
    severity: str
    tags: list[str]


def _build_client(provider: str, api_key: str) -> tuple[OpenAI, str]:
    if provider == "gemini":
        return OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL, timeout=30.0), GEMINI_MODEL
    # default: groq
    return OpenAI(api_key=api_key, base_url=GROQ_BASE_URL, timeout=float(GROQ_TIMEOUT_S)), GROQ_MODEL


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
        client, model = _build_client(provider, api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=LLM_MAX_TOKENS,
        )
        raw = response.choices[0].message.content or ""
        data = json.loads(raw)
        result = AnalysisResult(**data)
        return result.model_dump(), None
    except ValidationError as e:
        logger.error("LLM response failed validation for %s@%s: %s", repo, tag, e)
        return None, str(e)
    except Exception as e:
        logger.error("LLM call failed for %s@%s: %s", repo, tag, e)
        return None, str(e)
