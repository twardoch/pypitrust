# this_file: tests/test_pypitrust.py
import re

import pytest

from pypitrust import pypi
from pypitrust.config import Settings
from pypitrust.render import render
from pypitrust.repo import Repo, RepoError, parse_repo, project_name

PUB = pypi.Publisher("my-pkg", "octo", "my-pkg", "release.yml", "pypi")


@pytest.mark.parametrize(
    "spec",
    [
        "octo/my-pkg",
        "https://github.com/octo/my-pkg",
        "https://github.com/octo/my-pkg.git",
        "git@github.com:octo/my-pkg.git",
        "https://github.com/octo/my-pkg/",
    ],
)
def test_parse_repo_when_valid_spec_then_owner_and_name(spec):
    assert parse_repo(spec) == Repo("octo", "my-pkg")


def test_parse_repo_when_garbage_then_error():
    with pytest.raises(RepoError):
        parse_repo("not a repo")


def test_project_name_when_mixed_case_then_normalised():
    assert project_name('[project]\nname = "My_Cool.Pkg"\n') == "my-cool-pkg"


def test_project_name_when_missing_then_error():
    with pytest.raises(RepoError):
        project_name("[tool.x]\n")


def test_form_target_when_project_exists_then_project_settings():
    url, form = pypi.form_target(PUB, exists=True)
    assert url == "https://pypi.org/manage/project/my-pkg/settings/publishing/"
    assert form == "form#github-publisher-form"


def test_form_target_when_new_then_pending_publisher():
    url, form = pypi.form_target(PUB, exists=False)
    assert url.endswith("/manage/account/publishing/") and "pending" in form
    assert pypi.form_values(PUB, exists=False)["project_name"] == "my-pkg"
    assert "project_name" not in pypi.form_values(PUB, exists=True)


def test_is_registered_when_row_present_then_true():
    row = "my-pkg  Repository: octo/my-pkg  Workflow: release.yml  Environment: pypi"
    assert pypi.is_registered(row, PUB)
    assert not pypi.is_registered(row.replace("release.yml", "ci.yml"), PUB)


def test_render_workflow_when_test_pypi_then_test_urls():
    text = render(
        "release.yml.tmpl", "my-pkg", Settings(environment="testpypi", test_pypi=True)
    )
    assert not re.search(r"(?<!\$)\{\{", text) and "id-token: write" in text
    assert "https://test.pypi.org/legacy/" in text and "name: testpypi" in text


def test_needs_reauth_when_confirm_page_then_true():
    from pypitrust.pypi import needs_reauth

    assert needs_reauth("Confirm password · PyPI")
    assert not needs_reauth("Publishing · mcruft · PyPI")


def test_is_registered_when_page_shows_normalized_name_then_true():
    from pypitrust.pypi import Publisher, is_registered

    pub = Publisher("my_pkg", "octo", "my-pkg", "release.yml", "pypi")
    page = (
        "Manage publishers my-pkg GitHub Repository: octo/my-pkg Workflow: release.yml"
    )
    assert is_registered(page, pub)


def test_page_error_when_429_then_message():
    from pypitrust.pypi import page_error

    msg = page_error(
        "429 Too Many Requests",
        "429 Too Many Requests The action could not be performed because there were "
        "too many requests by the client. There have been too many attempted "
        "trusted publisher registrations. Try again later.",
    )
    assert msg and msg.startswith("429"), msg
    assert "trusted publisher registrations" in msg


def test_page_error_when_normal_page_then_none():
    from pypitrust.pypi import page_error

    assert page_error("Publishing · mcruft · PyPI", "Trusted publishers") is None
    assert page_error("Confirm password · PyPI", "") is None


def test_page_error_when_403_then_message():
    from pypitrust.pypi import page_error

    assert page_error("403 Forbidden", "Access denied").startswith("403")


def test_wait_for_login_when_playwright_times_out_then_login_timeout():
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    class Page:
        url = "https://pypi.org/manage/account/publishing/"

        def title(self):
            return "Confirm password · PyPI"

        def wait_for_function(self, *a, **k):
            raise PlaywrightTimeout("Timeout 1ms exceeded.")

    with pytest.raises(pypi.LoginTimeout, match="within 1 s"):
        pypi._wait_for_login(Page(), Page.url, 1)
