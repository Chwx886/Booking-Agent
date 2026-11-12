"""
Booking Agent MVP — recording-version phone booking agent (Perth restaurants).

Flow:
  Twilio number receives call
    -> play recording notice (English + Chinese)
    -> record the call
    -> /recording-complete webhook downloads the audio
    -> transcribe (ZERO_COST_MODE, the default: local faster-whisper if
       installed, otherwise mock — NO paid API call; paid mode uses
       OpenAI gpt-transcribe when ZERO_COST_MODE=0)
    -> extract ONLY booking fields (zero-cost: local Ollama if reachable,
       otherwise the rule-based extractor in this file — never invents;
       paid mode uses gpt-4o-mini)
    -> send a tidy summary to the owner's WhatsApp via Twilio WhatsApp
       (sandbox mode for testing; configurable to official)
    -> create a Google Calendar event (stub/disabled without credentials)
    -> append every booking to a local JSONL + CSV ledger (no database)

$0 test mode: ZERO_COST_MODE=1 (default). Twilio trial number
(75 free minutes, trial WhatsApp Sandbox, 100 free messages) + ngrok
free tier + local faster-whisper + local Ollama = $0 end-to-end.
See README.md "$0 test" section.

Secrets: environment variables ONLY. Never put a real key in this file,
in .env (git-ignored, not committed) or in the ledger. See .env.example.
"""

import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import PlainTextResponse

# ---------------------------------------------------------------- config ----
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LEDGER_DIR", BASE_DIR / "data"))
RECORDINGS_DIR = DATA_DIR / "recordings"
LEDGER_JSONL = DATA_DIR / "bookings.jsonl"
LEDGER_CSV = DATA_DIR / "bookings.csv"

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_NUMBER = os.environ.get("TWILIO_NUMBER", "")          # e.g. +61800000000
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-transcribe")
OPENAI_EXTRACT_MODEL = os.environ.get("OPENAI_EXTRACT_MODEL", "gpt-4o-mini")
OWNER_WHATSAPP_NUMBER = os.environ.get("OWNER_WHATSAPP_NUMBER", "")  # e.g. +61400000000
WHATSAPP_MODE = os.environ.get("WHATSAPP_MODE", "sandbox")  # sandbox | official
# Twilio WhatsApp sandbox sender is "whatsapp:+14155238886" by default.
TWILIO_WHATSAPP_FROM = os.environ.get(
    "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"
)
GOOGLE_CREDENTIALS_PATH = os.environ.get("GOOGLE_CREDENTIALS_PATH", "")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"
# $0 test mode — DEFAULT ON. No paid API is called while this is on:
# transcription = local faster-whisper (or mock, logged), extraction =
# local Ollama (or the rule-based extractor in this file, logged).
# Set ZERO_COST_MODE=0 to use the paid OpenAI path (needs OPENAI_API_KEY).
ZERO_COST_MODE = os.environ.get("ZERO_COST_MODE", "1") == "1"
LOCAL_WHISPER_MODEL = os.environ.get("LOCAL_WHISPER_MODEL", "tiny")  # tiny | base
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")  # or llama3.2:3b
OLLAMA_FALLBACK_MODEL = os.environ.get("OLLAMA_FALLBACK_MODEL", "llama3.2:3b")

# Last-used methods, reported by /health and written into the ledger.
LAST_TRANSCRIPTION_METHOD = "not run yet"
LAST_EXTRACTION_METHOD = "not run yet"

CSV_FIELDS = [
    "received_at_utc", "call_sid", "recording_sid", "date", "time",
    "tables", "adults", "children", "allergies", "name", "phone",
    "special_requests", "missing_fields", "transcript",
]

app = FastAPI(title="Booking Agent MVP")

# ------------------------------------------------------- extraction prompt --
BOOKING_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": ["string", "null"], "description": "Booking date, YYYY-MM-DD if known, else the caller's words"},
        "time": {"type": ["string", "null"], "description": "Booking time, 24h HH:MM if known"},
        "tables": {"type": ["integer", "null"]},
        "adults": {"type": ["integer", "null"]},
        "children": {"type": ["integer", "null"]},
        "allergies": {"type": ["string", "null"], "description": "Food allergies, or null if none stated"},
        "name": {"type": ["string", "null"]},
        "phone": {"type": ["string", "null"]},
        "special_requests": {"type": ["string", "null"]},
        "missing_fields": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["date", "time", "tables", "adults", "children",
                 "allergies", "name", "phone", "special_requests", "missing_fields"],
    "additionalProperties": False,
}

