from __future__ import annotations

import json
import logging

from groq import Groq
from pydantic import BaseModel, ValidationError

from src.config import GROQ_MODEL, GROQ_TIMEOUT_S, LLM_MAX_TOKENS
from src.prompts.release_analysis import RELEASE_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)


class AnalysisResult(BaseModel):
    summary: str
    key_changes: list[str]
    cve_references: list[str]
    severity: str
    tags: list[str]


def analyse_release(
    release: dict[str, object], api_key: str
) -> tuple[dict[str, object] | None, str | None]:
    repo = str(release.get("repo", ""))
    tag = str(release.get("tag_name", ""))
    name = str(release.get("name", tag))
    body = str(release.get("body", ""))[:4000]

    prompt = RELEASE_ANALYSIS_PROMPT.format(repo=repo, tag=tag, name=name, body=body)

    try:
        client = Groq(api_key=api_key, timeout=float(GROQ_TIMEOUT_S))
        response = client.chat.completions.create(
            model=GROQ_MODEL,
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
        logger.error("Groq response failed validation for %s@%s: %s", repo, tag, e)
        return None, str(e)
    except Exception as e:
        logger.error("Groq call failed for %s@%s: %s", repo, tag, e)
        return None, str(e)
