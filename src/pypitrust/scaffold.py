# this_file: src/pypitrust/scaffold.py
"""Apply the release setup (workflow, build.sh, publish.sh, .gitignore) to a local clone."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

from .config import Settings
from .render import render, template

UPLOAD_WORKFLOW = ".github/workflows/pypi-upload.yml"
PUBLISH_MARKERS = re.compile(
    r"gh-action-pypi-publish|twine upload|uv publish|PYPI_TOKEN|PYPI_API_TOKEN"
)


def version_file(pyproject_text: str) -> str | None:
    """Path of the hatch-vcs generated version file, if the build hook is configured."""
    data = tomllib.loads(pyproject_text)
    hook = data.get("tool", {}).get("hatch", {}).get("build", {}).get("hooks", {})
    return hook.get("vcs", {}).get("version-file")


def workflow_path(settings: Settings) -> str:
    return f".github/workflows/{settings.workflow}"


def write(root: Path, rel: str, content: str, overwrite: bool) -> str:
    """Write a file unless it is unchanged (or exists and overwrite is False)."""
    path = root / rel
    if path.exists() and (not overwrite or path.read_text() == content):
        return f"{rel} kept"
    verb = "replaced" if path.exists() else "created"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if rel.endswith(".sh"):
        path.chmod(0o755)
    return f"{rel} {verb}"


def ensure_ignored(root: Path, rel: str) -> list[str]:
    """Add rel to .gitignore if git doesn't ignore it yet; untrack it if tracked."""
    msgs = []
    if _git(root, "check-ignore", "-q", "--no-index", rel).returncode != 0:
        gi = root / ".gitignore"
        text = gi.read_text() if gi.exists() else ""
        gi.write_text(
            text + ("" if text.endswith("\n") or not text else "\n") + f"{rel}\n"
        )
        msgs.append(f".gitignore += {rel}")
    if _git(root, "ls-files", "--error-unmatch", rel).returncode == 0:
        _git(root, "rm", "--cached", "-q", rel)
        msgs.append(f"untracked {rel}")
    return msgs


def other_publishers(root: Path, workflow: str = "release.yml") -> list[str]:
    """Workflows other than ours that also upload to PyPI."""
    wf = root / ".github" / "workflows"
    hits = [
        p.relative_to(root).as_posix()
        for p in sorted(wf.glob("*.y*ml"))
        if p.name not in (workflow, "pypi-upload.yml")
        and PUBLISH_MARKERS.search(p.read_text())
    ]
    return [f"WARNING: {h} also publishes to PyPI" for h in hits]


def upgrade(root: Path, package: str, settings: Settings | None = None) -> list[str]:
    """Write the release workflow, publish.sh and build.sh, and fix .gitignore.

    The workflow and publish.sh are replaced; build.sh is only added when missing.
    Returns one message per action.
    """
    s = settings or Settings()
    msgs = [
        write(root, workflow_path(s), render("release.yml.tmpl", package, s), True),
        write(root, "publish.sh", render("publish.sh.tmpl", package, s), True),
        write(root, "build.sh", render("build.sh.tmpl", package, s), False),
    ]
    vfile = version_file((root / "pyproject.toml").read_text())
    if vfile:
        msgs += ensure_ignored(root, vfile)
    else:
        msgs.append(
            "WARNING: no [tool.hatch.build.hooks.vcs] version-file in pyproject.toml"
        )
    return msgs + other_publishers(root, s.workflow)


def add_upload_helper(root: Path) -> list[str]:
    """Add scripts/pypi-upload.sh + pypi-upload.yml for repos that build wheels locally.

    The script stages files on a draft GitHub release and dispatches the workflow,
    which uploads them through Trusted Publishing. Register the PyPI publisher
    with workflow pypi-upload.yml.
    """
    return [
        write(root, UPLOAD_WORKFLOW, template("pypi-upload.yml.tmpl"), True),
        write(root, "scripts/pypi-upload.sh", template("pypi-upload.sh.tmpl"), True),
    ]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
