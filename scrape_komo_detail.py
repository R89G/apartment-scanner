import asyncio
import json
import sys
import io
from playwright.async_api import async_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Already found detail URL
DETAIL_URL = "https://www.komo.co.il/code/nadlan/details/?modaaNum=4860872"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="he-IL", user_agent=UA, viewport={"width": 1366, "height": 768})
        page = await ctx.new_page()

        await page.goto(DETAIL_URL, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        title = await page.title()
        print(f"[KOMO] Title: {title}")

        # Get the full body text - increased to 10000
        body_text = await page.inner_text("body")
        print(f"[KOMO] Full body text ({len(body_text)} chars):")
        print(body_text)

        # Also search for specific selectors
        print("\n\n=== ELEMENT SEARCHES ===")
        selectors_to_check = [
            "td.detailsTableTd",
            "table.detailsTable",
            ".modaaDetails",
            "#modaaDetails",
            "td[class*='detail']",
            ".propertyDetails",
            "#propertyDetails",
            "td",
            "tr",
        ]
        for sel in selectors_to_check:
            els = await page.query_selector_all(sel)
            if els:
                txts = []
                for el in els[:5]:
                    txt = (await el.inner_text()).strip()
                    if txt and len(txt) > 2:
                        txts.append(txt[:100])
                if txts:
                    print(f"\nSelector '{sel}' ({len(els)} found):")
                    for t in txts:
                        print(f"  {t}")

        # Check all classes
        classes = await page.evaluate("""() => {
            const els = document.querySelectorAll('[class]');
            const cls = new Set();
            els.forEach(e => {
                if (e.className && typeof e.className === 'string') {
                    e.className.split(' ').forEach(c => { if(c) cls.add(c); });
                }
            });
            return [...cls].slice(0, 200);
        }""")
        print(f"\n\nAll classes: {classes}")

        await browser.close()

asyncio.run(main())
