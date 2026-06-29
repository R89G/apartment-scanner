import asyncio
import logging
import os
import random
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import aiohttp
import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from playwright.async_api import async_playwright

from scrapers.yad2 import TEL_AVIV_BOXES, YAD2_MAP_URL

try:
    from playwright_stealth import Stealth as _StealthCls
    _stealth = _StealthCls()
    HAS_STEALTH = True
except ImportError:
    _stealth = None
    HAS_STEALTH = False

BASE_DIR = Path(__file__).parent
LOG_PATH = BASE_DIR / "logs" / "checker.log"

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

INACTIVE_PATTERNS = [
    "חיפשנו בכל מקום",
    "אין לנו עמוד כזה",
    "מודעה לא פעילה",
    "עמוד לא נמצא",
    "המודעה הוסרה",
    "המודעה לא קיימת",
    "המודעה לא נמצאה",
    "הדף לא נמצא",
    "page not found",
    "listing not found",
    "listing removed",
]

_MOBILE_UAS = [
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]


def _yad2_api_headers() -> dict:
    return {
        "User-Agent": random.choice(_MOBILE_UAS),
        "Referer": "https://www.yad2.co.il/realestate/rent",
        "Origin": "https://www.yad2.co.il",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }


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


def _subdivide_boxes(boxes: list) -> list:
    result = []
    for lat_min, lon_min, lat_max, lon_max in boxes:
        lat_mid = (lat_min + lat_max) / 2
        lon_mid = (lon_min + lon_max) / 2
        result.extend([
            (lat_min, lon_min, lat_mid, lon_mid),
            (lat_min, lon_mid, lat_mid, lon_max),
            (lat_mid, lon_min, lat_max, lon_mid),
            (lat_mid, lon_mid, lat_max, lon_max),
        ])
    return result


async def _fetch_yad2_active_tokens() -> set[str]:
    """
    Fetch all currently active Yad2 tokens from the map API (16 bBoxes).
    Returns an empty set if the map API is blocked by PerimeterX this run.
    When the map API works, a token absent from the results is no longer
    being shown to renters (expired or removed from search).
    """
    boxes = _subdivide_boxes(TEL_AVIV_BOXES)
    active_tokens: set[str] = set()
    map_api_worked = False

    async with aiohttp.ClientSession(headers=_yad2_api_headers()) as session:
        for lat_min, lon_min, lat_max, lon_max in boxes:
            bbox = f"{lat_min},{lon_min},{lat_max},{lon_max}"
            params = {"city": "5000", "area": "1", "region": "3",
                      "property": "1", "bBox": bbox, "zoom": "14"}
            try:
                async with session.get(
                    YAD2_MAP_URL, params=params,
                    timeout=aiohttp.ClientTimeout(total=20), allow_redirects=False,
                ) as resp:
                    if resp.status in (301, 302, 303, 307, 308):
                        logger.warning("Map API redirected (PerimeterX?) for bBox %s — skipping", bbox)
                        continue
                    if resp.status != 200:
                        logger.warning("Map API HTTP %d for bBox %s — skipping", resp.status, bbox)
                        continue
                    data = await resp.json(content_type=None)
                    markers: list = []
                    if isinstance(data, dict):
                        inner = data.get("data") or {}
                        markers = inner.get("markers", []) if isinstance(inner, dict) else []
                    elif isinstance(data, list):
                        markers = data
                    count_before = len(active_tokens)
                    for m in markers:
                        token = str(m.get("token") or m.get("id") or "")
                        if token:
                            active_tokens.add(token)
                    logger.info("Map API bBox %s: %d markers, %d new tokens",
                                bbox, len(markers), len(active_tokens) - count_before)
                    if markers:
                        map_api_worked = True
            except Exception as exc:
                logger.warning("Map API error for bBox %s: %s", bbox, exc)
            await asyncio.sleep(random.uniform(2, 3))

    if map_api_worked:
        logger.info("Yad2 map inventory: %d unique active tokens", len(active_tokens))
    else:
        logger.warning("Map API returned no data — Yad2 rows will be kept as-is this run")
    return active_tokens if map_api_worked else set()


