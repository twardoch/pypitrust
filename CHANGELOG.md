---
this_file: CHANGELOG.md
---
# Changelog

## Unreleased

- A login or password-confirmation timeout now ends with a clear message and exit 1 instead of a traceback (`pypi.LoginTimeout`).

## 1.0.0 (2026-11-16)

First release as a standalone package.

- `pypitrust setup REPO|LIST`: creates the GitHub environment, commits the release workflow, and registers the PyPI trusted publisher (or a pending one) in a real browser. It is idempotent, detects login and sudo pages, and stops on PyPI error pages, exiting 75 on a 429.
- List mode: a resumable step pipeline with an atomic JSON status file, paced registrations, a pause on 429 and `--retry_failed`.
- `pypitrust upgrade PATH`: writes the release workflow (tag → build → GitHub Release → PyPI over OIDC), `publish.sh` and `build.sh`, gitignores and untracks the hatch-vcs version file, and warns about token-based publishers.
- `pypitrust upload-helper PATH`: a draft-release upload path for wheels built elsewhere.
- Configuration: TOML file (`--config`, `$PYPITRUST_CONFIG`, `./pypitrust.toml`, `[tool.pypitrust]`, XDG) overlaid by flags; `pypitrust config` shows the effective settings.
- Version from git tags via hatch-vcs; the package releases itself through Trusted Publishing.
