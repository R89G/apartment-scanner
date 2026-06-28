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

async def main():
    search_url = "https://www.komo.co.il/code/nadlan/apartments-for-rent.asp?nehes=1&cityName=%D7%AA%D7%9C+%D7%90%D7%91%D7%99%D7%91+%D7%99%D7%A4%D7%95"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="he-IL", user_agent=UA, viewport={"width": 1366, "height": 768})
        page = await ctx.new_page()

        print(f"[KOMO] Fetching search page...")
        await page.goto(search_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        title = await page.title()
        print(f"[KOMO] Search title: {title}")

        detail_url = None

        # Try specified selector first
        el = await page.query_selector("a.tdKotarotInner")
        if el:
            href = await el.get_attribute("href")
            print(f"[KOMO] Found a.tdKotarotInner: {href}")
            detail_url = href
        else:
            print("[KOMO] a.tdKotarotInner not found, trying alternatives...")
            for sel in ["a[href*='apartment']", "a[href*='nadlan']", ".listing a", "a.item-link", ".results a[href]"]:
                el = await page.query_selector(sel)
                if el:
                    href = await el.get_attribute("href")
                    if href:
                        detail_url = href
                        print(f"[KOMO] Found with '{sel}': {href}")
                        break

            if not detail_url:
                print("[KOMO] Dumping all links:")
                links = await page.query_selector_all("a[href]")
                for lnk in links[:30]:
                    href = await lnk.get_attribute("href")
                    text = (await lnk.inner_text())[:30]
                    print(f"  [{text}] {href}")
                body = await page.inner_text("body")
                print(f"\n[KOMO] Body (2000):\n{body[:2000]}")
                await browser.close()
                return

        if not detail_url:
            print("[KOMO] No detail URL found")
            await browser.close()
            return

        if not detail_url.startswith("http"):
            detail_url = "https://www.komo.co.il" + detail_url

        print(f"\n[KOMO] Detail URL: {detail_url}")
        await page.goto(detail_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        title = await page.title()
        print(f"[KOMO] Detail title: {title}")

        body_text = await page.inner_text("body")
        print(f"\n[KOMO] Body (3000):\n{body_text[:3000]}")

        fields = {"קומה": [], "פורסם": [], "מצב": [], "מעלית": [], "חני": []}
        lines = body_text.split("\n")
        for i, line in enumerate(lines):
            for key in fields:
                if key in line:
                    start = max(0, i-2)
                    end = min(len(lines), i+3)
                    fields[key].append((i, lines[start:end]))

        print("\n[KOMO] Fields:")
        for key, hits in fields.items():
            if hits:
                idx, ctx_lines = hits[0]
                print(f"  '{key}' line {idx}:")
                for l in ctx_lines:
                    print(f"    {l}")
            else:
                print(f"  '{key}': NOT FOUND")

        await browser.close()

asyncio.run(main())
