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
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--window-size=1366,768",
            ]
        )
        ctx = await browser.new_context(
            locale="he-IL",
            user_agent=UA,
            viewport={"width": 1366, "height": 768},
            extra_http_headers={
                "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
                "sec-ch-ua-platform": '"Windows"',
            }
        )
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['he-IL','he','en-US','en']});
            window.chrome = {runtime: {}};
        """)
        page = await ctx.new_page()

        # Intercept and log API calls
        api_responses = {}
        async def handle_response(response):
            if "yad2.co.il" in response.url and "item" in response.url.lower():
                try:
                    ct = response.headers.get("content-type","")
                    if "json" in ct:
                        body = await response.json()
                        api_responses[response.url] = body
                        print(f"[YAD2] API intercepted: {response.url}")
                except:
                    pass
        page.on("response", handle_response)

        # Go to listing directly
        await page.goto(listing_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)

        body_text = await page.inner_text("body")
        title = await page.title()
        print(f"[YAD2] Page title: {title}")
        print(f"[YAD2] Body (first 500): {body_text[:500]}")

        # Check for captcha
        if "captcha" in body_text.lower() or "Are you for real" in body_text:
            print("[YAD2] Still CAPTCHA page")
            # Try to get cookies and use requests
            cookies = await ctx.cookies()
            print(f"[YAD2] Got {len(cookies)} cookies")
            for c in cookies:
                print(f"  Cookie: {c['name']}={c['value'][:30]}")

        # Check __NEXT_DATA__
        el = await page.query_selector("script#__NEXT_DATA__")
        if el:
            nd = await el.inner_text()
            print(f"\n[YAD2] __NEXT_DATA__:\n{nd[:3000]}")
        else:
            print("[YAD2] No __NEXT_DATA__")

        if api_responses:
            for url_k, val in api_responses.items():
                print(f"\n[YAD2] API response from {url_k}:")
                print(json.dumps(val, ensure_ascii=False)[:2000])

        print(f"\n[YAD2] Full body:\n{body_text[:4000]}")

        await browser.close()

asyncio.run(main())
