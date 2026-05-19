from typing import TypedDict


class Analysis(TypedDict):
    summary: str
    key_changes: list[str]
    cve_references: list[str]
    severity: str
    tags: list[str]


class ReleaseRecord(TypedDict):
    id: int
    repo: str
    tag: str
    name: str
    body: str
    published_at: str
    html_url: str
    author: str
    prerelease: bool
    draft: bool
    fetched_at: str
    analysis: Analysis | None
    analysis_error: str | None


class CursorRecord(TypedDict):
    published_at: str
    updated_at: str


class RunStatus(TypedDict):
    ran_at: str
    repos: dict[str, dict[str, object]]