EXTRACT_SYSTEM_PROMPT = """You extract restaurant booking details from a phone-call transcript.
The transcript may be in English, Chinese, or a mix of both.

RULES — follow them exactly:
1. Extract ONLY the fields in the JSON schema. Ignore greetings, small talk,
   and anything unrelated to the booking.
2. NEVER invent a value. If a field was not stated, use null for it and list
   it in "missing_fields". Do not guess a date, time, party size or allergy.
3. "allergies": null if the caller did not mention allergies at all.
   If they said "no allergies", use "none stated".
4. Dates: convert to YYYY-MM-DD when the year/month/day are clear
   (assume the current/next occurrence in Perth, Australia, AWST).
   Times: convert to 24-hour HH:MM.
5. "tables": the number of tables requested, or null if only a headcount
   was given. Do not compute tables from headcount.
6. Reply with JSON ONLY, matching the schema. No extra text.
"""

EXTRACT_USER_PROMPT = "Transcript:\n{transcript}\n\nExtract the booking as JSON."


def extract_booking_llm(transcript: str) -> dict:
    """Production extraction via OpenAI chat completions (JSON mode)."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={
            "model": OPENAI_EXTRACT_MODEL,
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "messages": [
                {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": EXTRACT_USER_PROMPT.format(transcript=transcript)},
            ],
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = json.loads(resp.json()["choices"][0]["message"]["content"])
    return _normalise_booking(data)


def _normalise_booking(data: dict) -> dict:
    """Fill defaults so downstream code never sees a missing key."""
    out = {k: data.get(k) for k in BOOKING_JSON_SCHEMA["properties"]}
    out["missing_fields"] = data.get("missing_fields") or [
        k for k in ("date", "time", "tables", "adults", "children", "name", "phone")
        if out.get(k) in (None, "")
    ]
    return out


def extract_booking_mock(transcript: str) -> dict:
    """Deterministic test-only extractor for offline verification (test_pipeline.py).

    Regex-based, bilingual, deliberately conservative: anything it cannot
    parse is null + listed in missing_fields. NEVER used in production
    when an OpenAI key is present.

    Handles real Whisper output, not just digit-heavy mock text: English
    word numbers (two tables, eight adults), Chinese numerals incl.
    traditional 兩/點, "7 p.m.", and month names ("15th of November").
    Verified 2026-11-09 against real faster-whisper transcripts.
    """
    t = transcript
    # Normalise traditional -> simplified for the patterns below (Whisper
    # tiny often outputs traditional Chinese). Keep the original for display.
    _trad = str.maketrans({"兩": "两", "點": "点", "預": "预", "個": "个", "號": "号"})
    tn = t.translate(_trad)
    _en_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
               "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
               "eleven": 11, "twelve": 12, "a": 1, "an": 1}
    _zh_num = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
               "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}

    def _count(pat_en: str, pat_zh: str):
        # Collect every numbered mention of this unit and take the earliest
        # in the text (e.g. "4个小孩" beats the later "一个小孩" in the
        # allergy sentence). "a/an table" is NOT a number — tables fall
        # back to it only if no numbered tables phrase exists.
        cands = []
        for m in re.finditer(rf"(\d+|{'|'.join(k for k in _en_num if k not in ('a', 'an'))})\s*{pat_en}", t, re.I):
            v = m.group(1).lower()
            cands.append((m.start(), int(v) if v.isdigit() else _en_num.get(v)))
        for m in re.finditer(rf"(\d+)\s*个?\s*{pat_zh}", tn):
            cands.append((m.start(), int(m.group(1))))
        for m in re.finditer(rf"([一二两三四五六七八九十]+)\s*个?\s*{pat_zh}", tn):
            cands.append((m.start(), _zh_num.get(m.group(1))))
        if cands:
            return min(cands)[1]
        return None

    adults = _count(r"adults?", "大人")
    children = _count(r"(?:children|child|kids?)", "小孩|小朋友")
    tables = _count(r"tables?", "桌")
    if tables is None and (re.search(r"\b(a|an)\s+table\b", t, re.I) or "一桌" in tn):
        tables = 1
    # Times: 19:00 / 7pm / 7 p.m. / 晚上七点 — handle the common forms.
    time = None
    m = re.search(r"(\d{1,2}):(\d{2})", t)
    if m:
        time = f"{int(m.group(1)):02d}:{m.group(2)}"
    else:
        m = re.search(r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*(?:\.?\s*)?(p\.?m\.?|a\.?m\.?)\b", t, re.I)
        if m:
            raw = m.group(1).lower()
            h = int(raw) if raw.isdigit() else _en_num.get(raw, 0)
            if m.group(2).lower().startswith("p") and h != 12:
                h += 12
            time = f"{h:02d}:00"
        else:
            m = re.search(r"(晚上|下午|中午|早上|上午)?\s*([一二三四五六七八九十]+)点", tn)
            if m:
                h = _zh_num.get(m.group(2), 0)
                if m.group(1) in ("晚上", "下午") and h != 12:
                    h += 12
                time = f"{h:02d}:00"
    allergies = None
    if re.search(r"(peanut|花生|nut|坚果|gluten|麸质|seafood|海鲜|dairy|乳制|egg|鸡蛋)", t, re.I):
        m = re.search(
            r"((?:peanut|花生|nut|坚果|gluten|麸质|seafood|海鲜|dairy|乳制|egg|鸡蛋)[a-zA-Z\u4e00-\u9fff ]{0,12}?(?:allergy|过敏)?)",
            t, re.I)
        allergies = m.group(1).strip(" .，。") if m else None
    elif re.search(r"(no allerg|没有过敏|没有食物过敏)", t, re.I):
        allergies = "none stated"
    name = None
    m = re.search(r"(?:我叫|我是|my name is|this is)\s*([A-Za-z\u4e00-\u9fff]{2,20}(?:\s+[A-Za-z\u4e00-\u9fff]{2,20})?)", t, re.I)
    if m:
        name = m.group(1)
    phone = None
    m = re.search(r"(0\d[\d\s]{7,11})", t)
    if m:
        phone = re.sub(r"\s+", "", m.group(1))
    # Date: keep the caller's words — the mock does not resolve relative dates
    # (a bare weekday like "Friday" is not a firm date, so it stays missing).
    date = None
    m = re.search(r"(20\d{2}-\d{2}-\d{2}|\d{1,2}月\d{1,2}[日号])", tn)
    if m:
        date = m.group(1)
    else:
        months = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
                  "june": 6, "july": 7, "august": 8, "september": 9,
                  "october": 10, "november": 11, "december": 12}
        m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+of\s+(january|february|march|april|may|june|july|august|september|october|november|december)", t, re.I)
        if m:
            date = f"{months[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
        else:
            m = re.search(r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?", t, re.I)
            if m:
                date = f"{months[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    missing = [k for k, v in {
        "date": date, "time": time, "tables": tables,
        "adults": adults, "children": children, "name": name, "phone": phone,
    }.items() if v is None]
    return {
        "date": date, "time": time, "tables": tables, "adults": adults,
        "children": children, "allergies": allergies, "name": name,
        "phone": phone, "special_requests": None, "missing_fields": missing,
    }


# Rule-based extractor = the deterministic mock extractor above, renamed
# for its real role in $0 mode. Same code, same guarantees (missing = null,
# never invents); only the name changes so logs read honestly.
extract_booking_rule_based = extract_booking_mock


def _ollama_reachable() -> bool:
    """True if a local Ollama server answers — no paid call, localhost only."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def extract_booking_ollama(transcript: str, model: str | None = None) -> dict:
    """Extraction via a local Ollama model (OpenAI-compatible endpoint).

    Tries OLLAMA_MODEL, then OLLAMA_FALLBACK_MODEL. Raises on failure so
    the caller can fall back to the rule-based extractor.
    """
    models = [m for m in (model or OLLAMA_MODEL, OLLAMA_FALLBACK_MODEL) if m]
    last_error: Exception | None = None
    for m in models:
        try:
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/v1/chat/completions",
                json={
                    "model": m,
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
                        {"role": "user", "content": EXTRACT_USER_PROMPT.format(transcript=transcript)},
                    ],
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = json.loads(resp.json()["choices"][0]["message"]["content"])
            booking = _normalise_booking(data)
            booking["_extraction_method"] = f"ollama:{m}"
            return booking
        except Exception as exc:  # noqa: BLE001 — try the next model, then fall back
            last_error = exc
    raise RuntimeError(f"Ollama extraction failed for {models}: {last_error}")


