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
    import ssl
    sslctx = ssl.create_default_context()
    sslctx.check_hostname = False
    sslctx.verify_mode = ssl.CERT_NONE

    map_url = (
        "https://gw.yad2.co.il/realestate-feed/rent/map"
        "?city=5000&area=1&region=3&property=1"
        "&bBox=32.03,34.74,32.12,34.83&zoom=13"
    )
    req = urllib.request.Request(map_url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15, context=sslctx) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    markers = data.get("data", {}).get("markers", [])
    token = markers[0].get("token") if markers else None
    print(f"[YAD2] Token: {token}")

    listing_url = f"https://www.yad2.co.il/item/{token}"
    print(f"[YAD2] URL: {listing_url}")

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
            window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)
        page = await ctx.new_page()

        # Capture ALL JSON responses from gw.yad2.co.il
        captured = {}
        async def on_response(response):
            if "gw.yad2" in response.url or ("yad2" in response.url and "item" in response.url.lower()):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        body = await response.json()
                        captured[response.url] = body
                        print(f"  [INTERCEPT] {response.url[:80]} -> {list(body.keys()) if isinstance(body, dict) else type(body)}")
                except:
                    pass
        page.on("response", on_response)

        # First load the homepage to set cookies
        try:
            await page.goto("https://www.yad2.co.il/realestate/rent", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            print(f"[YAD2] Rent page title: {await page.title()}")
        except Exception as e:
            print(f"[YAD2] Rent page error: {e}")

        # Now try the listing
        try:
            await page.goto(listing_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(4)
        except Exception as e:
            print(f"[YAD2] Listing goto error: {e}")

        title = await page.title()
        print(f"[YAD2] Listing title: {title}")
        body_text = await page.inner_text("body")

        if "ShieldSquare" in title or "captcha" in body_text.lower():
            print("[YAD2] CAPTCHA. Trying to get cookies and retry...")
            cookies = await ctx.cookies()
            print(f"  Cookies: {[(c['name'], c['value'][:20]) for c in cookies]}")

            # Try fetching the listing via urllib with cookies
            import http.cookiejar
            cj = http.cookiejar.CookieJar()
            for c in cookies:
                ck = http.cookiejar.Cookie(
                    version=0, name=c['name'], value=c['value'],
                    port=None, port_specified=False,
                    domain=c.get('domain', '.yad2.co.il'), domain_specified=True, domain_initial_dot=c.get('domain','').startswith('.'),
                    path=c.get('path', '/'), path_specified=True,
                    secure=c.get('secure', False),
                    expires=None, discard=True, comment=None, comment_url=None, rest={}
                )
                cj.set_cookie(ck)
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            try:
                req2 = urllib.request.Request(listing_url, headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
                    "Referer": "https://www.yad2.co.il/realestate/rent",
                })
                with opener.open(req2, timeout=15) as resp:
                    html = resp.read().decode('utf-8', errors='replace')
                print(f"  Got {len(html)} chars via urllib with cookies")
                import re
                m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
                if m:
                    print(f"  __NEXT_DATA__:\n{m.group(1)[:2000]}")
                if "ShieldSquare" in html or "captcha" in html.lower():
                    print("  Still CAPTCHA via urllib")
                else:
                    print(f"  HTML snippet:\n{html[:500]}")
            except Exception as e:
                print(f"  urllib with cookies error: {e}")

        # Check captured API responses
        if captured:
            print("\n[YAD2] Captured API responses:")
            for url, body in captured.items():
                print(f"  {url}:")
                print(f"  {json.dumps(body, ensure_ascii=False)[:500]}")
        else:
            print("[YAD2] No API responses captured")

        # Get __NEXT_DATA__ if not captcha
        el = await page.query_selector("script#__NEXT_DATA__")
        if el:
            nd = await el.inner_text()
            print(f"\n[YAD2] __NEXT_DATA__:\n{nd[:3000]}")
        else:
            print("[YAD2] No __NEXT_DATA__")

        print(f"\n[YAD2] Body:\n{body_text[:2000]}")

        await browser.close()

asyncio.run(main())
