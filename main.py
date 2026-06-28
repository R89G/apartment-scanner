import argparse
import asyncio
import ctypes
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

def _prevent_sleep() -> None:
    if sys.platform != "win32":
        return
    try:
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    except Exception:
        pass


def _allow_sleep() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
    except Exception:
        pass

from dotenv import load_dotenv

from models.listing import Listing
from scrapers.ashtrom import AshtromScraper
from scrapers.azrieli_town import AzrieliTownScraper
from scrapers.homeless import HomelessScraper
from scrapers.homeland import HomelandScraper
from scrapers.komo import KomoScraper
from scrapers.madlan import MadlanScraper
from scrapers.melisron import MelisronScraper
from scrapers.nester import NesterScraper
from scrapers.onmap import OnMapScraper
from scrapers.renten import RentenScraper
from scrapers.site_discovery import discover_new_sites
from scrapers.yad2 import Yad2Scraper
from services import dedup, email_notifier
from services.sheets import (
    append_listings_batch,
    ensure_header,
    get_or_create_sheet,
    get_sheet_url,
    resize_columns,
)

BASE_DIR = Path(__file__).parent
LAST_RUN_FILE = BASE_DIR / "last_run.json"
DB_PATH = str(BASE_DIR / "data" / "seen_listings.db")
LOG_PATH = BASE_DIR / "logs" / "scanner.log"

# Old North neighborhoods (soft preference)
OLD_NORTH_KEYWORDS = [
    "כיכר רבין", "לונדון מיניסטור", "דיזנגוף", "הבימה", "נורדאו", "בן גוריון",
    "פרישמן", "גורדון", "כיכר בזל", "בזל", "nordau", "dizengoff", "gordon",
    "frishman", "rabin square", "habima",
]

ROOMMATE_KEYWORDS = ["שותף", "שותפים", "שותפות", "room", "חדר בשיתוף"]

VALID_CITIES_LOWER = {
    "תל אביב",
    "תל אביב יפו",
    "tel aviv",
    "tel-aviv",
    "tel aviv-yafo",
    "tel-aviv-yafo",
    "telaviv",
}


def setup_logging(debug: bool) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if debug else logging.INFO
    handler = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logging.basicConfig(level=level, handlers=[handler, console])


def load_last_run() -> datetime | None:
    if LAST_RUN_FILE.exists():
        data = json.loads(LAST_RUN_FILE.read_text(encoding="utf-8"))
        ts = data.get("last_run")
        return datetime.fromisoformat(ts) if ts else None
    return None


