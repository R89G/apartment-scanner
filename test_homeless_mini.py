"""Run just the Homeless scraper on 5 detail pages and print what was extracted."""
import asyncio
import logging
import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from dotenv import load_dotenv
load_dotenv()

# Force DEBUG so we see the extracted logs
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s [%(name)s]: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Silence noisy libs
for lib in ("aiohttp", "urllib3", "asyncio", "playwright"):
    logging.getLogger(lib).setLevel(logging.WARNING)

from playwright.async_api import async_playwright
from scrapers.homeless import HomelessScraper, HOMELESS_URL, _HOMELESS_DETAIL_JS, _apply_homeless_fields
from scrapers.utils import detail_page_blocked, quick_passes

FIELDS = ["price_nis", "floor", "floors_in_building", "size_sqm",
          "property_status", "has_elevator", "has_parking"]


async def main():
    scraper = HomelessScraper()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="he-IL",
            viewport={"width": 1280, "height": 800},
        )
        page = await ctx.new_page()

        # Collect listings from search page
        await page.goto(HOMELESS_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        from scrapers.homeless import _parse_row
        rows = await page.query_selector_all('tr[type="ad"]')
        print(f"\nSearch page: {len(rows)} rows found\n")

        listings = []
        for row in rows:
            try:
                listing = await _parse_row(row)
                if listing:
                    listings.append(listing)
            except Exception as e:
                pass

        candidates = [l for l in listings if quick_passes(l)]
        print(f"Total listings: {len(listings)}, candidates for detail: {len(candidates)}\n")

        # Enrich first 5 candidates with full logging
        to_test = candidates[:5]
        for i, listing in enumerate(to_test):
            detail = await ctx.new_page()
            try:
                print(f"--- Detail {i+1}/5: {listing.url} ---")
                await detail.goto(listing.url, wait_until="domcontentloaded", timeout=30000)
                await detail.wait_for_timeout(2500)
                text = await detail.inner_text("body")

                if detail_page_blocked(text):
                    print(f"  BLOCKED (first 200 chars of body): {text[:200]!r}")
                    continue

                # Count IconOption elements
                icon_count = await detail.evaluate("() => document.querySelectorAll('div.IconOption').length")
                print(f"  Page loaded. div.IconOption count: {icon_count}")

                if icon_count == 0:
                    # Dump first 1000 chars to understand the page
                    print(f"  Body text (first 1000):\n{text[:1000]}")
                    # Also try to find what elements exist
                    relevant = await detail.evaluate("""() => {
                        const kws = ['קומה','מ"ר','מעלית','חניה','משופצ'];
                        const hits = [];
                        document.querySelectorAll('[class]').forEach(el => {
                            const t = el.innerText && el.innerText.trim();
                            if (t && kws.some(k => t.includes(k))) {
                                hits.push({tag: el.tagName, cls: el.className, text: t.substring(0,80)});
                            }
                        });
                        return hits.slice(0,20);
                    }""")
                    print(f"  Elements with keywords: {relevant}")
                else:
                    # Run extraction and dump all IconOption items
                    icon_dump = await detail.evaluate("""() => Array.from(
                        document.querySelectorAll('div.IconOption')
                    ).map((el,i) => ({
                        i, cls: el.className,
                        img: el.querySelector('img') ? el.querySelector('img').src : null,
                        h3: el.querySelector('h3') ? el.querySelector('h3').textContent.trim() : null,
                        lastChild: el.lastElementChild ? el.lastElementChild.textContent.trim() : null,
                        text: el.innerText.trim().substring(0,60)
                    }))""")
                    print(f"  IconOption items:")
                    for item in icon_dump:
                        print(f"    [{item['i']}] cls={item['cls']!r} img={item['img']} h3={item['h3']!r} last={item['lastChild']!r} text={item['text']!r}")

                    extracted = await detail.evaluate(_HOMELESS_DETAIL_JS)
                    print(f"  Extracted: {extracted}")
                    _apply_homeless_fields(listing, extracted)

                print(f"  Final listing fields:")
                for f in FIELDS:
                    print(f"    {f}: {getattr(listing, f, None)}")
                print()

            except Exception as e:
                print(f"  ERROR: {e}")
            finally:
                await detail.close()
            await asyncio.sleep(4)

        await ctx.close()
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
