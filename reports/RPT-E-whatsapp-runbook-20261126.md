# Agent E — WhatsApp Cloud API registration runbook (2026-11-26)

**Status: sandbox tests only, not live.** You, the owner, do every account,
SIM, billing and registration step. Never give an agent your passwords, codes,
app secret or tokens. Do not turn on S-1 chatty mode: the host only has the
S-0 deterministic concierge. Meta can reject the use case, templates, number,
or account; don't work around a rejection.

## Before paying or registering

1. Choose an owner-controlled spare SIM for Elaria's **business** number,
   distinct from your personal WhatsApp number (`owner_e164` is your personal
   destination, not the spare). It must receive Meta's registration SMS or
   call. Check Meta's current number eligibility and migration rules before
   using a number already on WhatsApp; registration may disrupt its old use.
2. On your laptop, sign into Meta for Developers and create a business app;
   add the WhatsApp product and link/create your Meta Business Portfolio and
   WhatsApp Business Account (WABA). Follow Meta's current onboarding prompts;
   eligibility, business verification, permissions and app review may be needed.
3. Start with Meta's provided test business number and temporary token in the
   WhatsApp API Setup page. Add and verify your own personal recipient there.
   Test numbers are restricted to registered test recipients and have Meta-set
   sending limits; inspect the current setup page rather than assuming a fixed
   allowance. Temporary tokens expire; don't call that a production setup.
4. When Meta permits it, add the spare SIM in WhatsApp Manager; select SMS or
   voice, enter the code yourself, set the display name and complete registration
   and two-step verification as prompted. Record the **phone number ID** (not
   the phone number) and WABA ID. Ensure the recipient has opted in. Do not
   register someone else's number.
5. Set up a least-privilege production system-user token with the necessary
   WhatsApp messaging and account permissions and WABA asset access; check its
   expiry and Meta's current instructions. Store the original in your laptop's
   encrypted secret manager, not Git, Drive, logs, or chat. The always-on host
   also needs the token, app secret, verify token and shared MAC key to operate:
   provision them via its secret manager or an owner-only config file (0600),
   never a public environment or repository. Rotate/revoke immediately if exposed.
   The existing `load_config` reads those values from the host TOML; secret
   manager injection into that TOML is a deployment responsibility, not built.
6. **Deployment prerequisite, not delivered here:** choose a serverless platform
   with a publicly reachable HTTPS endpoint bound to `alive.webhook.handle_request`,
   persistent private storage supporting SQLite transactions across requests and
   jobs, and a durable shared spool; wire the real sync backend, heartbeat and
   scheduled `reminders.tick`. The repo's `alive.serve` is a WSGI development
   runner, not a deployed serverless endpoint or scheduler. Ephemeral local disks,
   multiple independent replicas, or resetting SQLite can defeat dedup and the
   daily cap; do not deploy that way. If the provider cannot supply those
   guarantees, stop. `src/alive` must be included in the host deployment: the
   current Python wheel packages only `assistant`. Back up the state privately.
7. In Meta's app dashboard set the WhatsApp webhook callback to **your deployed
   serverless HTTPS endpoint URL** (for example `https://YOUR-HOST/webhook`,
   not localhost), and use a long random verify token matching the host config.
   Subscribe the app/WABA to the `messages` field. Configure the exact phone
   number ID, owner E.164, app secret, token and MAC key. Verify the GET challenge
   and signed POST; unsolicited/invalid signatures must get 403. Keep app secret
   private. This checkout cannot provision the host or give you its URL.
8. In WhatsApp Manager submit the pack below as `en`, proposed **utility**,
   with example values and the exact variable order. Meta decides approval and
   category; check approved spelling, language and final category before use.
   Don't change the submitted text without changing/versioning the code. The
   host currently fires `reminder_v1` and `mirror_stale_v1`; the other reviewed
   candidate strings are available to the adapter but event classification and
   an outbound already-sent knock scheduler are **not wired**. Existing laptop
   knock logic consumes the reminder log. Approval is not a promise of delivery.

