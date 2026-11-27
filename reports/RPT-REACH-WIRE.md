# REACH-WIRE — live wiring (2026-11-27)

**Status: fixture-tested. Owner hardware pass pending.** The branch was synced
with `main` before editing. `OWNERS.yaml` was not changed.

- `assist reach {fetch,news,github} URL` uses the existing local-owner Unix
  socket authority check. `news` takes a public RSS/Atom URL; `github` takes a
  public `https://api.github.com/…` URL. There is no auth, shell fallback,
  discovery feed or automated retry. Disabled by default; offline and halt
  also block the entry point. Direct results are bounded local extracts with
  the final URL and hash, explicitly quoted as untrusted, with no model calls.
- `web.fetch` is an explicit read-only errand plan step. For a one-step owner
  errand use `assist errand start 'Read this page' --web-url URL`. The body
  lands in an `UntrustedObservation`; only an attributed, quoted excerpt is
  visible in the step result. Web text cannot enter analysis, evidence-to-memory,
  owner questions, or plan construction. A terminal refusal stops the errand.
- `assist reach status [--json]` reads the safety journal. It shows the
  configured sliding-hour caps, usage in the last hour and since midnight UTC,
  and the last terminal by channel. An admitted operation consumes one slot
  (including a later DNS/robots/server refusal); a pre-admission refusal does
  not. The journal charge is fsynced before DNS and survives restarts. HTTP
  uses a validated IP while retaining the original HTTPS identity; each
  redirect is checked again. No live network was used to test this lane.
- Interestingness is off unless the owner sets `[reach].interests`. It checks
  only pages the owner explicitly fetches through direct REACH commands, and
  routes a matched, novel finding through the existing initiative reason gate.
  The reason doesn't repeat page-authored instructions or claims. There is no
  background polling or feed.
- **BUG-C1 was open in `bugs.md` and is fixed in this lane.** A redirected
  `robots.txt` now terminates as `ROBOTS_UNREACHABLE`; neither its Location
  nor the page is fetched. A direct ruleset that disallows the target returns
  `ROBOTS_DISALLOWED`.

## Fixture evidence

```sh
pytest -q tests/test_reach* tests/test_z_errand_runner.py \
  tests/test_ipc_handler_integrity.py tests/test_default_sync.py tests/test_bug7_cli_smoke.py
```

The focused run covers real local Unix-socket IPC/CLI with fixture HTTP/DNS:
preflight refusal and quota exhaustion are journaled with no socket activity;
the action exists before DNS/HTTP; usage persists when the service is rebuilt;
a prompt-injecting page is quoted but cannot steer the errand or become memory;
robots denials and redirects do not request the target.

## Owner hardware test script

Run on the owner's machine, not CI. Edit the existing `[reach]` section in
`${ASSIST_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/assistant/config.toml}` (don't
add a duplicate section):

```toml
[reach]
enabled = true
interests = []
```

Then, from the updated checkout:

```sh
uv sync
systemctl --user restart assistant
assist reach status
assist reach fetch 'https://example.com/'
assist reach status
```

Read the local extract and its **Source** line; it should be labelled untrusted,
not presented as verified. The second status should show `web` up by one and
its last terminal as `OK`. If the example host's policy has changed, use an
owner-approved public HTTPS page whose robots rules permit the request.

Next pick a public URL whose current, directly served `/robots.txt` explicitly
blocks the target for `Elaria-Reach` (or `*`). Set `BLOCKED_URL` to that URL.
Keep at least one web quota slot free so the request reaches the robots check.

```sh
assist reach fetch "$BLOCKED_URL" --json  # expected exit 2, ROBOTS_DISALLOWED
assist reach status                     # web usage +1; last terminal ROBOTS_DISALLOWED
journal="${XDG_DATA_HOME:-$HOME/.local/share}/assistant/journal.jsonl"
# Substitute the action_id printed by the refused fetch.
grep -F '<action_id>' "$journal"
```

Check the `reach.request` action and terminal `ROBOTS_DISALLOWED` observation
with that ID, with no page extract. If the site's robots file redirects, expect
`ROBOTS_UNREACHABLE` instead; use a directly served disallow to complete this
check. Set `enabled = false` and restart afterward if you don't want REACH on.
