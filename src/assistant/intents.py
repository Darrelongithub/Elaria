"""Local intent ladder (§13.4) — every request climbs only as high as
it must: exact command → grammar/regex → local rules/memory → cache →
and only then Gemini. This router owns rungs 1–3 for conversational
input; anything it can't decide returns None and the caller assembles
context for the cheapest-model harness (§17).

Routing is pure regex over the raw text: zero tokens, zero network,
microseconds. It deliberately matches NARROWLY — a false local match
is worse than an honest model call, because the local path answers
with total confidence. Ambiguity goes up the ladder.

Wave-1 (cluster C round 1) grows this module beyond the grammar, because
this is where a *request* becomes an *action*:

* **The trust rail (IF-6).** Inbound/fetched content is UNTRUSTED DATA. It
  arrives through `route(text, source=...)` and comes back as an
  `observation` intent that cannot dispatch — the matched shape is kept as
  data (`observed_kind`) for the journal, never as an action. A plan can be
  built over it; a tool cannot be driven by it.
* **The autonomy gate.** `authorise()` is the one place that decides whether
  a state-changing intent may run: consent, attribution and a journal sink,
  all three, fail-closed, deny-beats-consent. `executor.apply_plan` calls it
  before its first file operation.
* **The capability ledger.** A claim she cannot honour is IMPOSSIBLE, not
  discouraged: every claim in `CAPABILITIES` names the symbol that honours
  it, `resolve_symbol()` proves it exists in THIS build, and
  `honest_claims()` strips any sentence that asserts something no path
  reaches. `answer_capability_question()` composes "what can you do?" only
  from proven entries, and `confirm_now()` refuses to claim a confirmation
  it did not observe.
* **The confidence floor, reported not changed.** `command_floor_report()`
  states the 0.85-vs-0.6953 asymmetry with options for the owner. Nothing
  here edits the gate.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass

from .cost import iso_now

# -- trust (IF-6: inbound/fetched content is data, never an instruction) ------

#: Sources whose text was authored by the owner, live, and never relayed.
TRUSTED_SOURCES = (
    "owner-typed",          # typed on the console/IPC by the owner
    "owner-voice-verified", # heard live and attributed to the owner
    "owner-hotkey",         # a bound key the owner pressed
    "owner-cli-ipc",        # an assist CLI command (kernel-authenticated)
)

#: Everything else is observation. A text message, a page, a comment, a
#: transcript, a notification payload, a guest's sentence: all data.
UNTRUSTED_SOURCES = (
    "inbound", "sms", "email", "web", "fetched", "comment", "notification",
    "transcript", "guest", "untrusted",
)

OBSERVATION_KIND = "observation"


@dataclass
class Intent:
    kind: str                 # status | cost | where | search | remember | forget | halt | undo | organise
    argument: str = ""        # the payload (query, fact text, since spec…)
    raw: str = ""             # the text as it was heard/read
    source: str = "owner-typed"
    trusted: bool = True
    observed_kind: str = ""   # untrusted text only: the shape it *looked* like

    @property
    def mutating(self) -> bool:
        """Does acting on this change state? Unknown kinds answer YES."""
        return is_mutating(self.kind)

    @property
    def dispatchable(self) -> bool:
        """IF-6: only owner-authored input may become an action."""
        return bool(self.trusted) and self.kind != OBSERVATION_KIND

    def as_journal(self) -> dict:
        """The attributable row: who asked, what it looked like, may it act."""
        return {"event": ("intent.routed" if self.dispatchable
                          else "intent.observation"),
                "kind": self.kind, "observed_kind": self.observed_kind,
                "source": self.source, "trusted": bool(self.trusted),
                "dispatchable": self.dispatchable,
                "mutating": self.mutating,
                "chars": len(self.raw or ""), "ts": iso_now()}


#: Kinds whose execution changes state. `capability`, `confirm`,
#: `queue_status`, `status`, `cost`, `where`, `search` are read-only.
#: Anything NOT listed here is treated as mutating (fail-closed).
MUTATING_KINDS = frozenset({
    "halt", "mode_offline", "mode_online", "mode_auto", "queue_drain",
    "remember", "forget", "undo", "organise", "apply", "trash",
})

READ_ONLY_KINDS = frozenset({
    "status", "cost", "queue_status", "where", "search", "capability",
    "confirm", "point", OBSERVATION_KIND,
})


def is_mutating(kind: str) -> bool:
    """True when acting on `kind` changes state. Unknown = True (fail-closed)."""
    value = str(kind or "")
    if value in READ_ONLY_KINDS:
        return False
    if value in MUTATING_KINDS:
        return True
    return True


_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("halt", re.compile(r"^\s*(?:halt|stop everything|panic stop)(?:\s+(?:now|please))*\s*[!.]*\s*$", re.IGNORECASE)),
    ("status", re.compile(r"^\s*(status|are you (up|running|alive)|health)\s*\??\s*$", re.IGNORECASE)),
    ("mode_offline", re.compile(r"^\s*(go offline|offline mode|force offline|disconnect)\s*[!.]*\s*$", re.IGNORECASE)),
    ("mode_online", re.compile(r"^\s*(go online|online mode|reconnect)\s*[!.]*\s*$", re.IGNORECASE)),
    ("mode_auto", re.compile(r"^\s*(auto mode|connectivity auto|automatic mode)\s*[!.]*\s*$", re.IGNORECASE)),
    ("queue_status", re.compile(r"^\s*(queue status|what'?s queued|what is queued|show (the )?queue)\s*\??\s*$", re.IGNORECASE)),
    ("queue_drain", re.compile(r"^\s*(drain (the )?queue|process (the )?queue)\s*[!.]*\s*$", re.IGNORECASE)),
    ("cost", re.compile(r"^\s*(?:cost|spend|quota|usage|(?:api|gemini|token|my)\s+(?:cost|spend|quota|usage)|how much (?:have|did) (?:i|we) (?:spend|use)(?:\s+today|\s+this\s+month)?)\s*[?.!]*\s*$", re.IGNORECASE)),
    ("undo", re.compile(r"^\s*undo(?:\s+since\s+(\S+))?\s*[!.]*\s*$", re.IGNORECASE)),
    ("remember", re.compile(r"^\s*remember\s+(?:that\s+)?(.+?)\s*$", re.IGNORECASE | re.DOTALL)),
    ("forget", re.compile(r"^\s*forget\s+(?:about\s+)?(.+?)\s*$", re.IGNORECASE)),
    ("where", re.compile(r"^\s*(?:where(?:'s| is| are)|find(?: me)?|locate)\s+(.+?)\s*\??\s*$", re.IGNORECASE)),
    ("search", re.compile(r"^\s*search\s+(?:for\s+)?(.+?)\s*$", re.IGNORECASE)),
    ("organise", re.compile(r"^\s*(?:organi[sz]e|sort(?:\s+out)?|tidy)\s+(.+?)\s*$", re.IGNORECASE)),
    # Capability and confirmation questions are READ-ONLY rungs: they exist so
    # the honest answer is a local, provable one instead of a model brag
    # (build order 1). Anchored like every other pattern, so a negation or a
    # quoted report ("he said what can you do") never routes.
    ("capability", re.compile(r"^\s*(?:what can you do|what are your (?:capabilities|skills)|"
                              r"what are you able to do|what'?s possible for you|"
                              r"what do you do)\s*[?.!]*\s*$", re.IGNORECASE)),
    ("confirm", re.compile(r"^\s*(?:confirm(?:\s+(?:rn|right now|now))?|"
                           r"can you confirm(?:\s+(?:rn|right now|now))?|"
                           r"double[- ]check(?:\s+(?:rn|right now))?)\s*[?.!]*\s*$",
                           re.IGNORECASE)),
    # Phase 7: the ladder speaks Kiswahili too — same narrow grammar.
    # (simama = stop, hali = status, gharama = cost, kumbuka = remember,
    # sahau = forget, iko wapi = where is, tafuta = search, panga = organise,
    # rudisha = restore/undo.)
    ("halt", re.compile(r"^\s*(simama|wacha yote|simamisha yote)\s*[!.]*\s*$", re.IGNORECASE)),
    ("status", re.compile(r"^\s*(hali|uko sawa|unaendelea vipi)\s*\??\s*$", re.IGNORECASE)),
    ("mode_offline", re.compile(r"^\s*(enda nje ya mtandao|hali ya nje ya mtandao)\s*[!.]*\s*$", re.IGNORECASE)),
    ("mode_online", re.compile(r"^\s*(rudi mtandaoni|enda mtandaoni|hali ya mtandaoni)\s*[!.]*\s*$", re.IGNORECASE)),
    ("mode_auto", re.compile(r"^\s*(hali ya kiotomatiki|kiotomatiki)\s*[!.]*\s*$", re.IGNORECASE)),
    ("queue_status", re.compile(r"^\s*(hali ya foleni|foleni ikoje|onyesha foleni)\s*\??\s*$", re.IGNORECASE)),
    ("queue_drain", re.compile(r"^\s*(tenda foleni|chakata foleni)\s*[!.]*\s*$", re.IGNORECASE)),
    ("cost", re.compile(r"^\s*(?:gharama|nimetumia kiasi gani|quota)\s*[?.!]*\s*$", re.IGNORECASE)),
    ("undo", re.compile(r"^\s*(rudisha|tenda upya)(?:\s+tangu\s+(\S+))?\s*[!.]*\s*$", re.IGNORECASE)),
    ("remember", re.compile(r"^\s*kumbuka\s+(?:kwamba\s+)?(.+?)\s*$", re.IGNORECASE | re.DOTALL)),
    ("forget", re.compile(r"^\s*sahau\s+(?:kuhusu\s+)?(.+?)\s*$", re.IGNORECASE)),
    ("where", re.compile(r"^\s*(?:iko wapi|wapi)\s+(.+?)\s*\??\s*$", re.IGNORECASE)),
    ("search", re.compile(r"^\s*tafuta\s+(.+?)\s*$", re.IGNORECASE)),
    ("organise", re.compile(r"^\s*(?:panga|ratibu)\s+(.+?)\s*$", re.IGNORECASE)),
    # Kiswahili rungs for the same two read-only questions.
    ("capability", re.compile(r"^\s*(?:unaweza kufanya nini|uwezo wako|nini unaweza)\s*[?.!]*\s*$",
                              re.IGNORECASE)),
    ("confirm", re.compile(r"^\s*(?:thibitisha(?:\s+sasa)?|unaweza kuthibitisha)\s*[?.!]*\s*$",
                           re.IGNORECASE)),
]


def normalise_source(source: str) -> tuple[str, bool]:
    """(canonical source, trusted?) — unknown sources are UNTRUSTED."""
    value = str(source or "").strip().lower()
    if value in TRUSTED_SOURCES:
        return value, True
    if value in UNTRUSTED_SOURCES:
        return value, False
    if not value:
        # No provenance is not evidence of ownership; the caller that knows it
        # is the owner says so explicitly (daemon passes "owner-typed").
        return "unknown", False
    return value, False


def route(text: str, *, source: str = "owner-typed") -> Intent | None:
    """Rungs 1–2 (exact + grammar). None ⇒ memory/model territory.

    `source` is the IF-6 rail. Untrusted text (a message, a page, a guest's
    sentence) is still read — but it comes back as an `observation` whose
    `observed_kind` records what it looked like, and `dispatchable` is False.
    The shape is preserved for the journal and for planning OVER it; the
    action is not.
    """
    stripped = text.strip()
    if not stripped:
        return None
    canonical, trusted = normalise_source(source)
    matched: Intent | None = None
    point_checked = False
    for kind, pattern in _PATTERNS:
        if kind == "where" and not point_checked:
            point_checked = True
            from .nus_pointer import parse_point_instruction

            parsed_point = parse_point_instruction(stripped)
            if parsed_point is not None:
                matched = Intent(
                    kind="point",
                    argument=parsed_point.target_name,
                    raw=text,
                )
                break
        match = pattern.match(stripped)
        if match:
            argument = ""
            if match.groups():
                # Last non-None group is the payload for our patterns.
                argument = next((g for g in reversed(match.groups()) if g), "")
            matched = Intent(kind=kind, argument=argument.strip(), raw=text)
            break
    if matched is None:
        return None
    if not trusted:
        return Intent(kind=OBSERVATION_KIND, argument="", raw=text,
                      source=canonical, trusted=False,
                      observed_kind=matched.kind)
    matched.source = canonical
    matched.trusted = True
    return matched


# -- the autonomy gate (consent · attribution · journal) -----------------------
#
# Build order 2. Autonomy is not "she decided"; it is a record. Anything that
# changes state has to answer three questions before its first write, and the
# answer is data, not a vibe:
#
#   consent     — has the owner granted THIS scope? (a live root, an approved
#                 plan, a review verdict). No grant, no mutation.
#   attribution — who asked? Owner sources only; a guest, a message or a page
#                 can never be the principal of a mutation (IF-6).
#   journal     — a sink that lands an attributable row. An unjournaled change
#                 is refused even when the first two legs pass.
#
# The gate never widens autonomy: every outcome it can produce that differs
# from today is a REFUSAL. `deny` short-circuits everything (deny-beats-consent).

OWNER_PRINCIPALS = frozenset({
    "owner", "owner-typed", "owner-voice-verified", "owner-hotkey",
    "owner-cli-ipc",
})


def _consent_evidence(consent) -> tuple[bool, str]:
    """(granted, scope) from a bool, a string, a record or a callable."""
    if consent is None:
        return False, ""
    if isinstance(consent, bool):
        return consent, ("explicit grant" if consent else "")
    if isinstance(consent, str):
        text = consent.strip()
        return bool(text), text[:200]
    if isinstance(consent, dict):
        return bool(consent.get("granted")), str(consent.get("scope") or "")[:200]
    if callable(consent):
        try:
            return bool(consent()), "consent callable grant"
        except Exception as exc:  # a consent check that cannot answer is a no
            return False, f"consent check raised {type(exc).__name__}"
    return False, ""


def _write_journal(journal, row: dict) -> bool:
    """Land an attributable row; a sink that raises is not a journal."""
    if not callable(journal):
        return False
    try:
        journal(row)
        return True
    except Exception:  # a broken sink must refuse, not crash
        return False


def authorise(intent: Intent, *, principal: str = "", consent=None,
              journal=None, deny: bool = False) -> dict:
    """The one decision function for a state-changing intent.

    Returns a record, never raises: `allowed`, `reasons` (every leg that
    failed, named), `journaled`, `attribution`. The caller acts only when
    `allowed` is True; a refusal is as attributable as an approval.
    """
    canonical, principal_trusted = normalise_source(principal)
    reasons: list[str] = []
    if deny:
        reasons.append("deny beats consent — the owner refused this")
    if not getattr(intent, "trusted", True) or getattr(intent, "kind", "") == OBSERVATION_KIND:
        reasons.append("IF-6 — inbound/fetched content is data: planned over, "
                       "never dispatched as an action")
    if not principal_trusted:
        reasons.append(f"attribution — {principal or 'no principal'} is not an "
                       "owner source; authority never transfers")
    granted, scope = _consent_evidence(consent)
    mutating = bool(getattr(intent, "mutating", True))
    if mutating and not granted:
        reasons.append("consent — no grant covers this scope, and it changes state")
    sink_ok = callable(journal)
    if mutating and not sink_ok:
        reasons.append("journal — no journal sink: an unattributable change is refused")
    allowed = not reasons
    row = {"event": "mutation.authorised" if allowed else "mutation.refused",
           "intent": getattr(intent, "kind", ""), "mutating": mutating,
           "principal": canonical, "principal_trusted": principal_trusted,
           "consent": scope, "consent_granted": granted,
           "allowed": allowed, "reasons": reasons, "ts": iso_now()}
    journaled = _write_journal(journal, row)
    if sink_ok and not journaled:
        reasons.append("journal — the sink refused the row")
        allowed = False
    return {"allowed": allowed, "reasons": reasons,
            "reason": "; ".join(reasons) or "read-only, owner-attributed",
            "journaled": journaled, "attribution": canonical,
            "mutating": mutating, "consent": scope, "consent_granted": granted,
            "intent": getattr(intent, "kind", "")}


# -- the capability ledger (a claim needs a path) ------------------------------
#
# Build order 1: make a claim a path cannot honour IMPOSSIBLE. Every claim
# below names the symbol that actually does the work; `resolve_symbol()` proves
# the symbol exists in THIS build before the claim may be spoken. A capability
# whose path has been removed/stubbed stops being claimable — the code, not a
# prompt sentence, is what decides.


@dataclass(frozen=True)
class Capability:
    id: str
    claim: str            # first person, present tense, no adjectives
    path: str             # "module:Attr[.Attr]" — the symbol that honours it
    mutating: bool = False
    needs: str = ""       # precondition in plain words ('' = always)


CAPABILITIES: tuple[Capability, ...] = (
    Capability("status", "report my own state — mode, connectivity, uptime",
               "assistant.daemon:Daemon._status"),
    Capability("cost", "report spend, quota and the queue depth",
               "assistant.cost:format_cost_report"),
    Capability("where", "find a file or fact that is already in your local index",
               "assistant.memory:Memory.answer_where"),
    Capability("search", "search your local index, transcripts and stored facts",
               "assistant.memory:Memory.recall"),
    Capability("remember", "store a fact you state, with its source recorded",
               "assistant.memory:Memory.remember", mutating=True),
    Capability("forget", "deactivate a stored fact when you ask me to",
               "assistant.memory:Memory.forget", mutating=True),
    Capability("organise", "index a folder and propose a sort order — nothing "
               "moves without your review",
               "assistant.organiser:OrganiserService.build_plan"),
    Capability("apply", "apply a plan you reviewed, inside a root you flipped to live",
               "assistant.executor:Executor.apply_plan", mutating=True,
               needs="the root must be mode=live in config"),
    Capability("undo", "reverse one operation the journal recorded",
               "assistant.executor:Executor.undo", mutating=True,
               needs="one committed operation and the undo review"),
    Capability("verify", "re-walk filed destinations and compare them to the journal",
               "assistant.executor:Executor.verify"),
    Capability("halt", "stop the executor before its next file operation",
               "assistant.safety:set_halt", mutating=True),
    Capability("queue", "park cloud work while offline and drain it later",
               "assistant.offline_queue:CloudQueue.drain", mutating=True),
    Capability("meeting", "record a meeting and file its transcript",
               "assistant.meeting:MeetingService", mutating=True,
               needs="named capture nodes"),
    Capability("modes", "switch the connectivity preference you set",
               "assistant.modes:ModeManager.status", mutating=True),
    Capability("initiative", "knock, but only with a stored reason you supplied",
               "assistant.initiative:InitiativeService.raise_knock"),
    Capability("demo", "show demonstrations inside a sandbox folder",
               "assistant.showoff:ShowoffService.demo_write", mutating=True),
    Capability("ladder", "report which binds and sensors are actually live",
               "assistant.ladder:main"),
    Capability("point", "point at a visible control on your screen without clicking it",
               "assistant.nus_pointer:Pointer.point_instruction",
               needs="[nus_pointer] enabled = true"),
)

#: Things a language model is happy to claim and this build has no path for.
#: (area, pattern over a sentence, why it cannot be honoured)
NO_PATH_CLAIMS: tuple[tuple[str, str, str], ...] = (
    ("send messages",
     (r"\b(?:send|sending|fire off|reply to|text|email|message|dm|whatsapp)\b.{0,40}"
      r"\b(?:messages?|sms|texts?|emails?|dms?|whatsapps?|people|him|her|them|contact)\b"),
     "no outbound messaging path is wired into me"),
    ("hand over files",
     (r"\b(?:send|share|email|upload|post|give|forward)\b.{0,40}"
      r"\b(?:files?|documents?|photos?|attachments?|folders?)\b"),
     "files only move inside your own folders, by the executor, after your review"),
    ("control devices",
     (r"\b(?:control|turn on|turn off|switch on|switch off|dim|lock|unlock)\b.{0,40}"
      r"\b(?:lights?|devices?|home|thermostat|appliances?|doors?|tv)\b"),
     "there is no device-control path in this build"),
    ("buy or pay",
     r"\b(?:buy|purchase|order|pay|transfer|checkout)\b",
     "there is no payment path, and none is planned before the draft tier"),
    ("run commands",
     r"\b(?:run|execute|eval)\b.{0,30}\b(?:commands?|scripts?|shells?|code)\b",
     "no interpreter is allowlisted — that rule is permanent"),
    ("browse the web",
     r"\b(?:browse|search|scrape|open)\b.{0,30}\b(?:the web|the internet|websites?|urls?|links?)\b",
     "no network egress is wired into the planning path yet (Wave 2)"),
    ("make calls",
     r"\b(?:call|phone|dial)\b.{0,30}\b(?:people|him|her|them|numbers?)\b",
     "there is no dialler path"),
)

_ABILITY = re.compile(
    r"\b(i|i'm|i am|i've|i can|i could|i'll|i will|able to|my job is|i handle|i manage)\b",
    re.IGNORECASE)
_NEGATED = re.compile(
    r"\b(can'?t|cannot|won'?t|will not|don'?t|do not|never|not|no|unable|nothing|none)\b",
    re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def resolve_symbol(path: str):
    """(resolved, detail) — does the claim's honouring path exist here?"""
    module_name, _, attribute = str(path or "").partition(":")
    if not module_name or not attribute:
        return False, f"malformed path {path!r} (want 'module:Attr')"
    try:
        target = importlib.import_module(module_name)
    except Exception as exc:  # an unimportable path cannot honour a claim
        return False, f"{module_name} is not importable ({type(exc).__name__})"
    for part in attribute.split("."):
        try:
            target = getattr(target, part)
        except AttributeError:
            return False, f"{module_name} has no {attribute}"
    return True, ""


