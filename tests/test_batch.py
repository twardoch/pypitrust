# this_file: tests/test_batch.py
import json

import pytest

from pypitrust import batch, pypi
from pypitrust.config import Settings

LIST = """
# comment line
https://github.com/octo/alpha          # package from pyproject
octo/beta beta pypi-upload.yml
acme/gamma -  pypi-upload.yml
"""


def test_parse_jobs_when_urls_slugs_and_comments_then_jobs():
    jobs = batch.parse_jobs(LIST)
    assert [j.repo.slug for j in jobs] == [
        "octo/alpha",
        "octo/beta",
        "acme/gamma",
    ]
    assert jobs[0].package is None and jobs[0].workflow == "release.yml"
    assert jobs[1].package == "beta" and jobs[1].workflow == "pypi-upload.yml"
    assert jobs[2].package is None, "'-' means read the package from pyproject"


def test_parse_jobs_when_bad_line_then_error_names_line():
    with pytest.raises(ValueError, match="line 2"):
        batch.parse_jobs("octo/alpha\nnot a repo at all really\n")


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def do(name, job, package, opts):
        calls.append((job.repo.name, name))
        if job.repo.name == "broken" and name == "github_env":
            raise RuntimeError("gh says no")
        if job.repo.name == "limited" and name == "pypi_publisher":
            raise pypi.RateLimited("429 Too Many Requests")
        return f"{name} ok", package or job.repo.name

    monkeypatch.setattr(batch, "_do", do)
    return calls


def _run(tmp_path, text, settings=None, **kw):
    settings = settings or {}
    status = batch.Status.load(tmp_path / "s.json")
    code = batch.run(
        batch.parse_jobs(text),
        status,
        batch.Options(Settings(delay=0, **settings), **kw),
        report=lambda m: None,
        sleep=lambda s: None,
    )
    return code, status


def test_run_when_rerun_then_done_steps_skipped(tmp_path, fake):
    code, _ = _run(tmp_path, "a/one\na/two\n")
    assert code == 0 and len(fake) == 8
    fake.clear()
    code, _ = _run(tmp_path, "a/one\na/two\na/three\n")
    assert code == 0
    assert fake == [("three", s) for s in batch.STEPS], "only the new job should run"
    saved = json.loads((tmp_path / "s.json").read_text())
    assert saved["jobs"]["a/one|*|release.yml"]["package"] == "one"


def test_run_when_step_fails_then_job_stops_batch_continues(tmp_path, fake):
    code, _ = _run(tmp_path, "a/broken\na/fine\n")
    assert code == 1
    assert ("broken", "workflow") not in fake, "a failed job must not run later steps"
    assert ("fine", "pypi_publisher") in fake
    fake.clear()
    _run(tmp_path, "a/broken\na/fine\n")
    assert fake == [], "failed steps stay failed without --retry_failed"
    _run(tmp_path, "a/broken\na/fine\n", retry_failed=True)
    assert ("broken", "github_env") in fake


def test_run_when_rate_limited_then_pauses_and_refuses_until_cooldown(tmp_path, fake):
    code, status = _run(tmp_path, "a/limited\na/later\n")
    assert code == pypi.EXIT_RATE_LIMITED
    assert ("later", "package") not in fake, "a 429 stops the whole batch"
    assert (
        status.step(batch.parse_jobs("a/limited")[0], "pypi_publisher")["state"]
        == batch.PENDING
    )
    fake.clear()
    code, _ = _run(tmp_path, "a/limited\na/later\n")
    assert code == pypi.EXIT_RATE_LIMITED and fake == [], "still paused: nothing runs"


def test_run_when_cooldown_passed_then_resumes(tmp_path, fake):
    _run(tmp_path, "a/limited\na/later\n", settings={"cooldown": 0})
    fake.clear()
    _run(tmp_path, "a/limited\na/later\n", settings={"cooldown": 0})
    assert ("limited", "pypi_publisher") in fake and ("limited", "package") not in fake


def test_run_when_step_skipped_then_stays_pending_and_runs_later(tmp_path, monkeypatch):
    calls = []

    def do(name, job, package, opts):
        calls.append(name)
        skip = name == "pypi_publisher" and opts.skip_pypi
        return ("skipped (--skip_pypi)" if skip else "ok"), "pkg"

    monkeypatch.setattr(batch, "_do", do)
    _run(tmp_path, "a/one\n", skip_pypi=True)
    calls.clear()
    _run(tmp_path, "a/one\n")
    assert calls == ["pypi_publisher"], "a skipped step must run on the next full run"
