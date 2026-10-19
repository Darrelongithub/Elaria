"""Elaria — personal AI assistant (blueprint v29).

Phase 0: daemon, Unix-socket IPC, `assist` CLI, Gemini client with cost
ledger, mock/record/live fixture harness, persona governor skeleton, and
the standalone `assist-voice-test` harness (§13.10).

Design rules that hold across the whole package:
- 99% code (§13.4): Gemini is a scarce specialist, called only when code
  genuinely can't decide — and then cheapest-model-first (§17).
- Nothing on the ack path touches the network (§18).
- Tests must pass with NO API key: no key => GEMINI_MODE=mock (§12.9).
"""

__version__ = "0.0.1"
