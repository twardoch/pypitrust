# this_file: tests/test_scaffold.py
import subprocess

from pypitrust import scaffold
from pypitrust.config import Settings

PYPROJECT = """
[project]
name = "Demo_Pkg"
dynamic = ["version"]
[tool.hatch.build.hooks.vcs]
version-file = "src/demo/__version__.py"
"""


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "pyproject.toml").write_text(PYPROJECT)
    vf = tmp_path / "src/demo/__version__.py"
    vf.parent.mkdir(parents=True)
    vf.write_text("__version__ = '0'\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    return tmp_path


def test_version_file_when_hook_configured_then_path():
    assert scaffold.version_file(PYPROJECT) == "src/demo/__version__.py"


def test_version_file_when_missing_then_none():
    assert scaffold.version_file("[project]\nname='x'\n") is None


def test_upgrade_when_fresh_repo_then_files_written_and_version_untracked(tmp_path):
    root = _repo(tmp_path)
    (root / ".github/workflows").mkdir(parents=True)
    (root / ".github/workflows/ci.yml").write_text(
        "uses: pypa/gh-action-pypi-publish@v1\n"
    )
    msgs = scaffold.upgrade(root, "demo-pkg", Settings())
    assert "id-token: write" in (root / ".github/workflows/release.yml").read_text()
    assert "gh workflow run release.yml" in (root / "publish.sh").read_text()
    assert (root / "build.sh").stat().st_mode & 0o111, "build.sh must be executable"
    assert "src/demo/__version__.py" in (root / ".gitignore").read_text()
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "__version__.py" not in tracked
    assert any("ci.yml also publishes" in m for m in msgs), msgs


def test_upgrade_when_rerun_then_idempotent(tmp_path):
    root = _repo(tmp_path)
    scaffold.upgrade(root, "demo-pkg", Settings())
    msgs = scaffold.upgrade(root, "demo-pkg", Settings())
    assert all(m.endswith("kept") for m in msgs), msgs


def test_upgrade_when_build_sh_exists_then_kept(tmp_path):
    root = _repo(tmp_path)
    (root / "build.sh").write_text("custom\n")
    scaffold.upgrade(root, "demo-pkg", Settings())
    assert (root / "build.sh").read_text() == "custom\n"


def test_add_upload_helper_when_fresh_then_script_and_workflow(tmp_path):
    root = _repo(tmp_path)
    msgs = scaffold.add_upload_helper(root)
    script = root / "scripts/pypi-upload.sh"
    assert script.stat().st_mode & 0o111, "pypi-upload.sh must be executable"
    assert "gh workflow run pypi-upload.yml" in script.read_text()
    assert "id-token: write" in (root / scaffold.UPLOAD_WORKFLOW).read_text()
    assert all(m.endswith("created") for m in msgs), msgs
    assert scaffold.other_publishers(root) == [], (
        "pypi-upload.yml is OIDC, not a stray publisher"
    )
