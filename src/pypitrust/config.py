# this_file: src/pypitrust/config.py
"""Settings: built-in defaults < config file < command-line flags.

The config file is TOML. It is looked up in this order, first found wins:
``--config PATH``, ``$PYPITRUST_CONFIG``, ``./pypitrust.toml``,
``[tool.pypitrust]`` in ``./pyproject.toml``, and
``$XDG_CONFIG_HOME/pypitrust/config.toml`` (``~/.config/...``).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    """Everything the commands can be configured with."""

    environment: str = "pypi"  # GitHub environment the workflow publishes from
    workflow: str = "release.yml"  # workflow filename registered with PyPI
    test_pypi: bool = False  # target test.pypi.org
    profile: str = "default"  # playwrightauthor browser profile (keeps the login)
    debug_port: int | None = None  # CDP port of playwrightauthor's Chrome
    login_timeout: float = 300.0  # seconds to wait for a manual PyPI login
    action_timeout: float = 30.0  # seconds per browser action
    delay: float = 90.0  # list runs: seconds between PyPI registrations
    cooldown: float = 3600.0  # list runs: pause after PyPI answers 429

    @property
    def index_host(self) -> str:
        return "test.pypi.org" if self.test_pypi else "pypi.org"

    def merged(self, **overrides: Any) -> Settings:
        """Apply the flags that were actually given (None means 'not given')."""
        given = {k: v for k, v in overrides.items() if v is not None}
        return replace(self, **_checked(given, "command line"))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _checked(values: dict[str, Any], where: str) -> dict[str, Any]:
    known = {f.name: f for f in fields(Settings)}
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise ValueError(f"unknown setting(s) in {where}: {', '.join(unknown)}")
    for key, value in values.items():
        default = getattr(Settings, key)
        numeric = isinstance(default, float) and isinstance(value, int)
        if default is not None and not numeric and type(value) is not type(default):
            raise ValueError(
                f"{where}: {key} must be {type(default).__name__}, got {value!r}"
            )
    return values


def find_config(explicit: str | os.PathLike | None = None) -> Path | None:
    """The config file in use, or None."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"config file not found: {path}")
        return path
    if env := os.environ.get("PYPITRUST_CONFIG"):
        return find_config(env)
    for path in (Path("pypitrust.toml"), Path("pyproject.toml")):
        if path.is_file() and _table(path) is not None:
            return path
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = base / "pypitrust" / "config.toml"
    return path if path.is_file() else None


def _table(path: Path) -> dict[str, Any] | None:
    data = tomllib.loads(path.read_text())
    if path.name == "pyproject.toml":
        return data.get("tool", {}).get("pypitrust")
    return data


def load(explicit: str | os.PathLike | None = None) -> Settings:
    """Defaults overlaid with the config file, if any."""
    path = find_config(explicit)
    if path is None:
        return Settings()
    return Settings(**_checked(_table(path) or {}, str(path)))
