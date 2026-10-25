"""Bug 8 + ADOPT-1: generated replies are delivered VERBATIM over the real
socket, wake phrases route locally, and every substitution is logged.

Owner repro 2026-10-20 (hardware): `assist talk "What is 2 plus 2? …"`
returned a canned check-in for EVERY question while `assist cost` showed the
calls landing (550 tokens in, ~15 out, failure count unchanged). Root cause
(BUG F): the 4 s total-turn bound cancelled
the `asyncio.to_thread(generate)` await — which does NOT stop the worker thread.
The generation completed and hit the ledger; its text was discarded and the
canned fallback was stored.

What these tests pin (all through the real Unix socket + real handlers dict):

1. A fake generation returning "Four" to "2 plus 2" yields reply "Four" —
   verbatim, and stored in the conversation as "Four".
2. "Elaria, status" / "Elaria, cost" resolve as local intents with ZERO Gemini
   calls; "Elaria" alone is a check-in; mid-sentence "Elaria" never triggers.
3. A dead transport fails fast with a TURN-AWARE fallback (never an answer to a
   question nobody asked) and the substitution is logged + surfaced in
   `assist cost`/`status`.
4. Validator rejection -> regenerate once -> best attempt delivered + logged
   with the rule hit (REJECT-2: never silently bin a successful generation).
"""

from __future__ import annotations

import time

from assistant.gemini_client import GeminiClient
from assistant.hotword import match_wake
from assistant.ipc import call
from assistant.persona import CHECKIN_REPLY, chat_reply_violation


# ---------------------------------------------------------------------------
# Generation doubles
# ---------------------------------------------------------------------------
class FakeChatTransport:
    """Scripted generation: returns the given texts in order (first repeats)."""

    def __init__(self, texts, *, per_call_s: float = 0.0):
        self.texts = list(texts)
        self.per_call_s = per_call_s
        self.calls: list[str] = []

    def generate(self, model, contents, config, on_first_token=None):
        if self.per_call_s:
            time.sleep(self.per_call_s)
        text = self.texts[min(len(self.calls), len(self.texts) - 1)]
        self.calls.append(text)
        if on_first_token is not None:
            on_first_token()
        return {"text": text, "usage": {"tokens_in": 7, "tokens_out": 3}}


class HangingChatTransport:
    """Dead transport: produces nothing within any sane deadline."""

    def __init__(self, hang_s: float = 2.0):
        self.hang_s = hang_s
        self.calls = 0

    def generate(self, model, contents, config, on_first_token=None):
        self.calls += 1
        time.sleep(self.hang_s)      # never signals on_first_token
        return {"text": "too late", "usage": {"tokens_in": 1, "tokens_out": 1}}


class StreamingChatTransport:
    """Streaming shape (the hardware SDK path): first token EARLY, then the
    rest of the generation. The first-token deadline must see progress and
    hand over to the generous total bound."""

    def __init__(self, text: str, *, first_token_s: float = 0.05,
                 total_s: float = 0.35):
        self.text = text
        self.first_token_s = first_token_s
        self.total_s = total_s

    def generate(self, model, contents, config, on_first_token=None):
        time.sleep(self.first_token_s)
        if on_first_token is not None:
            on_first_token()         # streaming: the turn has STARTED
        time.sleep(self.total_s - self.first_token_s)
        return {"text": self.text, "usage": {"tokens_in": 4, "tokens_out": 2}}


def _attach(daemon, transport) -> None:
    daemon.client = GeminiClient(daemon.config, daemon.store, transport=transport)


def _llm_call_count(daemon) -> int:
    """Every ledger row, mock included — 'zero Gemini calls' must be provable."""
    with daemon.store._lock:
        return int(daemon.store._conn.execute(
            "SELECT COUNT(*) AS n FROM llm_calls").fetchone()["n"])


