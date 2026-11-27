# DISPATCH-REACH-WIRE — wire the internet fetcher (2026-11-27)

Found at the hardware pass (`bugs.md` GAP-HW4): `src/assistant/
reach/**` is complete and test-proven but nothing outside the
package imports it — `[reach] enabled` enables nothing.

## REACH-WIRE — Agent REACH

> You are Agent REACH. Wire your Phase-0 fetcher into the live
> system without weakening its contract. Existing: egress
> allowlist (GitHub API + web/news), journal-first ordering,
> terminal outcomes (`PLATFORM_BLOCKED`/`NEED_LOGIN`/rate-limit —
> never evaded), provenance-tagged untrusted landing (IF-6),
> `[reach]` config (disabled by default, per-channel caps).
> Build: (1) an errand skill `web.fetch` admitted to the
> errand runner's READ-ONLY vocabulary (fetched content enters
> errands only as `UntrustedObservation`; it can never become a
> plan step, tool call, or stated fact); (2) owner-gated daemon
> IPC + `assist reach {fetch,news,github,status}` CLI for direct
> asks; (3) `assist reach status` shows: enabled?, per-channel
> caps used today (from the journal, not memory), last terminal
> outcomes. (4) Interestingness stays reason-gated and OFF until
> the owner sets interests — wiring must not invent a feed.
> Eye-checks: fixture HTTP only in tests (allowlist refusal
> journaled BEFORE any socket; a prompt-injecting page lands as
> data and cannot steer the errand; rate cap refuses with the
> terminal outcome, journaled). Live network is the OWNER's
> hardware test, never CI's. (5) Owner test script ending the
> report: enable `[reach]`, `assist reach fetch` a public page,
> read her summary-with-sources, check `assist reach status`
> accounting, then a robots-disallowed URL → terminal refusal in
> the journal (BUG-C1 is fixed by then or this lane includes it —
> check `bugs.md` and say which). Sync main first. New `arena/*`
> branch, merged PR or it didn't happen. Never edit OWNERS.yaml.
