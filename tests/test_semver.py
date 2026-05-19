import pytest

from src.semver import parse_semver


@pytest.mark.parametrize(
    "tag,major,minor,patch",
    [
        ("v12.3.1", 12, 3, 1),
        ("v12.3.1-rc2", 12, 3, 1),
        ("v2.0.0-beta.1", 2, 0, 0),
        ("1.0.0", 1, 0, 0),
        ("0.9.5", 0, 9, 5),
    ],
)
def test_valid_semver(tag: str, major: int, minor: int, patch: int) -> None:
    sv = parse_semver(tag)
    assert sv.valid is True
    assert sv.major == major
    assert sv.minor == minor
    assert sv.patch == patch


@pytest.mark.parametrize("tag", ["20240501", "main", "nightly", "latest", ""])
def test_invalid_semver(tag: str) -> None:
    sv = parse_semver(tag)
    assert sv.valid is False