# ---------------------------------------------------------------------------
# 1. End-to-end delivery: "Four" MUST reach the user
# ---------------------------------------------------------------------------
def test_bug8_four_is_delivered_verbatim_over_the_real_socket(
        config, running_daemon):
    daemon, _server = running_daemon
    transport = FakeChatTransport(["Four"])
    _attach(daemon, transport)

    result = call(config.socket_path, "console.say",
                  {"text": "Elaria, what is 2 plus 2? Answer with one word only."},
                  timeout=15.0)

    assert result["reply"] == "Four", (
        "a successful generation must be delivered verbatim — got "
        f"{result['reply']!r} via {result.get('via')!r}")
    assert result["via"] == "gemini"
    # The stored turn is the generation, not a fallback (the bug stored the
    # canned line *before* the user ever saw it).
    state = call(config.socket_path, "console.state", timeout=3.0)
    texts = [m["text"] for m in state["conversation"]["messages"]
             if m["role"] == "assistant"]
    assert "Four" in texts
    assert CHECKIN_REPLY not in texts
    # Nothing was substituted.
    status = call(config.socket_path, "status", timeout=3.0)
    assert status.get("reply_substitutions") == []
    # The ledger saw exactly one generation call.
    assert _llm_call_count(daemon) == 1


def test_bug8_plain_ask_without_wake_is_also_verbatim(config, running_daemon):
    daemon, _server = running_daemon
    _attach(daemon, FakeChatTransport(["Doing well."]))
    result = call(config.socket_path, "ask", {"text": "How are you?"}, timeout=15.0)
    assert result["reply"] == "Doing well."
    assert result["via"] == "gemini"


# ---------------------------------------------------------------------------
# 2. ADOPT-1: phrase hotword (start-anchored) routes locally, zero Gemini
# ---------------------------------------------------------------------------
def test_hotword_match_is_start_anchored_and_strips_the_wake_phrase():
    bare = match_wake("Elaria")
    hey = match_wake("hey Elaria")
    assert bare is not None and hey is not None
    assert (bare.remainder, bare.is_checkin) == (hey.remainder, hey.is_checkin) \
        == ("", True)                                    # both are check-ins
    m = match_wake("Elaria, status")
    assert m is not None and m.remainder == "status" and not m.is_checkin
    m = match_wake("Hey Elaria — what is the cost?")
    assert m is not None and m.remainder == "what is the cost?"
    # Mid-sentence mentions must NOT trigger.
    assert match_wake("What can you do, Elaria?") is None
    assert match_wake("Ask Elaria about this") is None
    # Word boundary: "Elariaish" is not the wake phrase.
    assert match_wake("Elariaish ideas") is None
    assert match_wake("") is None


def test_wake_commands_resolve_as_local_intents_with_zero_llm_calls(
        config, running_daemon):
    daemon, _server = running_daemon
    _attach(daemon, HangingChatTransport())   # any Gemini call would hang

    before = _llm_call_count(daemon)
    t0 = time.monotonic()
    status_turn = call(config.socket_path, "ask",
                       {"text": "Elaria, status"}, timeout=10.0)
    cost_turn = call(config.socket_path, "ask",
                     {"text": "Elaria, cost"}, timeout=10.0)
    checkin = call(config.socket_path, "ask",
                   {"text": "hey Elaria"}, timeout=10.0)
    elapsed = time.monotonic() - t0

    assert status_turn["via"] == "local-intent"
    assert "Running" in status_turn["reply"]
    assert cost_turn["via"] == "local-intent"
    assert "Tier" in cost_turn["reply"] or "quota" in cost_turn["reply"].lower()
    assert checkin["reply"] == CHECKIN_REPLY
    assert checkin["via"] == "local-hotword-checkin"
    # The wake strip is what makes these local: no generation ran at all.
    assert _llm_call_count(daemon) == before
    assert elapsed < 3.0, "a wake command must not wait on a generation"


def test_mid_sentence_elaria_never_triggers_the_wake_layer(
        config, running_daemon):
    daemon, _server = running_daemon
    _attach(daemon, FakeChatTransport(["I can organise, search, and listen."]))
    result = call(config.socket_path, "ask",
                  {"text": "What can you do, Elaria?"}, timeout=15.0)
    assert result["via"] == "gemini", "mid-sentence mention must not go local"
    assert result["reply"] == "I can organise, search, and listen."