def save_last_run() -> None:
    LAST_RUN_FILE.write_text(
        json.dumps({"last_run": datetime.utcnow().isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )


def should_run_catchup(last_run: datetime | None) -> bool:
    if last_run is None:
        return True
    return (datetime.utcnow() - last_run) > timedelta(days=6)


def filter_listing(listing: Listing) -> tuple[bool, list[str]]:
    notes: list[str] = []
    text_blob = " ".join(filter(None, [
        listing.neighborhood or "",
        listing.street or "",
    ])).lower()

    # Hard: roommate keywords
    if any(kw in text_blob for kw in ROOMMATE_KEYWORDS):
        return False, []

    # Hard: city — if explicitly set, must be a Tel Aviv variant
    if listing.city and listing.city.lower().strip() not in VALID_CITIES_LOWER:
        return False, []

    # Hard: non-TA names appearing in neighborhood field (fallback for scrapers without city)
    if listing.neighborhood:
        nbhd_lower = listing.neighborhood.lower().strip()
        non_ta_cities = [
            "רמת גן", "גבעתיים", "בני ברק", "הולון", "חולון", "פתח תקווה", "בת ים",
            "ramat gan", "givatayim", "bnei brak", "holon", "petah tikva", "bat yam",
        ]
        if any(city in nbhd_lower for city in non_ta_cities):
            return False, []

    # Hard: rooms
    if listing.rooms is not None and listing.rooms < 2:
        return False, []

    # Hard: size
    if listing.size_sqm is not None and listing.size_sqm < 40:
        return False, []

    # Hard: floor (0 = ground floor, excluded; negative = basement, excluded)
    if listing.floor is not None and listing.floor < 2:
        return False, []

    # Hard: price
    if listing.price_nis is not None and listing.price_nis > 8000:
        return False, []

    # Soft: missing info notes
    if listing.floor is None:
        notes.append("Floor unknown")
    if listing.size_sqm is None:
        notes.append("Size unknown")
    if listing.price_nis is None:
        notes.append("Price unknown")

    # Soft: Old North
    combined = " ".join(filter(None, [listing.neighborhood, listing.street])).lower()
    if any(kw.lower() in combined for kw in OLD_NORTH_KEYWORDS):
        listing.is_old_north = True
        notes.append("✓ Old North")
    else:
        listing.is_old_north = False

    return True, notes


async def main() -> None:
    parser = argparse.ArgumentParser(description="Apartment scanner")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(args.debug)
    logger = logging.getLogger("main")

    load_dotenv()

    _prevent_sleep()

    start_time = datetime.now()
    logger.info("=== Apartment Scanner started at %s ===", start_time.isoformat())

    # Catch-up check
    last_run = load_last_run()
    if last_run and not should_run_catchup(last_run):
        logger.info("Last run was %s — no catch-up needed today", last_run.isoformat())
        # Still run, Task Scheduler called us deliberately

    # Init SQLite
    try:
        dedup.init_db(DB_PATH)
    except Exception as exc:
        logger.error("SQLite init failed: %s", exc)

    # Connect to Google Sheet
    creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "./google_credentials.json")
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "Apartment Listings")
    worksheet = None
    sheet_url = "N/A"
    try:
        worksheet = get_or_create_sheet(creds_path, sheet_name)
        ensure_header(worksheet)
        sheet_url = get_sheet_url(worksheet)
        logger.info("Connected to Google Sheet: %s", sheet_url)
    except Exception as exc:
        logger.error("Google Sheets connection failed: %s\n%s", exc, traceback.format_exc())
        logger.error("Will continue run but sheet writing will be skipped")

    # Run all scrapers
    scrapers = [
        Yad2Scraper(),
        OnMapScraper(),
        MadlanScraper(),
        HomelessScraper(),
        NesterScraper(),
        MelisronScraper(),
        KomoScraper(),
        AshtromScraper(),
        HomelandScraper(),
        RentenScraper(),
        AzrieliTownScraper(),
    ]

    all_raw: list[Listing] = []
    sites_scanned: list[str] = []

    for scraper in scrapers:
        logger.info("Scraping: %s", scraper.site_name)
        try:
            results = await scraper.run()
            logger.info("%s: %d raw listings returned", scraper.site_name, len(results))
            all_raw.extend(results)
            sites_scanned.append(scraper.site_name)
        except Exception as exc:
            logger.error("%s: unexpected error: %s\n%s", scraper.site_name, exc, traceback.format_exc())

    # Site discovery (weekly bonus)
    try:
        new_domains = await discover_new_sites()
        if new_domains:
            logger.info("Site discovery found %d new domains: %s", len(new_domains), new_domains)
    except Exception as exc:
        logger.warning("Site discovery failed: %s", exc)

    # Filter + dedup
    new_listings: list[Listing] = []
    skipped_filter = 0
    skipped_dedup = 0

    for listing in all_raw:
        if not listing.url:
            logger.warning("Listing missing URL — skipped (source: %s)", listing.source_site)
            continue

        passes, notes = filter_listing(listing)
        if not passes:
            skipped_filter += 1
            continue

        listing.notes = notes

        try:
            if dedup.is_seen(listing):
                skipped_dedup += 1
                continue
        except Exception as exc:
            logger.error("Dedup check failed for %s: %s — writing to sheet anyway", listing.url, exc)

        try:
            dedup.mark_seen(listing)
        except Exception as exc:
            logger.error("Dedup mark_seen failed for %s: %s", listing.url, exc)

        new_listings.append(listing)

    # Batch-write all new listings to the sheet (10 rows per request, 2s gap)
    if worksheet is not None and new_listings:
        try:
            append_listings_batch(worksheet, new_listings)
        except Exception as exc:
            logger.error("Sheet batch write failed: %s\n%s", exc, traceback.format_exc())

    # Auto-resize columns
    if worksheet is not None and new_listings:
        try:
            resize_columns(worksheet)
        except Exception as exc:
            logger.warning("Column resize failed: %s", exc)

    # Email notification
    run_stats = {
        "sites_scanned": sites_scanned,
        "sheet_url": sheet_url,
    }
    email_sent = False
    try:
        email_sent = email_notifier.send_notification(new_listings, run_stats)
    except Exception as exc:
        logger.error("Email notification failed: %s", exc)

    # Save last run timestamp
    save_last_run()

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logger.info("=== Run complete ===")
    logger.info("Sites attempted: %d", len(scrapers))
    logger.info("Raw listings found: %d", len(all_raw))
    logger.info("Filtered out: %d", skipped_filter)
    logger.info("Duplicates skipped: %d", skipped_dedup)
    logger.info("New listings added: %d", len(new_listings))
    logger.info("Email sent: %s", email_sent)
    logger.info("Duration: %.1fs", duration)
    _allow_sleep()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        logging.getLogger("main").critical("Unhandled exception: %s\n%s", exc, traceback.format_exc())
        sys.exit(1)
