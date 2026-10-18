"""Persona engine — a GOVERNOR, not a comedian (§13.2).

Hard rules encoded here:
- There is no joke bank. There will never be a joke bank. This module
  contains zero canned humorous lines and never returns joke *text*; it
  returns *permissions and registers*. Wit, when it happens at all, is
  contextual phrasing by a model call that was already happening.
- Restraint is the default. The governor's most frequent humour decision
  is "not now". Silence is a valid, common output.
- No humour-only model calls. Routine work gets plain, factual narration
  built from real task state (counts, tiers, confidence) — never filler.
- Serious-gates come from humour.toml [serious_gates], not from copies
  hardcoded here; if the profile is missing, fall back to restraint.
- Tone is read from the WRITING (humour.toml [tone]): absolutes, CAPS
  bursts, ellipsis pauses, burst length, direct address. Emoji is never
  read as a signal and never used in output (owner instruction).
- The ack path (§18) lives here and is pure local code: no network, no
  model, <300ms by construction.

Phase 0 scope: governor skeleton with state (familiarity, pushback
budget), serious-gates, tone reading, factual narration, local ack.
Expressive-voice wiring arrives with conversation surfaces (Phase 1+).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from datetime import time as dtime

# humour.toml serious-gate keys -> context flags that trip them.
# (Mapping only; the gate *list* itself is read from the profile.)
GATE_TRIGGERS: dict[str, str] = {
    "user-stressed-or-upset": "user_stressed",
    "money-health-family-topics": "sensitive_topic",
    "hard-no-or-safety-refusal": "safety_refusal",
    "destructive-action-pending-confirmation": "destructive_pending",
    "error-or-data-loss": "error",
    "user-gives-a-direct-order-twice": "direct_order_twice",
}

DEFAULT_SERIOUS_GATES = list(GATE_TRIGGERS)

_ABSOLUTES = {"always", "never", "everyone", "everything", "nothing", "nobody"}


@dataclass
class ToneSignals:
    """What the writing itself says — no emoji, ever ([tone].read_from)."""

    caps_burst: bool = False          # raised voice / mock outrage
    ellipsis_pause: bool = False      # pause before a verdict
    incredulous_challenge: bool = False  # "???"
    playful_absolutes: int = 0        # always/never/everyone = exaggeration
    very_short: bool = False          # one-beat reaction (banter energy)
    direct_address: bool = False      # you/u/wewe aimed at someone
    codeswitch_beat: bool = False     # Swahili/Sheng tag marking the joke

    @property
    def banter_energy(self) -> bool:
        return bool(self.caps_burst or self.incredulous_challenge
                    or self.playful_absolutes or self.codeswitch_beat)


_CODESWITCH_MARKERS = {"sasa", "alafu", "kwanza", "mbona", "sijui", "unajua", "wewe", "apana"}


def read_tone(text: str) -> ToneSignals:
    """Read tone the way a person reads a text: from the writing.

    Emoji and other symbols are ignored entirely — they are stripped
    before analysis so they can neither create nor mask a signal.
    """
    plain = "".join(ch for ch in text if ch.isalnum() or ch in " .?…!,'-")
    words = re.findall(r"[A-Za-z']+", plain)
    lowered = [w.lower() for w in words]
    alpha_words = [w for w in words if len(w) >= 3]
    caps_ratio = (sum(1 for w in alpha_words if w.isupper()) / len(alpha_words)
                  if alpha_words else 0.0)
    return ToneSignals(
        caps_burst=caps_ratio >= 0.5 and bool(alpha_words),
        ellipsis_pause=("…" in text) or ("..." in text),
        incredulous_challenge="??" in text,
        playful_absolutes=sum(1 for w in lowered if w in _ABSOLUTES),
        very_short=len(text.strip()) <= 12,
        direct_address=any(w in {"you", "u", "wewe"} for w in lowered),
        codeswitch_beat=any(w in _CODESWITCH_MARKERS for w in lowered),
    )


@dataclass
class TurnContext:
    """Everything the governor may consider about *this* moment."""

    user_text: str = ""
    user_stressed: bool = False
    sensitive_topic: bool = False
    safety_refusal: bool = False
    destructive_pending: bool = False
    error: bool = False
    direct_order_twice: bool = False
    # A genuinely funny opening exists in this moment (this file, this
    # hour, shared history). Judged by callers with real state; the
    # governor can only veto, never manufacture one.
    real_opportunity: bool = False
    strange_hour: bool = False  # e.g. bulk rename at 1am — pushback evidence


@dataclass
class Decision:
    speak: bool                       # should it say anything unprompted?
    register: str                     # plain | expressive-allowed
    serious_gate: str | None          # humour.toml gate that fired, if any
    pushback: str                     # none | taste | pushback | hard-no (§13.3)
    reason: str                       # evidence, always — vibes-based nagging is banned
    teasing_licence: str = "none"     # none | tease | roast (earned, §13.7)


def _parse_quiet_hours(spec: str) -> tuple[dtime, dtime] | None:
    try:
        start_s, end_s = spec.split("-")
        parse = lambda s: dtime(int(s.split(":")[0]), int(s.split(":")[1]))
        return parse(start_s), parse(end_s)
    except Exception:
        return None


@dataclass
class PersonaGovernor:
    profile: dict = field(default_factory=dict)
    candour: float = 0.7
    verbosity: str = "normal"
    quiet_hours: str = "23:00-07:00"
    pushback_budget_per_day: int = 5
    proactive_max_per_day: int = 3
    # Relationship state (§13.1.4, §16): grows over time; roasting unlocks
    # with shared history, like a real friendship.
    familiarity: float = 0.0          # 0..1
    pushback_used_today: int = 0
    proactive_used_today: int = 0
    overrides_in_a_row: int = 0       # user quiet/overriding -> dial down

    @classmethod
    def from_config(cls, config, profile: dict) -> PersonaGovernor:
        persona = config.section("persona")
        return cls(
            profile=profile,
            candour=float(persona.get("candour", 0.7)),
            verbosity=str(persona.get("verbosity", "normal")),
            quiet_hours=str(persona.get("quiet_hours", "23:00-07:00")),
            pushback_budget_per_day=int(persona.get("pushback_budget_per_day", 5)),
            proactive_max_per_day=int(persona.get("proactive_max_per_day", 3)),
        )

    # -- serious gates -------------------------------------------------------
    def active_gate(self, ctx: TurnContext) -> str | None:
        gates = (self.profile.get("serious_gates", {}).get("no_jokes_when")
                 or DEFAULT_SERIOUS_GATES)
        for gate in gates:
            flag = GATE_TRIGGERS.get(gate)
            if flag and getattr(ctx, flag, False):
                return gate
        return None

    def in_quiet_hours(self, now: datetime | None = None) -> bool:
        window = _parse_quiet_hours(self.quiet_hours)
        if window is None:
            return False
        start, end = window
        current = (now or datetime.now()).time()
        return start <= current or current < end if start > end else start <= current < end

    # -- the decision ---------------------------------------------------------
    def decide(self, ctx: TurnContext, *, now: datetime | None = None) -> Decision:
        gate = self.active_gate(ctx)
        if ctx.safety_refusal:
            return Decision(True, "plain", gate, "hard-no",
                            "safety spine refusal — non-negotiable, explain the rule (§13.3)")
        if gate:
            return Decision(True, "plain", gate, "none",
                            f"serious-gate '{gate}' active — humour off, no exceptions")
        if ctx.destructive_pending:
            return Decision(True, "plain", gate, "pushback",
                            "destructive action awaiting confirmation — state facts only")
        if ctx.strange_hour and self.pushback_used_today < self.pushback_budget_per_day:
            return Decision(True, "plain", None, "pushback",
                            "evidence: the clock — bulk/irreversible work at this hour "
                            "is against the user's own track record; offer the safer "
                            "version, accept a deliberate override")
        if self.in_quiet_hours(now) and not ctx.user_text:
            return Decision(False, "plain", None, "none",
                            "quiet hours and nothing was asked — stay silent (§13.5)")

        tone = read_tone(ctx.user_text) if ctx.user_text else ToneSignals()
        # Teasing/roasting licence: earned by familiarity, aimed only at
        # observable behaviour, withdrawn when the user stops volleying.
        licence = "none"
        if self.overrides_in_a_row < 2:
            if self.familiarity >= 0.6:
                licence = "roast"
            elif self.familiarity >= 0.2:
                licence = "tease"

        # The quality gate (humour.toml): if unsure it lands, stay silent.
        # Expression requires a REAL opening in this moment AND matching
        # energy — banter_mode = match-user, never perform at them.
        if ctx.real_opportunity and (tone.banter_energy or licence != "none"):
            return Decision(True, "expressive-allowed", None, "none",
                            "real situational opening + matching register; phrasing is "
                            "the expressive voice's job, in this moment only — if the "
                            "line could be said to anyone, it is banned",
                            teasing_licence=licence)
        return Decision(True, "plain", None, "none",
                        "no genuine opening — restraint is the default; a missed "
                        "silence is invisible, a forced joke is not",
                        teasing_licence=licence)

    # -- feedback loop (§13.7: wit is tuned, not prompted) ---------------------
    def note_user_reaction(self, reaction: str) -> None:
        """reaction: riffed | ignored | overrode | not-funny"""
        if reaction == "riffed":
            self.familiarity = min(1.0, self.familiarity + 0.02)
            self.overrides_in_a_row = 0
        elif reaction in ("ignored", "overrode"):
            self.overrides_in_a_row += 1
        elif reaction == "not-funny":
            self.overrides_in_a_row += 2
            self.familiarity = max(0.0, self.familiarity - 0.05)

    # -- factual narration: facts may vary mechanically, never gagged up -------
    def narrate_fact(self, event: str, data: dict) -> str:
        """Transparent reasoning from real task state (§13.1.1).

        Templates exist ONLY for facts. Numbers must come from `data`;
        unknown events degrade to a plain key-value summary.
        """
        if event == "organise.summary":
            return (f"Sorted {data.get('filed', 0)} files; "
                    f"{data.get('review', 0)} need your review, "
                    f"{data.get('unsorted', 0)} parked in _Unsorted.")
        if event == "transcribe.done":
            return (f"Transcript saved ({data.get('words', 0)} words, "
                    f"{data.get('seconds', 0):.0f}s of audio). Raw audio kept.")
        if event == "plan.proposed":
            return (f"Plan ready: {data.get('ops', 0)} operation(s) across "
                    f"{data.get('roots', 1)} root(s). Nothing has moved.")
        summary = ", ".join(f"{k}={v}" for k, v in sorted(data.items()))
        return f"{event}: {summary}" if summary else event

    # -- local ack (§18: <300ms, NOTHING on this path touches the network) -----
    def ack(self) -> dict:
        """Instant local acknowledgement descriptor.

        Phase 0 has no TTS yet (Piper-class voice-out is Phase 2), so the
        ack is a local state/event the UI renders (Waybar/overlay pulse,
        later a cached earcon). What matters architecturally is already
        true: this call is pure in-process code — no socket, no model,
        no disk wait beyond the caller's event log.
        """
        return {"ack": True, "kind": "local", "network": False, "budget_ms": 300}
