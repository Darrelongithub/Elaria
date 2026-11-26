# BUILD-10 Owner Runbook — WhatsApp Cloud API Registration & S-0 Template Pack

- **Agent:** E (Phone Link, Alive Layer & Drafts)
- **Dispatch:** `reports/DISPATCH-BUILD-3.md` (`BUILD-10`)
- **Timestamp (UTC):** `2026-11-26T08:35:00Z`
- **Channel:** Meta WhatsApp Cloud API (`v21.0`) + serverless webhook endpoint + spare Safaricom/Airtel KE SIM
- **Mode:** **S-0 ONLY** (`responder_mode = "S-0"`; S-1 chatty mode is hard-OFF in code)

---

## 0. Plain-English Summary — How Her Phone Line Works

1. **Two numbers, one owner:**
   - **Elaria's line (spare SIM):** a second SIM (`+2547...`) registered on Meta's official WhatsApp Cloud API. Do **not** use your personal WhatsApp SIM here — registering a number on Cloud API disconnects it from the normal WhatsApp phone app.
   - **Your personal phone (`owner_e164`):** your everyday WhatsApp number. You message Elaria's spare-SIM number just like texting a contact.
2. **Inside 24 hours = FREE (`0 KES-cents`):**
   - Every time you send Elaria a message on WhatsApp, Meta opens a **24-hour customer service window** from that message's timestamp.
   - Inside that 24-hour window, Elaria's acks/replies are **free-form session replies** (`type: "text"`), covered by Meta's **1,000 free service replies per month** (`0 KES-cents`).
3. **Outside 24 hours = S-0 Utility Template or Nothing (`52 KES-cents`):**
   - If more than 24 hours pass without a message from you, Meta blocks free-form messages (`#131047`).
   - Elaria's transport (`src/alive/transport.py`) enforces this **before any network call**: a cold free-form send raises `OutsideServiceWindow` and sends zero packets.
   - Outside 24 hours, Elaria can **only** knock using one of the 4 pre-approved **S-0 `UTILITY` templates** (`meeting`, `deadline`, `commitment-due`, `already-sent knock`), capped in code at **`5` templates/day** by default (`max_templates_per_day = 5`, ceiling `10`).
4. **Laptop stays in charge:**
   - Nothing sent on WhatsApp executes on your laptop while it is asleep. Instructions wait in the HMAC-signed inbox and land in `awaiting_approval` when your laptop opens.

---

## 1. KES-Cents Cost Arithmetic (Kenya `+254` Rate Card)

Cited against Meta's official WhatsApp Business Platform per-message pricing for **Kenya / Rest of Africa** (effective Oct 2026, billed per **delivered** message; `1 USD ≈ 130 KES`, `1 KES = 100 KES-cents`):

| Message Type | When Used | Meta USD Rate | Cost in KES-Cents | Cost in KES | Code Guard |
| --- | --- | --- | --- | --- | --- |
| **Inbound message from you** | You text Elaria's number | `$0.0000` | **`0 KES-cents`** | `KES 0.00` | Capped at `owner_messages_per_day = 200` |
| **In-window session reply** (`send_service_reply`) | Elaria replies `< 24h` after your last message | `$0.0000` (first 1,000/mo) | **`0 KES-cents`** | `KES 0.00` | `stranger_messages_per_month = 800` keeps total well under 1,000 free/mo |
| **Out-of-window S-0 Utility template** (`send_utility_template`) | Reminder/knock when `> 24h` silent | `$0.0040` | **`52 KES-cents`** | `KES 0.52` | Default `max_templates_per_day = 5` (hard ceiling `10`), journaled per send |
| *(Hazard avoided)* Marketing template | Promotional / chatty copy | `$0.0248` | `322 KES-cents` | `KES 3.22` | **Blocked in code** (`TemplateSpecError` refuses non-`UTILITY` & promo words; S-1 OFF) |

### Monthly Budget Envelope (in KES-Cents & KES)

- **Typical student week (~1–2 out-of-window reminder knocks/day = 45 templates/month):**
  - `45 × 52 KES-cents = 2,340 KES-cents` = **`KES 23.40 / month`** (`~$0.18 / month`).
