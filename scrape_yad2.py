import asyncio
import json
import sys
import io
import urllib.request
from playwright.async_api import async_playwright

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

async def main():
    # Step 1: fetch the map feed to get a token
    url = (
        "https://gw.yad2.co.il/realestate-feed/rent/map"
        "?city=5000&area=1&region=3&property=1"
        "&bBox=32.03,34.74,32.12,34.83&zoom=13"
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    token = None
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        data = json.loads(raw.decode('utf-8'))
        if isinstance(data, dict):
            markers = data.get("markers") or data.get("data", {}).get("markers", [])
            if markers:
                first = markers[0]
                token = first.get("token") or first.get("id") or first.get("listing_id")
        print(f"[YAD2] API keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        if token:
            print(f"[YAD2] Token found: {token}")
        else:
            print("[YAD2] No token found, sample:")
            print(json.dumps(data, ensure_ascii=False)[:1000])
    except Exception as e:
        print(f"[YAD2] API fetch error: {e}")

    if not token:
        print("[YAD2] Cannot proceed without token")
        return

    listing_url = f"https://www.yad2.co.il/item/{token}"
    print(f"[YAD2] Detail URL: {listing_url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="he-IL", user_agent=UA)
        page = await ctx.new_page()
        await page.goto(listing_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Get __NEXT_DATA__
        next_data = ""
        try:
            el = await page.query_selector("script#__NEXT_DATA__")
            if el:
                next_data = await el.inner_text()
                print(f"\n[YAD2] __NEXT_DATA__ (first 3000 chars):\n{next_data[:3000]}")
            else:
                print("[YAD2] No __NEXT_DATA__ script tag found")
        except Exception as e:
            print(f"[YAD2] __NEXT_DATA__ error: {e}")

        body_text = await page.inner_text("body")
        print(f"\n[YAD2] body text (first 3000 chars):\n{body_text[:3000]}")

        # Search for fields
        fields = {
            "קומה": [],
            "פורסם": [],
            "מצב": [],
            "מעלית": [],
            "חני": [],
        }
        lines = body_text.split("\n")
        for i, line in enumerate(lines):
            for key in fields:
                if key in line:
                    start = max(0, i-2)
                    end = min(len(lines), i+3)
                    fields[key].append((i, lines[start:end]))

        print("\n[YAD2] Field contexts:")
        for key, hits in fields.items():
            if hits:
                idx, ctx_lines = hits[0]
                print(f"  '{key}' (line {idx}):")
                for l in ctx_lines:
                    print(f"    {l}")
            else:
                print(f"  '{key}': NOT FOUND in body text")

        await browser.close()

asyncio.run(main())
