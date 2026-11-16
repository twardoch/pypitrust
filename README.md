---
this_file: README.md
---
# pypitrust

One command takes a GitHub repo from "has a `pyproject.toml`" to "pushing a `v*` tag publishes it to PyPI". No API token is stored anywhere: publishing uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC).

```bash
uv tool install pypitrust

pypitrust setup octo/my-pkg              # owner/name, a GitHub URL, or a local clone
pypitrust setup octo/my-pkg --dry_run    # show what would change
pypitrust setup octo/my-pkg --test_pypi  # rehearse on test.pypi.org
pypitrust setup repos.txt                # many repos, resumable
pypitrust upgrade ~/src/my-pkg           # write the release files into a clone
pypitrust workflow my-pkg                # print the workflow it would commit
pypitrust config                         # show the settings in effect
```

## What `setup` does

1. **GitHub**, through your logged-in `gh` CLI:
   - creates the deployment environment (default `pypi`);
   - commits `.github/workflows/release.yml` unless you pass `--skip_workflow`. An existing file is never overwritten; you get a warning if it lacks `id-token: write`.
2. **PyPI**, through a real Chrome driven by [playwrightauthor](https://pypi.org/project/playwrightauthor/):
   - if the project exists, adds a trusted publisher in its *Publishing* settings;
   - if it doesn't, adds a *pending* publisher to your account, so the first release creates the project.
   - It's idempotent: a matching publisher is detected and left alone, and a new one is checked once PyPI lists it.

PyPI has no API for trusted-publisher settings ([warehouse#14456](https://github.com/pypi/warehouse/issues/14456)), which is why a browser is involved. If PyPI asks you to log in or to confirm your password (its hourly sudo mode), do it in the window that opens, 2FA included. The tool waits, then continues. It never types your password. The browser profile keeps the session for later runs.

## The release setup

`pypitrust upgrade PATH` writes these into a local clone and commits nothing:

- **`.github/workflows/release.yml`**: on a `v*` tag push, or a manual dispatch with a `tag` input, the jobs run in order:
  1. create the tag (dispatch only);
  2. `uv build` from that tag, checking the built version matches it;
  3. create a GitHub Release with the files;
  4. publish to PyPI over OIDC from the protected environment.
- **`publish.sh`**: picks the next patch tag (or takes `vX.Y.Z`) and dispatches the workflow.
- **`build.sh`**: `uv build`, added only when missing.
- **`.gitignore`**: gets the hatch-vcs version file (for example `src/pkg/__version__.py`), which is also untracked, so CI never builds a `+dirty` version.

It warns about other workflows that still publish with a token. Then run `pypitrust setup OWNER/REPO --skip_workflow` to register the publisher.

Versions come from git tags via [hatch-vcs](https://github.com/ofek/hatch-vcs). Your `pyproject.toml` needs:

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
dynamic = ["version"]

[tool.hatch.version]
source = "vcs"

[tool.hatch.build.hooks.vcs]
version-file = "src/my_pkg/__version__.py"
```

Repos whose wheels are built on your machine (maturin, several packages per repo) use `pypitrust upload-helper PATH` instead. It adds `scripts/pypi-upload.sh FILE...`, which attaches the files to a draft GitHub release, dispatches `.github/workflows/pypi-upload.yml` and waits for the upload. Drafts create no git tag, so tag-derived versions stay put. Register that workflow with `--workflow pypi-upload.yml`.

## Many repos at once

Give `setup` a text file instead of a repo. Each line holds one job, `REPO [PACKAGE|-] [WORKFLOW]`, and `#` starts a comment:

```text
octo/alpha                      # package name read from pyproject.toml
https://github.com/octo/beta beta
acme/gamma - pypi-upload.yml
```

Each job runs four steps: package, github_env, workflow, pypi_publisher. Every outcome goes into `repos.txt.status.json` (or the file `--status` names), so running the same command again skips finished steps.

- A step skipped with `--skip_pypi` or `--skip_workflow` stays pending and runs on a later full run.
- A failed step stops only its own job; `--retry_failed` tries it again.
- PyPI registrations are spaced `delay` seconds apart.
- PyPI rate-limits registrations. On a 429 the whole run pauses for `cooldown` seconds, records the pause in the status file and exits 75 (`EX_TEMPFAIL`). Before then, running it again does nothing.

## Configuration

Settings come from the built-in defaults, then a TOML config file, then command-line flags. The first config file found wins: `--config PATH`, `$PYPITRUST_CONFIG`, `./pypitrust.toml`, `[tool.pypitrust]` in `./pyproject.toml`, and `$XDG_CONFIG_HOME/pypitrust/config.toml` (`~/.config/...`). Unknown keys and wrong types are errors. [`pypitrust.example.toml`](pypitrust.example.toml) lists every key:

| key | default | meaning |
|---|---|---|
| `environment` | `"pypi"` | GitHub environment the workflow publishes from |
| `workflow` | `"release.yml"` | workflow filename registered with PyPI |
| `test_pypi` | `false` | target test.pypi.org |
| `profile` | `"default"` | playwrightauthor browser profile |
| `debug_port` | unset | Chrome CDP port, when another Chrome already holds the default |
| `login_timeout` | `300` | seconds to wait for a manual login |
| `action_timeout` | `30` | seconds per browser action |
| `delay` | `90` | list runs: seconds between registrations |
| `cooldown` | `3600` | list runs: pause after a 429 |

Run-only flags: `--package`, `--dry_run`, `--skip_pypi`, `--skip_workflow`, `--retry_failed`, `--status`, `--verbose`.

## Caveats

- A pending publisher is void if someone else registers the name first, so register early.
- When PyPI shows an error page, the tool stops and leaves the browser as it is, rather than retrying blindly.

## Development

```bash
uv sync
uv run pytest
./build.sh            # version from the latest tag
./publish.sh          # release the next patch version
```

pypitrust releases itself with the setup it writes. CI runs ruff and the tests on Python 3.12 and 3.13.

## Licence

Apache-2.0
