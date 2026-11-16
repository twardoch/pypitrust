# this_file: src/pypitrust/batch.py
"""Run `setup` over a list of repos, resumably.

The input file has one job per line: ``REPO [PACKAGE] [WORKFLOW]`` where REPO is
a GitHub URL or owner/name; ``#`` starts a comment. Each job runs a fixed
pipeline of steps; every step's outcome goes to a JSON status file (written
atomically), so a rerun skips finished steps. A PyPI rate limit (HTTP 429)
pauses the whole batch and records when to resume.
"""

from __future__ import annotations

import dataclasses
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import github, pypi
from .config import Settings
from .render import render
from .repo import Repo, parse_repo, project_name

STEPS = ("package", "github_env", "workflow", "pypi_publisher")
DONE, FAILED, PENDING = "done", "failed", "pending"


@dataclass(frozen=True)
class Job:
    """One line of the input file."""

    repo: Repo
    package: str | None = None
    workflow: str = "release.yml"

    @property
    def key(self) -> str:
        return f"{self.repo.slug}|{self.package or '*'}|{self.workflow}"


@dataclass(frozen=True)
class Options:
    """Per-run switches; everything configurable lives in `settings`."""

    settings: Settings = field(default_factory=Settings)
    skip_workflow: bool = True
    skip_pypi: bool = False
    retry_failed: bool = False


def parse_jobs(text: str, default_workflow: str = "release.yml") -> list[Job]:
    """Parse the input file; raise ValueError naming the bad line."""
    jobs = []
    for n, raw in enumerate(text.splitlines(), 1):
        parts = raw.split("#", 1)[0].split()
        if not parts:
            continue
        if len(parts) > 3:
            raise ValueError(f"line {n}: expected 'REPO [PACKAGE] [WORKFLOW]': {raw!r}")
        try:
            repo = parse_repo(parts[0])
        except ValueError as e:
            raise ValueError(f"line {n}: {e}") from e
        package = parts[1] if len(parts) > 1 and parts[1] != "-" else None
        jobs.append(
            Job(repo, package, parts[2] if len(parts) > 2 else default_workflow)
        )
    return jobs


@dataclass
class Status:
    """The status file: per job, per step: {state, at, msg}; plus a pause marker."""

    path: Path
    jobs: dict[str, dict] = field(default_factory=dict)
    paused_until: str | None = None

    @classmethod
    def load(cls, path: Path) -> Status:
        if not path.exists():
            return cls(path)
        data = json.loads(path.read_text())
        return cls(path, data.get("jobs", {}), data.get("paused_until"))

    def save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        data = {"version": 1, "paused_until": self.paused_until, "jobs": self.jobs}
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
        os.replace(tmp, self.path)

    def step(self, job: Job, name: str) -> dict:
        return self.jobs.get(job.key, {}).get("steps", {}).get(name, {})

    def record(self, job: Job, name: str, state: str, msg: str, **extra) -> None:
        entry = self.jobs.setdefault(job.key, {"steps": {}})
        entry.update(extra)
        entry["steps"][name] = {"state": state, "at": _now(), "msg": msg}
        self.save()

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.jobs.values():
            steps = list(entry["steps"].values())
            states = [s["state"] for s in steps]
            only_skips = all(
                s["msg"].startswith("skipped") for s in steps if s["state"] == PENDING
            )
            if FAILED in states:
                overall = FAILED
            elif PENDING not in states:
                overall = DONE
            else:
                overall = "done with skips" if only_skips else PENDING
            counts[overall] = counts.get(overall, 0) + 1
        return counts


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def paused(status: Status) -> datetime | None:
    """When the batch may resume, if a 429 pause is still in force."""
    if not status.paused_until:
        return None
    until = datetime.fromisoformat(status.paused_until)
    return until if until > datetime.now(UTC) else None


def run(
    jobs: list[Job],
    status: Status,
    opts: Options,
    report: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run every job's pending steps. Returns 0, 1 (some failed) or 75 (paused)."""
    if until := paused(status):
        report(
            f"Paused by a PyPI rate limit until {until:%H:%M} UTC; rerun after that."
        )
        return pypi.EXIT_RATE_LIMITED
    status.paused_until = None
    last_pypi = 0.0
    for job in jobs:
        report(f"{job.repo.slug} [{job.package or 'from pyproject'} @ {job.workflow}]")
        package = job.package or status.jobs.get(job.key, {}).get("package")
        for name in STEPS:
            prev = status.step(job, name)
            if prev.get("state") == DONE:
                report(f"  = {name}: done earlier")
                continue
            if prev.get("state") == FAILED and not opts.retry_failed:
                report(
                    f"  ✗ {name}: failed earlier ({prev['msg']}); use --retry_failed"
                )
                break
            if name == "pypi_publisher" and not opts.skip_pypi:
                wait = opts.settings.delay - (time.monotonic() - last_pypi)
                if last_pypi and wait > 0:
                    sleep(wait)
                last_pypi = time.monotonic()
            try:
                msg, package = _do(name, job, package, opts)
            except pypi.RateLimited as e:
                status.record(job, name, PENDING, str(e))
                until = datetime.now(UTC) + timedelta(seconds=opts.settings.cooldown)
                status.paused_until = until.isoformat(timespec="seconds")
                status.save()
                report(
                    f"  ⏸ {e}\nPaused until {until:%H:%M} UTC; rerun the same command then."
                )
                return pypi.EXIT_RATE_LIMITED
            except Exception as e:  # noqa: BLE001 - one job must not stop the batch
                status.record(job, name, FAILED, f"{type(e).__name__}: {e}"[:500])
                report(f"  ✗ {name}: {e}")
                break
            # A skipped step stays pending, so a later full run still does it.
            state = PENDING if msg.startswith("skipped") else DONE
            status.record(job, name, state, msg, package=package)
            report(f"  • {name}: {msg}")
    counts = status.summary()
    report("Summary: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    return 1 if counts.get(FAILED) else 0


def _do(
    name: str, job: Job, package: str | None, opts: Options
) -> tuple[str, str | None]:
    """Run one step; return (message, package name)."""
    if name == "package":
        if package:
            return package, package
        text = github.read_file(job.repo, "pyproject.toml")
        if text is None:
            raise RuntimeError("no pyproject.toml on the default branch; give PACKAGE")
        found = project_name(text)
        return found, found
    assert package, "package step runs first"
    if name == "github_env":
        return github.ensure_environment(
            job.repo, opts.settings.environment, False
        ), package
    if name == "workflow":
        if opts.skip_workflow:
            return "skipped (committed from a local clone)", package
        settings = dataclasses.replace(opts.settings, workflow=job.workflow)
        content = render("release.yml.tmpl", package, settings)
        return github.ensure_workflow(job.repo, job.workflow, content, False), package
    if opts.skip_pypi:
        return "skipped (--skip_pypi)", package
    pub = pypi.Publisher(
        package,
        job.repo.owner,
        job.repo.name,
        job.workflow,
        opts.settings.environment,
        opts.settings.test_pypi,
    )
    return pypi.register(pub, opts.settings), package
