# this_file: src/pypitrust/pypi.py
"""PyPI side: register a GitHub Trusted Publisher by driving PyPI's web form.

PyPI has no API for this (pypi/warehouse#14456), so we fill the form in a real
Chrome via playwrightauthor, reusing a persistent, logged-in profile.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from loguru import logger

from .config import Settings


@dataclass(frozen=True)
class Publisher:
    """Everything PyPI needs to trust one GitHub workflow."""

    project: str
    owner: str
    repository: str
    workflow: str
    environment: str
    test_pypi: bool = False

    @property
    def host(self) -> str:
        return "test.pypi.org" if self.test_pypi else "pypi.org"


def project_exists(pub: Publisher) -> bool:
    """True if the project is already registered on the index."""
    url = f"https://{pub.host}/pypi/{pub.project}/json"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def form_target(pub: Publisher, exists: bool) -> tuple[str, str]:
    """Return (page URL, form selector): project settings if it exists, else a pending publisher."""
    if exists:
        url = f"https://{pub.host}/manage/project/{pub.project}/settings/publishing/"
        return url, "form#github-publisher-form"
    return (
        f"https://{pub.host}/manage/account/publishing/",
        "form#pending-github-publisher-form",
    )


def is_registered(page_text: str, pub: Publisher) -> bool:
    """True if the page's publisher list already shows this project + repo + workflow."""
    text = page_text.lower()
    # PyPI shows the PEP 503 normalized name (split_markdown4gpt -> split-markdown4gpt).
    project = re.sub(r"[-_.]+", "-", pub.project).lower()
    if project not in re.sub(r"[-_.]+", "-", text):
        return False
    return all(
        n.lower() in text for n in (f"{pub.owner}/{pub.repository}", pub.workflow)
    )


def form_values(pub: Publisher, exists: bool) -> dict[str, str]:
    values = {
        "owner": pub.owner,
        "repository": pub.repository,
        "workflow_filename": pub.workflow,
        "environment": pub.environment,
    }
    return values if exists else {"project_name": pub.project, **values}


class RateLimited(RuntimeError):
    """PyPI answered 429: too many requests or too many publisher registrations."""


EXIT_RATE_LIMITED = 75  # EX_TEMPFAIL: retry later, don't hammer PyPI


def page_error(title: str, text: str) -> str | None:
    """Return PyPI's error message if the page is an HTTP error page, else None.

    PyPI keeps the requested URL (often with #errors) and only swaps the title,
    e.g. "429 Too Many Requests" or "403 Forbidden".
    """
    status = re.match(r"\s*([45]\d\d)\b", title)
    if not status:
        return None
    detail = " ".join(text.split())
    return f"{title.strip()}: {detail[:300]}" if detail else title.strip()


def _check_page(page) -> None:
    """Raise if PyPI returned an error page instead of the publishing page."""
    title = page.title()
    error = page_error(title, _publisher_list_text(page) if title else "")
    if error is None:
        return
    if error.startswith("429"):
        raise RateLimited(f"PyPI rate limit: {error}. Wait (often an hour) and rerun.")
    raise RuntimeError(f"PyPI error at {page.url}: {error}")


def needs_reauth(title: str) -> bool:
    """PyPI's hourly "sudo mode" page keeps the URL and only changes the title."""
    return title.startswith("Confirm password")


def _wait_for_login(page, url: str, timeout_s: float) -> None:
    """If PyPI wants a login or a password confirmation, let the human do it, then return."""
    if "/account/login" in page.url:
        logger.warning(
            "Log in to PyPI in the browser window (waiting up to %d s)...", timeout_s
        )
        page.wait_for_url(
            lambda u: "/account/login" not in u and "/account/two-factor" not in u,
            timeout=timeout_s * 1000,
        )
        page.goto(url)
    if needs_reauth(page.title()):
        logger.warning(
            "Confirm your PyPI password in the browser window (waiting up to %d s)...",
            timeout_s,
        )
        page.wait_for_function(
            "() => !document.title.startsWith('Confirm password')",
            timeout=timeout_s * 1000,
        )
        page.goto(url)


# PyPI renders publisher lists without a stable selector (and no <table> when
# empty), so read the page text with every <form> removed: the add-form's help
# text can never produce a false "already registered".
_TEXT_WITHOUT_FORMS_JS = """() => {
  const main = (document.querySelector('main') || document.body).cloneNode(true);
  main.querySelectorAll('form').forEach(f => f.remove());
  return main.textContent.replace(/\\s+/g, ' ');
}"""


def _publisher_list_text(page) -> str:
    return page.evaluate(_TEXT_WITHOUT_FORMS_JS)


def register(pub: Publisher, settings: Settings | None = None) -> str:
    """Add the trusted publisher on PyPI; idempotent. Returns a status line."""
    import os

    from playwrightauthor import Browser

    settings = settings or Settings()
    if settings.debug_port:
        os.environ["PLAYWRIGHTAUTHOR_DEBUG_PORT"] = str(settings.debug_port)

    exists = project_exists(pub)
    url, form = form_target(pub, exists)
    with Browser(profile=settings.profile) as browser:
        page = browser.get_page()
        page.set_default_timeout(settings.action_timeout * 1000)
        page.goto(url)
        _wait_for_login(page, url, settings.login_timeout)
        _check_page(page)
        if is_registered(_publisher_list_text(page), pub):
            return f"PyPI publisher already registered ({url})"
        for field, value in form_values(pub, exists).items():
            page.locator(f"{form} [name='{field}']").fill(value)
        page.locator(f"{form} [type='submit']").click()
        page.wait_for_load_state()
        _wait_for_login(page, url, settings.login_timeout)
        _check_page(page)
        if not is_registered(_publisher_list_text(page), pub):
            raise RuntimeError(
                f"PyPI did not list the new publisher; check the browser at {page.url}"
            )
    kind = "publisher" if exists else "pending publisher"
    return f"PyPI {kind} registered for {pub.project} ({url})"
