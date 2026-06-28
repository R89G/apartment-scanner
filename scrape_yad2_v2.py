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
        if token:
            print(f"[YAD2] Token: {token}")
        else:
            print("[YAD2] No token, sample:")
            print(json.dumps(data, ensure_ascii=False)[:500])
    except Exception as e:
        print(f"[YAD2] API fetch error: {e}")

    if not token:
        return

    listing_url = f"https://www.yad2.co.il/item/{token}"
    print(f"[YAD2] Detail URL: {listing_url}")

    # Also try the API endpoint directly for item data
    api_item_url = f"https://gw.yad2.co.il/feed-search-legacy/realestate/rent/{token}"
    print(f"[YAD2] Trying API item URL: {api_item_url}")
    try:
        req2 = urllib.request.Request(api_item_url, headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Referer": "https://www.yad2.co.il/",
        })
        with urllib.request.urlopen(req2, timeout=15) as resp:
            item_raw = resp.read()
        item_data = json.loads(item_raw.decode('utf-8'))
        print(f"[YAD2] Item API keys: {list(item_data.keys()) if isinstance(item_data, dict) else type(item_data)}")
        print(f"[YAD2] Item API sample:\n{json.dumps(item_data, ensure_ascii=False)[:3000]}")
    except Exception as e:
        print(f"[YAD2] Item API error: {e}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ])
        ctx = await browser.new_context(
            locale="he-IL",
            user_agent=UA,
            viewport={"width": 1366, "height": 768},
            extra_http_headers={
                "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )
        # Remove automation flags
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        page = await ctx.new_page()

        # First visit yad2 homepage to get cookies
        print("[YAD2] Visiting homepage first...")
        await page.goto("https://www.yad2.co.il/", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        print("[YAD2] Now visiting listing...")
        await page.goto(listing_url, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        # Check for captcha
        body_text = await page.inner_text("body")
        if "captcha" in body_text.lower() or "Are you for real" in body_text:
            print("[YAD2] CAPTCHA detected, trying to wait longer...")
            await asyncio.sleep(5)
            body_text = await page.inner_text("body")

        # Get __NEXT_DATA__
        try:
            el = await page.query_selector("script#__NEXT_DATA__")
            if el:
                next_data = await el.inner_text()
                print(f"\n[YAD2] __NEXT_DATA__ (first 3000 chars):\n{next_data[:3000]}")
            else:
                # Try other script tags that might have data
                scripts = await page.query_selector_all("script[type='application/json']")
                print(f"[YAD2] Found {len(scripts)} application/json scripts")
                for s in scripts[:3]:
                    txt = await s.inner_text()
                    print(f"  Script: {txt[:200]}")
                print("[YAD2] No __NEXT_DATA__ found")
        except Exception as e:
            print(f"[YAD2] Script search error: {e}")

        print(f"\n[YAD2] Full body text (first 4000 chars):\n{body_text[:4000]}")

        # Field search
        fields = {"קומה": [], "פורסם": [], "מצב": [], "מעלית": [], "חני": []}
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
                    print(f"    {repr(l)}")
            else:
                print(f"  '{key}': NOT FOUND")

        await browser.close()

asyncio.run(main())