def extract_booking_with_source(transcript: str) -> tuple[dict, str]:
    """Return (booking, method-log-string). Logs which extractor was used."""
    global LAST_EXTRACTION_METHOD
    if ZERO_COST_MODE:
        if _ollama_reachable():
            try:
                booking = extract_booking_ollama(transcript)
                method = booking.pop("_extraction_method", f"ollama:{OLLAMA_MODEL}")
                LAST_EXTRACTION_METHOD = method
                print(f"[zero-cost] extraction: {method}")
                return booking, method
            except Exception as exc:  # noqa: BLE001 — fall through to rule-based
                print(f"[zero-cost] extraction: Ollama failed ({exc}), falling back to rule-based")
        booking = extract_booking_rule_based(transcript)
        method = "rule-based (no Ollama reachable — install Ollama + pull a model for LLM extraction)"
        LAST_EXTRACTION_METHOD = method
        print(f"[zero-cost] extraction: {method}")
        return booking, method
    if MOCK_MODE or not OPENAI_API_KEY:
        booking = extract_booking_mock(transcript)
        LAST_EXTRACTION_METHOD = "rule-based (mock / no OpenAI key)"
        return booking, LAST_EXTRACTION_METHOD
    booking = extract_booking_llm(transcript)
    LAST_EXTRACTION_METHOD = f"openai:{OPENAI_EXTRACT_MODEL} (paid)"
    return booking, LAST_EXTRACTION_METHOD


