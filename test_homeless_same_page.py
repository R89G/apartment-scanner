"""Test 1: print raw cell values from search rows.
   Test 2: navigate the SAME page object to a detail URL (not new_page)."""
import asyncio
import sys
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from scrapers.homeless import HOMELESS_URL, _HOMELESS_DETAIL_JS
from scrapers.utils import detail_page_blocked

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="he-IL",
            viewport={"width": 1280, "height": 800},
        )
        page = await ctx.new_page()
        await page.goto(HOMELESS_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        rows = await page.query_selector_all('tr[type="ad"]')
        print(f"=== Search page rows: {len(rows)} ===\n")

        # Print raw cell values from first 5 rows
        urls = []
        print("Row cell values (indices 3=city 4=neighborhood 5=street 6=rooms 7=floor 8=price):")
        for i, row in enumerate(rows[:5]):
            tds = await row.query_selector_all("td")
            cells = []
            for j in range(min(12, len(tds))):
                txt = (await tds[j].inner_text()).strip()
                cells.append(f"[{j}]={txt!r}")
            # Get URL
            details_td = await row.query_selector("td.details")
            link_el = await details_td.query_selector("a") if details_td else None
            href = await link_el.get_attribute("href") if link_el else ""
            url = href if href.startswith("http") else f"https://www.homeless.co.il{href}"
            urls.append(url)
            print(f"  Row {i+1}: {' '.join(cells)}")
            # Also print img alt
            img = await row.query_selector("img.PictureDisplayOnBoard")
            if img:
                alt = await img.get_attribute("alt") or ""
                print(f"    img alt: {alt!r}")
        print()

        # Test 2: same-page navigation to first detail URL
        if urls:
            print(f"=== Testing same-page navigation to detail URL ===")
            print(f"URL: {urls[0]}")
            await asyncio.sleep(5)
            await page.goto(urls[0], wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2500)
            text = await page.inner_text("body")
            blocked = detail_page_blocked(text)
            print(f"Blocked: {blocked}")
            if not blocked:
                count = await page.evaluate("() => document.querySelectorAll('div.IconOption').length")
                print(f"div.IconOption count: {count}")
                extracted = await page.evaluate(_HOMELESS_DETAIL_JS)
                print(f"Extracted: {extracted}")
                print(f"\nBody text (first 1500):")
                print(text[:1500])
            else:
                print(f"Still blocked. Body: {text[:300]!r}")

        await ctx.close()
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
