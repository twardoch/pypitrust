# this_file: tests/test_render.py
import re

from pypitrust.config import Settings
from pypitrust.render import render


def test_render_when_defaults_then_no_placeholders_left():
    for name in ("release.yml.tmpl", "publish.sh.tmpl", "build.sh.tmpl"):
        assert not re.search(r"(?<!\$)\{\{\s*\w+\s*\}\}", render(name, "my-pkg")), name


def test_render_when_custom_workflow_then_publish_sh_dispatches_it():
    text = render("publish.sh.tmpl", "my-pkg", Settings(workflow="ship.yml"))
    assert "gh workflow run ship.yml" in text and "release.yml" not in text


def test_render_release_when_defaults_then_oidc_and_environment():
    text = render("release.yml.tmpl", "my-pkg", Settings(environment="prod"))
    assert "id-token: write" in text
    assert "name: prod" in text
    assert "https://pypi.org/p/my-pkg" in text
