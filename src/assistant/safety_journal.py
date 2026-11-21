"""Journal service — the unified action+observation spine (D-SAFETY).

Every *governed action* in Elaria becomes an attributable **action +
observation pair** in one append-only journal. The journal is the record
the other clusters feed: the phone sidecar's post-approve ``sms.send_sms``,
the hands rail's verified observations, a Tier-0 file move, a disclosure
``leak_blocked`` — anything a human could later ask "what did she do, who
instructed it, and how did it turn out?"

Design rules (§4.2 write-ahead intent, extended from file operations to all
governed actions):

* **One journal file, append-only, mode 0600.** Records are JSONL lines under
  ``<XDG_DATA_HOME>/assistant/journal.jsonl``. Each record is flushed +
  ``os.fsync`` before the call returns, so the intent is durable *before* the
  governed syscall runs (INVARIANTS I6: the journal is written before the
  action it records).
* **Two record kinds, exactly one pair per governed action.** ``action`` is
  written before the act; ``observation`` after. A governed action that never
  observed is an *outstanding intent* — the analogue of `operations.status ==
  'intent'` in the §4.2 safety spine — and is listed by :meth:`JournalLog.outstanding`
  and counted as a violation by :meth:`JournalLog.verify`.
* **Attribution is mandatory.** ``actor`` (the cluster or lane on whose
  authority the act happens) and a ``correlation_id`` are required; an empty
  actor is a programming error, not a default.
* **DENY BEATS CONSENT.** A policy deny is refused and journaled *even when a
  valid consent token is present*. Approval is not authorisation; consent is
  necessary, never sufficient. A deny is a hard stop.
* **Untrusted input is seen, never used.** Loading untrusted content (the
  IF-6 doctrine shared with cluster O) is itself journaled as an
  action+observation pair with outcome ``seen``; the content never enters the
  journal and never drives a tool from here.
* **Fail closed on corruption.** A line that does not parse is not skipped,
  it is raised as :class:`JournalCorrupt` with its line number — a silent
  gap in the journal is worse than a loud stop.

This module is deliberately self-contained: it writes only its own JSONL
file. The DB-backed ``operations`` journal in ``safety.py`` remains the
file-operation spine; folding this journal into the store is a hook-request
for Z (HR-D-1), never a direct edit of ``store.py``.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cost import iso_now

JOURNAL_VERSION = 1

OUTCOME_OK = "ok"
OUTCOME_FAILED = "failed"
OUTCOME_REFUSED = "refused"
OUTCOME_SEEN = "seen"
OUTCOMES = frozenset({OUTCOME_OK, OUTCOME_FAILED, OUTCOME_REFUSED, OUTCOME_SEEN})

DEFAULT_JOURNAL_NAME = "journal.jsonl"
_ACTOR_MAX = 128
_ACTION_MAX = 128
_ERROR_MAX = 500


class JournalCorrupt(RuntimeError):
    """A journal line failed to parse. Raised, never skipped (fail closed)."""

    def __init__(self, line_no: int, why: str):
        super().__init__(f"journal corrupt at line {line_no}: {why}")
        self.line_no = line_no
        self.why = why


class JournalStateError(RuntimeError):
    """The exactly-one-observation-per-action invariant would be broken."""


class Denied(Exception):
    """A policy deny fired. Consent, if any, does NOT override a deny.

    Carries the denial ``reason`` and the journaled ``action_id`` so the
    refusal is attributable and auditable after the fact.
    """

    def __init__(self, reason: str, *, action_id: str, consent_present: bool):
        super().__init__(f"denied: {reason}")
        self.reason = reason
        self.action_id = action_id
        self.consent_present = consent_present


def default_journal_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base / "assistant" / DEFAULT_JOURNAL_NAME


def deny_beats_consent(denied: bool, consent: bool) -> bool:
    """Module-level statement of the precedence rule, kept tiny on purpose.

    Returns True when the action MUST be refused. ``denied`` wins outright;
    ``consent`` is only consulted when nothing denies. There is deliberately
    no third input — no scope, no urgency, no "owner's override" flag —
    because the rule exists precisely for the moment one of those feels
    tempting.
    """
    return bool(denied)


def _clean_label(value: Any, field: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{field} must be a non-empty string (attribution is mandatory)")
    if len(text) > _ACTOR_MAX:
        raise ValueError(f"{field} exceeds {_ACTOR_MAX} chars")
    return text


def _jsonable(detail: dict | None, field: str = "detail") -> dict:
    if detail is None:
        return {}
    if not isinstance(detail, dict):
        raise TypeError(f"{field} must be a dict, got {type(detail).__name__}")
    try:
        json.dumps(detail, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field} must be JSON-serialisable: {exc}") from exc
    return detail


def _verdict(decision: Any) -> tuple[bool, str]:
    """Normalise a policy verdict: PolicyDecision-like, (bool, str), or bool."""
    if isinstance(decision, tuple):
        allowed, reason = decision
        return bool(allowed), str(reason)
    if isinstance(decision, bool):
        return decision, ("allowed by policy" if decision else "denied by policy")
    allowed = getattr(decision, "allowed", None)
    reason = getattr(decision, "reason", None)
    if allowed is None:
        raise TypeError(
            "policy must return a PolicyDecision-like object (with .allowed/.reason), "
            f"a (bool, str) tuple, or a bool — got {type(decision).__name__}")
    return bool(allowed), str(reason if reason is not None else "")


@dataclass
class GovernedAction:
    """Handle for one in-flight governed action.

    Normally you never touch this: the :func:`JournalLog.governed` context
    manager writes the observation for you on exit (``ok``, or ``failed`` if
    the body raised, and the exception propagates). Call :meth:`conclude`
    only when the outcome is known *inside* the body and differs from
    success — exactly once.
    """

    journal: JournalLog
    id: str
    actor: str
    action: str
    target: str | None
    correlation_id: str
    _concluded: bool = False

    def conclude(self, outcome: str, *, detail: dict | None = None) -> dict:
        if self._concluded:
            raise JournalStateError(
                f"action {self.id} already has its observation — "
                "exactly one observation per action is the invariant")
        record = self.journal.observe(self.id, outcome, actor=self.actor, detail=detail)
        self._concluded = True
        return record


class JournalLog:
    """Append-only action+observation journal (JSONL, fsync'd, 0600)."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else default_journal_path()

    # -- writing -------------------------------------------------------------
    def _append(self, record: dict) -> dict:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        # Tighten a pre-existing loose journal rather than refuse to run.
        if self.path.exists() and (self.path.stat().st_mode & 0o077):
            os.chmod(self.path, 0o600)
        fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, line.encode("utf-8") + b"\n")
            os.fsync(fd)
        finally:
            os.close(fd)
        return record

    def begin(self, actor: str, action: str, *, target: str | None = None,
              correlation_id: str | None = None, consent_present: bool = False,
              consent_via: str | None = None, detail: dict | None = None) -> str:
        """Write the action (intent) record BEFORE the governed act."""
        actor = _clean_label(actor, "actor")
        action = _clean_label(action, "action")[:_ACTION_MAX]
        if target is not None:
            target = str(target)
        record = {
            "v": JOURNAL_VERSION,
            "kind": "action",
            "id": f"act_{uuid.uuid4().hex}",
            "ts": iso_now(),
            "actor": actor,
            "action": action,
            "target": target,
            "correlation_id": correlation_id or f"corr_{uuid.uuid4().hex}",
            "consent_present": bool(consent_present),
            "consent_via": consent_via,
            "detail": _jsonable(detail),
        }
        self._append(record)
        return record["id"]

    def observe(self, action_id: str, outcome: str, *, actor: str | None = None,
                detail: dict | None = None) -> dict:
        """Write the observation record for ``action_id`` (exactly once)."""
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}, got {outcome!r}")
        action = self._find_action(action_id)
        if action is None:
            raise KeyError(f"no action record {action_id} — refusing to journal an orphan")
        record = {
            "v": JOURNAL_VERSION,
            "kind": "observation",
            "id": f"obs_{uuid.uuid4().hex}",
            "action_id": action_id,
            "ts": iso_now(),
            "actor": actor or action["actor"],
            "correlation_id": action["correlation_id"],
            "outcome": outcome,
            "detail": _jsonable(detail),
        }
        self._append(record)
        return record

    # -- governed execution ---------------------------------------------------
    @contextmanager
    def governed(self, actor: str, action: str, *, target: str | None = None,
                 policy: Callable[[str, str | None, dict], Any] | None = None,
                 consent: bool = False, consent_via: str | None = None,
                 consent_required: bool = False,
                 correlation_id: str | None = None,
                 detail: dict | None = None) -> Iterator[GovernedAction]:
        """Journal a governed action end-to-end: deny-check, intent, act, observe.

        Order of operations (DENY BEATS CONSENT):

        1. If ``policy`` is given, evaluate it FIRST. On deny: write the
           action+observation pair with outcome ``refused`` — consent status
           is recorded, not honoured — then raise :class:`Denied`. The act
           never runs.
        2. Else if ``consent_required`` and no consent: same refusal pair,
           raise :class:`Denied` with reason "consent required".
        3. Otherwise write the intent, yield the handle; on clean exit write
           ``ok``, on exception write ``failed`` (error type + truncated
           message, never a traceback) and re-raise.
        """
        detail = _jsonable(detail)
        correlation_id = correlation_id or f"corr_{uuid.uuid4().hex}"

        if policy is not None:
            allowed, reason = _verdict(policy(action, target, detail))
            if not allowed:
                action_id = self.begin(actor, action, target=target,
                                       correlation_id=correlation_id,
                                       consent_present=consent, consent_via=consent_via,
                                       detail=detail)
                self.observe(action_id, OUTCOME_REFUSED,
                             detail={"reason": reason, "consent_present": bool(consent),
                                     "denied": True})
                raise Denied(reason, action_id=action_id, consent_present=bool(consent))

        if consent_required and not consent:
            reason = "consent required and not present"
            action_id = self.begin(actor, action, target=target,
                                   correlation_id=correlation_id,
                                   consent_present=False, consent_via=consent_via,
                                   detail=detail)
            self.observe(action_id, OUTCOME_REFUSED,
                         detail={"reason": reason, "consent_present": False,
                                 "denied": False})
            raise Denied(reason, action_id=action_id, consent_present=False)

        action_id = self.begin(actor, action, target=target,
                               correlation_id=correlation_id,
                               consent_present=consent, consent_via=consent_via,
                               detail=detail)
        handle = GovernedAction(journal=self, id=action_id, actor=_clean_label(actor, "actor"),
                                action=action, target=target,
                                correlation_id=correlation_id)
        try:
            yield handle
        except Exception as exc:
            if not handle._concluded:
                handle.conclude(OUTCOME_FAILED, detail={
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:_ERROR_MAX]})
            raise
        else:
            if not handle._concluded:
                handle.conclude(OUTCOME_OK)

    # -- untrusted input (IF-6 doctrine, shared with cluster O) ---------------
    def note_untrusted_input(self, source: str, *, actor: str = "assistant",
                             correlation_id: str | None = None,
                             detail: dict | None = None) -> str:
        """Journal that untrusted content was *seen* — never that it was used.

        The content itself is never written to the journal. The pair records
        provenance and length only, so the audit trail shows the moment
        untrusted bytes entered the process without leaking them (or
        accidentally treating them as instructions) later.
        """
        action_id = self.begin(actor, "untrusted_input.load", target=str(source),
                               correlation_id=correlation_id,
                               detail=_jsonable(detail))
        observed = dict(detail or {})
        observed["disposition"] = "seen_never_used"
        self.observe(action_id, OUTCOME_SEEN, detail=observed)
        return action_id

    # -- reading / verification ------------------------------------------------
    def records(self) -> Iterator[dict]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise JournalCorrupt(line_no, str(exc)) from exc
                if not isinstance(record, dict) or record.get("v") != JOURNAL_VERSION:
                    raise JournalCorrupt(line_no, "missing or unsupported version field")
                if record.get("kind") not in ("action", "observation"):
                    raise JournalCorrupt(line_no, f"unknown record kind {record.get('kind')!r}")
                yield record

    def _find_action(self, action_id: str) -> dict | None:
        for record in self.records():
            if record["kind"] == "action" and record.get("id") == action_id:
                return record
        return None

    def outstanding(self) -> list[dict]:
        """Actions with no observation — crashed or refused mid-flight acts."""
        observed = {r.get("action_id") for r in self.records() if r["kind"] == "observation"}
        return [r for r in self.records()
                if r["kind"] == "action" and r["id"] not in observed]

    def pairs(self) -> list[tuple[dict, dict]]:
        """Completed (action, observation) pairs in journal order."""
        actions: dict[str, dict] = {}
        pairs: list[tuple[dict, dict]] = []
        for record in self.records():
            if record["kind"] == "action":
                actions[record["id"]] = record
            else:
                action = actions.get(record.get("action_id"))
                if action is not None:
                    pairs.append((action, record))
        return pairs

    def verify(self) -> dict:
        """Structural check of the whole journal. Binary, with numbers.

        Violations found: observations with an unknown action, actions with a
        duplicate observation, unknown/missing outcomes, or unpaired actions.
        ``ok`` is True only when there are zero violations AND every action
        has exactly one observation. An empty journal verifies clean with
        zero records — and says so, rather than implying coverage.
        """
        actions: dict[str, int] = {}
        observations = 0
        unknown_action = 0
        duplicate_observation = 0
        bad_outcome = 0
        seen: set[str] = set()
        for record in self.records():
            if record["kind"] == "action":
                actions[record["id"]] = 0
            else:
                observations += 1
                action_id = record.get("action_id")
                if action_id not in actions:
                    unknown_action += 1
                else:
                    actions[action_id] += 1
                    if action_id in seen:
                        duplicate_observation += 1
                    seen.add(action_id)
                if record.get("outcome") not in OUTCOMES:
                    bad_outcome += 1
        unpaired = sum(1 for count in actions.values() if count == 0)
        multi_observed = sum(1 for count in actions.values() if count > 1)
        violations = unknown_action + duplicate_observation + bad_outcome + unpaired
        return {
            "ok": violations == 0,
            "path": str(self.path),
            "actions": len(actions),
            "observations": observations,
            "pairs": min(len(actions) - unpaired, observations - unknown_action),
            "unpaired_actions": unpaired,
            "actions_with_multiple_observations": multi_observed,
            "observations_unknown_action": unknown_action,
            "duplicate_observations": duplicate_observation,
            "unknown_outcomes": bad_outcome,
        }