# ---------------------------------------------------------------------------
# 3. Deadline: turn-aware fallback + logged substitution (BUG F)
# ---------------------------------------------------------------------------
def test_deadline_fallback_is_turn_aware_for_a_real_question(
        config, running_daemon):
    daemon, _server = running_daemon
    daemon._chat_first_token_s = 0.15
    daemon._chat_timeout_s = 0.15
    _attach(daemon, HangingChatTransport(hang_s=1.0))

    t0 = time.monotonic()
    result = call(config.socket_path, "console.say",
                  {"text": "What is 2 plus 2? Answer with one word only."},
                  timeout=10.0)
    elapsed = time.monotonic() - t0

    assert elapsed < 3.0, f"dead transport must fail fast, took {elapsed:.2f}s"
    assert result["via"] == "local-timeout-fallback"
    # TURN-AWARE: a failed arithmetic question is NEVER answered with the
    # check-in line (that is answering a different question).
    assert result["reply"] != CHECKIN_REPLY
    assert "2 plus 2" in result["reply"]      # quotes the turn it died on
    assert "timed out" in result["reply"].lower() or "moment" in result["reply"].lower()
    # Stored turn is the fallback — and the substitution is recorded.
    status = call(config.socket_path, "status", timeout=3.0)
    subs = status.get("reply_substitutions") or []
    assert any(s.get("reason", "").startswith("deadline") for s in subs), (
        f"substitution not logged: {subs}")
    logged = next(s for s in subs if s["reason"].startswith("deadline"))
    assert logged["reason"] in ("deadline:first_token", "deadline:total")
    # …and surfaced through `assist cost`.
    cost = call(config.socket_path, "cost", timeout=3.0)
    assert cost["today"].get("reply_substitutions")


def test_deadline_fallback_for_a_checkin_keeps_the_settled_line(
        config, running_daemon):
    daemon, _server = running_daemon
    daemon._chat_first_token_s = 0.15
    daemon._chat_timeout_s = 0.15
    _attach(daemon, HangingChatTransport(hang_s=1.0))
    result = call(config.socket_path, "ask",
                  {"text": "Elaria, are you awake?"}, timeout=10.0)
    # For a check-in turn the settled terse line IS the turn-aware answer.
    assert result["reply"] == CHECKIN_REPLY
    assert result["via"] == "local-timeout-fallback"


def test_slow_but_successful_generation_is_delivered_not_replaced(
        config, running_daemon):
    # A generation that STARTS (first token signals) gets the generous total
    # bound even when it is slow — verbatim, never the canned line (Bug 8).
    daemon, _server = running_daemon
    daemon._chat_first_token_s = 2.0
    daemon._chat_timeout_s = 10.0
    _attach(daemon, FakeChatTransport(["Four"], per_call_s=0.6))
    result = call(config.socket_path, "ask",
                  {"text": "What is 2 plus 2? Answer with one word only."},
                  timeout=15.0)
    assert result["reply"] == "Four"
    assert result["via"] == "gemini"


def test_streaming_first_token_hands_over_to_the_total_bound(
        config, running_daemon):
    # The BUG F shape exactly: first token lands inside the first-token
    # deadline, the full reply arrives later — delivered verbatim, and the
    # latency is bounded by the TOTAL bound, not the first-token one.
    daemon, _server = running_daemon
    daemon._chat_first_token_s = 0.2
    daemon._chat_timeout_s = 5.0
    _attach(daemon, StreamingChatTransport("Four", first_token_s=0.05,
                                           total_s=0.5))
    t0 = time.monotonic()
    result = call(config.socket_path, "ask",
                  {"text": "What is 2 plus 2? Answer with one word only."},
                  timeout=15.0)
    elapsed = time.monotonic() - t0
    assert result["reply"] == "Four"
    assert result["via"] == "gemini"
    assert elapsed >= 0.4, "the generation should have been awaited in full"
    status = call(config.socket_path, "status", timeout=3.0)
    assert status.get("reply_substitutions") == []


# ---------------------------------------------------------------------------
# 4. REJECT-2: validator rejection -> regenerate once -> best attempt + log
# ---------------------------------------------------------------------------
def test_validator_rejection_regenerates_once_and_delivers_the_retry(
        config, running_daemon):
    daemon, _server = running_daemon
    transport = FakeChatTransport(["*A soft rustle* Four", "Four"])
    _attach(daemon, transport)

    result = call(config.socket_path, "ask",
                  {"text": "What is 2 plus 2? Answer with one word only."},
                  timeout=15.0)

    assert result["reply"] == "Four"
    assert len(transport.calls) == 2, "one regeneration on rejection, not zero"
    subs = call(config.socket_path, "status", timeout=3.0)["reply_substitutions"]
    hit = [s for s in subs if s.get("reason") == "validator:asterisk"]
    assert hit, f"rejection must be logged with the rule hit: {subs}"
    assert hit[0]["original_len"] == len("*A soft rustle* Four")


