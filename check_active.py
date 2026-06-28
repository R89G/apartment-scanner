import asyncio
import logging
import os
import random
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).parent
LOG_PATH = BASE_DIR / "logs" / "checker.log"

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Hebrew/English text patterns that mean the listing is gone
INACTIVE_PATTERNS = [
    "חיפשנו בכל מקום",      # Yad2
    "אין לנו עמוד כזה",      # Yad2
    "מודעה לא פעילה",        # OnMap
    "עמוד לא נמצא",          # Komo
    "המודעה הוסרה",
    "המודעה לא קיימת",
    "המודעה לא נמצאה",
    "הדף לא נמצא",
    "page not found",
    "listing not found",
    "listing removed",
]

logger = logging.getLogger("checker")


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, console])


async def is_inactive(page, url: str) -> bool:
    """Visit a listing URL and return True if the listing is no longer active."""
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=25000)

        # Hard 404/410 = definitely gone
        if resp and resp.status in (404, 410):
            return True

        # Wait for JS to render (needed for OnMap overlay etc.)
        await page.wait_for_timeout(2500)

        text = (await page.inner_text("body")).lower()
        for pattern in INACTIVE_PATTERNS:
            if pattern.lower() in text:
                return True

        return False
    except Exception as exc:
        # On timeout/network error: keep the row (safe default)
        logger.warning("Could not check %s: %s — keeping row", url, exc)
        return False


def delete_rows_batch(ws: gspread.Worksheet, row_numbers: list[int]) -> None:
    """Delete multiple rows in one Sheets API call (sorted highest first to avoid index shift)."""
    requests = []
    for row_num in sorted(row_numbers, reverse=True):
        requests.append({
            "deleteDimension": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "ROWS",
                    "startIndex": row_num - 1,  # 0-based, inclusive
                    "endIndex": row_num,         # 0-based, exclusive
                }
            }
        })
    ws.spreadsheet.batch_update({"requests": requests})


async def main() -> None:
    setup_logging()
    load_dotenv()

    logger.info("=== Active listing checker started ===")

    creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "./google_credentials.json")
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "Apartment Listings")

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    ws = client.open(sheet_name).sheet1

    all_values = ws.get_all_values()
    if len(all_values) <= 1:
        logger.info("Sheet has no listings to check.")
        return

    header = all_values[0]
    try:
        url_col_idx = header.index("URL")
    except ValueError:
        logger.error("Could not find 'URL' column in sheet header.")
        return

    data_rows = all_values[1:]
    logger.info("Checking %d listings...", len(data_rows))

    rows_to_delete: list[int] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="he-IL",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        for i, row in enumerate(data_rows):
            sheet_row_num = i + 2  # 1-based + skip header row
            url = row[url_col_idx] if url_col_idx < len(row) else ""
            if not url or not url.startswith("http"):
                continue

            inactive = await is_inactive(page, url)
            if inactive:
                logger.info("INACTIVE (will delete): row %d — %s", sheet_row_num, url)
                rows_to_delete.append(sheet_row_num)
            else:
                logger.info("active: row %d — %s", sheet_row_num, url)

            await asyncio.sleep(random.uniform(2.0, 3.5))

        await context.close()
        await browser.close()

    if not rows_to_delete:
        logger.info("All %d listings are still active. Nothing deleted.", len(data_rows))
    else:
        logger.info("Deleting %d inactive rows from sheet...", len(rows_to_delete))
        delete_rows_batch(ws, rows_to_delete)
        logger.info("Done. Deleted rows: %s", rows_to_delete)

    logger.info("=== Checker complete ===")


if __name__ == "__main__":
    asyncio.run(main())
