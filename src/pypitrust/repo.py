# this_file: src/pypitrust/repo.py
"""Parse a GitHub repo spec into a validated `Repo` and read its PyPI project name."""

from __future__ import annotations

import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

_NAME = r"[A-Za-z0-9_.-]+"
_URL = re.compile(
    rf"(?:https?://|git@)github\.com[/:]({_NAME})/({_NAME}?)(?:\.git)?/?$"
)
_SLUG = re.compile(rf"^({_NAME})/({_NAME})$")


class RepoError(ValueError):
    """Raised when a repo spec cannot be resolved."""


@dataclass(frozen=True)
class Repo:
    """A GitHub repository, identified by owner and name."""

    owner: str
    name: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


def parse_repo(spec: str) -> Repo:
    """Turn `owner/name`, a GitHub URL, or a local clone path into a `Repo`."""
    spec = spec.strip()
    if m := _URL.match(spec):
        return Repo(m[1], m[2])
    path = Path(spec).expanduser()
    if path.is_dir():
        return parse_repo(_origin_url(path))
    if m := _SLUG.match(spec):
        return Repo(m[1], m[2])
    raise RepoError(f"Not a GitHub repo, URL, or local clone: {spec!r}")


def _origin_url(path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RepoError(f"{path} has no 'origin' remote: {result.stderr.strip()}")
    return result.stdout.strip()


def project_name(pyproject_text: str) -> str:
    """Return `[project].name` from pyproject.toml text, normalised per PEP 503."""
    data = tomllib.loads(pyproject_text)
    name = data.get("project", {}).get("name")
    if not name:
        raise RepoError("pyproject.toml has no [project].name")
    return re.sub(r"[-_.]+", "-", name).lower()
