# this_file: tests/test_config.py
import pytest

from pypitrust import config
from pypitrust.config import Settings


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PYPITRUST_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def test_load_when_no_file_then_defaults():
    assert config.find_config() is None
    assert config.load() == Settings()


def test_load_when_pypitrust_toml_then_values_applied(tmp_path):
    (tmp_path / "pypitrust.toml").write_text('environment = "release"\ndelay = 5\n')
    s = config.load()
    assert s.environment == "release" and s.delay == 5.0


def test_load_when_pyproject_tool_table_then_used(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pypitrust]\ntest_pypi = true\n")
    assert config.load().index_host == "test.pypi.org"


def test_find_when_pyproject_without_table_then_falls_through_to_xdg(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    user = tmp_path / "xdg" / "pypitrust" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text('profile = "work"\n')
    assert config.find_config() == user
    assert config.load().profile == "work"


def test_load_when_env_var_then_that_file(tmp_path, monkeypatch):
    f = tmp_path / "elsewhere.toml"
    f.write_text("debug_port = 9222\n")
    monkeypatch.setenv("PYPITRUST_CONFIG", str(f))
    assert config.load().debug_port == 9222


def test_load_when_unknown_key_then_error(tmp_path):
    (tmp_path / "pypitrust.toml").write_text("enviroment = 'x'\n")
    with pytest.raises(ValueError, match="enviroment"):
        config.load()


def test_load_when_wrong_type_then_error(tmp_path):
    (tmp_path / "pypitrust.toml").write_text("test_pypi = 'yes'\n")
    with pytest.raises(ValueError, match="test_pypi must be bool"):
        config.load()


def test_load_when_explicit_missing_then_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        config.load(tmp_path / "nope.toml")


def test_merged_when_none_then_kept_and_values_override():
    s = Settings(environment="a").merged(environment=None, workflow="ci.yml")
    assert s.environment == "a" and s.workflow == "ci.yml"
