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

DETAIL_URL = "https://www.komo.co.il/code/nadlan/details/?modaaNum=4860872"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="he-IL", user_agent=UA, viewport={"width": 1366, "height": 768})
        page = await ctx.new_page()

        await page.goto(DETAIL_URL, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Get the HTML of key sections
        # 1. The floor info
        print("=== FLOOR INFO ===")
        floor_sel = ".floor, .firstInfo.floor, [class*='floor']"
        els = await page.query_selector_all(floor_sel)
        for el in els:
            html = await el.inner_html()
            txt = await el.inner_text()
            cls = await el.get_attribute("class")
            print(f"Class: {cls}, Text: {txt}, HTML: {html[:200]}")

        # 2. The secondInfoWrap (has מצב הנכס, קומות בבניין, etc.)
        print("\n=== SECOND INFO ===")
        els2 = await page.query_selector_all(".secondInfoElement")
        for el in els2:
            txt = await el.inner_text()
            html = await el.inner_html()
            print(f"Text: {repr(txt)}")
            print(f"HTML: {html[:300]}")
            print("---")

        # 3. The thirdInfo (amenities)
        print("\n=== THIRD INFO (amenities) ===")
        els3 = await page.query_selector_all(".thirdInfo1, .thirdInfo")
        for el in els3[:5]:
            txt = await el.inner_text()
            html = await el.inner_html()
            cls = await el.get_attribute("class")
            print(f"Class: {cls}, Text: {repr(txt)}")
            print(f"HTML: {html[:400]}")
            print("---")

        # 4. Get full HTML of the main modaa section
        main_el = await page.query_selector(".modaaWContent, #modaaContent, .modaaW")
        if main_el:
            main_html = await main_el.inner_html()
            print(f"\n=== MAIN CONTENT HTML (first 5000) ===\n{main_html[:5000]}")

        # 5. Search for date published
        all_text = await page.inner_text("body")
        lines = all_text.split("\n")
        for i, line in enumerate(lines):
            if any(kw in line for kw in ["פורסם", "תאריך פרסום", "עודכן", "הועלה"]):
                print(f"\nDate line {i}: {line}")

        await browser.close()

asyncio.run(main())
