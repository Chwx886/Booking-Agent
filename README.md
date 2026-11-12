# Booking Agent MVP — restaurant phone bookings

Recording-version phone booking agent for Perth restaurants (later: any
appointment business — auto repair, beauty, clinics).

**Flow:** caller dials the Twilio number → bilingual recording notice
(EN + ZH) → call is recorded → on recording-complete the audio is
downloaded → transcribed (in $0 mode: local faster-whisper, or mock if
not installed — logged) → booking fields extracted (in $0 mode: local
Ollama if reachable, otherwise the rule-based extractor — never invents;
missing = "not stated") → tidy summary sent to the owner's WhatsApp via
Twilio WhatsApp Sandbox → Google Calendar event (optional/stub) → every
booking logged to `data/bookings.jsonl` + `data/bookings.csv`. No database,
no heavy framework.

## $0 test — end-to-end, no paid API, no paid number

**Default mode is $0: `ZERO_COST_MODE=1` in `.env` (the default).**
No OpenAI API key is required, and no paid Twilio number is required.
What is $0, and what is not:

| Piece | $0 version | What it costs in production |
|---|---|---|
| Phone number | **Twilio trial number** — the free trial number in the account. 75 free voice minutes in the trial. Calls only to **verified numbers** — Charles's own phone is already verified (he verified it by SMS at signup), so his self-test calls work. It is not an AU local number and is not for a real restaurant. | AU local number $3/mo (Perth, voice-only) — needs paid upgrade + validated AU address |
| Webhook exposure | **ngrok free tier** (`ngrok http 8000`) | A small VPS / Render / Fly.io for a stable URL |
| Transcription | **Local faster-whisper** (CPU, `tiny` or `base` model). Install: `pip install faster-whisper`. If it is not installed, the app logs `mock transcription — install faster-whisper for real audio` and does **not** call any paid API — the booking is still logged, with all fields missing, so nothing is silently invented. | OpenAI `gpt-transcribe` $0.0045/min (only if `ZERO_COST_MODE=0`) |
| Extraction | **Local Ollama** if reachable at `http://localhost:11434` — install from https://ollama.com, then `ollama pull qwen2.5:3b` (or `llama3.2:3b`). If Ollama is not running, the app falls back to the **rule-based extractor** in `app.py` and logs which one was used for every booking. | OpenAI `gpt-4o-mini` ~$0.01/call (only if `ZERO_COST_MODE=0`) |
| WhatsApp | **Twilio WhatsApp Sandbox** — 100 free messages in the trial. Owner joins once from his phone (`join <code>` to `+14155238886`). No Meta approval needed for the test. | Official WhatsApp Business sender + approved Utility template |
| Calendar | Google Calendar API is free. The calendar step stays **disabled** until OAuth credentials exist (`GOOGLE_CREDENTIALS_PATH`); the intended event is logged instead. | Free (API), once credentials exist |

**Exact commands for the $0 pipeline:**

```bash
cd ~/workspace/goals/booking-agent-mvp-restaurant-phone-bookings
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install faster-whisper          # $0 transcription (optional but recommended)
# Optional, for LLM extraction instead of rule-based:
#   install Ollama from https://ollama.com, then: ollama pull qwen2.5:3b
#   (leave Ollama stopped to test the rule-based fallback)
cp .env.example .env                # fill in Twilio SID/token + trial number only;
                                    # leave OPENAI_API_KEY blank, keep ZERO_COST_MODE=1
uvicorn app:app --host 0.0.0.0 --port 8000
ngrok http 8000                     # free tier; set the Twilio trial number's
                                    # Voice webhook to https://<ngrok-url>/voice (POST)
# Offline re-check, no calls, no paid APIs:
ZERO_COST_MODE=1 python3 test_pipeline.py
# Live check (no call needed):
curl http://localhost:8000/health
#   -> zero_cost_mode: true, transcription_method / extraction_method,
#      ollama_reachable: true/false
```

**$0 self-test (Charles as owner AND customer):** join the WhatsApp
sandbox from your phone, call the Twilio **trial** number from your
verified phone, say a booking in Chinese, hang up, wait ~30–60 s.
You should get the WhatsApp summary (or, if faster-whisper is not
installed, a logged "mock transcription" booking with fields missing —
install faster-whisper and repeat). Repeat in English and with a vague
call. See §6 for the full 6-call script.

**Plainly, what is still NOT $0 in production:** the AU local number
($3/mo, paid upgrade + validated address), and OpenAI API fees *only if*
you switch `ZERO_COST_MODE=0`. The $0 mode is a test mode — it proves
the pipeline end-to-end before any money is spent.


**Money flow:** restaurant pays a monthly subscription (Starter $99/mo /
60 calls, Standard $179/mo / 150 calls + calendar, Pro $299/mo / 400 calls;
$249 setup, waived for the first test restaurant). Direct cost is
~A$0.12–0.20 per 3-minute call.

## 1. What you need (accounts — create these yourself, no secrets here)

| Account | Why | Where |
|---|---|---|
| Twilio | Trial number, call recording, WhatsApp sending | https://www.twilio.com — sign up (trial, no card) |
| OpenAI | Transcription + extraction — **only if `ZERO_COST_MODE=0`**; not needed for the $0 test | https://platform.openai.com/api-keys |
| Local (free) | faster-whisper + Ollama — the $0 transcription/extraction path | `pip install faster-whisper`; https://ollama.com |
| Google Cloud (optional) | Calendar events only; MVP works without it | https://console.cloud.google.com |

