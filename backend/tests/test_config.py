"""Where configuration comes from when two sources disagree.

The deployed .env has to win over the ambient environment. Getting this
backwards produces a service that runs fine under systemd (which passes the
same file in as EnvironmentFile) while the CLI fails against what looks like
identical config — the symptom is an unexplained 401 from OpenRouter when a
key for some other tool happens to be exported in the operator's shell.
"""
import os

from curio.config import _load_env


def write_env(tmp_path, body):
    p = tmp_path / ".env"
    p.write_text(body)
    return p


def test_env_file_overrides_the_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_TEST_KEY", "stale-value-from-some-other-tool")
    _load_env(write_env(tmp_path, "CURIO_TEST_KEY=the-deployed-value\n"))
    assert os.environ["CURIO_TEST_KEY"] == "the-deployed-value"


def test_env_file_sets_unset_values(tmp_path, monkeypatch):
    monkeypatch.delenv("CURIO_TEST_UNSET", raising=False)
    _load_env(write_env(tmp_path, "CURIO_TEST_UNSET=from-file\n"))
    assert os.environ["CURIO_TEST_UNSET"] == "from-file"


def test_shell_survives_when_the_file_is_silent(tmp_path, monkeypatch):
    # Only keys the file actually mentions are replaced.
    monkeypatch.setenv("CURIO_TEST_UNTOUCHED", "kept")
    _load_env(write_env(tmp_path, "SOMETHING_ELSE=x\n"))
    assert os.environ["CURIO_TEST_UNTOUCHED"] == "kept"


def test_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_TEST_NOFILE", "kept")
    _load_env(tmp_path / "does-not-exist")
    assert os.environ["CURIO_TEST_NOFILE"] == "kept"
