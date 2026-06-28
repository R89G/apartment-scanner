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
    # Use a specific Tel Aviv listing URL - try different ones
    listing_ids = ["740650", "740447", "740445", "740354", "740325"]

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
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['he-IL','he','en-US','en']});
        """)
        page = await ctx.new_page()

        # First load the homepage to get cookies
        print("[HOMELESS] Loading homepage...")
        await page.goto("https://www.homeless.co.il/", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        title = await page.title()
        print(f"[HOMELESS] Homepage title: {title}")

        # Now try a listing
        for listing_id in listing_ids:
            detail_url = f"https://www.homeless.co.il/rent/viewad,{listing_id}.aspx"
            print(f"\n[HOMELESS] Trying: {detail_url}")
            try:
                await page.goto(detail_url, wait_until="domcontentloaded")
                await asyncio.sleep(6)
                title = await page.title()
                body = await page.inner_text("body")
                print(f"  Title: {title}")
                if "cloudflare" in body.lower() or "אימות" in title or "רק רגע" in title:
                    print("  Still blocked, trying next...")
                    continue
                print(f"  SUCCESS! Body:\n{body[:3000]}")

                fields = {"קומה": [], "פורסם": [], "מצב": [], "מעלית": [], "חני": []}
                lines = body.split("\n")
                for i, line in enumerate(lines):
                    for key in fields:
                        if key in line:
                            start = max(0, i-2)
                            end = min(len(lines), i+3)
                            fields[key].append((i, lines[start:end]))
                print("\nFields:")
                for key, hits in fields.items():
                    if hits:
                        idx, ctx_lines = hits[0]
                        print(f"  '{key}' line {idx}: {ctx_lines}")
                    else:
                        print(f"  '{key}': NOT FOUND")
                break
            except Exception as e:
                print(f"  Error: {e}")

        await browser.close()

asyncio.run(main())
