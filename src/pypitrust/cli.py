# this_file: src/pypitrust/cli.py
"""Command line: `pypitrust setup|upgrade|upload-helper|workflow|config`.

Every option that has a setting (see `config.Settings`) defaults to None here,
meaning "use the config file, else the built-in default".
"""

from __future__ import annotations

import sys
from pathlib import Path

import fire
from loguru import logger
from rich.console import Console

from . import __version__, batch, github, pypi, scaffold
from . import config as _config
from .render import render
from .repo import Repo, parse_repo, project_name

console = Console()


def _configure_logging(verbose: bool) -> None:
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "WARNING")


def _settings(config_path: str | None, **overrides) -> _config.Settings:
    try:
        return _config.load(config_path).merged(**overrides)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(f"pypitrust: {exc}") from exc


def _step(msg: str) -> None:
    style = "yellow" if msg.startswith(("WARNING", "would")) else "green"
    console.print(f"  [{style}]•[/] {msg}")


def _package_from_repo(ref: Repo) -> str:
    text = github.read_file(ref, "pyproject.toml")
    if text is None:
        raise SystemExit(
            f"{ref.slug} has no pyproject.toml on its default branch; pass --package"
        )
    return project_name(text)


def setup(
    repo: str,
    package: str | None = None,
    workflow: str | None = None,
    environment: str | None = None,
    test_pypi: bool | None = None,
    profile: str | None = None,
    debug_port: int | None = None,
    delay: float | None = None,
    cooldown: float | None = None,
    config: str | None = None,
    dry_run: bool = False,
    skip_pypi: bool = False,
    skip_workflow: bool = False,
    retry_failed: bool = False,
    status: str | None = None,
    verbose: bool = False,
) -> None:
    """Set up GitHub (environment + release workflow) and PyPI (trusted publisher).

    REPO is owner/name, a GitHub URL, a local clone, or a text file listing one job
    per line (`REPO [PACKAGE|-] [WORKFLOW]`, `#` comments). A list runs every job
    as a resumable pipeline whose progress is kept in a status file.

    Args:
        repo: owner/name, GitHub URL, local clone path, or list file.
        package: PyPI project name (single repo); default: the repo's pyproject.toml.
        workflow: workflow filename registered with PyPI.
        environment: GitHub environment the workflow publishes from.
        test_pypi: target test.pypi.org instead of pypi.org.
        profile: playwrightauthor browser profile (keeps your PyPI login).
        debug_port: CDP port for playwrightauthor's Chrome.
        delay: list run: seconds between PyPI registrations.
        cooldown: list run: seconds to pause after PyPI answers 429.
        config: config file (default: see `pypitrust config`).
        dry_run: single repo: report what would change, change nothing.
        skip_pypi: only do the GitHub side.
        skip_workflow: don't commit the workflow through the GitHub API (use
            `upgrade` on a local clone instead).
        retry_failed: list run: retry steps that failed before.
        status: list run: status file (default `<list>.status.json`).
        verbose: debug logging.
    """
    _configure_logging(verbose)
    s = _settings(
        config,
        workflow=workflow,
        environment=environment,
        test_pypi=test_pypi,
        profile=profile,
        debug_port=debug_port,
        delay=delay,
        cooldown=cooldown,
    )
    listing = Path(repo).expanduser()
    if listing.is_file():
        _setup_list(
            listing,
            s,
            status,
            skip_workflow,
            skip_pypi,
            retry_failed,
            single_only=dry_run or bool(package),
        )
    else:
        _setup_one(parse_repo(repo), package, s, dry_run, skip_workflow, skip_pypi)


def _setup_list(
    listing: Path,
    s: _config.Settings,
    status: str | None,
    skip_workflow: bool,
    skip_pypi: bool,
    retry_failed: bool,
    single_only: bool,
) -> None:
    if single_only:
        raise SystemExit("--dry_run and --package apply to a single repo, not a list")
    try:
        jobs = batch.parse_jobs(listing.read_text(), s.workflow)
    except ValueError as exc:
        raise SystemExit(f"{listing}: {exc}") from exc
    state = batch.Status.load(
        Path(status) if status else listing.with_name(listing.name + ".status.json")
    )
    opts = batch.Options(s, skip_workflow, skip_pypi, retry_failed)
    console.print(f"[bold]{len(jobs)} jobs[/] from {listing}; status in {state.path}")
    sys.exit(batch.run(jobs, state, opts, report=console.print))


