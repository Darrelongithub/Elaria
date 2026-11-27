# Hardware pass — live status (owner laptop, 2026-11-26)

| Phase | State |
|---|---|
| 1. Install + `assist doctor` | ✅ PASS — 41/43 OK; warnings: missing `assist ptt cancel` bind (cosmetic), hotword was paused (fixed: `keyword_model` → `models/elaria_head.onnx`, armed-ready) |
| 2. Voice / wake | 📌 **PINNED by owner (2026-11-26, in a library).** Capture blocker BUG-HW1 FIXED + manager-verified (PRs #164/#165: `pw-record -` emitted AU/big-endian, daemon read s16le → static). Owner must: `git pull && uv sync`, restart, interactive PTT test (transcript + clean WAV playback), then "Elaria, what time is it?" + stranger test; report `last_trigger` + scores. Thresholds frozen (1.75/0.75/0.5) whatever happens — if the model under-scores, the answer is labelled samples, never a lowered bar. **Remind the owner of this pin when voice comes up.** |
| 3. Orb eye-check | ✅ **PASS (owner, 2026-11-27)** — after BUG-HW1/HW2/HW2B fixes and session repairs (graphical-session.target pull-in now in owner's `hyprland.lua` startup; `toolkit-accessibility=true`; mako privacy criteria for KDE Connect set same day). Owner ran the zenity script post-HW2B (manager-verified 31 tests): ring landed on the real Cancel button. Remaining formalities when convenient: nonexistent-label + password-field no-ring checks. |
| 4. Phone pairing | ⏳ Runnable silently. Pairing is the owner's act in the KDE Connect sidecar (daemon only reads paired devices + journals transitions — never accepts/requests codes). Verify daemon sees the pair; SMS = draft → owner approve → `sms.send_sms` only (owner ruling 2026-11-26). |
| 5. Seams (WhatsApp runbook, rclone→Drive, `[reach] enabled`, provider checklist) | ⏳ Separate sittings. |

Also outstanding (owner, any time): `OWNERS.yaml` cleanup — lint
now reads 48 zero-owner on current main; laptop stash
(`stash@{0}`, copies in `/tmp`) is superseded — do not pop.
