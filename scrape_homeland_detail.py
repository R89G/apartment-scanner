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

# Use the already-found detail URL
DETAIL_URL = "https://www.homeland.co.il/property/%d7%9c%d7%94%d7%a9%d7%9b%d7%a8%d7%94-%d7%91%d7%a9%d7%95%d7%a7-%d7%9c%d7%95%d7%99%d7%a0%d7%a1%d7%a7%d7%99-%d7%9c%d7%95%d7%a4%d7%98-%d7%9e%d7%a8%d7%95%d7%94%d7%98-%d7%91%d7%91%d7%a0%d7%99%d7%99%d7%9f/"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="he-IL", user_agent=UA, viewport={"width": 1366, "height": 768})
        page = await ctx.new_page()

        await page.goto(DETAIL_URL, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Get full HTML to find all elements
        html = await page.content()
        print(f"[HOMELAND] HTML length: {len(html)}")

        body_text = await page.inner_text("body")
        print(f"[HOMELAND] Full body text length: {len(body_text)}")
        print(f"\n[HOMELAND] FULL body text:\n{body_text}")

        # Also try to get specific elements
        for sel in [".property-details", ".listing-details", ".details-table",
                    "[class*='detail']", "[class*='property']", "table", ".specs"]:
            els = await page.query_selector_all(sel)
            if els:
                for el in els[:2]:
                    txt = await el.inner_text()
                    if len(txt.strip()) > 20:
                        cls = await el.get_attribute("class")
                        print(f"\n  Selector '{sel}' class='{cls}':\n  {txt[:300]}")
                        break

        await browser.close()

asyncio.run(main())