def _setup_one(
    ref: Repo,
    package: str | None,
    s: _config.Settings,
    dry_run: bool,
    skip_workflow: bool,
    skip_pypi: bool,
) -> None:
    name = package or _package_from_repo(ref)
    pub = pypi.Publisher(
        name, ref.owner, ref.name, s.workflow, s.environment, s.test_pypi
    )
    console.print(
        f"[bold]{ref.slug}[/] → [bold]{pub.host}/p/{name}[/]"
        + (" (dry run)" if dry_run else "")
    )
    _step(github.ensure_environment(ref, s.environment, dry_run))
    if not skip_workflow:
        content = render("release.yml.tmpl", name, s)
        _step(github.ensure_workflow(ref, s.workflow, content, dry_run))
    if skip_pypi:
        return
    if dry_run:
        exists = pypi.project_exists(pub)
        url, _ = pypi.form_target(pub, exists)
        kind = "publisher" if exists else "pending publisher"
        _step(f"would register {kind} at {url}")
        return
    try:
        _step(pypi.register(pub, s))
    except pypi.RateLimited as exc:
        Console(stderr=True).print(f"[red]✗ {exc}[/red]")
        sys.exit(pypi.EXIT_RATE_LIMITED)
    console.print("Done. Release with: [cyan]./publish.sh[/] or push a vX.Y.Z tag")


def workflow(
    package: str,
    workflow: str | None = None,
    environment: str | None = None,
    test_pypi: bool | None = None,
    config: str | None = None,
) -> None:
    """Print the release workflow that `setup` would commit."""
    s = _settings(
        config, workflow=workflow, environment=environment, test_pypi=test_pypi
    )
    print(render("release.yml.tmpl", package, s), end="")


def upgrade(
    path: str = ".",
    package: str | None = None,
    workflow: str | None = None,
    environment: str | None = None,
    test_pypi: bool | None = None,
    config: str | None = None,
    verbose: bool = False,
) -> None:
    """Write the release workflow, publish.sh and build.sh into a local clone (no commit).

    Replaces the workflow and publish.sh, adds build.sh only when missing,
    gitignores and untracks the hatch-vcs version file, and warns about other
    workflows that also publish to PyPI.
    """
    _configure_logging(verbose)
    s = _settings(
        config, workflow=workflow, environment=environment, test_pypi=test_pypi
    )
    root = Path(path).expanduser().resolve()
    name = package or project_name((root / "pyproject.toml").read_text())
    console.print(f"[bold]{root}[/] → {name}")
    for msg in scaffold.upgrade(root, name, s):
        _step(msg)


def upload_helper(path: str = ".", verbose: bool = False) -> None:
    """Add scripts/pypi-upload.sh and .github/workflows/pypi-upload.yml (no commit).

    For repos whose wheels are built elsewhere (maturin, several packages per
    repo): the script stages files on a draft GitHub release; the workflow uploads
    them through Trusted Publishing. Then register it with
    `pypitrust setup OWNER/REPO --package NAME --workflow pypi-upload.yml --skip_workflow`.
    """
    _configure_logging(verbose)
    for msg in scaffold.add_upload_helper(Path(path).expanduser().resolve()):
        _step(msg)


def show_config(config: str | None = None) -> None:
    """Print the config file in use and the effective settings (as TOML)."""
    try:
        path = _config.find_config(config)
        settings = _config.load(config)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(f"pypitrust: {exc}") from exc
    console.print(f"# config file: {path or '(none; built-in defaults)'}", markup=False)
    for key, value in settings.as_dict().items():
        line = f"# {key} = (unset)" if value is None else f"{key} = {_toml(value)}"
        console.print(line, markup=False)


def _toml(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def version() -> None:
    """Print the installed version."""
    print(__version__)


def main() -> None:
    fire.Fire(
        {
            "setup": setup,
            "upgrade": upgrade,
            "upload-helper": upload_helper,
            "workflow": workflow,
            "config": show_config,
            "version": version,
        }
    )


if __name__ == "__main__":
    main()
