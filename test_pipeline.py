"""Offline pipeline test — NO Twilio / OpenAI calls.

Runs transcription (mock: the sample transcripts ARE the transcription)
-> extraction (mock extractor in app.py) -> WhatsApp formatting -> ledger
write (to a temp dir), and asserts the expected fields.

Usage:
    MOCK_MODE=1 python3 test_pipeline.py
    # or: ZERO_COST_MODE=1 python3 test_pipeline.py  (the $0 default)
    # or simply: python3 test_pipeline.py   (mock is forced on here)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["MOCK_MODE"] = "1"
os.environ["ZERO_COST_MODE"] = "1"
# Prove the $0 path needs no paid key: strip any OpenAI key from the env.
os.environ.pop("OPENAI_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import extract_booking, format_whatsapp, append_ledger  # noqa: E402
import app as app_module  # noqa: E402

SAMPLES = json.loads(
    (Path(__file__).resolve().parent / "samples" / "transcripts.json").read_text(encoding="utf-8")
)["samples"]


def check(sample: dict) -> list[str]:
    failures = []
    booking, method = app_module.extract_booking_with_source(sample["transcript"])
    # $0 mode must never claim a paid extractor when no key / no Ollama is present.
    if "openai" in method:
        failures.append(f"zero-cost test used a paid extractor: {method}")
    print(f"  extraction method: {method}")
    expected = sample.get("expected", {})
    for key, want in expected.items():
        if key == "missing_fields_must_include":
            continue
        got = booking.get(key)
        # Mock keeps Chinese dates in the caller's words; accept substring match.
        if isinstance(want, str) and isinstance(got, str):
            ok = want in got or got in want
        else:
            ok = got == want
        if not ok:
            failures.append(f"{key}: expected {want!r}, got {got!r}")
    for field in expected.get("missing_fields_must_include", []):
        if field not in (booking.get("missing_fields") or []):
            failures.append(f"missing_fields should include {field!r}, got {booking.get('missing_fields')}")
    # WhatsApp text must contain the key facts and never invent a phone number.
    wa = format_whatsapp(booking)
    if expected.get("phone") and expected["phone"] not in wa:
        failures.append("WhatsApp text is missing the caller's phone number")
    if not expected.get("phone") and "04" in wa.split("Phone:")[1].split("\n")[0]:
        failures.append("WhatsApp text invented a phone number")
    return failures


def main() -> int:
    # Ledger writes go to a temp dir so the test never touches real data.
    tmp = Path(tempfile.mkdtemp(prefix="booking-mvp-test-"))
    app_module.DATA_DIR = tmp
    app_module.LEDGER_JSONL = tmp / "bookings.jsonl"
    app_module.LEDGER_CSV = tmp / "bookings.csv"

    total_failures = 0
    for sample in SAMPLES:
        booking = extract_booking(sample["transcript"])
        wa = format_whatsapp(booking)
        append_ledger(booking, call_sid="TEST", recording_sid=f"TEST-{sample['id']}",
                      transcript=sample["transcript"])
        failures = check(sample)
        status = "PASS" if not failures else "FAIL"
        total_failures += len(failures)
        print(f"\n=== {sample['id']} [{status}] ===")
        print(f"Booking: {json.dumps(booking, ensure_ascii=False)}")
        print("--- WhatsApp message ---")
        print(wa)
        for f in failures:
            print(f"  ✗ {f}")

    print(f"\nLedger written to: {tmp / 'bookings.jsonl'} and {tmp / 'bookings.csv'}")
    print(f"Samples: {len(SAMPLES)}, failures: {total_failures}")
    print(f"ZERO_COST_MODE={os.environ.get('ZERO_COST_MODE')}, OPENAI_API_KEY set: {bool(os.environ.get('OPENAI_API_KEY'))}")
    if total_failures:
        print("RESULT: FAIL — see failures above")
        return 1
    print("RESULT: PASS — $0 pipeline (rule-based extract -> WhatsApp format -> ledger) works offline, no paid API")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