async def _check_yad2_playwright(page, url: str) -> bool:
    """
    Open the Yad2 item page in Playwright and intercept GW API responses.
    Only used as a last resort when the map API is unavailable.
    """
    gw_404 = False

    async def _on_response(response):
        nonlocal gw_404
        try:
            if "gw.yad2.co.il" in response.url and response.status == 404:
                gw_404 = True
        except Exception:
            pass

    page.on("response", _on_response)
    try:
        nav_resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if nav_resp and nav_resp.status in (404, 410):
            return True
        await page.wait_for_timeout(6000)
        if gw_404:
            logger.info("Yad2 Playwright GW 404 intercept → inactive: %s", url)
            return True
        try:
            text = (await page.inner_text("body")).lower()
            for pattern in INACTIVE_PATTERNS:
                if pattern.lower() in text:
                    logger.info("Yad2 Playwright text '%s' → inactive: %s", pattern, url)
                    return True
        except Exception:
            pass
    except Exception as exc:
        logger.warning("Yad2 Playwright check failed for %s: %s — keeping row", url, exc)
    finally:
        page.remove_listener("response", _on_response)
    return False


async def _check_browser(page, url: str) -> bool:
    """Check a non-Yad2 listing using Playwright."""
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        if resp and resp.status in (404, 410):
            return True
        await page.wait_for_timeout(2500)
        text = (await page.inner_text("body")).lower()
        for pattern in INACTIVE_PATTERNS:
            if pattern.lower() in text:
                return True
        return False
    except Exception as exc:
        logger.warning("Browser check failed for %s: %s — keeping row", url, exc)
        return False


def delete_rows_batch(ws: gspread.Worksheet, row_numbers: list[int]) -> None:
    requests_list = []
    for row_num in sorted(row_numbers, reverse=True):
        requests_list.append({
            "deleteDimension": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "ROWS",
                    "startIndex": row_num - 1,
                    "endIndex": row_num,
                }
            }
        })
    ws.spreadsheet.batch_update({"requests": requests_list})


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

    # Try to build Yad2 map inventory.
    # When available this is the only signal used for Yad2 rows.
    # When blocked by PerimeterX all Yad2 rows are kept (safe default).
    yad2_active_tokens = await _fetch_yad2_active_tokens()

    rows_to_delete: list[int] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="he-IL",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        if HAS_STEALTH:
            await _stealth.apply_stealth_async(page)

        for i, row in enumerate(data_rows):
            sheet_row_num = i + 2
            url = row[url_col_idx] if url_col_idx < len(row) else ""
            if not url or not url.startswith("http"):
                continue

            if "yad2.co.il" in url:
                token = url.rstrip("/").rsplit("/", 1)[-1]

                if yad2_active_tokens:
                    # Map inventory available: token absent = no longer in search results
                    if token in yad2_active_tokens:
                        logger.info("Yad2 map: token found → active: %s", url)
                        inactive = False
                    else:
                        logger.info("Yad2 map: token absent from search results → inactive: %s", url)
                        inactive = True
                else:
                    # Map blocked this run — use Playwright as last resort, otherwise keep
                    inactive = await _check_yad2_playwright(page, url)
                    if not inactive:
                        logger.info("Yad2 map unavailable, Playwright inconclusive — keeping: %s", url)
            else:
                inactive = await _check_browser(page, url)

            if inactive:
                logger.info("INACTIVE (will delete): row %d — %s", sheet_row_num, url)
                rows_to_delete.append(sheet_row_num)
            else:
                logger.info("active: row %d — %s", sheet_row_num, url)

            await asyncio.sleep(random.uniform(1.5, 3.0))

        await context.close()
        await browser.close()

    if rows_to_delete:
        logger.info("Deleting %d inactive rows from sheet...", len(rows_to_delete))
        delete_rows_batch(ws, rows_to_delete)
        logger.info("Done. Deleted rows: %s", rows_to_delete)
    else:
        logger.info("No inactive listings found. Nothing deleted.")

    logger.info("=== Checker complete ===")


if __name__ == "__main__":
    asyncio.run(main())
