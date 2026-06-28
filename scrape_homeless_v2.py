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
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        ctx = await browser.new_context(
            locale="he-IL",
            user_agent=UA,
            viewport={"width": 1366, "height": 768},
        )
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        page = await ctx.new_page()

        print(f"[HOMELESS] Loading search page...")
        await page.goto(search_url, wait_until="domcontentloaded")
        await asyncio.sleep(4)

        title = await page.title()
        body = await page.inner_text("body")
        print(f"[HOMELESS] Title: {title}")
        print(f"[HOMELESS] Body first 500: {body[:500]}")

        # Check for Cloudflare
        if "cloudflare" in body.lower() or "security" in title.lower():
            print("[HOMELESS] Cloudflare challenge, waiting longer...")
            await asyncio.sleep(8)
            body = await page.inner_text("body")
            title = await page.title()
            print(f"[HOMELESS] Title after wait: {title}")
            print(f"[HOMELESS] Body after wait: {body[:500]}")

        # Get all links
        links = await page.query_selector_all("a[href]")
        listing_links = []
        for lnk in links:
            href = await lnk.get_attribute("href")
            text = (await lnk.inner_text())[:50]
            if href and ("viewad" in href or "/item/" in href or "/listing/" in href):
                listing_links.append((href, text))
                print(f"  Listing link: {href} [{text}]")

        if not listing_links:
            print("[HOMELESS] No listing links found, dumping all links:")
            for lnk in links[:30]:
                href = await lnk.get_attribute("href")
                text = (await lnk.inner_text())[:40]
                print(f"  [{text}] {href}")

        if listing_links:
            detail_url = listing_links[0][0]
            if not detail_url.startswith("http"):
                detail_url = "https://www.homeless.co.il" + detail_url
            print(f"\n[HOMELESS] Detail URL: {detail_url}")
            await page.goto(detail_url, wait_until="domcontentloaded")
            await asyncio.sleep(5)

            title = await page.title()
            body_text = await page.inner_text("body")
            print(f"[HOMELESS] Detail title: {title}")
            print(f"[HOMELESS] Detail body (3000):\n{body_text[:3000]}")

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
