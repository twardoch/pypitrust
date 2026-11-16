# this_file: src/pypitrust/github.py
"""GitHub side of Trusted Publishing, done through the authenticated `gh` CLI."""

from __future__ import annotations

import base64
import json
import subprocess

from loguru import logger

from .repo import Repo


class GhError(RuntimeError):
    """Raised when a `gh` call fails."""


def gh_api(path: str, *args: str, input_json: dict | None = None) -> dict | None:
    """Call `gh api`; return parsed JSON, or None on HTTP 404."""
    cmd = ["gh", "api", path, *args]
    payload = json.dumps(input_json) if input_json is not None else None
    if payload is not None:
        cmd += ["--input", "-"]
    logger.debug("$ {}", " ".join(cmd))
    res = subprocess.run(
        cmd, input=payload, capture_output=True, text=True, check=False
    )
    if res.returncode != 0:
        if "HTTP 404" in res.stderr or '"status":"404"' in res.stdout:
            return None
        raise GhError(
            f"gh api {path} failed: {res.stderr.strip() or res.stdout.strip()}"
        )
    return json.loads(res.stdout) if res.stdout.strip() else {}


def read_file(repo: Repo, path: str) -> str | None:
    """Return a file's text from the default branch, or None if absent."""
    data = gh_api(f"repos/{repo.slug}/contents/{path}")
    if data is None:
        return None
    return base64.b64decode(data["content"]).decode()


def ensure_environment(repo: Repo, environment: str, dry_run: bool) -> str:
    """Create the deployment environment the workflow publishes from."""
    if gh_api(f"repos/{repo.slug}/environments/{environment}") is not None:
        return f"environment '{environment}' exists"
    if gh_api(f"repos/{repo.slug}") is None:
        raise GhError(f"GitHub repo {repo.slug} not found (or no access)")
    if not dry_run and (
        gh_api(f"repos/{repo.slug}/environments/{environment}", "-X", "PUT") is None
    ):
        raise GhError(f"could not create environment '{environment}' on {repo.slug}")
    return f"environment '{environment}' created"


def ensure_workflow(repo: Repo, filename: str, content: str, dry_run: bool) -> str:
    """Commit the workflow unless one with that name exists (never overwrites)."""
    path = f".github/workflows/{filename}"
    existing = read_file(repo, path)
    if existing is not None:
        if "id-token: write" not in existing:
            return f"WARNING: {path} exists but lacks 'id-token: write'; Trusted Publishing will fail"
        return f"workflow {path} exists"
    if not dry_run:
        body = {
            "message": f"ci: add {filename} for PyPI Trusted Publishing",
            "content": base64.b64encode(content.encode()).decode(),
        }
        gh_api(f"repos/{repo.slug}/contents/{path}", "-X", "PUT", input_json=body)
    return f"workflow {path} committed"