- **Default daily cap hit every single day (`max_templates_per_day = 5` × 30 days = 150 templates/month):**
  - Daily ceiling: `5 × 52 KES-cents = 260 KES-cents / day` = **`KES 2.60 / day`**.
  - 30-day ceiling: `150 × 52 KES-cents = 7,800 KES-cents / month` = **`KES 78.00 / month`** (`~$0.60 / month`).
- **Absolute code ceiling (`max_templates_per_day = 10` × 30 days = 300 templates/month):**
  - `300 × 52 KES-cents = 15,600 KES-cents / month` = **`KES 156.00 / month`** (`~$1.20 / month`). Setting `max_templates_per_day > 10` in `alive.toml` raises `AliveConfigError` at startup.
- **Spare SIM airtime keep-alive (Safaricom/Airtel Kenya):**
  - Top up **`KES 50`** (`5,000 KES-cents`) once every 60–90 days so the carrier never recycles the spare SIM.
- **Serverless endpoint + Google Drive sync:** **`0 KES-cents`** (Cloudflare Workers Free tier = 100,000 requests/day hard-capped with `$0` overage; existing personal Google Drive = 15 GB free).

Every paid template send writes a `paid_template_journaled` JSONL line to `<state_dir>/journal.jsonl` and `<reminder_log>/` with `cost_usd_est: 0.004`, `cost_kes_cents_est: 52`, and `spent_kes_cents_today_est`.

---

## 2. What You Need Before Starting (15 Minutes Prep)

1. **One spare Kenyan SIM card** (Safaricom or Airtel, `+2547...` or `+2541...`) inserted into any handset just long enough to receive **one 6-digit SMS or voice OTP**.
   - **Important:** Make sure this spare number is **not** currently logged into WhatsApp or WhatsApp Business on a phone. If it is, open WhatsApp on that phone → *Settings → Account → Delete my account* first so Meta allows Cloud API registration.
2. **A Facebook / Meta account** (needed once to log into `developers.facebook.com` and `business.facebook.com`).
3. **A Visa/Mastercard or M-PESA Global virtual card** (for Meta Billing so real S-0 utility templates can send outside the 5-number sandbox). Set a card spend limit of `KES 300/month` for belt-and-braces peace of mind.
4. **Your deployed serverless alive endpoint URL** (for example `https://elaria-alive.<your-subdomain>.workers.dev/webhook`).

---

## 3. Step-by-Step Registration (Non-Expert Checklist)

### Step 1 — Generate Your Local Secrets on the Laptop

On your laptop inside `/home/user/Elaria` (or your Elaria checkout), generate fresh secrets and save them in a root/owner-only file:

```bash
mkdir -p ~/.config/elaria
umask 077
PYTHONPATH=src python3 -m alive.provision init > ~/.config/elaria/alive.toml
chmod 600 ~/.config/elaria/alive.toml
```

Copy down the generated `verify_token` from `~/.config/elaria/alive.toml` — you will paste it into Meta in Step 6.

---

### Step 2 — Create the Meta Developer App

