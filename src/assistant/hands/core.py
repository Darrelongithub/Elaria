"""Sandbox-only intent/plan -> gate -> fake runner -> reread -> report.

All calls are local. No production service, broker, transport, or subprocess.
A reported outcome is a decision; exit codes alone never establish completion.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from assistant.cost import iso_now
from assistant.safety import check_blast_radius, is_halted

from .gate import GateChecker, SyntheticFacts, adjudicate
from .injection import DataInput, suspected
from .plan import Plan
from .queue import ParkedQueue
from .runner import FakeRunner
from .verify import Expected, operation_expectations, verify


@dataclass
class Reporter:
    """Private in-memory console data only; never copied into telemetry detail."""
    lines: list[str] = field(default_factory=list)
    plans: list[bytes] = field(default_factory=list)
    disclosures: list[list[dict]] = field(default_factory=list)

    def say(self, message: str):
        self.lines.append(message)


class SandboxCore:
    def __init__(self, space, queue: ParkedQueue, runner: FakeRunner, sink, *, facts=None,
                 expectations: dict[int, tuple[Expected, ...]] | None = None):
        if type(runner) is not FakeRunner or runner.space is not space:
            raise TypeError("only the fake runner for this workspace is permitted")
        if queue.path.parent != space.control:
            raise ValueError("state workspace mismatch")
        self.space, self.queue, self.runner, self.sink = space, queue, runner, sink
        self.gate = GateChecker(space)
        self.facts = facts or (lambda step, phase: SyntheticFacts())
        self.expectations = expectations or {}
        self.reporter = Reporter()
        self.active = False
        self.errand = "-"

    def emit(self, event, verdict, **metadata):
        return self.sink.emit(ts=iso_now(), level="INFO", event="hands." + event,
                              session_id=self.errand, peak="-", verdict=verdict, **metadata)

    def report(self, status: str):
        self.reporter.say(status)
        self.emit("report", "ok")
        return status

    def ingest(self, data: DataInput) -> bool:
        if not suspected(data):
            return False
        self.emit("inject", "inject")
        self.reporter.say("suspected injection in data; its instructions were refused")
        return True

    def cancel(self):
        self.emit("cancel", "cancel-intent")
        self.queue.cancel(self.errand)
        if self.active:
            self.emit("cancel", "refused")
            self.reporter.say("mid-step cancellation is not available; stopping at the next boundary")

    def decision(self, ask_id: int, digest: str, choice: str):
        verdict = self.queue.decide(ask_id, digest, choice)
        self.emit("decision", verdict, hashes=[digest])
        if verdict == "stale":
            self.emit("ask", "stale", hashes=[digest])
        return verdict

    def check(self, step, phase):
        try:
            facts = self.facts(step, phase)
            checker = None if facts is None else self.gate.derive(step, facts)
        except Exception:
            checker = "invalid"
        result = adjudicate(step.tier, checker, self.queue.mismatches(self.errand))
        self.queue.mismatches(self.errand, result.mismatches)
        metadata = {"reason": result.reason} if result.reason in {
            "unadjudicable", "two-mismatch-halt"} else {"counts": {"step": step.i}}
        self.emit("gate", result.verdict, **metadata)
        return result

    def refused(self, plan, step, verdict):
        self.emit("step", "refused", counts={"step": step.i})
        if verdict.halt:
            self.queue.park(self.errand, plan, step.i, kind="replan")
            self.emit("ask", "ok", hashes=[plan.digest])
            self.reporter.say("two mismatches; only a new plan may be requested, not a tier override")
        return self.report("refused")

    def run(self, plan: Plan, *, errand: str | None = None,
            data: tuple[DataInput, ...] = ()) -> str:
        self.errand = errand or secrets.token_hex(6)
        self.queue.register(self.errand, plan)
        if any(self.ingest(d) for d in data):
            self.emit("plan", "refused")
            self.emit("step", "refused")
            return self.report("refused")
        # Gate the whole plan before disclosure, so control/protected targets
        # never enter a private plan disclosure, let alone a notification/log.
        checked = {}
        for step in plan.steps:
            state = self.queue.step_state(self.errand, plan, step.i)
            if state == "done":
                continue
            if state is not None:
                return self.report("outcome unknown; no replay")
            result = self.check(step, "plan")
            checked[step.i] = result
            if result.verdict == "refused":
                self.emit("plan", "refused")
                return self.refused(plan, step, result)
        mutations = sum(v.tier is not None and v.tier > 0 for v in checked.values())
        blast = check_blast_radius(mutations, len(self.space.store.documents_in_root(str(self.space.work))),
                                   max_ops_per_run=self.space.executor.max_per_run,
                                   tripwire_pct=self.space.executor.tripwire_pct)
        if not blast.allowed:
            self.emit("plan", "refused", counts={"operations": mutations})
            self.queue.park(self.errand, plan, 0, kind="replan")
            self.emit("ask", "ok", hashes=[plan.digest])
            return self.report("blast-radius cap; re-plan required, not an execution override")
        self.reporter.plans.append(plan.canonical)
        self.reporter.disclosures.append([s.disclosure() for s in plan.steps])
        self.emit("plan", "ok", hashes=[plan.digest], counts={"steps": len(plan.steps)})
        self.reporter.say("plan posted before execution")
        for step in plan.steps:
            if self.queue.cancelled(self.errand) or is_halted(self.space.control):
                self.emit("cancel", "cancelled")
                self.emit("step", "cancelled")
                return self.report("cancelled at a step boundary")
            if self.queue.step_state(self.errand, plan, step.i) == "done":
                continue
            # Mandatory fresh facts on every dispatch/resume.
            result = self.check(step, "pre-exec")
            if result.verdict == "refused":
                return self.refused(plan, step, result)
            needs_yes = result.ask or checked[step.i].ask
            if needs_yes:
                ask = self.queue.park(self.errand, plan, step.i)
                if ask["state"] == "no":
                    return self.report("declined; no retry for this plan version")
                if ask["state"] != "yes":
                    self.emit("ask", "ok", hashes=[plan.digest])
                    self.reporter.say("exact argv, cwd and env-diff await your decision; this is not sandboxing")
                    return self.report("parked")
            try:
                expected = operation_expectations(self.space, step) or self.expectations.get(step.i, ())
            except (OSError, ValueError, PermissionError):
                self.emit("step", "refused")
                return self.report("source changed or not indexed; re-plan")
            if not expected:
                self.emit("step", "degraded")
                return self.report("no independent re-read verifier; nothing executed")
            if not self.queue.claim(self.errand, plan, step.i, needs_yes=needs_yes):
                return self.report("stale or uncertain claim; nothing replayed")
            self.active = True
            try:
                outcome = self.runner.run(step)
                self.emit("exec", "ok" if outcome.returncode == 0 else "failed")
                # Output is only data. It cannot call a planner or modify steps.
                for origin, value in (("stdout", outcome.stdout), ("stderr", outcome.stderr)):
                    self.ingest(DataInput(origin, value))
                verified = outcome.returncode == 0 and verify(self.space, expected)
                if step.tool in {"move", "resolve_collision", "trash"}:
                    verified = (verified and bool(outcome.op_ids)
                                and not self.space.executor.verify()["problems"])
                self.emit("verify", "ok" if verified else "mismatch")
                self.queue.finish(self.errand, plan, step.i, "done" if verified else "failed")
                if not verified:
                    self.emit("step", "refused")
                    return self.report("verification mismatch")
                self.emit("step", "ok", counts={"step": step.i})
            except TimeoutError:
                self.queue.finish(self.errand, plan, step.i, "timeout")
                self.emit("exec", "timeout")
                self.emit("step", "timeout")
                return self.report("step timed out; no retry")
            except Exception:
                self.queue.finish(self.errand, plan, step.i, "failed")
                self.emit("exec", "failed")
                self.emit("step", "refused")
                return self.report("step failed; outcome requires inspection")
            finally:
                self.active = False
                self.runner.cleanup(step)
        if self.queue.cancelled(self.errand):
            self.emit("cancel", "cancelled")
            return self.report("cancelled at a step boundary")
        return self.report("verified complete")