def test_validator_rejection_twice_delivers_best_attempt_never_the_canned_line(
        config, running_daemon):
    daemon, _server = running_daemon
    second = "*chuckles* It is four."
    transport = FakeChatTransport(["*sigh* What do you need?", second])
    _attach(daemon, transport)

    result = call(config.socket_path, "ask",
                  {"text": "What is 2 plus 2? Answer with one word only."},
                  timeout=15.0)

    # REJECT-2: the best attempt is DELIVERED — a successful generation is
    # never silently binned, and the canned check-in line must not appear
    # for an arithmetic question.
    assert result["reply"] == second
    assert result["reply"] != CHECKIN_REPLY
    subs = call(config.socket_path, "status", timeout=3.0)["reply_substitutions"]
    rules = sorted(s.get("rule") for s in subs
                   if s.get("reason", "").startswith("validator:"))
    assert rules == ["asterisk", "asterisk"] or set(rules) == {"asterisk"}


def test_chat_reply_violation_names_the_rule():
    assert chat_reply_violation("*softly* Hi") == "asterisk"
    assert chat_reply_violation("Understood, what are you working on?") == "filler"
    assert chat_reply_violation("") == "empty"
    assert chat_reply_violation("Four") is None
    long_checkin = ("Yes! I am completely awake and fully operational and "
                    "ready for absolutely anything you need this very moment, "
                    "and I have been waiting here patiently for you to ask.")
    assert chat_reply_violation(
        long_checkin, original_user_text="are you awake?") == "verbosity"


# ---------------------------------------------------------------------------
# REJECT-1 guard: no acoustic/energy wake path may exist in the hotword layer
# ---------------------------------------------------------------------------
def test_hotword_layer_has_no_acoustic_or_energy_trigger():
    from assistant import hotword

    assert not hasattr(hotword, "EnergyScorer"), (
        "loudness-triggered activation is REJECTED (speaker-verified "
        "activation is the only authority)")
    assert hotword.match_wake("A VERY LOUD NOISE") is None
    # The layer is pure text matching over transcripts — no audio, no scorer.
    import inspect

    source = inspect.getsource(hotword)
    assert "EnergyScorer" not in source

# ---------------------------------------------------------------------------
# BUG 8b: blocking transport that completes after first-token deadline but
# within total bound must be DELIVERED (first-token applies only to streaming)
# ---------------------------------------------------------------------------
class BlockingChatTransport:
    """Hardware SDK shape: never fires on_first_token mid-generation (blocking)."""
    def __init__(self, text: str, delay: float = 0.8):
        self.text = text
        self.delay = delay
        self.calls = 0

    def generate(self, model, contents, config, on_first_token=None):
        # Do NOT call on_first_token — blocking transport
        time.sleep(self.delay)
        self.calls += 1
        return {"text": self.text, "usage": {"tokens_in": 4, "tokens_out": 2}}


def test_blocking_transport_late_but_within_total_is_delivered(config, running_daemon):
    """BUG 8b regression: blocking fake transport whose on_first_token never
    fires but completes at ~0.8s must be delivered, not substituted. Real
    hardware showed \"Four\" at 8s after 5s first-token deadline was logged
    instead of delivered because first-token was treated as hard deadline.
    """
    daemon, _server = running_daemon
    daemon._chat_first_token_s = 0.3
    daemon._chat_timeout_s = 2.0
    _attach(daemon, BlockingChatTransport("Four", delay=0.8))

    t0 = time.monotonic()
    result = call(config.socket_path, "ask",
                  {"text": "What is 2 plus 2? Answer with one word only."},
                  timeout=10.0)
    elapsed = time.monotonic() - t0
    assert result["reply"] == "Four", f"blocking late generation must be delivered, got {result!r}"
    assert result["via"] == "gemini"
    assert elapsed >= 0.7, "should have awaited the blocking generation"
    assert elapsed < 2.5, "should have delivered within total bound"
    # Must NOT be counted as a substitution (not delivered)
    status = call(config.socket_path, "status", timeout=3.0)
    assert status.get("reply_substitutions") == [], f"late delivered should not be a substitution, got {status.get('reply_substitutions')}"
    # But it should be marked late in the log (reply_late)
    late = daemon.store.list_persona_events(kind="reply_late", limit=5)
    assert late, "late delivery must be marked in log"
    assert any("first_token" in (r.get("detail") or "") for r in late)