def extract_booking(transcript: str) -> dict:
    booking, _method = extract_booking_with_source(transcript)
    return booking


# ------------------------------------------------------------- formatting ---
def _show(v):
    return str(v) if v not in (None, "") else "— not stated —"


def format_whatsapp(booking: dict) -> str:
    """The exact message the owner receives on WhatsApp."""
    lines = [
        "🍽️ New booking",
        f"Date: {_show(booking.get('date'))}",
        f"Time: {_show(booking.get('time'))}",
        f"Tables: {_show(booking.get('tables'))}",
        f"Adults: {_show(booking.get('adults'))}  |  Children: {_show(booking.get('children'))}",
        f"Allergies: {_show(booking.get('allergies'))}",
        f"Name: {_show(booking.get('name'))}",
        f"Phone: {_show(booking.get('phone'))}",
        f"Special requests: {_show(booking.get('special_requests'))}",
    ]
    if booking.get("missing_fields"):
        lines.append(f"⚠️ Missing: {', '.join(booking['missing_fields'])} — please confirm with the customer.")
    lines.append("— Booking Agent (recording)")
    return "\n".join(lines)


# ------------------------------------------------------------- downstream ---
def transcribe_audio_local(audio_path: Path) -> tuple[str, str]:
    """$0 transcription with local faster-whisper (CPU, tiny/base model).

    Returns (text, method). If faster-whisper is not installed, returns
    ("", "mock transcription — install faster-whisper for real audio")
    and logs that plainly — no paid API is ever called in this mode.
    The caller still logs the booking (all fields missing) so nothing
    is silently dropped; install faster-whisper to get real transcripts.
    """
    global LAST_TRANSCRIPTION_METHOD
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        method = "mock transcription — install faster-whisper for real audio (pip install faster-whisper)"
        LAST_TRANSCRIPTION_METHOD = method
        print(f"[zero-cost] transcription: {method}")
        return "", method
    model = WhisperModel(LOCAL_WHISPER_MODEL, device="cpu", compute_type="int8")
    # language=None = auto-detect per call (bilingual EN/ZH). Do NOT hardcode
    # "zh": that mis-transcribes English calls. Verified 2026-11-09 on this
    # VM: tiny + base both auto-detect en/zh at p>=0.98 on 15 s test audio.
    segments, _info = model.transcribe(str(audio_path), language=None)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    method = f"faster-whisper:{LOCAL_WHISPER_MODEL} (local, $0)"
    LAST_TRANSCRIPTION_METHOD = method
    print(f"[zero-cost] transcription: {method}")
    return text, method


