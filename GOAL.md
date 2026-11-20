# Booking Agent MVP — restaurant phone bookings

Goal ID: goal_46b0cd6695a8
Goal slug: booking-agent-mvp-restaurant-phone-bookings

## Description
Build a recording-version phone booking agent for Perth restaurants, then other appointment businesses. It records booking calls, transcribes them, extracts date, time, tables, adults, children, allergies, name and phone, pushes a tidy summary to the owner's WhatsApp, and creates a Google Calendar event. Test with one restaurant first, then sell as a monthly subscription.

## Build notes (2026-11-09, MVP scaffold)

- Scaffold built in this folder: `app.py` (FastAPI: `/voice` TwiML with EN+ZH recording notice, `/recording-complete` webhook, `/health`, `/test-extract`), `requirements.txt`, `.env.example` (no real values), `README.md` (setup: Twilio ACMA AU number, ngrok webhook, WhatsApp Sandbox, OpenAI, Google Calendar stub), `samples/transcripts.json` (3 samples) and `test_pipeline.py` (offline mock test, no Twilio/OpenAI calls).
- Decisions confirmed 2026-11-09: recording version (not live answering); new Twilio booking number (cleanest); bilingual zh/en; WhatsApp push + Google Calendar event; test first with Charles as both customer and owner using his own phone.
- Pricing discussed: Starter $99/mo (60 calls), Standard $179/mo (150 calls + calendar), Pro $299/mo (400 calls); $249 setup waived for first test restaurant.
- NOT done yet (needs Charles): no Twilio/OpenAI/Google account created, no credentials in any file, no live call tested, WhatsApp still sandbox mode, Google Calendar disabled (stub) until credentials exist.

## Build notes (2026-11-09, $0 mode)
- ZERO_COST_MODE=1 is now the default: no OpenAI key required, no paid
  Twilio number required. Transcription = local faster-whisper (tiny/base,
  CPU) if installed, else a clearly logged mock. Extraction = local Ollama
  (qwen2.5:3b, fallback llama3.2:3b) if reachable at localhost:11434,
  else the rule-based extractor in app.py. Method used is logged per
  booking and shown on /health.
- WhatsApp stays on the Twilio trial Sandbox (100 free messages);
  Google Calendar stays a stub until credentials exist.
- Verified 2026-11-09: py_compile OK, test_pipeline.py 3/3 PASS in
  ZERO_COST_MODE with OPENAI_API_KEY unset; live /health + /test-extract
  smoke test OK (rule-based fallback, Ollama not reachable in test env).
- Still NOT $0 in production: AU local number $3/mo (paid upgrade +
  validated address), OpenAI API only if ZERO_COST_MODE=0.

## Build notes (2026-11-09, $0 test env on this VM)

- Venv `.venv/` installed in this folder (FastAPI, faster-whisper 1.2.1,
  av==13.1.0 pinned — av 19.x breaks faster-whisper, av 14.x has no
  Python 3.12 wheel). Whisper tiny + base downloaded (~430 MB cache).
- Real-audio test with gTTS speech (15 s EN + 15 s ZH booking calls):
  tiny EN 1.2 s / ZH 1.0 s, base EN 2.0 s / ZH 1.6 s. Base is word-perfect
  incl. "Charles Wang" (tiny wrote "Wong"); ZH content-perfect both.
  Recommend base for the live test (`LOCAL_WHISPER_MODEL=base`).
- Two bugs fixed by the real-audio test: app forced `language="zh"` in
  transcription (now auto-detect, verified p>=0.98 EN/ZH); rule-based
  extractor only handled digit-heavy mock text (now handles word numbers,
  "7 p.m.", traditional 兩/點, month names, and "a table" vs numbered
  tables). After fixes: test_pipeline.py 3/3 PASS, real transcripts
  extract date/time/tables/adults/children/allergy/name correctly.
- FastAPI verified in ZERO_COST_MODE=1: /health zero_cost_mode true,
  openai_configured false, whatsapp sandbox; POST /voice returns
  bilingual TwiML; POST /test-extract returns correct booking + WhatsApp.
- Full runbook: RUN_TEST.md. Still missing for a live call: Twilio trial
  number + SID/token in .env, ngrok (not installed here), WhatsApp
  Sandbox join from Charles's phone. Ollama not installed — optional,
  rule-based extraction is the verified fallback. Google Calendar stub.

## Build notes (2026-11-19, after the first live call)

- Live call 2026-11-19 captured only Adults. Rule-based extractor fixed:
  12点半 times, 没有小孩 -> 0 children, bare 没有 allergy answer -> none
  stated, and relative dates (星期六 / 这周六 / this Saturday / 今天 /
  明天 / 后天 / 下星期X / next X) now resolve against the call date
  (Perth). Occasion (birthday/生日, anniversary, wedding, party ...) and
  extra comments go to special_requests.
- Recording notice is now English only: "This call is recorded to take
  your booking details."
- Owner summary moved from WhatsApp to SMS, sent from the 08 number
  +61 8 7562 7188 (SMS_FROM_NUMBER) to OWNER_SMS_NUMBER. Same content.
