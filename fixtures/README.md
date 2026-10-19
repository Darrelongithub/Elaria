# fixtures/ — recorded request/response pairs (committed on purpose)

The shared debugging artifact (§12.9). An LLM app is non-deterministic, so
a fixture *is* a bug report:

```bash
GEMINI_MODE=record assist ask "..."     # on the owner's machine, with key
git add fixtures/ && git commit -m "repro: <what went wrong>"
GEMINI_MODE=mock pytest                 # anywhere, no key — exact replay
```

- Files are named `<sha256-of-canonical-request>.json` (`fixtures.py`).
- `seq-<name>.jsonl` files are Live-session message sequences (Phase 1).
- Mock mode with no matching fixture returns a deterministic response
  flagged `"synthetic": true` — never mistake it for recorded behaviour.
- Never record fixtures containing private content you wouldn't commit;
  if in doubt, reproduce with toy inputs.