def transcribe_audio_openai(audio_path: Path) -> tuple[str, str]:
    """Paid transcription with OpenAI gpt-transcribe (zh/en)."""
    global LAST_TRANSCRIPTION_METHOD
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    with open(audio_path, "rb") as f:
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"file": (audio_path.name, f, "audio/mpeg")},
            data={"model": OPENAI_TRANSCRIBE_MODEL, "language": "zh"},
            timeout=120,
        )
    resp.raise_for_status()
    method = f"openai:{OPENAI_TRANSCRIBE_MODEL} (paid)"
    LAST_TRANSCRIPTION_METHOD = method
    return resp.json()["text"], method


def transcribe_audio(audio_path: Path) -> str:
    """Dispatch: $0 local Whisper by default, OpenAI only when
    ZERO_COST_MODE=0. Kept for backwards compatibility — new code
    should use transcribe_audio_with_source()."""
    text, _method = transcribe_audio_with_source(audio_path)
    return text


def transcribe_audio_with_source(audio_path: Path) -> tuple[str, str]:
    if ZERO_COST_MODE:
        return transcribe_audio_local(audio_path)
    return transcribe_audio_openai(audio_path)


def send_whatsapp(message: str) -> dict:
    """Send via Twilio WhatsApp. Sandbox: TWILIO_WHATSAPP_FROM is the
    Twilio sandbox number (+14155238886) and the owner must first join it
    (see README). Official: set TWILIO_WHATSAPP_FROM to the approved
    WhatsApp Business sender, e.g. whatsapp:+61800000000."""
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN):
        return {"status": "skipped", "reason": "Twilio credentials not set"}
    if not OWNER_WHATSAPP_NUMBER:
        return {"status": "skipped", "reason": "OWNER_WHATSAPP_NUMBER not set"}
    url = (f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}"
           f"/Messages.json")
    resp = requests.post(
        url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        data={
            "From": TWILIO_WHATSAPP_FROM,
            "To": f"whatsapp:{OWNER_WHATSAPP_NUMBER}",
            "Body": message,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return {"status": "sent", "mode": WHATSAPP_MODE, "sid": resp.json().get("sid")}


def create_calendar_event(booking: dict) -> dict:
    """Google Calendar — STUB / configurable.

    Disabled unless GOOGLE_CREDENTIALS_PATH points at a valid OAuth
    credentials file AND google-api-python-client is installed.
    When disabled, the intended event is recorded in the ledger so no
    booking is silently lost. Full enablement steps are in README.md §5.
    """
    if not GOOGLE_CREDENTIALS_PATH or not Path(GOOGLE_CREDENTIALS_PATH).exists():
        return {"status": "disabled",
                "reason": "GOOGLE_CREDENTIALS_PATH not set or file not found"}
    try:
        from googleapiclient.discovery import build  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
    except ImportError:
        return {"status": "disabled",
                "reason": "google-api-python-client not installed (see requirements.txt)"}
    # Real implementation lives here once credentials exist; kept minimal
    # so the MVP runs without Google at all.
    creds = Credentials.from_authorized_user_file(GOOGLE_CREDENTIALS_PATH)
    service = build("calendar", "v3", credentials=creds)
    event = {
        "summary": f"Booking — {booking.get('name') or 'customer'} "
                   f"({booking.get('adults') or '?'} adults, "
                   f"{booking.get('children') or 0} children)",
        "description": format_whatsapp(booking),
        "start": {"dateTime": f"{booking.get('date')}T{booking.get('time')}:00+08:00",
                  "timeZone": "Australia/Perth"},
        "end": {"dateTime": f"{booking.get('date')}T{booking.get('time')}:00+08:00",
                "timeZone": "Australia/Perth"},
    }
    created = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
    return {"status": "created", "event_id": created.get("id")}


def append_ledger(booking: dict, call_sid: str, recording_sid: str, transcript: str,
                   transcription_method: str = "", extraction_method: str = "") -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "received_at_utc": datetime.now(timezone.utc).isoformat(),
        "call_sid": call_sid, "recording_sid": recording_sid,
        "date": booking.get("date"), "time": booking.get("time"),
        "tables": booking.get("tables"), "adults": booking.get("adults"),
        "children": booking.get("children"), "allergies": booking.get("allergies"),
        "name": booking.get("name"), "phone": booking.get("phone"),
        "special_requests": booking.get("special_requests"),
        "missing_fields": ",".join(booking.get("missing_fields") or []),
        "transcript": transcript,
        "transcription_method": transcription_method or LAST_TRANSCRIPTION_METHOD,
        "extraction_method": extraction_method or LAST_EXTRACTION_METHOD,
        "zero_cost_mode": ZERO_COST_MODE,
    }
    with open(LEDGER_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_header = not LEDGER_CSV.exists()
    with open(LEDGER_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            w.writeheader()
        # CSV keeps only the original booking columns; the extra
        # zero-cost method fields live in the JSONL row above.
        w.writerow({k: row[k] for k in CSV_FIELDS})


# ---------------------------------------------------------------- routes ----
@app.get("/health")
def health():
    return {
        "status": "ok",
        "mock_mode": MOCK_MODE,
        "zero_cost_mode": ZERO_COST_MODE,
        "transcription_method": LAST_TRANSCRIPTION_METHOD,
        "extraction_method": LAST_EXTRACTION_METHOD,
        "ollama_reachable": _ollama_reachable() if ZERO_COST_MODE else None,
        "twilio_configured": bool(TWILIO_ACCOUNT_SID and TWILIO_NUMBER),
        "openai_configured": bool(OPENAI_API_KEY),
        "whatsapp_mode": WHATSAPP_MODE,
        "calendar": "enabled" if GOOGLE_CREDENTIALS_PATH else "disabled (stub)",
    }


@app.post("/voice", response_class=PlainTextResponse)
def voice():
    """TwiML: recording notice (EN + ZH), then record the call.

    Set this URL as the Twilio number's Voice webhook (POST).
    """
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say language="en-AU">Hello, this call will be recorded to take your booking. Please speak after the tone.</Say>
  <Say language="zh-CN">您好，这通电话将会被录音，用于记录您的预订信息。请在提示音后开始说话。</Say>
  <Record maxLength="300" playBeep="true"
          recordingStatusCallback="/recording-complete"
          recordingStatusCallbackMethod="POST" />
  <Say language="en-AU">Thank you. Your booking details have been recorded and we will confirm shortly.</Say>
</Response>"""
    return twiml


def _process_recording(recording_url: str, recording_sid: str, call_sid: str):
    """Background job: download -> transcribe -> extract -> WhatsApp -> calendar -> ledger."""
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = RECORDINGS_DIR / f"{recording_sid}.mp3"
    # Twilio recording URL needs .mp3 suffix and Basic Auth.
    resp = requests.get(recording_url + ".mp3",
                        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=60)
    resp.raise_for_status()
    audio_path.write_bytes(resp.content)
    transcript, transcription_method = transcribe_audio_with_source(audio_path)
    if ZERO_COST_MODE and not transcript:
        # faster-whisper not installed: log plainly, do not invent a transcript.
        print("[zero-cost] transcription: no transcript produced (mock) — "
              "booking will be logged with all fields missing; "
              "install faster-whisper for real audio.")
    booking, extraction_method = extract_booking_with_source(transcript)
    message = format_whatsapp(booking)
    wa = send_whatsapp(message)
    cal = create_calendar_event(booking)
    append_ledger(booking, call_sid, recording_sid, transcript,
                  transcription_method=transcription_method,
                  extraction_method=extraction_method)
    return {"transcript": transcript, "booking": booking,
            "transcription_method": transcription_method,
            "extraction_method": extraction_method,
            "whatsapp": wa, "calendar": cal}


@app.post("/recording-complete")
async def recording_complete(request: Request, background_tasks: BackgroundTasks):
    """Twilio recordingStatusCallback. Returns 200 immediately; work runs in background."""
    form = await request.form()
    recording_url = str(form.get("RecordingUrl", ""))
    recording_sid = str(form.get("RecordingSid", ""))
    call_sid = str(form.get("CallSid", ""))
    if not recording_url:
        return {"status": "ignored", "reason": "no RecordingUrl"}
    background_tasks.add_task(_process_recording, recording_url, recording_sid, call_sid)
    return {"status": "accepted", "recording_sid": recording_sid}


@app.post("/test-extract")
def test_extract(transcript: str = Form(...)):
    """Manual test helper: POST a transcript, get the extracted booking + WhatsApp text.
    In $0 mode uses Ollama if reachable, otherwise the rule-based extractor.
    No phone call needed, no paid API in $0 mode."""
    booking, extraction_method = extract_booking_with_source(transcript)
    return {"booking": booking, "whatsapp": format_whatsapp(booking),
            "extraction_method": extraction_method, "zero_cost_mode": ZERO_COST_MODE}
