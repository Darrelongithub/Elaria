"""Configuration loading — XDG paths only, no hardcoded absolutes.

Phase 0 build order #1 (GETTING-STARTED Step 5). Resolution order:
  config file:  $ASSIST_CONFIG > $XDG_CONFIG_HOME/assistant/config.toml
  API key:      $GEMINI_API_KEY > ~/.config/assistant/gemini.env (0600)
  Gemini mode:  $GEMINI_MODE > config [gemini] mode > auto
                (auto = "mock" when no key is present, "live" with a key)

The key value is never logged, never printed, and never stored in
config.toml (Step 1). Only its presence and file permissions are reported.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

VALID_MODES = ("live", "record", "mock")


def _xdg(env: str, fallback: Path) -> Path:
    value = os.environ.get(env)
    return Path(value).expanduser() if value else fallback


def config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config")


def data_home() -> Path:
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")


def state_home() -> Path:
    return _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state")


def runtime_dir() -> Path:
    """$XDG_RUNTIME_DIR, with a per-user /tmp fallback for headless/test envs.

    On Fedora under systemd --user this is always set (/run/user/$UID).
    The fallback exists so tests and containers can still exercise IPC;
    doctor reports which one was used.
    """
    value = os.environ.get("XDG_RUNTIME_DIR")
    if value:
        return Path(value)
    return Path(f"/tmp/assistant-{os.getuid()}")


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


# Defaults mirror config.toml.example / blueprint Appendix A. Anything the
# blueprint marks open in §10 defaults to its stated recommendation and is
# flagged in README.md for the owner's confirmation — Phase 0 does not
# silently settle later-phase decisions.
DEFAULTS: dict = {
    "gemini": {
        "model_default": "gemini-flash-lite-latest",
        "model_organise": "gemini-flash-lite-latest",
        "model_cleanup": "gemini-flash-lite-latest",
        "model_chat": "gemini-flash-latest",
        "model_transcribe_live": "gemini-3.5-transcribe-live",
        "model_transcribe_batch": "gemini-flash-lite-latest",
        "escalation_ladder": ["gemini-flash-lite-latest", "gemini-flash-latest"],
        "escalate_after_failures": 2,
        "max_scaffold_calls": 6,
        "mode": "mock",
    },
    "quota": {
        "flash_rpm": 10,
        "flash_lite_rpm": 15,
        "max_requests_per_day": 1200,
        "max_requests_per_minute": 12,
    },
    "asr": {
        "primary": "gemini_live",
        "fallback": ["gemini_batch", "local"],
        "offline_model": "small",
        "languages": ["en"],
        "preserve_code_switching": False,
        "assert_output_language": True,
    },
    "capture": {"source": "mic", "sample_rate": 16000, "chunk_ms": 30, "retention_days": 30},
    "persona": {
        "name": "Elaria",
        "candour": 0.7,
        "verbosity": "normal",
        "humour": "witty",
        "humour_profile": "~/.local/share/assistant/persona/humour.toml",
        "proactive": True,
        "proactive_max_per_day": 3,
        "pushback_budget_per_day": 5,
        "quiet_hours": "23:00-07:00",
    },
    "privacy": {"tier": "free", "never_send_to_cloud": []},
    "organise": {
        "mode": "shadow",
        "confidence_auto": 0.90,
        "confidence_review": 0.60,
        "max_ops_per_run": 200,
        "max_ops_per_hour": 500,
        "tree_tripwire_pct": 25,
    },
    "policy": {
        "protected": ["~/.ssh", "~/.gnupg", "~/.config", "~/.local/share/assistant"],
        "recently_modified_guard_minutes": 15,
    },
    "tools": {"shell": "confirm"},
    "voice_test": {
        "keyword": "Elaria",
        "speaker_threshold": 0.75,
        "keyword_threshold": 0.5,
        "save_near_miss_clips": False,
    },
}


@dataclass
class Config:
    raw: dict
    config_path: Path
    config_found: bool
    api_key_present: bool
    api_key_source: str  # "env" | "file" | "none"
    api_key_file_mode: int | None  # permission bits of gemini.env, if read
    gemini_mode: str
    gemini_mode_source: str  # "env" | "config" | "auto-no-key" | "auto-key"
    _api_key: str | None = field(default=None, repr=False)

    # -- section accessors -------------------------------------------------
    def section(self, name: str) -> dict:
        return dict(self.raw.get(name, {}))

    def model_for_role(self, role: str) -> str:
        gemini = self.raw["gemini"]
        return gemini.get(f"model_{role}", gemini["model_default"])

    @property
    def api_key(self) -> str | None:
        """The key itself. Callers must never log or print this."""
        return self._api_key

    # -- paths -------------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return data_home() / "assistant"

    @property
    def state_dir(self) -> Path:
        return state_home() / "assistant"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "assistant.db"

    @property
    def socket_path(self) -> Path:
        return runtime_dir() / "assistant.sock"

    @property
    def fixtures_dir(self) -> Path:
        override = os.environ.get("ASSIST_FIXTURES")
        if override:
            return Path(override).expanduser()
        # Dev checkout: fixtures/ sits next to pyproject.toml. Installed:
        # fall back to the data dir so record mode still has somewhere sane.
        repo_fixtures = Path(__file__).resolve().parents[2] / "fixtures"
        if repo_fixtures.parent.joinpath("pyproject.toml").exists():
            return repo_fixtures
        return self.data_dir / "fixtures"

    def humour_profile_path(self) -> Path | None:
        """Locate humour.toml: persona dir first, then repo root (dev)."""
        configured = Path(self.raw["persona"]["humour_profile"]).expanduser()
        if configured.exists():
            return configured
        repo_root = Path(__file__).resolve().parents[2] / "humour.toml"
        if repo_root.exists():
            return repo_root
        cwd = Path.cwd() / "humour.toml"
        return cwd if cwd.exists() else None

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.state_dir, runtime_dir()):
            path.mkdir(parents=True, exist_ok=True)


def _read_env_file(path: Path) -> tuple[str | None, int | None]:
    """Parse GEMINI_API_KEY=... from gemini.env. Returns (key, file_mode)."""
    if not path.exists():
        return None, None
    mode = path.stat().st_mode & 0o777
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GEMINI_API_KEY="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return (value or None), mode
    return None, mode


def load_config() -> Config:
    config_path = Path(
        os.environ.get("ASSIST_CONFIG", config_home() / "assistant" / "config.toml")
    ).expanduser()
    raw = _deep_merge(DEFAULTS, {})
    found = config_path.exists()
    if found:
        with config_path.open("rb") as handle:
            raw = _deep_merge(raw, tomllib.load(handle))

    env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    file_key, file_mode = _read_env_file(config_home() / "assistant" / "gemini.env")
    if env_key:
        api_key, source = env_key, "env"
    elif file_key:
        api_key, source = file_key, "file"
    else:
        api_key, source = None, "none"

    env_mode = os.environ.get("GEMINI_MODE", "").strip().lower()
    if env_mode in VALID_MODES:
        mode, mode_source = env_mode, "env"
    elif raw["gemini"].get("mode") in VALID_MODES and "mode" in _file_sections(config_path):
        mode, mode_source = raw["gemini"]["mode"], "config"
    elif api_key:
        mode, mode_source = "live", "auto-key"
    else:
        # §12.9 guardrail: a missing key means "no network", never a crash.
        mode, mode_source = "mock", "auto-no-key"

    return Config(
        raw=raw,
        config_path=config_path,
        config_found=found,
        api_key_present=api_key is not None,
        api_key_source=source,
        api_key_file_mode=file_mode,
        gemini_mode=mode,
        gemini_mode_source=mode_source,
        _api_key=api_key,
    )


def _file_sections(config_path: Path) -> set[str]:
    """Top-level keys actually present in the user's file (vs defaults)."""
    if not config_path.exists():
        return set()
    try:
        with config_path.open("rb") as handle:
            parsed = tomllib.load(handle)
        return {"mode"} if "mode" in parsed.get("gemini", {}) else set()
    except Exception:
        return set()


def load_humour_profile(config: Config) -> dict:
    """Parse humour.toml (the calibrated taste profile, §13.7).

    Returns {} when absent — the governor must degrade to safe restraint,
    never crash, and never invent a personality the owner didn't approve.
    """
    path = config.humour_profile_path()
    if path is None:
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)
