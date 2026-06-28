"""Mini test: run each scraper, cap at 3 listings per site, print extracted fields."""
import asyncio
import logging
import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s]: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
for lib in ("aiohttp", "urllib3", "asyncio", "playwright", "urllib3.connectionpool",
            "google", "gspread"):
    logging.getLogger(lib).setLevel(logging.WARNING)
# Enable DEBUG for scrapers so we see extracted values
logging.getLogger("scrapers").setLevel(logging.DEBUG)

from playwright.async_api import async_playwright
from scrapers.yad2 import Yad2Scraper
from scrapers.onmap import OnMapScraper
from scrapers.homeless import HomelessScraper
from scrapers.komo import KomoScraper

FIELDS = ["source_site", "neighborhood", "street", "floor", "floors_in_building",
          "rooms", "size_sqm", "price_nis", "property_status",
          "has_elevator", "has_parking", "date_published", "url"]

def fmt(v):
    if v is None: return "None"
    if isinstance(v, bool): return "YES" if v else "NO"
    return str(v)

def print_listings(listings, cap=3):
    shown = listings[:cap]
    print(f"  Total: {len(listings)}, showing {len(shown)}")
    for l in shown:
        print(f"  ---")
        for f in FIELDS:
            print(f"    {f:22s}: {fmt(getattr(l, f, None))}")
    print()


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="he-IL",
            viewport={"width": 1280, "height": 800},
        )

        # ── Yad2 (API, no browser needed) ─────────────────────────────────────
        print("=== Yad2 (scrape only, no detail enrichment) ===")
        yad2 = Yad2Scraper()
        yad2.max_detail_pages = 0  # skip detail pages
        yad2_listings = await yad2.scrape(None)
        print_listings(yad2_listings)

        # ── OnMap (API, no browser needed) ─────────────────────────────────────
        print("=== OnMap (scrape + 3 detail API calls) ===")
        onmap = OnMapScraper()
        # Run full run() but it caps itself; we'll just check first 3 raw listings too
        onmap_raw = await onmap.scrape(None)
        print_listings(onmap_raw)

        # ── Homeless (browser) ─────────────────────────────────────────────────
        print("=== Homeless (search page only — detail pages CF-blocked) ===")
        page = await ctx.new_page()
        homeless = HomelessScraper()
        # Patch to skip detail enrichment entirely for this test
        from scrapers.homeless import _parse_row
        from scrapers.utils import quick_passes
        from scrapers.homeless import HOMELESS_URL
        await page.goto(HOMELESS_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        rows = await page.query_selector_all('tr[type="ad"]')
        h_listings = []
        for row in rows[:10]:
            try:
                l = await _parse_row(row)
                if l:
                    h_listings.append(l)
            except:
                pass
        await page.close()
        print_listings(h_listings)

        await ctx.close()
        await browser.close()

    print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
