"""BH-K26: doctor's deployment-drift check covered ONE shipped file.

The LimitCORE lesson (repo unit fixed, installed copy stale for weeks)
was applied to `assistant.service` only. The same copy-on-deploy
pattern ships `elaria-overlay.service`, `elaria-console.service` and
`ui/sounds/knock.wav`, and the Hyprland binds are appended into the
user's compositor config — all drifted silently. The UI units also
hardcode the checkout path (`%h/Elaria/...`), so a repo living
elsewhere yields a service that starts nothing, unflagged.

Fix: `_deployment_drift_checks` covers every shipped-and-copied file:
byte-compare where a copy exists, quickshell path sanity for the UI
units, and bind-marker presence in the Hyprland config.
"""

from __future__ import annotations

from pathlib import Path

from assistant.cli import _deployment_drift_checks

SOUND = "~/.local/share/assistant/sounds/knock.wav"
UNITS = ("assistant.service", "elaria-overlay.service", "elaria-console.service")


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "Elaria"
    home = tmp_path / "home"
    (repo / "systemd").mkdir(parents=True)
    (repo / "ui" / "sounds").mkdir(parents=True)
    (repo / "ui" / "quickshell").mkdir(parents=True)
    (repo / "ui" / "quickshell" / "console").mkdir(parents=True)
    for unit in UNITS:
        body = "[Service]\nExecStart=/usr/bin/quickshell -p %h/Elaria/ui/quickshell\n"
        if unit == "assistant.service":
            body = "[Service]\nLimitCORE=0\nExecStart=%h/.local/bin/assistd\n"
        (repo / "systemd" / unit).write_text(body)
    (repo / "ui" / "sounds" / "knock.wav").write_bytes(b"repo-knock")
    home.mkdir(exist_ok=True)
    return repo, home


def _install(home: Path, unit: str, text: str) -> None:
    dest = home / ".config" / "systemd" / "user"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / unit).write_text(text)


def _by_name(checks: list[dict], fragment: str) -> dict:
    for check in checks:
        if fragment in check["check"]:
            return check
    raise AssertionError(f"no check named like {fragment!r} in {checks}")


def test_stale_overlay_unit_is_flagged(tmp_path):
    repo, home = _tree(tmp_path)
    _install(home, "elaria-overlay.service", "[Service]\nExecStart=/old\n")
    checks = _deployment_drift_checks(repo, home, {}, sound=SOUND)
    overlay = _by_name(checks, "elaria-overlay")
    assert overlay["status"] != "ok"
    assert "differs" in overlay["detail"]


def test_matching_console_unit_is_ok(tmp_path):
    repo, home = _tree(tmp_path)
    text = (repo / "systemd" / "elaria-console.service").read_text()
    _install(home, "elaria-console.service", text)
    checks = _deployment_drift_checks(repo, home, {}, sound=SOUND)
    assert _by_name(checks, "elaria-console")["status"] == "ok"


def test_assistant_unit_limitcore_drift_still_called_out(tmp_path):
    repo, home = _tree(tmp_path)
    _install(home, "assistant.service", "[Service]\nExecStart=%h/.local/bin/assistd\n")
    checks = _deployment_drift_checks(repo, home, {}, sound=SOUND)
    unit = _by_name(checks, "systemd unit")
    assert unit["status"] != "ok"
    assert "LimitCORE drift" in unit["detail"]


def test_broken_quickshell_path_is_flagged(tmp_path):
    repo, home = _tree(tmp_path)
    # Installed verbatim, but this "home" has no Elaria checkout in it:
    # the unit points quickshell at a directory that does not exist.
    text = (repo / "systemd" / "elaria-overlay.service").read_text()
    _install(home, "elaria-overlay.service", text)
    checks = _deployment_drift_checks(repo, home, {}, sound=SOUND)
    path_check = _by_name(checks, "quickshell path (elaria-overlay.service)")
    assert path_check["status"] != "ok"


def test_stale_knock_sound_is_flagged(tmp_path):
    repo, home = _tree(tmp_path)
    dest = home / ".local" / "share" / "assistant" / "sounds"
    dest.mkdir(parents=True)
    (dest / "knock.wav").write_bytes(b"stale-knock")
    checks = _deployment_drift_checks(repo, home, {}, sound=SOUND)
    knock = _by_name(checks, "knock sound")
    assert knock["status"] != "ok"


def test_missing_hyprland_binds_are_flagged(tmp_path):
    repo, home = _tree(tmp_path)
    hypr = home / ".config" / "hypr"
    hypr.mkdir(parents=True)
    (hypr / "hyprland.conf").write_text("bind = SUPER, Q, killactive\n")
    checks = _deployment_drift_checks(repo, home, {}, sound=SOUND)
    binds = _by_name(checks, "hyprland binds")
    assert binds["status"] != "ok"


def test_present_hyprland_binds_are_ok(tmp_path):
    repo, home = _tree(tmp_path)
    hypr = home / ".config" / "hypr"
    hypr.mkdir(parents=True)
    (hypr / "hyprland.conf").write_text(
        "bind = SUPER, grave, exec, assist ptt start\n"
        "bindr = SUPER, grave, exec, assist ptt stop\n"
        "bind = SUPER SHIFT, F12, exec, assist halt\n")
    checks = _deployment_drift_checks(repo, home, {}, sound=SOUND)
    assert _by_name(checks, "hyprland binds")["status"] == "ok"
