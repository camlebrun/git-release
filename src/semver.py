from __future__ import annotations

import re
from dataclasses import dataclass

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


@dataclass
class SemVer:
    major: int
    minor: int
    patch: int
    valid: bool

    @classmethod
    def invalid(cls) -> "SemVer":
        return cls(major=0, minor=0, patch=0, valid=False)


def parse_semver(tag: str) -> SemVer:
    m = _SEMVER_RE.match(tag)
    if not m:
        return SemVer.invalid()
    return SemVer(
        major=int(m.group(1)),
        minor=int(m.group(2)),
        patch=int(m.group(3)),
        valid=True,
    )