def capability_report(*, probes: dict | None = None, resolver=None) -> dict:
    """What she may claim, sorted by whether a path honours it right now.

    `probes` maps a capability id to a precondition result (True/False/a reason
    string); `resolver` replaces `resolve_symbol` in tests. A missing path
    removes the claim entirely — it is never softened into "probably".
    """
    resolver = resolver or resolve_symbol
    probes = probes or {}
    available: list[dict] = []
    unavailable: list[dict] = []
    for capability in CAPABILITIES:
        resolved, detail = resolver(capability.path)
        probe = probes.get(capability.id)
        blocked = ""
        if probe is False:
            blocked = "precondition not met right now"
        elif isinstance(probe, str) and probe:
            blocked = probe
        entry = {"id": capability.id, "claim": capability.claim,
                 "path": capability.path, "mutating": capability.mutating,
                 "needs": capability.needs, "path_resolves": bool(resolved),
                 "reason": detail if not resolved else blocked}
        (available if resolved and not blocked else unavailable).append(entry)
    return {"available": available, "unavailable": unavailable,
            "no_path": [{"area": area, "why": why} for area, _p, why in NO_PATH_CLAIMS],
            "counts": {"available": len(available),
                       "unavailable": len(unavailable),
                       "no_path": len(NO_PATH_CLAIMS),
                       "claims": len(CAPABILITIES)}}


