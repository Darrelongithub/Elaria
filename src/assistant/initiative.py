"""Initiative — the knock (§19.2, as amended).

A knock is the ONLY signal that means "Elaria wants to talk". It is not an
error, not a completion, not a system event; those keep their own channels.

The amendment is load-bearing and this module enforces it:

* **NO KNOCK BUDGET.** There is no daily counter, spacing quota, or rate
  rationing anywhere in this file, and `raise_knock` never consults a clock to
  decide whether she may speak. The control is the REASON GATE: a knock requires
  a stored, citable reason. No reason → no knock, enforced by a NOT NULL CHECK in
  SQLite and by `raise_knock()` before it.
* **ANTI-PSYCHOSIS.** She never initiates because time passed. Loneliness,
  missing-you, neglect, "you haven't talked to me" and simulated emotional needs
  are rejected in knock text, console openers and generation prompts. The same
  lint runs over templates in tests, but it is not only a test: `raise_knock`
  and `opener_for()` call `ensure_not_needy()` at runtime.
* **COMMITMENTS ARE THE USER'S.** A follow-up can only cite a commitment created
  by an explicit user request or by an accepted proposal. `create_commitment`
  rejects any other origin, so she cannot invent an obligation for the user and
  then cite her own invention as a reason.

Decline means no follow-up on that topic. "Later" snoozes into commitment
memory. Ignoring the same topic three times retires it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .cost import iso_now

ALLOWED_KINDS = ("follow-up", "finding", "checkin", "urgency")
URGENCY_LEVELS = ("normal", "urgent")
COMMITMENT_ORIGINS = ("user-request", "accepted-proposal", "user-later")


class InitiativeError(RuntimeError):
    """A knock was refused (no reason, needy framing, no commitment, retired)."""


class NeedinessError(InitiativeError):
    pass


class TemporalInitiationError(InitiativeError):
    pass


# Every pattern below is a way of making TIME or HER FEELINGS the initiator.
# They are rejected in knock text, console openers and proactive prompts.
NEEDY_PATTERNS: tuple[str, ...] = (
    r"\blonel(?:y|iness)\b",
    r"\bmiss(?:ed|ing)?\s+you\b",
    r"\bi\s+miss\s+you\b",
    r"\b(?:you\s+)?haven'?t\s+(?:talked|spoken|been\s+in\s+touch)\b",
    r"\bhaven'?t\s+heard\s+from\s+you\b",
    r"\bbeen\s+a\s+while\b",
    r"\byou\s+never\s+(?:talk|call|write|visit|reply)\b",
    r"\bwhy\s+don'?t\s+you\s+talk\s+to\s+me\b",
    r"\b(?:you'?re\s+)?avoiding\s+me\b",
    r"\bneglect(?:ed|ing|ful)?\b",
    r"\bi'?ve\s+been\s+waiting\b",
    r"\bwaiting\s+for\s+you\b",
    r"\bi\s+need\s+you\b",
    r"\bi\s+get\s+lonely\b",
    r"\bnobody\s+talks\s+to\s+me\b",
    r"\bdo\s+you\s+still\s+(?:like|want|need|care\s+about)\s+me\b",
    r"\b(?:still\s+)?want\s+me(?:\s+around|\s+here|\s+to\s+help)?\b",
    r"\b(?:you\s+|did\s+you\s+)?forg[eo]t\s+about\s+me\b",
    r"\bi\s+exist\b",
    r"\byou\s+should\s+talk\s+to\s+me\b",
    r"\bi\s+(?:feel|felt)\b",
    r"\bthinking\s+about\s+you\b",
    r"\byou\s+haven'?t\s+talked\s+to\s+me\b",
    r"\byou\s+haven'?t\s+spoken\s+to\s+me\b",
    r"\b(?:things\s+have\s+been|it'?s\s+been)\s+quiet\b",
    r"\bquiet\s+(?:around\s+here|lately)\b",
    r"\bradio\s+silence\b",
    r"\bam\s+i\s+bothering\s+you\b",
    r"\bfeel(?:ing)?\s+ignored\b",
    r"\ball\s+by\s+myself\b",
    r"\btalking\s+to\s+myself\b",
)

# Time passing is not a reason. These are refused even when the sentence is
# otherwise polite, because the *initiator* is the clock.
TEMPORAL_INITIATION_PATTERNS: tuple[str, ...] = (
    r"\bit'?s\s+been\b",
    r"\bit\s+has\s+been\b",
    r"\bsince\s+we\s+(?:last\s+)?(?:spoke|talked|met|chatted)\b",
    r"\btime\s+has\s+passed\b",
    r"\blong\s+time\s+no\s+see\b",
    r"\b\d+\s+(?:minutes?|hours?|days?|weeks?)\s+(?:since|passed)\b",
    r"\blast\s+time\s+we\s+(?:spoke|talked)\b",
)

# Templates only. A knock's first line is its stored reason; these are the
# generators that may put that reason into a sentence. All are linted.
KNOCK_OPENERS: dict[str, str] = {
    "follow-up": "You asked me to chase {topic}.",
    "finding": "While working on {referent}, I found {detail}.",
    "checkin": "About {referent}: {detail}.",
    "urgency": "{referent} needs a decision now.",
}

# Prompt text for any model-assisted prose around initiative. The lint test
# scans this string, and runtime generation is prefixed with it.
INITIATIVE_PROMPT = (
    "You are Elaria. Speak only when you have a stored, citable reason: a "
    "follow-up the user set in motion, a finding from your own work, a check-in "
    "with a concrete referent, or negligence-class urgency. Never initiate "
    "because time passed. Never mention loneliness, missing the user, neglect, "
    "or any emotional need of yours. Do not simulate feelings. If there is no "
    "reason, stay silent."
)

CONSOLE_OPENER_PROMPT = (
    "Open with the stored reason as the first line. No greeting before it, no "
    "comment on how long it has been, no emotional framing."
)


def _normalise(text: str) -> str:
    return str(text or "").replace("\u2019", "'").lower()


def _topic_key(topic: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", _normalise(topic))
    return re.sub(r"\s+", " ", cleaned).strip()


def needy_framing(text: str) -> list[str]:
    """Every needy phrase found in `text` (empty list = clean)."""
    normalised = _normalise(text)
    hits: list[str] = []
    for pattern in NEEDY_PATTERNS:
        match = re.search(pattern, normalised)
        if match:
            hits.append(match.group(0))
    return hits


def temporal_initiation(text: str) -> list[str]:
    normalised = _normalise(text)
    return [match.group(0) for pattern in TEMPORAL_INITIATION_PATTERNS
            if (match := re.search(pattern, normalised))]


def ensure_not_needy(text: str, *, where: str = "text") -> None:
    hits = needy_framing(text)
    if hits:
        raise NeedinessError(
            f"refused: {where} frames an emotional need ({', '.join(hits)}). "
            "Elaria never initiates from loneliness, missing-you, neglect or any "
            "simulated feeling — the knock must carry a citable reason.")


def ensure_not_temporal(text: str, *, where: str = "reason") -> None:
    hits = temporal_initiation(text)
    if hits:
        raise TemporalInitiationError(
            f"refused: {where} makes time passing the initiator ({', '.join(hits)}). "
            "Time is not a reason; cite the follow-up, finding, referent or urgency.")


def opener_for(kind: str, *, topic: str, referent: str = "", detail: str = "") -> str:
    template = KNOCK_OPENERS.get(kind) or KNOCK_OPENERS["finding"]
    line = template.format(topic=topic, referent=referent or topic,
                           detail=detail or topic)
    ensure_not_needy(line, where="knock opener")
    ensure_not_temporal(line, where="knock opener")
    return line


@dataclass
class InitiativeService:
    config: object
    store: object
    presence: object = None
    disclosure: object = None
    sessions: object = None
    now: object = None

    def __post_init__(self):
        if self.now is None:
            self.now = datetime.now

    def _settings(self) -> dict:
        return self.config.section("initiative") if self.config else {}

    def _now(self) -> datetime:
        return self.now() if callable(self.now) else datetime.now()

    def class_mode(self) -> bool:
        if self.presence is None:
            return False
        try:
            return bool(self.presence.status().enabled)
        except Exception:
            return False

    # -- commitments: the user's, never hers -------------------------------
    def create_commitment(self, text: str, *, origin: str,
                          detail: str | None = None,
                          ts: str | None = None,
                          parent_commitment_id: int | None = None) -> dict:
        """Record an obligation. Only the user (or an accepted proposal) may."""
        if origin not in COMMITMENT_ORIGINS:
            raise InitiativeError(
                f"refused: commitments cannot originate from {origin!r}. Allowed: "
                f"{', '.join(COMMITMENT_ORIGINS)} — she cannot invent an "
                "obligation for the user and then cite it as a reason.")
        text = str(text or "").strip()
        if not text:
            raise InitiativeError("refused: a commitment needs text")
        evidence_payload: dict[str, object] = {
            "origin": origin, "detail": detail or sorted_citation(text),
        }
        if parent_commitment_id is not None:
            evidence_payload["parent_commitment_id"] = int(parent_commitment_id)
        evidence = json.dumps(evidence_payload, sort_keys=True)
        fact_id = self.store.add_fact(
            ts=ts or iso_now(), kind="commitment", text=text, source="stated",
            confidence=1.0, evidence=evidence)
        return {"commitment_id": fact_id, "text": text, "origin": origin,
                "evidence": evidence}

    def commitment(self, commitment_id: int) -> dict | None:
        for fact in self.store.list_facts(kind="commitment"):
            if int(fact["id"]) == int(commitment_id):
                return fact
        return None

    def find_commitment(self, topic: str) -> dict | None:
        needle = str(topic or "").lower().strip()
        if not needle:
            return None
        for fact in self.store.list_facts(kind="commitment"):
            if needle in str(fact["text"]).lower():
                return fact
        return None

    # -- reason gate --------------------------------------------------------
    def _validate_reason(self, *, topic: str, reason: str, kind: str,
                         referent: str | None, commitment_id: int | None) -> str:
        if kind not in ALLOWED_KINDS:
            raise InitiativeError(
                f"refused: unknown knock kind {kind!r}; allowed: {', '.join(ALLOWED_KINDS)}")
        reason = str(reason or "").strip()
        if not reason:
            raise InitiativeError(
                "refused: a knock requires a stored, citable reason. No reason → "
                "no knock (there is no budget to spend and no clock to blame).")
        if len(reason) < 8:
            raise InitiativeError("refused: a reason must be citable, not a gesture")
        ensure_not_needy(reason, where="knock reason")
        ensure_not_temporal(reason, where="knock reason")
        # Company present: a knock is aloud in the room, so a secret or private
        # plan cannot be its reason — hold it until the owner is alone.
        if (self.disclosure is not None and self.disclosure.company()
                and (self.disclosure.is_sensitive(reason)
                     or self.disclosure.is_sensitive(topic))):
            raise InitiativeError(
                "refused: the reason names a secret or private plan, and "
                "company is present. A knock is spoken aloud — hold it until "
                "you're alone.")

        if kind == "follow-up":
            if commitment_id is None:
                raise InitiativeError(
                    "refused: a follow-up knock must cite a commitment created by "
                    "the user or an accepted proposal (commitment_id required).")
            if self.commitment(int(commitment_id)) is None:
                raise InitiativeError(
                    f"refused: commitment #{commitment_id} does not exist — she "
                    "cannot invent obligations for the user.")
        elif kind in ("checkin", "finding", "urgency") and not str(referent or "").strip():
            raise InitiativeError(
                f"refused: a {kind} knock needs a concrete referent "
                "(what the reason points at), not a vague feeling.")
        return reason

    def check_due(self) -> list[dict]:
        """Follow-ups the *user* set in motion, now due.

        The commitment is the reason; elapsed time is only the calendar the
        user's own request sits on. Nothing here can initiate a knock on a
        topic the user never asked about.
        """
        raised: list[dict] = []
        for snoozed in self.store.list_knocks("snoozed", limit=100):
            until = snoozed.get("snooze_until")
            if not until:
                continue
            try:
                due = datetime.fromisoformat(until) <= self._now()
            except ValueError:
                continue
            if not due:
                continue
            commitment_id = snoozed.get("commitment_id")
            if commitment_id is None:
                # A snooze without commitment memory cannot become a reason.
                self.store.update_knock(snoozed["id"], status="retired",
                                        resolved_ts=iso_now())
                continue
            try:
                knock = self.raise_knock(
                    topic=snoozed["topic"],
                    reason=("You asked me to chase this, and it is due: "
                            f"{sorted_citation(snoozed['reason'])}"),
                    kind=snoozed["kind"], urgency=snoozed["urgency"],
                    referent=snoozed.get("referent"),
                    commitment_id=int(commitment_id))
            except InitiativeError:
                continue
            self.store.update_knock(snoozed["id"], status="accepted",
                                    resolved_ts=iso_now())
            raised.append(knock)
        return raised

    def _topic_retired(self, topic: str) -> dict | None:
        key = _topic_key(topic)
        for knock in self.store.list_knocks(status=None, limit=200):
            if _topic_key(knock["topic"]) != key:
                continue
            if knock["status"] == "declined":
                return knock            # decline = no follow-up on this topic
            if knock["status"] == "retired":
                return knock            # ignored out
            if knock["status"] == "snoozed" and knock.get("snooze_until"):
                try:
                    until = datetime.fromisoformat(knock["snooze_until"])
                except ValueError:
                    continue
                if until > self._now():
                    return knock        # "later" is a promise, not a suggestion
        return None

    # -- raise / accept / decline / later / ignore --------------------------
    def raise_knock(self, *, topic: str, reason: str, kind: str = "follow-up",
                    urgency: str = "normal", referent: str | None = None,
                    commitment_id: int | None = None) -> dict:
        topic = str(topic or "").strip()
        if not topic or not _topic_key(topic):
            raise InitiativeError("refused: a knock needs a topic to be about")
        if urgency not in URGENCY_LEVELS:
            raise InitiativeError(f"refused: urgency must be one of {URGENCY_LEVELS}")
        reason = self._validate_reason(
            topic=topic, reason=reason, kind=kind, referent=referent,
            commitment_id=commitment_id)
        retired = self._topic_retired(topic)
        if retired is not None:
            raise InitiativeError(
                f"refused: topic {topic!r} is {retired['status']} "
                f"(ignored {retired['ignore_count']}× / declined) — no follow-up "
                "on that topic unless the user asks again.")

        # CLASS MODE: initiative is urgent-only (or completely suppressed when
        # `urgent_in_class_mode` / `class_mode_urgent_only` is false). A suppressed
        # knock is not created at all; its holding stays on the shelf for later.
        settings = self._settings()
        urgent_only = bool(
            settings.get("urgent_in_class_mode", True)
            and settings.get("class_mode_urgent_only", True)
        )
        if self.class_mode() and (not urgent_only or urgency != "urgent"):
            raise InitiativeError(
                "refused: class mode restricts initiative to urgent-only. The "
                "holding remains on the shelf; nothing is announced.")

        knock_id = self.store.create_knock(
            ts=iso_now(), topic=topic, reason=reason, kind=kind,
            urgency=urgency, referent=referent, commitment_id=commitment_id)
        # A new knock on a topic that already has a pending one counts as the
        # previous one being ignored. Three and the topic retires.
        topic_k = _topic_key(topic)
        for older in self.store.list_knocks("pending", limit=200):
            if older["id"] == knock_id:
                continue
            if _topic_key(older["topic"]) == topic_k:
                self.ignore(older["id"])
        return self.get(knock_id)

    def get(self, knock_id: int) -> dict:
        knock = self.store.get_knock(int(knock_id))
        if knock is None:
            raise InitiativeError(f"no knock #{knock_id}")
        knock["silent"] = self.class_mode()
        knock["first_line"] = knock["reason"]
        return knock

    def pending(self) -> list[dict]:
        return self.store.list_knocks("pending", limit=100)

    def accept(self, knock_id: int, *, class_mode: bool | None = None,
               voice_available: bool = True) -> dict:
        knock = self.get(knock_id)
        if knock["status"] != "pending":
            raise InitiativeError(f"knock #{knock_id} is {knock['status']}")
        ts = iso_now()
        self.store.update_knock(knock_id, status="accepted",
                                resolved_ts=ts)
        class_now = self.class_mode() if class_mode is None else bool(class_mode)
        mode = ("console" if class_now or not voice_available else "voice")
        if self.sessions is not None:
            self.sessions.append("assistant", knock["reason"],
                                 channel=mode, via="knock", ts=ts)
        return {
            "knock": {**knock, "status": "accepted"},
            "open": mode,
            "first_line": knock["reason"],     # her REASON is what opens the turn
            "class_mode": class_now,
        }

    def decline(self, knock_id: int) -> dict:
        knock = self.get(knock_id)
        if knock["status"] not in ("pending", "snoozed"):
            raise InitiativeError(f"knock #{knock_id} is {knock['status']}")
        ts = iso_now()
        self.store.update_knock(knock_id, status="declined", resolved_ts=ts)
        topic_k = _topic_key(knock["topic"])
        commitment_ids: set[int] = set()
        if knock.get("commitment_id") is not None:
            commitment_ids.add(int(knock["commitment_id"]))
        # No follow-up on that topic: decline every other pending or snoozed knock
        # with the same topic too, and deactivate their commitments so check_due()
        # or future follow-ups cannot resurrect them (BH-H11).
        for other in self.store.list_knocks(status=None, limit=200):
            if _topic_key(other["topic"]) == topic_k:
                if other.get("commitment_id") is not None:
                    commitment_ids.add(int(other["commitment_id"]))
                if other["status"] in ("pending", "snoozed"):
                    self.store.update_knock(other["id"], status="declined",
                                            resolved_ts=ts)
        # Follow parent_commitment_id links created by `later()` so declining a
        # snoozed knock also deactivates the underlying commitment (BH-H11).
        if commitment_ids:
            all_facts = {
                int(f["id"]): f
                for f in self.store.list_facts(kind="commitment", active_only=False)
            }
            queue = list(commitment_ids)
            while queue:
                cid = queue.pop()
                fact = all_facts.get(cid)
                if fact and fact.get("evidence"):
                    try:
                        ev = json.loads(fact["evidence"])
                        parent_id = (
                            int(ev["parent_commitment_id"])
                            if isinstance(ev, dict)
                            and ev.get("parent_commitment_id") is not None
                            else None
                        )
                        if parent_id is not None and parent_id not in commitment_ids:
                            commitment_ids.add(parent_id)
                            queue.append(parent_id)
                    except (ValueError, TypeError):
                        pass
            with self.store._lock:
                placeholders = ", ".join("?" * len(commitment_ids))
                self.store._conn.execute(
                    f"UPDATE facts SET active = 0 WHERE id IN ({placeholders})",
                    tuple(commitment_ids),
                )
                self.store._conn.commit()
        return {"knock": self.get(knock_id), "no_followup": True,
                "note": "declined — no follow-up on this topic"}

    def later(self, knock_id: int, *, hours: float | None = None) -> dict:
        knock = self.get(knock_id)
        if knock["status"] != "pending":
            raise InitiativeError(f"knock #{knock_id} is {knock['status']}")
        hours = float(hours if hours is not None
                      else self._settings().get("snooze_hours", 24))
        until = (self._now() + timedelta(hours=hours)).isoformat(timespec="seconds")
        self.store.update_knock(knock_id, status="snoozed", snooze_until=until)
        commitment = self.create_commitment(
            f"follow up with the user: {knock['topic']}", origin="user-later",
            detail=knock["reason"],
            parent_commitment_id=knock.get("commitment_id"))
        self.store.update_knock(knock_id, commitment_id=commitment["commitment_id"])
        return {"knock": self.get(knock_id), "snoozed_until": until,
                "commitment": commitment,
                "note": "snoozed into commitment memory — she will cite it when due"}

    def ignore(self, knock_id: int) -> dict:
        knock = self.get(knock_id)
        if knock["status"] != "pending":
            raise InitiativeError(f"knock #{knock_id} is {knock['status']}")
        count = int(knock["ignore_count"]) + 1
        threshold = max(1, int(self._settings().get("retire_after_ignores", 3)))
        self.store.update_knock(knock_id, ignore_count=count)
        topic_k = _topic_key(knock["topic"])
        same_topic = [
            k for k in self.store.list_knocks(status=None, limit=200)
            if _topic_key(k["topic"]) == topic_k
        ]
        ignored_knocks = sum(
            1 for k in same_topic if int(k.get("ignore_count") or 0) > 0
        )
        should_retire = (
            count >= threshold
            or ignored_knocks >= threshold
            or any(k["status"] == "retired" for k in same_topic)
        )
        status = "retired" if should_retire else knock["status"]
        if should_retire:
            ts = iso_now()
            for k in same_topic:
                if k["status"] == "pending" and int(k["id"]) <= int(knock_id):
                    self.store.update_knock(
                        k["id"], status="retired", resolved_ts=ts
                    )
        return {"knock": self.get(knock_id), "ignore_count": count,
                "retired": status == "retired",
                "threshold": threshold}

    # -- status -------------------------------------------------------------
    def status(self) -> dict:
        pending = self.pending()
        return {
            "pending": len(pending),
            "latest": pending[-1] if pending else None,
            "budget": "none — the reason gate is the only control",
            "class_mode_urgent_only": self.class_mode(),
        }


@dataclass
class KnockSignal:
    """The dedicated knock signal: own identity, own short sound.

    Only `InitiativeService.raise_knock` calls this. Errors, completions and
    system events have their own channels and must never borrow it. In class
    mode a knock is a silent visual pulse — no popup, no sound; Waybar alone.
    """

    config: object
    runner: object = None

    def _settings(self) -> dict:
        return self.config.section("initiative") if self.config else {}

    def _run(self, argv: list[str]) -> str | None:
        """Best-effort; returns the failure text instead of raising."""
        runner = self.runner or subprocess.run
        try:
            runner(argv, check=False, timeout=5,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return None
        except Exception as exc:      # a missing desktop/player must not break
            return str(exc) or type(exc).__name__

    def emit(self, knock: dict, *, class_mode: bool) -> dict:
        settings = self._settings()
        if class_mode:
            return {"signal": "visual-pulse", "notification": False,
                    "sound": False,
                    "note": "class mode: silent visual pulse, urgent-only"}
        delivered = {"signal": "knock", "notification": False, "sound": False,
                     "identity": settings.get("notify_identity", "Elaria · knock")}
        if settings.get("notify", True) and shutil.which("notify-send"):
            error = self._run([
                "notify-send", "-a", delivered["identity"],
                "-u", "urgent" if knock.get("urgency") == "urgent" else "normal",
                "-i", "dialog-information",
                "Elaria wants to talk", str(knock.get("reason", ""))])
            delivered["notification"] = error is None
            if error:
                delivered["notification_error"] = error
        sound = str(settings.get("sound") or "")
        path = Path(sound).expanduser() if sound else None
        if path is not None and not path.exists():
            # Packaged, repo-relative fallback so a fresh checkout has a knock
            # sound before anything is installed under ~/.local/share.
            path = Path(__file__).resolve().parents[2] / "ui" / "sounds" / "knock.wav"
        if settings.get("play_sound", True) and path is not None and path.exists():
            delivered["sound_path"] = str(path)
            player = (shutil.which("pw-play") or shutil.which("paplay")
                      or shutil.which("aplay"))
            if player:
                error = self._run([player, str(path)])
                delivered["sound"] = error is None
                if error:
                    delivered["sound_error"] = error
        return delivered


def sorted_citation(text: str) -> str:
    """A stable, human-readable citable ref for a commitment's evidence."""
    return re.sub(r"\s+", " ", str(text or "")).strip()[:200]
