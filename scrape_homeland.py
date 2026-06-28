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
    search_url = "https://www.homeland.co.il/location/%D7%AA%D7%9C-%D7%90%D7%91%D7%99%D7%91-%D7%99%D7%A4%D7%95/"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="he-IL", user_agent=UA, viewport={"width": 1366, "height": 768})
        page = await ctx.new_page()

        print(f"[HOMELAND] Fetching search page...")
        await page.goto(search_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        title = await page.title()
        print(f"[HOMELAND] Search title: {title}")

        detail_url = None

        # Try specified selector
        el = await page.query_selector("a.card-link")
        if el:
            href = await el.get_attribute("href")
            print(f"[HOMELAND] Found a.card-link: {href}")
            detail_url = href
        else:
            print("[HOMELAND] a.card-link not found, trying alternatives...")
            for sel in [".property-card a", ".listing a", "a[href*='/item/']", "a[href*='/listing/']", ".card a", "article a"]:
                el = await page.query_selector(sel)
                if el:
                    href = await el.get_attribute("href")
                    if href:
                        detail_url = href
                        print(f"[HOMELAND] Found with '{sel}': {href}")
                        break

            if not detail_url:
                print("[HOMELAND] Dumping all links:")
                links = await page.query_selector_all("a[href]")
                for lnk in links[:30]:
                    href = await lnk.get_attribute("href")
                    text = (await lnk.inner_text())[:30]
                    print(f"  [{text}] {href}")
                body = await page.inner_text("body")
                print(f"\n[HOMELAND] Body (2000):\n{body[:2000]}")
                await browser.close()
                return

        if not detail_url:
            print("[HOMELAND] No detail URL found")
            await browser.close()
            return

        if not detail_url.startswith("http"):
            detail_url = "https://www.homeland.co.il" + detail_url

        print(f"\n[HOMELAND] Detail URL: {detail_url}")
        await page.goto(detail_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        title = await page.title()
        print(f"[HOMELAND] Detail title: {title}")

        body_text = await page.inner_text("body")
        print(f"\n[HOMELAND] Body (3000):\n{body_text[:3000]}")

        fields = {"קומה": [], "פורסם": [], "מצב": [], "מעלית": [], "חני": []}
        lines = body_text.split("\n")
        for i, line in enumerate(lines):
            for key in fields:
                if key in line:
                    start = max(0, i-2)
                    end = min(len(lines), i+3)
                    fields[key].append((i, lines[start:end]))

        print("\n[HOMELAND] Fields:")
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