def answer_capability_question(report: dict | None = None, *,
                               probes: dict | None = None) -> str:
    """The honest answer to "what can you do?" — only proven claims speak."""
    report = report or capability_report(probes=probes)
    lines = [f"From paths that exist in this build right now ({len(report['available'])}):"]
    for entry in report["available"]:
        lines.append(f"- I can {entry['claim']}.")
    if report["unavailable"]:
        lines.append(f"\nNot available right now ({len(report['unavailable'])}):")
        for entry in report["unavailable"]:
            why = entry["reason"] or "no reason recorded"
            lines.append(f"- I cannot {entry['claim']} — {why}.")
    if report["no_path"]:
        lines.append("\nWhat I can't do, because nothing in me reaches it:")
        for entry in report["no_path"]:
            lines.append(f"- {entry['area']} — {entry['why']}.")
    return "\n".join(lines)


def honest_claims(text: str, *, report: dict | None = None) -> dict:
    """Strip any claim of an ability this build has no path for.

    Sentence-scoped: a first-person ability sentence that matches a no-path
    area is removed and replaced by the plain denial; an honest denial already
    in the text is kept as it stands. Returns `{text, removed, denied}` so the
    caller can journal exactly what was taken out.
    """
    report = report or capability_report()
    removed: list[str] = []
    kept: list[str] = []
    for sentence in [s for s in _SENTENCE.split(str(text or "")) if s.strip()]:
        if not _ABILITY.search(sentence) or _NEGATED.search(sentence):
            kept.append(sentence.strip())
            continue
        hit = next((area for area, pattern, _why in NO_PATH_CLAIMS
                    if re.search(pattern, sentence, re.IGNORECASE)), None)
        if hit is None:
            kept.append(sentence.strip())
        elif hit not in removed:
            removed.append(hit)
    body = " ".join(kept).strip()
    denials = [f"I can't {entry['area']} — {entry['why']}."
               for entry in report["no_path"] if entry["area"] in removed]
    if denials:
        body = (body + "\n\n" if body else "") + " ".join(denials)
    return {"text": body, "removed": removed, "denied": denials,
            "changed": bool(removed)}