1. Open **[https://developers.facebook.com/apps/](https://developers.facebook.com/apps/)** and sign in.
2. Click **Create App**.
3. When asked *"What do you want your app to do?"*, choose **Other** → **Next**.
4. Select app type **Business** → **Next**.
5. Fill in:
   - **App name:** `Elaria Personal Line`
   - **App contact email:** your email address
   - **Business portfolio:** choose **Create a new Business Portfolio** (if you don't already have one) and name it after yourself.
6. Click **Create app**.
7. On the App Dashboard, scroll to **WhatsApp** and click **Set up**.
8. In the left sidebar, open **App settings → Basic** and copy your **App Secret**. Paste it into `wa_app_secret` (see Step 5 token custody below — never commit it to Git).

---

### Step 3 — Understand Meta's Test Number Limits (Before Adding Your SIM)

Meta immediately gives your new app a free **Test Phone Number** under **WhatsApp → API Setup**. Know its exact limits so they don't surprise you:

- **5-recipient hard limit:** The Meta test number can message **at most 5 manually verified phone numbers** (you must type each recipient number in the dashboard and enter an WhatsApp OTP).
- **24-hour temporary token:** The token shown on the *API Setup* page expires every **24 hours** — never use that button for your deployed alive host.
- **Fixed display name & test templates:** You cannot customize the test number's display name, and strangers cannot message it.
- **When to use it:** Optional 5-minute smoke test only. Proceed to **Step 4** to register your real spare SIM.

---

### Step 4 — Register Your Spare SIM as the Business Number

1. Put your spare SIM into a phone with cellular signal so it can receive SMS/calls.
2. In the Meta App Dashboard left sidebar, go to **WhatsApp → API Setup** (or **WhatsApp → Getting Started**), scroll to **Step 5: Add a phone number**, and click **Add phone number**.
3. Fill in the profile shown on WhatsApp:
   - **WhatsApp Business Profile Display Name:** e.g. `Elaria Desk` (plain, non-impersonating — matches Elaria's front-door card, e.g. *"Elaria — assistant for <Your Name>"*).
   - **Timezone:** `(GMT+03:00) Africa/Nairobi`
   - **Category:** `Professional Services` (or `Other`)
4. Click **Next**, select **Kenya (+254)**, enter your spare SIM number (without the leading `0`, e.g. `712345678`), choose **Text message (SMS)** (or **Phone call** if SMS takes >60s), and click **Next**.
5. Enter the **6-digit verification code** that arrives on the spare SIM.
6. Once verified, look at **WhatsApp → API Setup → Send and receive messages → From**, select your newly added `+254...` number, and copy:
   - **`Phone number ID`** (a 15-digit number like `106540352242922` — **not** the `+254` phone number itself)
   - **`WhatsApp Business Account ID`** (WABA ID)
7. Open **[https://business.facebook.com/billing_hub/payment_settings](https://business.facebook.com/billing_hub/payment_settings)** (or click **Add payment method** banner in WhatsApp Manager) and attach your M-PESA Global virtual card / debit card to the WhatsApp Business Account. Set currency to **USD** (or KES if offered). Without a payment method on file, Meta blocks paid `UTILITY` templates outside 24h even after template approval.

---

### Step 5 — Mint a Permanent System User Token & Lock Custody on Your Laptop

Do **not** use the 24-hour temporary token. Mint a permanent System User token scoped strictly to this single app and WABA:

1. Open **[https://business.facebook.com/latest/settings/system_users](https://business.facebook.com/latest/settings/system_users)** (*Business Settings → Users → System users*).
2. Click **Add** → Name: `elaria-alive-bot` → Role: **Employee** → **Create system user**.
3. Click **Assign assets** on `elaria-alive-bot`:
   - Select **Apps** → pick `Elaria Personal Line` → toggle **Manage app** (Full control).
   - Select **WhatsApp accounts** → pick your WABA → toggle **Manage WhatsApp Business accounts** (Full control) → **Assign assets**.
4. Click **Generate new token**:
   - Choose app: `Elaria Personal Line`
   - Token expiration: **Never**
   - Permissions — tick **ONLY** these two:
     - `whatsapp_business_messaging`
     - `whatsapp_business_management`
   - Click **Generate token** and copy the `EAAG...` string immediately (Meta only shows it once).

#### Token Custody Rules on Your Laptop & Serverless Host

1. **Never** put `wa_token`, `wa_app_secret`, or `mac_key` inside the Git repo (`/home/user/Elaria`), shell history, notes, or screenshots.
2. **On your laptop:** store secrets only in `~/.config/elaria/alive.env` with `0600` permissions (readable only by your OS user), and load them via environment variables (`ALIVE_WA_TOKEN`, `ALIVE_WA_APP_SECRET`, `ALIVE_MAC_KEY`, `ALIVE_VERIFY_TOKEN`, `ALIVE_FROM_HASH_SALT`):
   ```bash
   umask 077
   cat > ~/.config/elaria/alive.env <<'EOF'
   export ALIVE_WA_TOKEN="paste-system-user-token-here"
   export ALIVE_WA_APP_SECRET="paste-meta-app-secret-here"
   EOF
   chmod 600 ~/.config/elaria/alive.env
   ```
   *(Notice: the laptop daemon itself **never** calls Meta's HTTP API — only the serverless alive host holds `ALIVE_WA_TOKEN` at runtime; keeping a `0600` backup in `~/.config/elaria/alive.env` or your password manager is strictly for recovery/rotation.)*
3. **On your serverless endpoint** (e.g. Cloudflare Workers / Fly / Cloud Run): push secrets exclusively via encrypted secret store, never `wrangler.toml`:
   ```bash
   wrangler secret put ALIVE_WA_TOKEN
   wrangler secret put ALIVE_WA_APP_SECRET
   wrangler secret put ALIVE_VERIFY_TOKEN
   wrangler secret put ALIVE_MAC_KEY
   wrangler secret put ALIVE_FROM_HASH_SALT
   ```
4. **Instant revocation:** If you ever suspect a leak, go to *Business Settings → System users → `elaria-alive-bot` → Revoke tokens*. Every token dies in seconds.

---

### Step 6 — Point Meta's Webhook URL at Your Serverless Endpoint

1. Ensure your serverless endpoint is live and serving `alive.webhook.handle_request` over HTTPS on `/webhook` with `wa_phone_number_id`, `owner_e164` (in `+254...` format), and the secrets from Step 5.
2. In Meta App Dashboard, go to **WhatsApp → Configuration → Webhook** and click **Edit**.
3. Enter:
   - **Callback URL:** `https://<your-serverless-endpoint>/webhook`
   - **Verify token:** the exact `verify_token` from Step 1
4. Click **Verify and save**. Meta sends a `GET /webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...` handshake; `alive.webhook.verify_hub` verifies it in constant time and echoes the challenge (`200 OK`).
5. Under **Webhook fields**, click **Manage** and subscribe to **`messages`** ONLY. Leave `smb_message_echoes`, `calls`, `flows`, and marketing fields **unsubscribed** (even if sent, `alive.webhook` safely ignores non-`messages` fields).
6. Switch the **App Mode** toggle at the top bar of `developers.facebook.com` from **Development** to **Live** (Meta requires a Privacy Policy URL in *App settings → Basic* — any static HTTPS page stating *"Personal single-owner assistant; no third-party data sold"* satisfies this).

---

### Step 7 — Submit the 4 S-0 `UTILITY` Templates in WhatsApp Manager

Run this command on your laptop to print the exact code-reviewed JSON payloads (`src/alive/templates.py`):

```bash
PYTHONPATH=src python3 -m alive.provision templates
```

Now open **[https://business.facebook.com/latest/whatsapp_manager/message_templates](https://business.facebook.com/latest/whatsapp_manager/message_templates)** → **Create template**. Create each of the **4 templates** below with:
- **Category:** `Utility`
- **Language:** `English (en)`
- **Header / Buttons:** `None`
- **Footer:** `Elaria reminder line (queued until laptop is on)`

| # | Exact Template Name (`name`) | Exact Body Text (copy verbatim from `alive/templates.py`) | Sample `{{1}}` | Sample `{{2}}` |
| --- | --- | --- | --- | --- |
| 1 | `elaria_meeting_v1` | `Elaria meeting reminder: you asked to remember {{1}} scheduled for {{2}}. Reply here to queue a note for when your laptop is on.` | `project sync with Amina` | `today at 19:00 EAT` |
| 2 | `elaria_deadline_v1` | `Elaria deadline reminder: {{1}} is due {{2}}. Reply here if you want an instruction queued for your laptop.` | `Distributed Systems lab report` | `Friday 17:00 EAT` |
| 3 | `elaria_commitment_due_v1` | `Elaria reminder: you asked me to follow up on {{1}} at {{2}}. Reply here to queue an instruction until your laptop is on.` | `calling Dr. Kamau about lab results` | `08:30 EAT` |
| 4 | `elaria_already_sent_knock_v1` | `Elaria knock update: {{1}} (already sent at {{2}}) is still waiting for your review. Reply here to queue a note for your laptop.` | `meeting with Amina` | `06:55 EAT` |

- Meta's automated review normally approves clean transactional `UTILITY` templates in **1–15 minutes**.
- **Check category after approval:** Confirm all 4 show **`Utility — Approved`**. If Meta's April 2025/2026 recategoriser ever marks one `Marketing`, delete and resubmit with the exact samples above — `alive/templates.py` will never send a `MARKETING` template.

---

### Step 8 — Run the Local Doctor Self-Check

Fill in `owner_e164` (`"+2547..."`) and `wa_phone_number_id` in `~/.config/elaria/alive.toml`, then run:

```bash
source ~/.config/elaria/alive.env
PYTHONPATH=src python3 -m alive.provision doctor ~/.config/elaria/alive.toml
```

Confirm every line prints `ok`:
- `ok   config loaded`
- `ok   state dir writable`
- `ok   sync round-trip passed`
- `ok   template cap in code: 5/day`
- `ok   S-0 template pack validated (4 utility templates)`
- `ok   S-1 chatty mode OFF (Meta policy guard)`
- `ok   fast lane OFF (manager binding)`
- `DOCTOR PASSED`

---

## 4. Final On-Laptop & Phone Eye Check

Run this two-part acceptance check once Steps 1–8 are green:

### Part A — Laptop OFF, In-Window Session Reply (`0 KES-cents`)

1. **Sync commitments once, then shut the laptop lid** (or stop the laptop Elaria daemon completely so the laptop is demonstrably offline).
2. From your **personal phone** (`owner_e164`), send a WhatsApp text to Elaria's spare-SIM number:
   > `Remind me to pack the HDMI adapter tomorrow morning`
3. **What you should see on your phone within ~2–5 seconds:**
   - Elaria replies in the same WhatsApp chat:
     > `Got it — queued for your laptop (item #1). It's asleep right now; nothing happens until it's on.`
   - Check the serverless journal / Meta Insights: `type: "text"` service reply, **cost = `0 KES-cents`** (`billable: false` / free service tier).

### Part B — `> 24h` Silence, Cold Free-Form Blocked, S-0 Template Knock Arrives (`52 KES-cents`)

1. **Wait `> 24 hours` with zero WhatsApp messages from your phone** (say 24 hours + 15 minutes), having scheduled a mirrored reminder (`remind_at`) for after that 24-hour mark before closing the laptop.
2. **Verify two things at reminder time:**
   - Any attempt to call `send_service_reply` outside the 24h window is refused locally with `OutsideServiceWindow` (`cold_freeform_refused` in `journal.jsonl`, zero free-form HTTP calls).
   - At `remind_at`, Elaria's cron tick calls `send_utility_template` and your phone receives the approved **S-0 template knock**, e.g.:
     > `Elaria meeting reminder: you asked to remember project sync with Amina scheduled for today at 19:00 EAT. Reply here to queue a note for when your laptop is on.`  
     > *(Footer: Elaria reminder line (queued until laptop is on))*
   - Check `journal.jsonl` on the alive host: one `paid_template_journaled` event with `cost_kes_cents_est: 52`, `templates_sent_today: 1`, `cap_per_day: 5`.
3. **Open your laptop:**
   - `alive_sync.ingest(...)` drains the queued instruction from Part A into `cloud_jobs` with `status = "awaiting_approval"`.
   - `alive_sync.already_sent_knock_for_commitment(...)` reads `reminder_log/` so your laptop greets you with the short anti-duplicate line (`"Already sent to your phone at ..."`), instead of nagging you twice.

---

## 5. Cited Official Meta Cloud API References Verified Against Code

1. **Webhook setup, `X-Hub-Signature-256`, `hub.challenge`, and inbound `messages[]` schema (`wa_id` / `from` bare digits):**  
   `https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks/`  
   `https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started`
2. **`POST /<GRAPH_API_VERSION>/<PHONE_NUMBER_ID>/messages` syntax for session text & `template` components:**  
   `https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages/`
3. **Interactive button & template quick-reply inbound payloads:**  
   `https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-reply-buttons-messages/`  
   `https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/button/`
4. **Delivery `statuses[]` (`sent`, `delivered`, `read`, `failed` + `pricing`) & `#131047` re-engagement 24h window error:**  
   `https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids/`  
   `https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes/`
