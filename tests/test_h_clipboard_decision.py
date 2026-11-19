"""H · DESKTOP — step 3: the clipboard decision, recorded AND pinned.

The brief offered "finish to a tested minimum OR mark dormant". The measurement that
decided it: clipboard.py is not a stub — transcribe.py calls copy_text() on every
accepted dictation ([transcribe] copy_to_clipboard, default true). Freezing a live
path would have left an untested write to the user's clipboard in the product;
"finished" here therefore means tests, not features.

The rationale lives in the module docstring (where a reader meets it) and in
reports/RPT-H-r1-*; this file makes the decision regression-proof: the three
branches, the single subprocess, and the things deliberately NOT built.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from assistant import clipboard
from assistant.clipboard import copy_text

REPO = Path(__file__).resolve().parents[1]


class Recorder:
    """Stands in for subprocess.run; records argv instead of touching a clipboard."""

    def __init__(self, *, fail=False):
        self.calls: list[list[str]] = []
        self.fail = fail

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.fail:
            raise RuntimeError("wayland said no")


# -- the three branches -----------------------------------------------------
def test_absent_wl_copy_is_reported_not_raised(monkeypatch):
    """A headless box must still land the dictation in the inbox, so the module
    that cannot copy must not be the module that crashes the path."""
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: None)
    calls: list = []
    result = copy_text("hello", runner=lambda *a, **k: calls.append(a))
    assert result["copied"] is False
    assert "wl-copy not found" in result["reason"]
    assert calls == []                       # nothing attempted, not even a fallback


def test_success_is_exactly_one_call_with_the_documented_argv(monkeypatch):
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: "/usr/bin/wl-copy")
    runner = Recorder()
    result = copy_text("text with -dash and spaces", runner=runner)
    assert result == {"copied": True, "reason": "wl-copy"}
    assert runner.calls == [["wl-copy", "--", "text with -dash and spaces"]]
    # 1 call, and `--` guards the leading-dash case (an option-smuggling argv)


def test_failure_is_data_so_the_transcript_survives(monkeypatch):
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: "/usr/bin/wl-copy")
    result = copy_text("x", runner=Recorder(fail=True))
    assert result["copied"] is False
    assert result["reason"].startswith("wl-copy failed")
    assert "wayland said no" in result["reason"]


def test_x11_tools_are_never_attempted(monkeypatch):
    """§3.3: xclip/xsel fail silently on Wayland. 'Silently' is the defect — they
    must not be tried as a fallback, so a headless run cannot look like a success."""
    seen: list[str] = []
    monkeypatch.setattr(clipboard.shutil, "which",
                        lambda name: seen.append(name) or None)
    copy_text("x", runner=Recorder())
    assert seen == ["wl-copy"]


# -- the decision itself, and its boundary ---------------------------------
def test_the_decision_is_recorded_where_it_will_be_read():
    doc = inspect.getdoc(clipboard) or ""
    assert "H's DECISION" in doc and "KEEP" in doc
    assert "transcribe.py" in doc                    # why it is not a stub
    for not_built in ("history", "paste-back", "xclip"):
        assert not_built in doc, f"the 'deliberately NOT built' list lost {not_built}"


def test_module_surface_is_one_function_and_no_new_hooks():
    """A dressing lane must not grow an API while it is being looked at: exactly
    one public callable, no listener, no class, no daemon-side polling."""
    public = sorted(name for name in vars(clipboard)
                    if not name.startswith("_")
                    and name not in {"shutil", "subprocess", "annotations"})
    assert public == ["copy_text"]
    assert len(inspect.signature(copy_text).parameters) == 2


def test_the_caller_still_treats_a_clipboard_as_optional():
    """The other half of the contract lives in A's file, so it is read, not edited:
    transcribe must keep going when copied is False."""
    src = (REPO / "src/assistant/transcribe.py").read_text()
    assert "clipboard = copy_text(" in src
    assert '"copied": False' in src
