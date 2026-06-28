"""Test Homeless detail page extraction — fetch fresh URLs then test with delays."""
import asyncio
import sys
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from scrapers.homeless import _HOMELESS_DETAIL_JS, _apply_homeless_fields, HOMELESS_URL
from models.listing import Listing
from datetime import date

FIELDS = ["price_nis", "floor", "floors_in_building", "size_sqm",
          "property_status", "has_elevator", "has_parking"]


def fmt(v):
    if v is None: return "None"
    if isinstance(v, bool): return "YES" if v else "NO"
    return str(v)


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="he-IL",
            viewport={"width": 1280, "height": 800},
        )

        # Step 1: collect 6 URLs from the search page
        search_page = await ctx.new_page()
        await search_page.goto(HOMELESS_URL, wait_until="domcontentloaded", timeout=30000)
        await search_page.wait_for_timeout(2000)
        rows = await search_page.query_selector_all('tr[type="ad"]')
        urls = []
        for row in rows:
            details_td = await row.query_selector("td.details")
            link_el = await details_td.query_selector("a") if details_td else None
            if link_el:
                href = await link_el.get_attribute("href") or ""
                url = href if href.startswith("http") else f"https://www.homeless.co.il{href}"
                urls.append(url)
            if len(urls) >= 6:
                break
        await search_page.close()
        print(f"Collected {len(urls)} URLs from search page\n")

        # Step 2: test detail extraction on the first 3 that load successfully
        tested = 0
        for url in urls:
            if tested >= 3:
                break
            await asyncio.sleep(3)  # polite delay to avoid Cloudflare rate-limiting
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(1500)

                body_text = await page.inner_text("body")
                if "ביצוע אימות אבטחה" in body_text or "cloudflare" in body_text.lower():
                    print(f"BLOCKED: {url}")
                    continue

                extracted = await page.evaluate(_HOMELESS_DETAIL_JS)
                print(f"=== {url} ===")
                print(f"  Raw JS: {extracted}")

                listing = Listing(
                    url=url, source_site="Homeless", date_found=date.today().isoformat(),
                    neighborhood=None, street=None, floor=None, rooms=3.0,
                    size_sqm=None, price_nis=None, property_status=None, notes=[],
                )
                _apply_homeless_fields(listing, extracted)

                all_missing = all(getattr(listing, f) is None for f in FIELDS)
                for f in FIELDS:
                    val = getattr(listing, f, None)
                    marker = " <-- MISSING" if val is None else ""
                    print(f"    {f:25s} = {fmt(val)}{marker}")
                if all_missing:
                    print("  *** ALL FIELDS MISSING ***")
                print()
                tested += 1

            finally:
                await page.close()

        await ctx.close()
        await browser.close()
        print(f"Tested {tested}/3 listings successfully.")


if __name__ == "__main__":
    asyncio.run(main())