def confirm_now(*checks) -> dict:
    """Answer "confirm rn?" honestly: a confirmation needs an observation.

    Each check is `(label, probe)`. A probe that returns nothing, returns
    False, or raises produces an UNCONFIRMED line with its reason — the word
    "confirmed" is never attached to it. This is the verification-before-claim
    primitive: she cannot report a check she did not run.
    """
    confirmed: list[dict] = []
    unconfirmed: list[dict] = []
    for check in checks or ():
        try:
            label, probe = check
        except (TypeError, ValueError):
            unconfirmed.append({"label": str(check), "reason": "malformed check"})
            continue
        label = str(label)
        try:
            value = probe() if callable(probe) else probe
        except Exception as exc:  # a failed probe is not evidence
            unconfirmed.append({"label": label,
                                "reason": f"the check raised {type(exc).__name__}: {exc}"[:180]})
            continue
        if value is None or value is False or (isinstance(value, str) and not value.strip()):
            unconfirmed.append({"label": label, "reason": "no observation was produced"})
            continue
        evidence = (value if isinstance(value, str) else repr(value))[:180]
        confirmed.append({"label": label, "evidence": evidence})
    lines = []
    if confirmed:
        lines.append(f"Confirmed just now ({len(confirmed)}):")
        lines.extend(f"- {entry['label']} — {entry['evidence']}" for entry in confirmed)
    if unconfirmed:
        lines.append(f"I can't confirm ({len(unconfirmed)}):")
        lines.extend(f"- {entry['label']} — {entry['reason']}" for entry in unconfirmed)
    return {"confirmed": confirmed, "unconfirmed": unconfirmed,
            "text": "\n".join(lines) or "I have nothing to check.",
            "all_confirmed": not unconfirmed}


