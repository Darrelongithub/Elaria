"""Test isolation: every test runs against temp XDG dirs with NO api key.

This is the §12.9 contract made executable: clone the repo anywhere,
`pytest` passes offline. GEMINI_API_KEY is explicitly removed even if
the developer's shell has one, so a green suite can never secretly
depend on the live API.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_MODE", "mock")
    home = tmp_path / "home"
    (home / ".config" / "assistant").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("ASSIST_FIXTURES", str(tmp_path / "fixtures"))
    monkeypatch.delenv("ASSIST_CONFIG", raising=False)
    yield tmp_path
    # sanity: the environment really has no key during the suite
    assert "GEMINI_API_KEY" not in os.environ


@pytest.fixture
def config():
    from assistant.config import load_config

    return load_config()
