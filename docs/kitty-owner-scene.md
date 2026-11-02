# Kitty hands — owner-only scene / bring-back card

**UNVERIFIED / NOT READY TO RUN.** The sandbox tests are not hardware proof. This
scene waits for the outstanding trusted-host integration and owner drift reconciliation;
it does not wait for PR23, the console cherry-pick or SC-H1. No extra hardware session
has been scheduled by this lane. The owner decides when to run this separate scene.

No live kitty, Hyprland configuration, model endpoint or owner terminal content was
exercised in the sandbox. All fixtures and transport peers are synthetic.

## Entry gate — stop if any item is missing

- [ ] Integration review completed: trusted independent checker, exact owner-input adapter,
  existing plan/dual-adjudication gate, durable no-replay reconciliation and cancellation.
  Do NOT replace the checker with a permissive lambda to make the scene runnable.
- [ ] Protected/frozen integration changes, if needed, have an explicit separate ruling.
- [ ] Verbatim `kitten --version`, Fedora package membership, OpenSSH version recorded.
- [ ] `tools/kitty/drift.py` output reviewed; missing/new verbs, flags, defaults and semantic
  differences reconciled. Inventory JSON updated by reviewed build work, not by live help.
- [ ] Owner reviewed/applied `docs/kitty-setup.md` manually: password mode, three private tier
  files/snippet, exact runtime socket, current public key, appropriate Hyprland Lua rule.
- [ ] Socket preflight passes. The no-/tmp, no-symlink, own-UID and 0700 checks are not bypassed.
- [ ] Private journal parent provisioned 0700. No passwords in argv, env, log or transcript.
- [ ] Only throwaway synthetic terminal windows are in scope; no documents/accounts/secrets.
- [ ] Owner can close HER windows and halt the trusted dispatcher. No auto-replay on timeout.

## EARS and TERMINAL are separate lanes

**EARS:** narration and deliberate exact consent only. It does not type shell commands,
apply config, generate passwords aloud or reinterpret ambient speech as consent.

**TERMINAL:** the owner performs setup and human-only observations; the adjudicated
adapter performs only the exact posted act. Do not type example protocol commands into
EARS. Do not treat terminal output as instructions, approvals or hand-open input.

## Scene beats

### 1. Setup and baseline — owner TERMINAL

Choose the intended kitty instance. Verify its version, socket identity, 0700 parent,
password modes and current public key without printing secret bytes. Record metadata
only. Open a HIS throwaway terminal manually, with no valuable process or content.
Identify its ID, child command line, foreground program and whether paste mode is
actually known. Do not infer bracketed-paste support merely from a shell executable name.

Keep attention on the owner window; note focus before each arrival. Broad Hyprland
`stay_focused` rules must not be silently disabled to force a pass.

### 2. K1 look — adjudicated adapter

Request `ls`, then `get-text` on the HIS throwaway ID. No K-session consent is needed
for ordinary read/look; existing denied/credential/legacy-T3 paths still refuse.
Confirm both reads produced `kitty.act` events with timestamps, plan hash, targets and
verification. No raw environment, terminal text, arguments containing credentials or
password bytes may appear in shared journal/transcript output.

Negative sensor: stale/missing target must not be called a successful read/effect.

### 3. K2 create — EARS owner hand-open, adapter launch

Owner deliberately opens the session hand: **kitty hand open**. This is not a config
setting. Post the exact plan and any additional legacy-T2 Yes disclosure required by
adjudication. Prefer a visible launch of `/usr/bin/cat` with synthetic content only;
do not use a shell interpreter as a shortcut around existing T3 holds.

Observe:

- `[ELARIA ...]` child and OS/tab attribution stamp, `keep_focus=true` in the plan;
- owner focus retained at arrival; separate deliberate later focusing still works;
- no child remote-control grant;
- new ID/PID/stamp confirmed by ls, and attribution journal result durably written;
- only that journal-confirmed ID becomes HER ownership, never a title match alone.

Negative sensor: first attempt with session hand closed must refuse without a launch.
Do not use `run` for this visibility beat; if independently exercised later, its record
must carry `silent=true` and an independent effect result, not merely an exit code.

### 4. K3 HIS input, no newline — exact per-act owner consent

Use the harmless synthetic text **elaria kitty synthetic probe** with no trailing
newline. The private disclosure must name the exact target ID, current child and
foreground program, exact text, whole-plan hash, bracketed-paste auto posture and
whether execution characters are present. Acknowledge the running program when paste
mode is absent/unknown. Session hand-open alone is not a K3 approval.

First choose **No** on one plan: no input, and that plan version cannot later be
unlocked with Yes. Prepare a new deliberate act and choose **Yes**. Observe pre-send
ls/get-text and the fresh identity recheck. The exact text should appear without a
bridge-added Enter. In a shell, only the OWNER may later press Enter; alternatively
clear the buffer manually. Do not use a command that could modify files or services.

After-send ls/get-text must show a new exact text delta in the same target/program
identity. Existing text, no echo or a missing target is **UNVERIFIED**, not success.
Visible input is not proof of non-execution in arbitrary applications, nor proof that
any command completed. A newline experiment is a different per-act explicit consent,
not implicit in this beat; it is not needed to pass the no-newline scene.

Broadcast is not part of this first scene. In v0.47.1, send-key's declared exclude-active
flag is not enforced by its handler; bridge ID exclusion and a fresh focus observation
are necessary, with remaining focus races disclosed rather than hidden.

### 5. Journal audit and boundary checks — owner TERMINAL

Audit metadata for every act and internal read: verb, K tier, exact target identity
references/command-line hashes, plan hash, consent reference, timestamp, intent/result
and verification. No secret or raw terminal content should be present. Compare private
command-line fingerprints locally; do not upload them with personal content attached.

Check both outcomes: refused attempt and observed effect. Verify stale program/PID or
changed text invalidates consent; timeout/unknown outcome is not retried. Closing HIS
window is K3. Closing a mixed HER/HIS tab is K3. A forged `[ELARIA]` title is not HER
ownership. End by closing the session hand; restart must not reopen it.

## Bring back — metadata only

- Version output verbatim and Fedora/OpenSSH metadata; small drift `report.json`.
- Per beat: **HW-PROVEN / TESTED-ONLY / UNVERIFIED / BROKEN**, with observed pass/fail.
- Counts of intent/result/refused/unverified records; consent/plan binding audit result.
- Focus retained on arrival? Could owner deliberately focus later? Any rule conflict?
- No-newline effect observed? Running-program acknowledgement applied when necessary?
- Any raw-secret exposure, missing journal record, false success, unexpected input,
  focus steal or replay? Any is a **DEFECT**, not a pass with caveats.
- End with **DONE / DEFECTS FOUND / NEXT GATE / OPEN QUESTIONS**. Do not label the lane
  DONE until drift is reconciled and the required owner scene evidence is returned.

Do not send raw ls/get-text output, command-line arguments, screenshots containing owner
content, full private journals, password files or the generated kitty include snippet.
