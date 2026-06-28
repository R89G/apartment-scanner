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
    search_url = "https://www.homeless.co.il/rent/apartments/?city=%D7%AA%D7%9C+%D7%90%D7%91%D7%99%D7%91&rooms=2&price_max=8000"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="he-IL", user_agent=UA, viewport={"width": 1366, "height": 768})
        page = await ctx.new_page()

        print(f"[HOMELESS] Fetching search page...")
        await page.goto(search_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        title = await page.title()
        print(f"[HOMELESS] Search page title: {title}")

        # Try to find first listing link
        detail_url = None
        selectors_to_try = [
            "td.details a",
            "a.listing-link",
            ".listing a",
            "a[href*='/item/']",
            "a[href*='/rent/']",
            ".results a",
            "table a[href]",
            "a[href*='homeless.co.il/item']",
        ]

        for sel in selectors_to_try:
            try:
                el = await page.query_selector(sel)
                if el:
                    href = await el.get_attribute("href")
                    if href and len(href) > 5:
                        detail_url = href
                        print(f"[HOMELESS] Found link with selector '{sel}': {href}")
                        break
            except Exception as e:
                pass

        # If no link found, dump all links
        if not detail_url:
            print("[HOMELESS] No link found with tried selectors, dumping all <a> hrefs:")
            links = await page.query_selector_all("a[href]")
            for lnk in links[:30]:
                href = await lnk.get_attribute("href")
                text = await lnk.inner_text()
                print(f"  [{text[:30]}] {href}")

            body = await page.inner_text("body")
            print(f"\n[HOMELESS] Search body (2000):\n{body[:2000]}")
            await browser.close()
            return

        if not detail_url.startswith("http"):
            detail_url = "https://www.homeless.co.il" + detail_url

        print(f"\n[HOMELESS] Detail URL: {detail_url}")
        await page.goto(detail_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        title = await page.title()
        print(f"[HOMELESS] Detail page title: {title}")

        body_text = await page.inner_text("body")
        print(f"\n[HOMELESS] Body (3000):\n{body_text[:3000]}")

        fields = {"קומה": [], "פורסם": [], "מצב": [], "מעלית": [], "חני": []}
        lines = body_text.split("\n")
        for i, line in enumerate(lines):
            for key in fields:
                if key in line:
                    start = max(0, i-2)
                    end = min(len(lines), i+3)
                    fields[key].append((i, lines[start:end]))

        print("\n[HOMELESS] Fields:")
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
