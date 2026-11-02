"""Additive synchronous service adapter; no daemon, UI, model call or config mutation.

All dispatch goes through Authorizer (existing R3/R5). A durable event writer and an
independent checker are mandatory trusted-host dependencies. UNVERIFIED is not success.
"""
from __future__ import annotations

import json
import secrets
import threading
from datetime import UTC, datetime

from .attribution import trace
from .policy import Act, Authorizer, canonical, digest, fingerprint, inventory, tier_for

TAB_VERBS = frozenset({"close-tab", "focus-tab", "set-tab-title", "set-tab-color", "goto-layout",
                       "last-used-layout", "set-enabled-layouts", "detach-tab", "select-window"})
CREATORS = frozenset({"launch", "new-window"})
SEND = frozenset({"send-text", "send-key"})


def exact_match(ids):
    return " or ".join(f"id:{i}" for i in sorted(set(ids)))


def make_act(verb, payload, target_ids=()):
    """Prepare invariants BEFORE hashing/disclosure; never silently alter an approved act."""
    payload = json.loads(canonical(payload))
    if verb in CREATORS:
        payload["keep_focus"] = True
        payload.pop("allow_remote_control", None)
        payload.pop("remote_control_password", None)
        title_key = "window_title" if verb == "launch" else "title"
        payload[title_key] = "[ELARIA " + secrets.token_hex(6) + "]"
        if verb == "launch":
            payload.setdefault("type", "window")
            for key in ("os_window_title", "tab_title"):
                payload[key] = payload[title_key]
    if verb in SEND:
        payload["match"] = exact_match(target_ids)
        payload["exclude_active"] = len(target_ids) > 1
        if verb == "send-text":
            payload["bracketed_paste"] = "auto"
    return Act(verb, canonical(payload), tuple(target_ids))


def windows_from_ls(data):
    raw = json.loads(data) if isinstance(data, str) else data
    if type(raw) is not list:
        raise ValueError("invalid ls response")
    result = []
    for osw in raw:
        for tab in osw["tabs"]:
            for window in tab["windows"]:
                if (type(window["id"]) is not int or type(window["pid"]) is not int
                        or type(window["cmdline"]) is not list
                        or any(not isinstance(x, str) for x in window["cmdline"])):
                    raise ValueError("invalid window identity")
                # Environment, cwd, scrollback and other unneeded content never enter our snapshot.
                result.append({k: window.get(k) for k in ("id", "pid", "cmdline", "title", "is_active", "is_focused", "foreground_processes", "created_at")}
                              | {"tab_id": tab["id"], "os_id": osw["id"], "tab_title": tab.get("title"),
                                 "tab_is_focused": tab.get("is_focused"), "layout": tab.get("layout")})
    if len({w["id"] for w in result}) != len(result):
        raise ValueError("ambiguous window IDs")
    return result


def target_metadata(targets):
    # Full command lines can contain credentials. Bind the exact line by digest, display only
    # executable basename; NEVER put arbitrary argv or terminal text in the event stream.
    return [{"id": w["id"], "pid": w["pid"], "tab_id": w["tab_id"], "os_id": w["os_id"],
             "cmdline": {"sha256": digest(w["cmdline"]), "argc": len(w["cmdline"])},
             "foreground_processes_sha256": digest(w.get("foreground_processes"))}
            for w in targets]


