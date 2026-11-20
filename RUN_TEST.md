# Booking Agent MVP — $0 live-test runbook (prepared 2026-11-09, this VM)

> ⚠️ CORRECTION (2026-11-10): the "$0 live test" claim below is WRONG for a
> live call. Checked in the Twilio Console 2026-11-09: the trial gives 75 free
> voice minutes and transcription is included in those minutes ($0 either way),
> but the trial includes NO phone number — Active numbers is empty, balance
> $0 — so nobody can dial in and no live call can run for $0. A live-call test
> needs a Perth local number at $3/month after a paid upgrade (AU number
> verification takes 1–3 days). The offline tests below are still valid; do
> NOT follow this runbook expecting a free trial number to exist.

$0 mode is READY on this VM for OFFLINE tests only. No OpenAI key needed.
Verified 2026-11-09 — see "Verified on this VM" below.

## What is installed (this VM)

- Python venv: `.venv/` (483 MB) — FastAPI, uvicorn, faster-whisper 1.2.1,
  **av==13.1.0** (pinned — see the warning below), gTTS (test audio only).
- Whisper models in `~/.cache/huggingface` (~430 MB total): `tiny` (~75 MB)
  and `base` (~145 MB), both downloaded and verified.
- Test audio: `test_audio/en_booking.mp3` + `test_audio/zh_booking.mp3`
  (15 s each, generated with free gTTS, no key). Scripts:
  English booking (Sat 15 Nov, 7pm, 2 tables, 8 adults + 2 children,
  1 peanut allergy, Charles Wang) and the same in Chinese.
- NOT installed here: `ngrok`, `ollama`. Ollama is optional (rule-based
  extraction is the fallback and is verified). ngrok is needed for the
  live Twilio webhook — install it at test time (step 2).

## Verified on this VM (2026-11-09)

- faster-whisper **tiny**, 15 s audio: EN transcribed in 1.2 s, ZH in 1.0 s.
  EN was word-perfect except the name ("Charles Wong" for Wang);
  ZH was content-perfect (traditional characters, all numbers/dates right).
- faster-whisper **base**, 15 s audio: EN in 2.0 s, ZH in 1.6 s.
  **Both word-perfect, including "Charles Wang".**
  Recommendation for the live test: `LOCAL_WHISPER_MODEL=base`
  (slower to load first time, ~15 s, but more accurate on names).
- Auto language detection works for both (p >= 0.98). The app previously
  forced `language="zh"`, which would have mis-transcribed English calls —
  fixed 2026-11-09 to auto-detect (`language=None`).
- Rule-based extraction on the REAL transcripts (not just the mock samples):
  EN and ZH both extract date 11-15, time 19:00, tables 2, adults 8,
  children 2, allergy peanut/花生, name — correctly. Phone is "not stated"
  because the test audio contains no phone number (correct, not invented).
  Two extractor bugs found by this real-audio test and fixed the same day:
  word numbers ("two tables", "eight adults"), "7 p.m.", traditional
  兩/點, month names ("15th of November"), and "a table" no longer
  overriding a numbered tables count.
- `ZERO_COST_MODE=1 python3 test_pipeline.py`: **3/3 samples PASS**.
- FastAPI in ZERO_COST_MODE=1: `/health` returns
  `zero_cost_mode: true, openai_configured: false, whatsapp_mode: sandbox,
  calendar: disabled (stub)`; `POST /voice` returns the bilingual
  recording-notice TwiML; `POST /test-extract` returns the correct booking
  + WhatsApp text. Ollama was NOT reachable in this environment, so
  extraction used the rule-based fallback (logged as such).

## ⚠️ Two gotchas found while setting this up — do not "fix" by upgrading

1. **av must stay at 13.1.0.** faster-whisper 1.2.1 + av 19.x fails
   (`av.open() got an unexpected keyword argument 'metadata_errors'`);
   av 14.x has no wheel for Python 3.12 and fails to build.
   Pinned in `requirements.txt`. Re-run the transcription test if av changes.
2. **Memory is tight on this VM** (6 GB shared, ~400 MB free at test time).
   tiny/base both ran fine, but do not load a larger Whisper model here
   and do not run Ollama on this VM at the same time as the server.

## Start the server (this VM)

```bash
cd ~/workspace/goals/booking-agent-mvp-restaurant-phone-bookings
cp .env.example .env   # fill in Twilio + owner values (see below) — never commit .env
# Use base for accuracy on names:
LOCAL_WHISPER_MODEL=base ZERO_COST_MODE=1 .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
# Health check (new terminal):
curl http://127.0.0.1:8000/health
# Quick extraction check, no phone call needed:
curl -X POST http://127.0.0.1:8000/test-extract -F "transcript=Hi, I would like to book for Saturday the 15th of November at 7pm, two tables, eight adults and two children, one person has a peanut allergy. My name is Charles Wang."
```

## Expose it for Twilio (test time only)

```bash
# Install ngrok first if missing (https://ngrok.com/download), then:
ngrok http 8000
# Note the https URL, e.g. https://abcd-1234.ngrok-free.app
# In Twilio Console, set the trial number's Voice webhook (POST) to:
#   https://<ngrok-url>/voice
```

## Still missing before Charles can call the trial number

Do NOT fetch Twilio credentials yourself. Charles / the parent agent must
supply these at test time:

1. **Twilio trial number** — the free number in Charles's Twilio account
   (created 2026-11-09, charlestest886@gmail.com, 30-day trial, 75 free
   minutes). Trial calls only go to verified numbers — Charles's own
   phone is already verified, so his test calls will work.
   Set in `.env`: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
   `TWILIO_NUMBER` (the trial number).
2. **SMS summary** — sent from the 08 number +61 8 7562 7188
   (`SMS_FROM_NUMBER`, must be SMS-capable in Twilio) to the owner.
   Set in `.env`: `OWNER_SMS_NUMBER=+61...` (Charles's mobile).
3. **ngrok URL** in the Twilio webhook (step above) + the server running
   on this VM while Charles calls.
4. Optional: Ollama + `ollama pull qwen2.5:3b` for LLM extraction instead
   of rule-based. NOT required — rule-based is verified and is the safer
   default for the $0 test (it never invents a field).
5. Google Calendar stays disabled (stub) until OAuth credentials exist —
   the booking is still logged and texted without it.

## Live test script (Charles, ~2 hours, from his phone)

Call the trial number from his own (verified) phone, 6 calls, ~3 min each:
1. English, complete info. 2. Chinese, complete info.
3. English, missing info — summary must say "not stated", not guess.
4. Chinese, with an allergy (e.g. 1 person peanut allergy).
5. Small talk first, then the booking — only booking fields extracted.
6. Greeting only, no booking — NO SMS/calendar, logged only.

Pass = all 6 in the ledger (`data/bookings.jsonl`), SMS within
~5 min of hangup, calendar/date/time/allergy correct, nothing invented.
