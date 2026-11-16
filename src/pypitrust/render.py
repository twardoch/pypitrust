# this_file: src/pypitrust/render.py
"""Fill the bundled templates in `pypitrust/templates/`.

Placeholders: ``{{package}}``, ``{{environment}}``, ``{{workflow}}``,
``{{index}}`` (pypi.org or test.pypi.org) and ``{{upload_url}}``.
"""

from __future__ import annotations

from importlib.resources import files

from .config import Settings

UPLOAD_URLS = {
    "pypi.org": "https://upload.pypi.org/legacy/",
    "test.pypi.org": "https://test.pypi.org/legacy/",
}


def template(name: str) -> str:
    """Raw text of a bundled template."""
    return files("pypitrust").joinpath("templates", name).read_text()


def render(name: str, package: str, settings: Settings | None = None) -> str:
    """A bundled template with every placeholder filled."""
    s = settings or Settings()
    values = {
        "package": package,
        "environment": s.environment,
        "workflow": s.workflow,
        "index": s.index_host,
        "upload_url": UPLOAD_URLS[s.index_host],
    }
    text = template(name)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text
