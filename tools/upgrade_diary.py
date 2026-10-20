"""Verify the maintained diary entry without overwriting the current flow."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
text = (root / "frontend/source/睡眠日誌表單.html").read_text(encoding="utf-8")
required = ["home-page", "member-page", "history-page", "review-area", "f-lights-out", "f-wore-watch", "f-sleep-medication", "f-drank-alcohol"]
missing = [field for field in required if f'id="{field}"' not in text]
if missing:
    raise SystemExit("Missing form fields: " + ", ".join(missing))
if 'type="time"' in text or 'id="f-sleep-time-ampm"' in text:
    raise SystemExit("Ambiguous clock input found")
print("Diary flow and 24-hour fields verified; maintained HTML left unchanged.")
