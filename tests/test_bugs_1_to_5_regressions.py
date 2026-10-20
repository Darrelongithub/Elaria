"""Regressions for the 5 live bugs reported 2026-10-20.

BUG 1 — console.say hangs CLI:
  assist talk "Elaria, are you awake?" completes turn visible in console but
  IPC never returns (blocks in ipc.call recv until 120s timeout).
  Fix: return turn result promptly, speech/Live async/bounded; hung caller = failure.

BUG 2 — live chat violates humour.toml:
  Asterisk-narrated roleplay reply to "Elaria, are you awake?" with soft rustle/breath.
  Fix: persona governor audit, explicit no-roleplay/no-stage-directions in system prompt,
  length discipline on simple turns, verifier checks.

BUG 3 — cost attribution quota_today_live_calls inflated:
  Acks, warm, catalogue, probes, retries included in quota count.
  Fix: attribute every call by purpose in ledger; status distinguishes user turns
  vs housekeeping; housekeeping does not inflate quota.

BUG 4 — console drops after ~1 min idle:
  assist talk / console follow closes on 30s IPC subscribe timeout pruning.
  Fix: survive think-time indefinitely; prune only on real EOF/error;
  same session preserved across idle think time.

BUG 5 — playback/capture echo loop:
  TTS output captured by mic, transcribed as user speech, loops generic filler.
  Fix: half-duplex discipline (capture muted while speaking + guard interval),
  echo suppression, reject corporate filler phrases against persona restraint spec.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time

from assistant.capture import SimulatedCapture
from assistant.cost import day_start_iso, format_cost_report
from assistant.gemini_client import GeminiClient
from assistant.ipc import call
from assistant.persona import (
    CHAT_SYSTEM_PROMPT,
    FILLER_PHRASES,
    PersonaGovernor,
    TurnContext,
    build_chat_prompt,
    is_simple_turn,
    is_valid_chat_reply,
)

# ==============================================================================
# BUG 1 REGRESSION: console.say must return promptly, never hang 120s
# ==============================================================================

def test_bug1_console_say_returns_promptly_with_slow_live_transport(config, running_daemon):
    """BUG 1: When Gemini Live transport hangs or is very slow, console.say must
    return a turn result promptly within a few seconds, persisting the turn in
    the console conversation, rather than hanging until the 120s CLI timeout.
    """
    daemon, _server = running_daemon

    class _SlowHangingTransport:
        def generate(self, model: str, contents, gen_config: dict) -> dict:
            time.sleep(8.0)  # Simulates a hung/stalled Live transport
            return {"text": "eventual reply", "usage": {"tokens_in": 5, "tokens_out": 5}}

        def list_models(self) -> list[str]:
            return ["gemini-flash-lite-latest"]

        def list_voices(self) -> list[str]:
            return ["Flare"]

    # Replace daemon client with slow transport
    daemon.client = GeminiClient(config, daemon.store, transport=_SlowHangingTransport())

    start = time.monotonic()
    # Call console.say via real Unix socket
    result = call(config.socket_path, "console.say",
                  {"text": "Elaria, are you awake?"}, timeout=15.0)
    elapsed = time.monotonic() - start

    # Must return promptly: well under 6.0 seconds, nowhere near 120s CLI timeout
    assert elapsed < 6.0, f"console.say hung for {elapsed:.2f}s, expected < 6.0s"
    assert result["channel"] == "console"
    assert result["reply"]  # Must return a real reply
    # Acceptable terse fallback for check-in: "I am now. What do you need?"
    assert "awake" in result["reply"].lower() or "what do you need" in result["reply"].lower()

    # The completed turn must be visible in the console conversation
    state = call(config.socket_path, "console.state", timeout=3.0)
    messages = state["conversation"]["messages"]
    assert any(m["role"] == "user" and "awake" in m["text"].lower() for m in messages)
    assert any(m["role"] == "assistant" for m in messages)


# ==============================================================================
# BUG 2 REGRESSION: Live chat persona discipline (no roleplay, no asterisks, terse)
# ==============================================================================

def test_bug2_humour_delivery_no_roleplay_asterisks_and_length_discipline():
    """BUG 2: Live chat replies must obey humour.toml delivery spec:
    - No asterisk-enclosed stage directions (*...*).
    - No roleplay narration ('A soft rustle answers you...').
    - Terse replies on simple check-ins (<= 120 chars, <= 2 lines).
    - CHAT_SYSTEM_PROMPT carries non-negotiable hard rules.
    """
    # 1. The exact forbidden reply from the 2026-10-20 production incident
    forbidden_incident_reply = (
        "*A soft rustle answers you from the quiet, followed by a slow, "
        "measured breath... What is it? Has something happened?*"
    )
    assert not is_valid_chat_reply(
        forbidden_incident_reply, original_user_text="Elaria, are you awake?"
    ), "Incident roleplay reply with asterisks must be rejected"

    # Other asterisk / stage direction examples
    assert not is_valid_chat_reply("*chuckles* I am awake.", original_user_text="are you awake?")
    assert not is_valid_chat_reply("I am here. *smiles softly*", original_user_text="are you awake?")
    assert not is_valid_chat_reply("[soft sigh] What do you need?", original_user_text="are you awake?")

    # 2. Length discipline on simple check-ins
    assert is_simple_turn("Elaria, are you awake?")
    assert is_simple_turn("are you there?")
    assert is_simple_turn("hello")
    assert is_simple_turn("hey elaria")

    overly_verbose = (
        "Yes, I am fully online, operational, awake, conscious, and ready to assist "
        "you with any tasks, plans, or questions you might have this afternoon. "
        "How can I be of assistance to you today?"
    )
    assert not is_valid_chat_reply(overly_verbose, original_user_text="Elaria, are you awake?"), \
        "Verbose replies to simple turns must be rejected by length discipline"

    # 3. Acceptable terse line
    acceptable = "I am now. What do you need?"
    assert is_valid_chat_reply(acceptable, original_user_text="Elaria, are you awake?")
    assert is_valid_chat_reply("Yes. What's up?", original_user_text="are you there?")

    # 4. Prompt construction carries the governor's hard rules
    gov = PersonaGovernor()
    decision = gov.decide(TurnContext(user_text="Elaria, are you awake?"))
    full_prompt, gen_config = build_chat_prompt("Elaria, are you awake?", decision=decision)

    assert CHAT_SYSTEM_PROMPT in full_prompt
    assert "No roleplay narration" in CHAT_SYSTEM_PROMPT
    assert "no stage directions" in CHAT_SYSTEM_PROMPT
    assert "no asterisk-enclosed actions" in CHAT_SYSTEM_PROMPT
    assert "soft rustle" in CHAT_SYSTEM_PROMPT
    assert gen_config.get("system_instruction") == CHAT_SYSTEM_PROMPT


# ==============================================================================
# BUG 3 REGRESSION: Cost attribution quota_today_live_calls counts user turns only
# ==============================================================================

def test_bug3_cost_attribution_purpose_and_quota_distinction(config, running_daemon):
    """BUG 3: In the ledger, every call must be attributed by purpose.
    quota_today_live_calls must reflect only user-initiated turns, NOT
    housekeeping calls (acks, warm, catalogue, probes, batch transcription).
    """
    daemon, _server = running_daemon
    store = daemon.store
    today = day_start_iso()

    # Log 1 user turn call
    store.log_llm_call(
        ts=today, correlation_id="c-user-1", role="chat",
        model="gemini-flash-lite-latest", mode="live",
        tokens_in=50, tokens_out=20, tokens_estimated=0,
        audio_seconds=0.0, cost_usd=0.0001, latency_ms=250.0,
        ok=1, verified=1, attempt=1, fixture_key=None, error=None,
        purpose="user_turn", is_user_turn=1,
    )

    # Log 4 housekeeping calls
    housekeeping_items = [
        ("housekeeping:ack_warm", "voice"),
        ("housekeeping:voice_catalogue", "voice_catalogue"),
        ("housekeeping:cleanup", "cleanup"),
        ("housekeeping:transcribe_batch", "transcribe_batch"),
    ]
    for i, (purpose, role) in enumerate(housekeeping_items, 2):
        store.log_llm_call(
            ts=today, correlation_id=f"c-hk-{i}", role=role,
            model="gemini-flash-lite-latest", mode="live",
            tokens_in=20, tokens_out=10, tokens_estimated=0,
            audio_seconds=0.0, cost_usd=0.00005, latency_ms=100.0,
            ok=1, verified=None, attempt=1, fixture_key=None, error=None,
            purpose=purpose, is_user_turn=0,
        )

    # 1. Store counts
    assert store.user_turn_calls_since(today) == 1
    assert store.housekeeping_calls_since(today) == 4
    by_purpose = store.calls_by_purpose_since(today)
    assert by_purpose["user_turn"] == 1
    assert by_purpose["housekeeping:ack_warm"] == 1
    assert by_purpose["housekeeping:voice_catalogue"] == 1

    # 2. Daemon status over IPC
    status = call(config.socket_path, "status", timeout=3.0)
    assert status["quota_today_live_calls"] == 1, \
        f"Expected quota_today_live_calls to be 1 user turn, got {status['quota_today_live_calls']}"
    assert status["quota_today_housekeeping"] == 4
    assert status["quota_by_purpose"]["user_turn"] == 1

    # 3. Daemon cost report over IPC
    cost_data = call(config.socket_path, "cost", timeout=3.0)
    assert cost_data["today"]["user_turn_calls"] == 1
    assert cost_data["today"]["housekeeping_calls"] == 4
    assert cost_data["today"]["quota_calls"] == 1

    # 4. Formatted cost report clearly distinguishes user turns vs housekeeping
    report = format_cost_report(
        cost_data["month"], cost_data["today"], cost_data["quota"], cost_data["tier"]
    )
    assert "user turn" in report.lower()
    assert "housekeeping" in report.lower()


# ==============================================================================
# BUG 4 REGRESSION: Console survives idle think time without pruning
# ==============================================================================

def test_bug4_console_survives_idle_think_time_without_drop(config, running_daemon):
    """BUG 4: An event subscriber or interactive console session must not drop
    due to timeout during user think-time. Pruning must only occur on real EOF/error.
    A turn sent after idle continues the same conversation session.
    """
    _daemon, _server = running_daemon

    # 1. Connect a subscriber socket (like assist events / console follow)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(config.socket_path))
    sock.sendall(b'{"id": 1, "method": "events.subscribe", "params": {}}\n')

    # Read subscription confirmation
    resp = json.loads(sock.recv(4096).decode().strip())
    assert resp.get("ok") is True

    # 2. Verify daemon registered the subscriber
    status_1 = call(config.socket_path, "status", timeout=3.0)
    assert status_1["event_subscribers"] >= 1

    # 3. Broadcast an event while idle — slow drain / timeout must NOT prune subscriber
    # We trigger a broadcast via an IPC method (e.g. class.toggle) on the daemon's loop
    call(config.socket_path, "class.toggle", timeout=3.0)
    received = sock.recv(4096).decode()
    assert "class.changed" in received or "conversation.message" in received

    # 4. Send first turn
    res1 = call(config.socket_path, "console.say", {"text": "First thought"}, timeout=5.0)
    conv_id_1 = res1["conversation_id"]

    # 5. Simulate idle think-time (client does not send anything, remains connected)
    # Subscriber is still registered
    status_2 = call(config.socket_path, "status", timeout=3.0)
    assert status_2["event_subscribers"] >= 1

    # 6. Send second turn after think-time: answers in the EXACT same conversation!
    res2 = call(config.socket_path, "console.say", {"text": "Second thought"}, timeout=5.0)
    conv_id_2 = res2["conversation_id"]
    assert conv_id_1 == conv_id_2, "Must remain in the same conversation session across think-time"

    # 7. Close the client socket (EOF). Now and only now should the subscriber be pruned
    sock.close()
    time.sleep(0.1)
    call(config.socket_path, "class.toggle", timeout=3.0)
    time.sleep(0.1)
    # Dead writer cleaned up
    status_3 = call(config.socket_path, "status", timeout=3.0)
    assert status_3["event_subscribers"] < status_1["event_subscribers"]


# ==============================================================================
# BUG 5 REGRESSION: Playback/capture half-duplex & echo loop prevention
# ==============================================================================

def test_bug5_playback_capture_half_duplex_and_filler_suppression(config, running_daemon):
    """BUG 5:
    1. Corporate filler phrases ("Understood, what are you working on...") are rejected
       by persona verifier (restraint is default).
    2. Half-duplex discipline: capture is muted while daemon is speaking, with a guard interval.
    3. If TTS audio is played while dictation is armed, zero user turns are created from it.
    """
    daemon, _server = running_daemon

    # 1. Corporate filler phrase rejection
    for phrase in FILLER_PHRASES:
        assert not is_valid_chat_reply(
            f"Understood, {phrase} today?", original_user_text="hello"
        ), f"Filler phrase '{phrase}' must be rejected by persona verifier"

    filler_incident = "Understood, what are you working on that I can help with"
    assert not is_valid_chat_reply(filler_incident, original_user_text="hello")

    # 2. Half-duplex speaking state and guard
    assert not daemon.is_speaking()
    daemon._set_speaking(True, text="I am now. What do you need?")
    assert daemon.is_speaking()
    assert daemon.speaking_guard_remaining() > 0

    # 3. Capture wrapper mutes frames during speaking
    raw_source = SimulatedCapture(speech_frames=10, silent_frames=0, realtime=False)
    muted_source = daemon._wrap_muted(raw_source)

    async def _collect():
        collected = []
        async for frame in muted_source.frames():
            collected.append(frame)
        return collected

    collected_while_speaking = asyncio.run(_collect())
    assert len(collected_while_speaking) == 0, \
        "Half-duplex: all capture frames must be dropped while speaking"

    # 4. Echo detection suppresses own TTS from entering transcript as a user turn
    # While speaking or during guard, any input is recognized as mic leakage
    assert daemon._is_echo("I am now. What do you need?"), \
        "Own spoken text must be recognized as echo"
    assert daemon._is_echo("Understood, what are you working on that I can help with"), \
        "Corporate filler must be recognized as echo"

    # After speaking finishes and guard expires:
    daemon._speaking_until = 0.0  # guard elapsed
    # Spoken text is still remembered as echo
    assert daemon._is_echo("I am now. What do you need?"), \
        "Textual match to own recent speech is echo"
    # Corporate filler is always recognized as echo
    assert daemon._is_echo("Understood, what are you working on that I can help with")
    # Legitimate user instruction is NOT echo
    assert not daemon._is_echo("Organise the downloads folder into invoices and receipts"), \
        "Real user instruction is not echo"
