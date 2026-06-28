import asyncio
import json
import sys
import io
import urllib.request
from playwright.async_api import async_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

async def main():
    # Get token
    url = (
        "https://gw.yad2.co.il/realestate-feed/rent/map"
        "?city=5000&area=1&region=3&property=1"
        "&bBox=32.03,34.74,32.12,34.83&zoom=13"
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    markers = data.get("data", {}).get("markers", [])
    token = markers[0].get("token") if markers else None
    print(f"[YAD2] Token: {token}")

    listing_url = f"https://www.yad2.co.il/item/{token}"
    print(f"[YAD2] URL: {listing_url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
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

        # Intercept network to capture API calls
        captured_urls = []
        async def on_response(response):
            if "gw.yad2" in response.url or "api.yad2" in response.url:
                captured_urls.append(response.url)

        page.on("response", on_response)

        try:
            await page.goto(listing_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[YAD2] goto error (continuing): {e}")

        await asyncio.sleep(5)

        print(f"[YAD2] Captured API URLs: {captured_urls[:10]}")

        body_text = await page.inner_text("body")
        title = await page.title()
        print(f"[YAD2] Title: {title}")
        print(f"[YAD2] Body first 1000:\n{body_text[:1000]}")

        # Try to get __NEXT_DATA__
        nd_handle = await page.query_selector("script#__NEXT_DATA__")
        if nd_handle:
            nd = await nd_handle.inner_text()
            print(f"\n[YAD2] __NEXT_DATA__ first 3000:\n{nd[:3000]}")
        else:
            print("[YAD2] No __NEXT_DATA__")

        # Full body
        print(f"\n[YAD2] Full body (3000):\n{body_text[:3000]}")

        fields = {"קומה": [], "פורסם": [], "מצב": [], "מעלית": [], "חני": []}
        lines = body_text.split("\n")
        for i, line in enumerate(lines):
            for key in fields:
                if key in line:
                    start = max(0, i-2)
                    end = min(len(lines), i+3)
                    fields[key].append((i, lines[start:end]))

        print("\n[YAD2] Fields:")
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