No account is created by this code, and no credential is stored in this repo.

## 2. Twilio setup (do this first — AU number verification can take 1–3 days)

1. In Twilio Console, complete identity verification. Australian numbers are
   regulated by ACMA — Twilio will ask for business/identity documents.
   Start this on day 1; it is the longest pole in the timeline.
2. Buy a number: Phone Numbers → Buy a Number → Australia → Local.
   Note the number, e.g. `+61800000000`.
3. Set the number's Voice webhook to your public app URL (step 3):
   `https://<your-public-url>/voice`, HTTP **POST**.
   Also set the recording callback implicitly — the `/voice` TwiML points
   `recordingStatusCallback` at `/recording-complete`.

## 3. Run the app locally

```bash
cd ~/workspace/goals/booking-agent-mvp-restaurant-phone-bookings
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in YOUR values in .env (never commit it)
uvicorn app:app --host 0.0.0.0 --port 8000
```

Check it: `curl http://localhost:8000/health`

Expose it publicly for Twilio (Twilio cannot reach `localhost`):

```bash
ngrok http 8000
# use the https URL ngrok prints, e.g. https://abcd1234.ngrok.io
# Twilio Voice webhook becomes https://abcd1234.ngrok.io/voice
```

For a real pilot, deploy the same app to a small VPS / Render / Fly.io
with the same `.env` values and a stable domain — the code does not change.

## 4. WhatsApp — sandbox first (test), official later

**Sandbox (MVP test — no Meta approval needed):**
1. Twilio Console → Messaging → Try it out → WhatsApp Sandbox.
2. The owner (Charles, for the self-test) sends the sandbox join code
   from his own phone to the Twilio sandbox number `+14155238886`,
   e.g. `join <code>`. This is a one-time opt-in per phone.
3. Set in `.env`: `WHATSAPP_MODE=sandbox`,
   `TWILIO_WHATSAPP_FROM=whatsapp:+14155238886`,
   `OWNER_WHATSAPP_NUMBER=+61...` (owner's mobile, E.164).
4. Sandbox messages only go to phones that have joined. That is fine for
   the self-test; it is not a product limitation to fix yet.

**Official (before a paying restaurant):**
Apply for a WhatsApp Business sender in Twilio (business verification +
a Utility template for the booking summary, e.g. "New booking: {{1}}").
Then set `WHATSAPP_MODE=official` and
`TWILIO_WHATSAPP_FROM=whatsapp:+61...` (your approved sender).
Template approval typically takes 1–2 days.

## 5. Google Calendar (optional — disabled by default)

1. Google Cloud Console → create a project → enable the Calendar API →
   create OAuth client credentials (Desktop app) → download the JSON.
2. Run the OAuth flow once to get an authorised-user token file, and set
   `GOOGLE_CREDENTIALS_PATH=/path/to/token.json` in `.env`.
3. Install the optional deps: `pip install google-api-python-client google-auth`
   (commented out in `requirements.txt`).
4. If the path is blank or the file is missing, `create_calendar_event()`
   returns `{"status": "disabled"}` and the booking is still logged —
   nothing is silently lost. Events are created in `Australia/Perth` time.

## 6. Test it — Charles as owner AND customer

No restaurant needed for the first test. One phone is enough:

1. Start the app + ngrok, set the Twilio webhook (steps 2–3).
2. Join the WhatsApp sandbox from your phone (step 4).
3. **As customer:** call the Twilio number from your phone.
   Say a booking in Chinese, hang up, wait ~30–60 s.
   Repeat in English. Try one vague call (no phone number / no firm date).
4. **As owner:** check WhatsApp — you should get a tidy summary, with
   `⚠️ Missing: ...` on the vague call. Check `data/bookings.jsonl`.
5. Verify offline any time, with no paid calls:
   ```bash
   MOCK_MODE=1 python3 test_pipeline.py
   ```
   Runs the 3 sample transcripts in `samples/transcripts.json`
   (Chinese complete / English complete / missing-info) through
   extraction → WhatsApp formatting → ledger, and asserts the fields.

## 7. Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Config status (no secrets returned) |
| `/voice` | POST | TwiML: notice + record (Twilio Voice webhook) |
| `/recording-complete` | POST | Twilio recording callback; work runs in background |
| `/test-extract` | POST form `transcript=...` | Extract + format without a phone call |

## 8. Files

- `app.py` — the whole app: TwiML, webhook, transcription, extraction
  prompt + JSON schema, WhatsApp send, calendar stub, ledger.
- `samples/transcripts.json` — 3 test transcripts + expected fields.
- `test_pipeline.py` — offline mock test (no Twilio/OpenAI calls).
- `requirements.txt`, `.env.example` — deps and config template.
- `data/` — created at runtime: `bookings.jsonl`, `bookings.csv`,
  `recordings/*.mp3`. Contains real customer audio/transcripts — treat as
  private, do not share or commit.

## 9. Known limits (MVP)

- Recording only — the agent never answers live or asks follow-up questions.
  If the caller omits a field, it is flagged "not stated", not chased.
- One number / one owner per deployment. Multi-restaurant = one deployment
  per restaurant (or one app + per-restaurant config — a later step).
- Recording consent: the notice at the start of every call is the consent
  step. Do not remove it.
- Twilio bills in USD; OpenAI bills in USD. Budget in AUD with ~1.5× FX.