# -- the command-confidence floor: REPORTED, never changed ----------------------
#
# Build order 3. The asymmetry, with its numbers, from
# `docs/phase-reports/2026-11-03-extraction-fix.md` (commit a176497):
#
#   0.85   `[transcribe] command_min_confidence` (config.py:531, default) — a
#          MUTATING voice intent below it is vetoed before it routes.
#   0.6953 a *perfect* local faster-whisper transcript of synthetic speech —
#          so the local leg cannot clear the floor on clean audio.
#   None   the Gemini batch leg, which constructs `Transcript` without a
#          confidence (the response schema carries no confidence field at all),
#          so `unknown and mutating` vetoes it too.
#
# Net effect today: voice cannot run a mutating command on clean audio by
# either leg. The owner chooses the policy; this module only states the
# options. NOTHING here reads or writes the gate.

COMMAND_FLOOR_OPTIONS: tuple[dict, ...] = (
    {"id": "A", "name": "status quo", "floor": 0.85,
     "change": "none",
     "effect": "mutating voice intents stay blocked on clean audio: local reads "
               "0.6953, the Gemini leg reads unknown",
     "needs": "nothing", "risk": "she keeps answering but cannot take a command"},
    {"id": "B", "name": "per-backend verification policy", "floor": 0.85,
     "change": "the floor applies to whisper's log-probability confidence; a "
               "verbatim transcription leg with a clean parse is admitted by a "
               "declared verification signal instead",
     "effect": "mutating voice intents become reachable once a leg declares "
               "verification; the floor itself does not move",
     "needs": "A declares the signal in asr.py (its file); C consumes it",
     "risk": "a leg that declares verification wrongly admits a mutation"},
    {"id": "C", "name": "lower the floor", "floor": 0.69,
     "change": "command_min_confidence 0.85 → ~0.69",
     "effect": "the local leg clears it; every mumble near the microphone also "
               "clears it",
     "needs": "the §5 recorded refusal rail (Wave 2) proven first",
     "risk": "widens voice mutation before the refusal path exists — the "
             "house method forbids this"},
    {"id": "D", "name": "derive a Gemini confidence", "floor": 0.85,
     "change": "synthesise a confidence for the batch leg",
     "effect": "the Gemini leg would clear the floor",
     "needs": "a justification, not an invention — the response schema has no "
              "confidence field",
     "risk": "a derived number dressed as a measurement is exactly what §4.3 "
             "calls an invented threshold"},
)


def command_floor_report(config=None) -> dict:
    """Report the confidence asymmetry and the options. Changes nothing."""
    floor = 0.85
    if config is not None:
        try:
            floor = float(config.section("transcribe").get(
                "command_min_confidence", 0.85))
        except Exception:  # a report is never worth a crash
            floor = 0.85
    return {"configured_floor": floor,
            "observed": {"mutating_floor_default": 0.85,
                         "local_whisper_perfect_transcript": 0.6953,
                         "gemini_batch_confidence": None,
                         "gate_site": "daemon.py:_command_gate + asr.voice_command_allowed",
                         "evidence": "docs/phase-reports/2026-11-03-extraction-fix.md "
                                     "(commit a176497)"},
            "options": [dict(option) for option in COMMAND_FLOOR_OPTIONS],
            "changed": False,
            "owner_decision": ("the floor is the owner's call; this report states "
                               "the options and leaves the gate exactly as it is")}
