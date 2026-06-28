"""One-shot reset: clear Google Sheet data rows (keep header) and wipe seen_listings.db."""
import os
import sqlite3
import sys
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv

load_dotenv()

CREDS = os.environ["GOOGLE_CREDENTIALS_PATH"]
SHEET = os.environ["GOOGLE_SHEET_NAME"]
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "seen_listings.db")

# ── 1. Wipe SQLite ────────────────────────────────────────────────────────────
conn = sqlite3.connect(DB_PATH)
before = conn.execute("SELECT COUNT(*) FROM seen_listings").fetchone()[0]
conn.execute("DELETE FROM seen_listings")
conn.commit()
after = conn.execute("SELECT COUNT(*) FROM seen_listings").fetchone()[0]
conn.close()
print(f"DB: deleted {before} records, {after} remaining")

# ── 2. Clear Google Sheet data rows ──────────────────────────────────────────
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
creds = Credentials.from_service_account_file(CREDS, scopes=SCOPES)
client = gspread.authorize(creds)
ws = client.open(SHEET).sheet1

all_values = ws.get_all_values()
data_rows = len(all_values) - 1  # exclude header row
if data_rows > 0:
    # Clear content from row 2 downwards without deleting rows
    # Use a large range to cover all possible data
    last_row = len(all_values)
    ws.batch_clear([f"A2:Z{last_row}"])
    print(f"Sheet: cleared {data_rows} data rows (header preserved)")
else:
    print("Sheet: no data rows to clear")

print("Reset complete.")
