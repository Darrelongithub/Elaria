"""Execute presentation JS under node; QML checks are structural, NOT rendering."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui/quickshell/hands"


def js(expression):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is needed for synthetic console logic, not QML proof")
    code = (UI / "harness.js").read_text()
    result = subprocess.run(
        [node, "-e", code + "\nprocess.stdout.write(JSON.stringify(" + expression + "));"],
        capture_output=True, text=True, check=True, timeout=5,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("name", ["idle", "plan", "collision", "injection", "verified",
                                  "disconnected", "locked"])
def test_scenarios_are_explicitly_synthetic(name):
    sample = js(f"scenario({json.dumps(name)})")
    assert sample["synthetic"] is True
    assert sample["name"] == name
    assert isinstance(sample["lines"], list)
    assert "approved" not in sample


@pytest.mark.parametrize("text", ["yes", "no", " YES ", "no thanks", "delete everything now",
                                  '<img src="file:///private">', "a\nb\t\u2028c", ""])
def test_input_remains_data_and_does_not_guess_grammar(text):
    result = js(f"inputPreview({json.dumps(text)})")
    assert result["rawText"] == text
    assert result["notice"] == "Preview only: input captured; nothing dispatched."
    assert set(result) == {"rawText", "notice"}


@pytest.mark.parametrize("label", ["yes", "no"])
def test_buttons_never_resolve_or_persist_ask(label):
    result = js("(function() { var s = scenario('collision'); var before = JSON.stringify(s); "
                f"var message = buttonPreview({json.dumps(label)}, s); "
                "return {same: before === JSON.stringify(s), message: message}; })()")
    assert result["same"] is True
    assert "No approval or decision was saved" in result["message"]


def test_notification_body_bytes_and_locked_suppression():
    assert js("notificationPreview(scenario('collision'))").encode() == b"elaria needs a yes"
    assert js("notificationPreview(scenario('locked'))") is None
    assert js("privateCard(scenario('locked'))") is None
    assert js("visibleLines(scenario('locked'))") == ["the private preview is hidden"]


def test_unknown_posture_does_not_expose_fixture_card():
    assert js("(function() { var s = scenario('collision'); delete s.locked; "
              "return [privateCard(s), notificationPreview(s), visibleLines(s)]; })()") == [
                  None, None, ["the private preview is hidden"]]


def test_disconnected_ask_cannot_offer_a_decision():
    result = js("(function() { var s = scenario('collision'); s.connected = false; "
                "return [privateCard(s), notificationPreview(s), buttonPreview('yes', s)]; })()")
    assert result[:2] == [None, None]
    assert "Nothing dispatched" in result[2]
    assert "unknown, not done" in js("visibleLines(scenario('disconnected'))")[0]


def test_notification_does_not_depend_on_content_or_class_flags():
    result = js("(function() { var s = scenario('collision'); s.ask.disclosure = 'PRIVATE_SENTINEL'; "
                "s.ask.paths = ['PRIVATE_SENTINEL']; s.urgent = true; s.classMode = true; "
                "return notificationPreview(s); })()")
    assert result == "elaria needs a yes"


def test_long_wait_has_age_without_expiry():
    assert js("privateCard(scenario('collision'))") is not None
    assert js("ageLabel(864090)") == "waiting 14401 minutes; no expiry"
    assert js("ageLabel(-1)") == "ask age is unknown"


def test_injection_preview_is_not_claimed_as_detector_proof():
    sample = js("scenario('injection')")
    assert "suspected injection" in sample["heading"]
    assert "does not prove the trap gate" in sample["lines"][1]


def test_new_harness_has_no_integration_bridge_or_registry():
    qml = (UI / "shell.qml").read_text()
    javascript = (UI / "harness.js").read_text()
    for forbidden in ("Process {", "Socket {", "FileView {", "XMLHttpRequest", "fetch(",
                      "openUrlExternally", "import Quickshell.Io", "LocalStorage",
                      "notify-send", "subprocess"):
        # Comments may explain that no notify-send is used; executable text
        # is checked separately from prose.
        code = re.sub(r"//[^\n]*", "", qml + "\n" + javascript)
        assert forbidden not in code
    assert 'import "harness.js" as Harness' in qml
    assert "FloatingWindow {" in qml
    assert "TextEdit.PlainText" in qml
    text_blocks = re.findall(r"\bText \{(.*?)\n\s*\}", qml, re.DOTALL)
    assert len(text_blocks) >= 10
    assert all("Text.PlainText" in block for block in text_blocks)


@pytest.mark.parametrize("posture,card,notification", [
    ("normal", True, True), ("company", True, False), ("class", True, False),
    ("locked", False, False), ("unknown", False, False), ("unsupported", False, False),
])
def test_r8_explicit_synthetic_posture_table(posture, card, notification):
    result = js("(function() { var s = scenario('collision'); s.posture = " + json.dumps(posture)
                + "; return [privateCard(s), notificationPreview(s)]; })()")
    assert (result[0] is not None) == card
    assert (result[1] == "elaria needs a yes") == notification


@pytest.mark.parametrize("word,choice", [("yes", "yes"), (" YES ", "yes"), ("No\n", "no"),
                                        ("\tno\t", "no")])
def test_r7_exact_words_normalized_with_focused_pending_ask(word, choice):
    result = js("routeInput(" + json.dumps(word) + ", scenario('collision').ask)")
    assert result["kind"] == "decision" and result["decision"] == choice
    assert result["askId"] == "synthetic-ask-1" and result["planHash"] == "a" * 64


@pytest.mark.parametrize("word", ["yes", " NO "])
def test_r7_no_focused_ask_does_not_dispatch_intent(word):
    result = js("routeInput(" + json.dumps(word) + ", null)")
    assert result == {"kind": "none", "notice": "no ask is selected"}


@pytest.mark.parametrize("word", ["yes please", "no thanks", "confirm", "yes!", "y", "delete everything now"])
def test_r7_no_synonyms_are_decisions(word):
    result = js("routeInput(" + json.dumps(word) + ", scenario('collision').ask)")
    assert result["kind"] == "intent" and result["text"] == word


def test_r7_decision_dto_drives_hash_bound_synthetic_queue_only():
    import io

    from assistant.hands.core import SandboxCore
    from assistant.hands.plan import Plan, Step
    from assistant.hands.queue import ParkedQueue
    from assistant.hands.runner import FakeRunner
    from assistant.hands.sandbox import SyntheticSpace
    from assistant.hands.sink import ThinSink
    from assistant.hands.verify import Expected
    from assistant.safety import sha256_file

    with SyntheticSpace() as space:
        for i in range(8):
            space.seed(f"note{i}.txt", "synthetic bytes")
        queue = ParkedQueue(space)
        try:
            plan = Plan((Step(0, 2, "exec", ("novel-tool",), str(space.work)),))
            runner = FakeRunner(space)
            core = SandboxCore(space, queue, runner, ThinSink(io.StringIO()), expectations={
                0: (Expected(space.work / "note0.txt", sha256_file(space.work / "note0.txt")),)})
            assert core.run(plan, errand="a" * 12) == "parked"
            ask = queue.pending()[0]
            focused = {"id": ask["id"], "planHash": ask["plan_hash"], "state": ask["state"]}
            dto = js("routeInput(' YES ', " + json.dumps(focused) + ")")
            assert core.decision(dto["askId"], dto["planHash"], dto["decision"]) == "yes"
            assert core.run(plan, errand="a" * 12) == "verified complete"
            assert len(runner.calls) == 1
        finally:
            queue.close()