## S-0 template submission pack

Source of truth: `src/alive/templates.py`; each is a body-only template with
text parameters, in order. Examples `{{1}} = project review`, `{{2}} =
Monday 10:00 EAT` (stale example: `{{1}} = 2026-11-01`). Review privacy before
sending any topic to Meta.

| Name | Exact body |
|---|---|
| `reminder_v1` | Reminder: {{1}} is due at {{2}}. |
| `meeting_reminder_v1` | Meeting reminder: {{1}} at {{2}}. |
| `deadline_reminder_v1` | Deadline reminder: {{1}} is due at {{2}}. |
| `commitment_due_v1` | Commitment reminder: {{1}} is due at {{2}}. |
| `already_sent_knock_v1` | A reminder for {{1}} was already sent at {{2}}. |
| `mirror_stale_v1` | Your reminder list has not been refreshed since {{1}}. Reminders are paused. |

## Cost and operating guard

The transport reserves a slot **before every template attempt**, including stale
notices and ambiguous failures, with a transactional SQLite record and journal.
Default is **3 attempts per UTC day**, not 3 per recipient or process. Zero
means no templates. The counter is deliberately conservative: it counts even
in-window utility messages and requests which may not have been delivered.
Inspect `template_attempts` and `alive-journal.jsonl`; an accepted API message
ID is not delivery or a bill. Meta's later status/billing is the authority.
The old 1,000 free-conversations assumption and the prior $0.004 estimate are
not a current price guarantee. Confirm current Kenya recipient, template
category, taxes, exchange rate, provider/platform costs and account billing
settings on Meta's pricing page and dashboard before enabling paid sends.

For a budgeting example only: if the confirmed *all-in* rate is **40 KES cents**
per delivered template, 3/day × 30 days × 40 cents = **3,600 KES cents = KES
36**; at 75 cents it is KES 67.50. These are hypothetical, not quotes, and the
code caps attempts rather than money. Check other possible fees separately.
In-window service replies are generally free under Meta's current terms, but
verify the current tariff. Outside 24 hours the transport refuses free-form;
only a permitted submitted and approved template may be attempted.

The mirror must be fresh and signed, and reminders require structured
`remind_at` values; normal commitment export does not yet derive them. Stale
mirror, suspected clock skew, platform restriction, exhausted cap, missing
approval or expired credentials can prevent a knock. The existing concierge
produces deterministic acknowledgements, not a general AI conversation.

## Documentation and fixture basis

- Meta Cloud API overview: https://developers.facebook.com/docs/whatsapp/cloud-api/
- Meta webhooks and message notifications:
  https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components
- Meta sending messages:
  https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages
- Meta template management: https://developers.facebook.com/docs/whatsapp/message-templates/
- Meta pricing: https://developers.facebook.com/docs/whatsapp/pricing/

`tests/test_e_whatsapp_cloud.py` exercises the documented nested WABA/entry/
changes/value shape, numeric `from`, phone-number metadata, text, media,
statuses and Unix timestamps with signed test fixtures; no live Meta request was
made and the documentation URLs were not independently fetched in this sandbox.
Confirm current docs at provisioning, including Graph API version v24.0 support.

## On-laptop eye check (after deployment and approval)

1. Use the Meta test number and verified personal recipient first; inspect the
   signed inbox, owner routing, journal and billing dashboard. Then repeat on
   the owner's registered spare number, within its approved terms.
2. Owner messages Elaria's number, then turns the laptop off. The deployed host
   should send its deterministic in-window acknowledgement; verify the message
   and Meta's billing rather than assuming success or zero charges.
3. With a fresh mirror containing a deliberately scheduled structured reminder,
   wait **more than 24 hours** after the last owner message and let it fire. An
   approved template knock should arrive, or the journal should explain why it
   did not. Confirm receipt, attempt count and actual charges. This is an owner
   acceptance test, not something this sandbox has performed.
