"""Mock planning seam: one reservation/attempt per advance, never live traffic."""
from dataclasses import dataclass

from assistant.cost import iso_now

from .plan import Plan

LITE = "gemini-3.5-flash-lite"
FLASH = "gemini-3.8-flash"


@dataclass(frozen=True)
class OwnerIntent:
    text: str
    channel: str = "console"

    def __post_init__(self):
        if not isinstance(self.text, str) or not self.text.strip() or self.channel not in {"console", "cli"}:
            raise ValueError("sandbox intent requires commanded text")


@dataclass(frozen=True)
class PlanningResult:
    status: str
    model: str
    plan: Plan | None = None
    reason: str = ""
    next_eligible: float | None = None


class MockPlanner:
    def __init__(self, queue, candidates, *, sink=None):
        self.queue = queue
        self.sink = sink
        self._candidates = iter(candidates)
        self.failed_revisions = 0
        self.attempts = []

    def failed_revision(self):
        self.failed_revisions += 1

    def advance(self, intent: OwnerIntent, *, day: str, now: float, cap: int,
                external_used: int = 0, reserved: int = 0) -> PlanningResult:
        if type(intent) is not OwnerIntent:
            raise TypeError("data-origin text is not owner intent")
        model = FLASH if self.failed_revisions >= 2 else LITE
        allowed, reason, when = self.queue.reserve_mock(
            day=day, model=model, now=now, cap=cap, external_used=external_used, reserved=reserved)
        if not allowed:
            return PlanningResult("parked", model, reason=reason, next_eligible=when)
        self.attempts.append(model)
        if self.sink is not None:
            self.sink.emit(ts=iso_now(), level="INFO", event="hands.plan", session_id="-", peak="-",
                           verdict="ok", counts={"mock_calls": len(self.attempts),
                           "flash_lite_calls": self.attempts.count(LITE),
                           "flash_calls": self.attempts.count(FLASH)})
        try:
            plan = Plan.parse(next(self._candidates))
        except (ValueError, TypeError, KeyError, StopIteration, UnicodeError):
            self.failed_revision()
            return PlanningResult("revision-failed", model, reason="invalid-mock-plan")
        return PlanningResult("planned", model, plan=plan)
