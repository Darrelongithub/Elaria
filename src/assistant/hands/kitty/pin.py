"""Single source of truth for the pinned upstream kitty release (ASK 49).

Every gate, tool and test reads the pin from THIS module. A kitty bump is then
"re-run the builder, review the diff, change this file, annotate history" — not a
23-file grep under time pressure. The gates stay exactly as strict as before; only
the pinned strings move (owner ruling 1, 2026-11-17).

Re-pin 0.47.1 -> 0.49.2 evidence: KITTY-REPIN-DECISION.md and
KITTY-SEMANTIC-DIFF.md (Drive, 2026-11-17), re-verified here against
`kovidgoyal/kitty` v0.49.2 source. Version-suffixed hazard flags are RE-DERIVED
against the pinned source; nothing carries over from the previous release
(owner ruling 2).
"""
from __future__ import annotations

UPSTREAM_VERSION = '0.49.2'
UPSTREAM_COMMIT = 'b2cb871254fbdac19a085188813c8dfb258b95cd'

# Approval 0 — measured on owner hardware 2026-11-17 (rpm -q + kitten --version).
OWNER_RPM_RULING = '0.49.2-1.fc44'
OWNER_VERSION_VERBATIM = 'kitten 0.49.2 created by Kovid Goyal'
OWNER_DRIFT_RECONCILED = True
RESEARCHED_ON = '2026-11-19'

SOURCE_URL = 'https://github.com/kovidgoyal/kitty/tree/v' + UPSTREAM_VERSION
# `kitty --version` prints 'kitty 0.49.2 created by Kovid Goyal'. The trailing
# space keeps the exact-prefix gate strict against a future '0.49.20'.
CLI_VERSION_PREFIX = 'kitty ' + UPSTREAM_VERSION + ' '


def cli_version_matches(stdout):
    """Exact-prefix, fail-closed gate over `kitty --version` output bytes."""
    return isinstance(stdout, bytes) and stdout.startswith(CLI_VERSION_PREFIX.encode())


def check_cli_version(stdout):
    """Raise the historical refusal reason when the installed kitty is not the pin."""
    if not cli_version_matches(stdout):
        raise ValueError('installed-kitty-version-not-inventory-version')


# Version-suffixed hazard flags are derived, never copied forward.
SEND_KEY_EXCLUDE_ACTIVE_UNENFORCED = (
    'K3-send-key-exclude-active-unenforced-' + UPSTREAM_VERSION)
GET_TEXT_EXTENT_UNASSESSED = 'get-text-extent-unassessed-' + UPSTREAM_VERSION

# ASK 50 / Approval 2c: narrowing the read reach needs no approval, widening it
# does. `get-text --extent` gained `alternate` and `alternate_scrollback` at
# v0.49.2; both reach the not-currently-visible screen and its scrollback. The
# hands worker needs marker readback, not that, so only the assessed subset is
# executable. A widening needs an explicit owner ruling.
UNASSESSED_GET_TEXT_EXTENTS = frozenset({'alternate', 'alternate_scrollback'})
ASSESSED_GET_TEXT_EXTENTS = frozenset({
    'screen', 'all', 'selection', 'first_cmd_output_on_screen', 'last_cmd_output',
    'last_visited_cmd_output', 'last_non_empty_output'})

# Never granted through the per-instance `remote_control_password` verb list, and
# refused again at the payload boundary. `screenshot` (new at 0.49.2) is both an
# arbitrary-path PNG write and a screen-content return-to-caller; `set_os_window_title`
# (new at 0.49.2) rewrites OS window identity (phishing/spoofing surface).
NEVER_GRANT_VERBS = frozenset({'screenshot', 'set-os-window-title'})

# Reviewed create-marker dependency chain, hashed from the v0.49.2 tree.
MARKER_SOURCES = {
    'kitty/rc/create_marker.py': '695cc7730a48a4ffc9a0ff4158643ab8d4f54c28d4fa7225bc94d785ae2ab6d4',
    'kitty/options/utils.py': '5fc552256355df39edcbaa7fbf1892079a7c0e2449500440a446e442b7cff08a',
    'kitty/window.py': 'b372875bd2816f9bd0bd9f5cf95d9257480e8479861f1fb5251b010f662009ed',
    'kitty/marks.py': '79a417c29e29cf452615e7bda392c59f937c649507fb7ab5365e74c8bbe59e03',
}