class Bridge:
    def __init__(self, transport, checker, journal, *, verifier=None, resolver=None, endpoint_ref=None):
        if not callable(journal):
            raise TypeError("durable kitty.act event sink is required")
        self.transport, self.journal, self.verifier = transport, journal, verifier
        self.resolver, self.endpoint_ref = resolver, endpoint_ref
        self.boundary = threading.RLock()
        self.active = None
        self.authorizer = Authorizer(checker, assessment_audit=self.record_assessment)
        self.catalogue = inventory()
        self.owned = set()  # journal-backed, this service session only; never infer from title
        self.session = secrets.token_hex(6)

    def event(self, *, verb, tier, plan_hash, targets, consent_ref, verification, **extra):
        self.journal({"kind": "kitty.act", "timestamp": datetime.now(UTC).isoformat(),
                      "session": self.session, "verb": verb, "tier": tier,
                      "operation": "act", "endpoint_ref": self.endpoint_ref,
                      "target": target_metadata(targets), "plan_hash": plan_hash,
                      "consent_ref": consent_ref, "verification": verification, **extra})

    def record_assessment(self, act, plan, phase, targets, result):
        receipt = trace(result, phase)
        self.event(verb=act.verb, tier=tier_for(act, result, targets, self.owned, self.catalogue),
                   plan_hash=plan.digest, targets=targets, consent_ref=None, phase="assessment",
                   verification="refused" if result.denied else "assessed-not-authorized",
                   assessment=receipt, silent=act.verb == "run" or act.payload.get("type") == "background")

    def probe(self, verb, payload, plan, targets=()):
        common = {"verb": verb, "tier": "K1", "plan_hash": plan.digest, "targets": targets, "consent_ref": None, "operation": "probe"}
        self.event(**common, verification="pending", phase="intent")
        try:
            result = self.transport.request(verb, payload, "K1")
        except Exception:
            self.event(**common, verification="transport-failed", phase="result")
            raise
        if verb == "ls":
            common["targets"] = windows_from_ls(result)
        self.event(**common, verification="response-observed", phase="result")
        return result

    def snapshot(self, plan):
        return windows_from_ls(self.probe("ls", {"all_env_vars": False}, plan))

    def targets(self, act, snapshot):
        if self.resolver is not None:
            return self.resolver(act, snapshot)
        by_id = {w["id"]: w for w in snapshot}
        if any(i not in by_id for i in act.target_ids):
            raise PermissionError("target disappeared")
        selected = [by_id[i] for i in act.target_ids]
        if not act.target_ids and (act.verb == "ls" or act.payload.get("all") is True):
            selected = list(snapshot)
        if act.verb in TAB_VERBS:
            tabs = {w["tab_id"] for w in selected}
            # A tab close necessarily affects EVERY child, including HIS windows.
            selected = [w for w in snapshot if w["tab_id"] in tabs]
        return selected

    def guards(self, act, targets):
        p = act.payload
        if p.get("allow_remote_control") or p.get("remote_control_password"):
            raise PermissionError("never grant child remote-control rights")
        if act.verb in CREATORS:
            title = p.get("window_title" if act.verb == "launch" else "title", "")
            if p.get("keep_focus") is not True or not title.startswith("[ELARIA ") or not title.endswith("]"):
                raise PermissionError("unstamped or focus-stealing launch")
            if any(p.get(k) and not p[k].startswith("[ELARIA ") for k in ("os_window_title", "tab_title")):
                raise PermissionError("unstamped launch title")
        if (act.verb == "set-window-title" and any(fingerprint([w]) in self.owned for w in targets)
                and (not act.payload.get("title", "").startswith("[ELARIA ") or act.payload.get("temporary"))):
            raise PermissionError("HER attribution stamp must persist")
        if act.verb in SEND | {"close-window", "signal-child"} | TAB_VERBS:
            if not targets:
                raise PermissionError("explicit target is required; no active-window default")
            ids = [w["tab_id"] if act.verb in TAB_VERBS else w["id"] for w in targets]
            if (p.get("match") != exact_match(ids) or p.get("match_tab") or p.get("all") or p.get("self")
                    or p.get("ignore_no_match")):
                raise PermissionError("target selectors do not bind the complete affected set")
        if act.verb in SEND:
            if len(targets) > 1 and (p.get("exclude_active") is not True or any(w["is_active"] for w in targets)):
                raise PermissionError("broadcast must explicitly exclude the active window")
            if act.verb == "send-text" and p.get("bracketed_paste") != "auto":
                raise PermissionError("bracketed-paste auto is required")

    def inspect(self, act, plan):
        """Plan-time assessment, then target observation for an exact private owner disclosure."""
        try:
            self.authorizer.assess(act, plan, "plan", ())  # reject forbidden plans before any I/O
            before = self.snapshot(plan)
            targets = self.targets(act, before)
            self.guards(act, targets)
            return targets
        except Exception:
            self.event(verb=act.verb, tier="K3", plan_hash=plan.digest, targets=[], consent_ref=None,
                       verification="refused", phase="result", requested_ids=list(act.target_ids))
            raise PermissionError("kitty plan refused before disclosure") from None

    def execute(self, act, plan):
        targets, tier, consent_ref = [], "K3", None
        common = lambda: {"verb": act.verb, "tier": tier, "plan_hash": plan.digest,
                              "targets": targets, "consent_ref": consent_ref}
        dispatched = False
        owns_active = False
        try:
            if plan.digest in self.authorizer.consumed:
                raise PermissionError("outcome already dispatched; no replay")
            self.authorizer.assess(act, plan, "plan", ())
            before = self.snapshot(plan)
            targets = self.targets(act, before)
            self.guards(act, targets)
            assessment, verdict = self.authorizer.assess(act, plan, "pre-exec", targets)
            tier = tier_for(act, assessment, targets, self.owned, self.catalogue)
            consent_ref = self.authorizer.authorize(act, plan, tier, assessment, verdict, targets)
            pre_text = {}
            if act.verb in SEND:
                if act.verb == "send-text":
                    for w in targets:
                        pre_text[w["id"]] = self.probe("get-text", {"match": exact_match([w["id"]])}, plan, [w])
                # BOTH send verbs need a fresh identity/focus observation and gate. In 0.47.1
                # send-key ignores exclude_active; this does NOT make broadcast exclusion atomic.
                # Fresh identity immediately before the send, after any get-text round trips.
                latest = self.targets(act, self.snapshot(plan))
                if fingerprint(latest) != fingerprint(targets):
                    raise PermissionError("target changed before send")
                self.guards(act, latest)
                assessment, verdict = self.authorizer.assess(act, plan, "pre-send", latest)
                tier = tier_for(act, assessment, latest, self.owned, self.catalogue)
                consent_ref = self.authorizer.authorize(act, plan, tier, assessment, verdict, latest)
            silent = act.verb == "run" or act.payload.get("type") == "background"
            entry = self.catalogue["verbs"].get(act.verb, {})
            async_id = secrets.token_urlsafe(24) if entry.get("async") else None
            cancel_event = threading.Event()
            with self.boundary:
                if self.active is not None:
                    raise PermissionError("another act is in flight")
                self.authorizer.authorize(act, plan, tier, assessment, verdict, targets)
                self.event(**common(), verification="pending", phase="intent", silent=silent,
                           async_id=async_id)
                self.authorizer.consumed.add(plan.digest)
                self.active = (plan.digest, act.verb, tier, async_id, cancel_event)
                owns_active = True
            dispatched = True
            response = self.transport.request(act.verb, act.payload, tier,
                no_response=entry.get("no_response", False), async_id=async_id,
                stream=entry.get("stream", False), cancel_event=cancel_event)
            after = self.snapshot(plan)
            verification = "unverified"
            if act.verb in CREATORS:
                title = act.payload.get("window_title", act.payload.get("title"))
                created = [w for w in after if str(w["id"]) == str(response)
                           and w["id"] not in {old["id"] for old in before} and w["title"] == title]
                if created:
                    verification = "created-id-and-stamp-observed"
                    # Publish successful attribution durably BEFORE granting HER-ID status.
                    self.event(**common(), verification=verification, phase="result",
                               created=target_metadata(created), ownership=[fingerprint([w]) for w in created], silent=silent)
                    self.owned.update(fingerprint([w]) for w in created)
                    return {"verification": verification, "data": response}
            elif act.verb == "send-text":
                needle = act.payload["data"][5:]
                observed = []
                for w in targets:
                    current = [x for x in after if x["id"] == w["id"]]
                    text = self.probe("get-text", {"match": exact_match([w["id"]])}, plan, [w]) if current else None
                    observed.append(bool(needle) and fingerprint(current) == fingerprint([w])
                                    and isinstance(text, str) and needle in text
                                    and isinstance(pre_text[w["id"]], str)
                                    and needle not in pre_text[w["id"]])
                if observed and all(observed):
                    verification = "text-delta-observed-not-execution-proof"
            elif act.verb in {"close-window", "close-tab"}:
                if all(w["id"] not in {x["id"] for x in after} for w in targets):
                    verification = "target-absence-observed"
            elif act.verb in {"ls", "get-text", "get-colors"}:
                verification = "response-observed"
            elif self.verifier is not None:
                # Trusted effect adapter, not an RC exit status. False/None stays UNVERIFIED.
                if self.verifier(act, tuple(before), tuple(after), response) is True:
                    verification = "independent-effect-observed"
            self.event(**common(), verification=verification, phase="result", silent=silent)
            return {"verification": verification, "data": response}
        except Exception:
            self.event(**common(), verification="effect-unknown" if dispatched else "refused",
                       phase="result")
            raise RuntimeError("kitty act refused or effect unknown; inspect journal, never replay") from None
        finally:
            with self.boundary:
                if owns_active and self.active is not None and self.active[0] == plan.digest:
                    self.active = None

    def cancel(self, plan_hash):
        # Before write-ahead dispatch, denial stops the act. After dispatch it is best effort,
        # never an undo claim. Both stages are durable before the caller receives a reply.
        with self.boundary:
            active = self.active if self.active is not None and self.active[0] == plan_hash else None
            common = {"verb": active[1] if active else "cancel", "tier": active[2] if active else "K3",
                      "plan_hash": plan_hash, "targets": [], "consent_ref": None}
            try:
                self.event(**common, phase="cancel-intent", verification="requested")
            finally:
                self.authorizer.denied.add(plan_hash)
                self.authorizer.consent.pop(plan_hash, None)
                if active:
                    active[4].set()
        verification = "effect-unknown" if active or plan_hash in self.authorizer.consumed else "stopped-before-dispatch"
        if active and active[3]:
            try:
                self.transport.request(active[1], {}, active[2], async_id=active[3],
                                       cancel=True, no_response=True)
                verification = "async-cancel-sent-effect-unknown"
            except Exception:
                verification = "cancel-transport-failed-effect-unknown"
        self.event(**common, phase="cancel-result", verification=verification)
        return {"verification": verification}
