# Kitty effect adapters — first family / attribution checkpoint

**TESTED-ONLY; partial implementation, not v1.1 completion. Scene NOT READY.**
Binding doctrine is recorded in `docs/design/kitty-2026-11-02-checkpoint-ruling.md`.
Missing evidence is **blocked, not bypassed**. These assessments do not authorize an
act, verify an effect, or replace legacy R3/T3, exact consent, session hand or ID guards.

## Implemented family: create-marker (partial)

`adapters/marker.py`, assessor `kitty.create-marker/v1`, owns this family's decision.
It does not assess another verb. `NativeChecker` constructs the exact class; IPC cannot
install an adapter, supply a verdict or submit an evidence receipt.

Reviewed upstream: kitty 0.47.1, commit
`fb5255b1ae4f0249ba832d6a773348fd103449ce`. Source identities:

| File | SHA256 |
| --- | --- |
| `kitty/rc/create_marker.py` | `ac844de07cd150c10ab76ca43685ef6bbe0ee7c6ea7baab67773205dd7989e90` |
| `kitty/options/utils.py` | `8a5a7ec2dca9f4d18fa68c5d9bfc9591281c66ed378ce227161df98472f0afa2` |
| `kitty/window.py` | `6e1b33931d3a3795bf082a886ed946b2f0a954a7e4171d4ba5e57bd1145ff846` |
| `kitty/marks.py` | `e4c5e9bbc0f4e4cc412c0dd97becb86d8ceeaf9d4c91d4c533f1946b4b99f6e2` |

Reviewed chain: `CreateMarker.response_from_kitty` → `Window.set_marker` →
`parse_marker_spec` → `marker_from_spec`. The parser calls `re.escape` for `text` and
`itext`; it does not escape regex forms. Function markers use `runpy.run_path`.
No upstream module or requested marker file is imported/executed/read by the adapter.

| Evidence / form | Assessment |
| --- | --- |
| Missing/changed catalogue version, commit, RC source path or source hash | REFUSE: `marker-source-evidence-missing-or-stale` |
| Missing specification or declared IDs | REFUSE with specific missing-evidence reason |
| Missing/mismatched resolved observations at disclosure/pre-exec | REFUSE: `marker-target-evidence-missing` |
| `text` / `itext` with proven literal grammar | Legacy T1, reversible native highlighting; still K2 hand + all normal gates |
| `function` | REFUSE: Python evaluation is legacy T3; owner Yes cannot unlock it |
| `regex` / `iregex` | REFUSE: complexity/effect evidence not implemented; compile success is not proof |
| Unknown type, malformed pairs, unproven integer form or exceeded parser bounds | REFUSE with specific reason |

Literal grammar currently accepts colors 1–3, nonempty NUL-free text, at most 32
color/text pairs and 4096 total characters in those pairs. These conservative parser
bounds are not completion of the later pending-plan/resource-bound gate. Upstream's
other integer/clamping forms remain unsupported, not silently normalized after hashing.
Literals can contain shell-looking text, regex punctuation or paths: the reviewed
escaping semantics, not an approved task/text list, determine their classification.

Plan-time assessment occurs before ls and proves only the effect grammar with declared
IDs; disclosure/pre-exec require matching resolved observations too. Existing selector
resolution and identity/consent gates still run. This does not close target TOCTOU races.
Marker state has no implemented independent post-effect probe: a successful reply stays
**UNVERIFIED**, not verified highlighting or proof of restoration of previous markers.

## NOT implemented: ten other families

`action`, `kitten`, `launch`, `new-window`, `run`, `load-config`, `env`, `send-text`,
`send-key`, `signal-child` still have **no family adapter**. The native boundary records
`<verb>-adapter-not-implemented` with a refusal and evidence reference. These are NOT
ten shipped adapters and are not counted as completion because they refuse. There is
no generic effect classifier that accepts model/owner assertions. Launch/typing scene
beats remain blocked, not bypassed. The legacy hands gate explicitly is not a production
command/effect analyser and has not been repurposed as one.

## Assessment trail: WHO and ON WHAT

`attribution.py` only formats/validates receipts; it makes no effect decision. Each
receipt includes assessor/version, reason code, assessment phase, legacy tier, nature,
denied verdict, bracketed-paste finding, and SHA256 references. The evidence contains:

- Exact act digest: verb, complete payload, declared target IDs and nonce.
- Observed target/program identity fingerprint (empty at pre-observation plan time).
- Catalogue digest, and the family source-review digest when that review matches.
- An `evidence_ref` over the complete receipt body, binding reason/verdict and phase too.

Only digests/codes persist; no raw input, argv, file content, password or exception text.
The source-review digest is reproducible from the commit and source table in the module.
It is a reference to reviewed upstream semantics, **not an installed-binary attestation**,
a signature or proof that hashes alone make an effect safe.

`phase=assessment` records are written/fsynced before the R3 gate and before dispatch,
including negative results. Disclosure also uses this path; it no longer calls a checker
without attribution. A write failure prevents dispatch. Invalid/throwing checkers are
recorded by `kitty.assessment-boundary/v1` as refusals, never generic positive assessments.
Recovery validates receipt shape/reference, retains the trail and never restores an
assessment as consent, hand-open or execution authority. Existing pre-attribution ledger
records remain readable; history is not rewritten or retroactively attributed.

Legacy injectable library test checkers without attribution are explicitly labeled
`unattributed-library-checker` with a null reference. This compatibility seam is not a
production adapter: mounted attach always constructs NativeChecker, whose results carry
attribution; request JSON cannot access test dependency injection.

## Parallel reconciliation / interpreter status

The pinned 39 RC source hashes and this family's dependency chain were rechecked in the
disposable upstream research tree. Inventory/renderer/drift outputs remain unchanged.
No owner Fedora membership, installed kitty/kitten help/version, OpenSSH or drift result
has been received. This missing reconciliation runs alongside adapters, not after them;
upstream inspection is not substituted for installed-owner evidence.

The sandbox has Python 3.11.2. A standalone 3.14 interpreter download was attempted via
GitHub, but its redirect to `release-assets.githubusercontent.com` failed with curl
exit 35 (`SSL_ERROR_SYSCALL`); that host is outside this sandbox's outbound allowlist.
No 3.14 interpreter was installed or executed. A local 3.14 full-suite gate remains
outstanding before the scene card; the owner's reported 3.14.8 is not sandbox evidence.
No shared fixture change or hardware request was made to work around this limitation.

Next: remaining per-family adapters and their primary missing-evidence tests. Only then
advance to full target/effect coverage, broader stream/cancel fault tests, resource
bounds, and lastly the scene card. Owner reconciliation continues alongside.
