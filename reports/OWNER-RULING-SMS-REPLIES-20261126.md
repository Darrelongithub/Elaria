# OWNER RULING — SMS replies (2026-11-26)

Owner ruled: **approve every reply.** "Responds to texts" means:
inbound SMS on the paired phone lands as untrusted content (IF-6);
Elaria drafts a reply in her own voice; the owner approves (or
edits/kills) each draft; only then does `sms.send_sms` fire.
Silence sends nothing. Every draft/approval/send is journaled.

No new authority: this is the existing approve-before-send rule
applied to replies. Her WhatsApp number (alive layer) remains the
autonomous-conversation channel for strangers — chat only, never
commands; the owner's personal SMS keeps the owner's thumb on
every send. Two channels, two trust levels, deliberate.

Also recorded same day: scrcpy phone-mirror idea PARKED
(`reports/DISPATCH-SCRCPY.md`); P0 bugfix waves in flight
(`bugs.md`); hardware pass begun by the owner 2026-11-26.
