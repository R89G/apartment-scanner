"""Print raw page text around קומה from the first 2 unblocked Yad2 detail pages."""
import asyncio, random, re, sys
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from playwright.async_api import async_playwright
from scrapers.base_scraper import USER_AGENTS, HAS_STEALTH, _stealth_instance
from scrapers.utils import detail_page_blocked, parse_detail_text
import aiohttp

MAP_URL = "https://gw.yad2.co.il/realestate-feed/rent/map"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; Pixel 4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Referer": "https://www.yad2.co.il/realestate/rent",
    "Origin": "https://www.yad2.co.il",
    "Accept": "application/json",
}


async def get_tokens(n=20):
    params = {"city": "5000", "area": "1", "region": "3", "property": "1",
              "bBox": "32.03,34.74,32.12,34.83", "zoom": "13"}
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.get(MAP_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)) as r:
            data = await r.json(content_type=None)
    markers = (data.get("data") or {}).get("markers", [])
    return [str(m["token"]) for m in markers[:n] if m.get("token")]


async def main():
    tokens = await get_tokens(30)
    print(f"Got {len(tokens)} tokens\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="he-IL",
            viewport={"width": 1280, "height": 800},
        )
        page = await ctx.new_page()
        if HAS_STEALTH:
            await _stealth_instance.apply_stealth_async(page)

        success_count = 0
        for token in tokens:
            if success_count >= 2:
                break
            url = f"https://www.yad2.co.il/item/{token}"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                text = await page.inner_text("body")
                if detail_page_blocked(text):
                    print(f"[{token}] BLOCKED")
                    continue

                success_count += 1
                print(f"\n{'='*60}")
                print(f"TOKEN: {token}  URL: {url}")
                print(f"{'='*60}")

                # Print 200 chars on each side of every occurrence of קומה
                for m in re.finditer(r"קומה", text):
                    start = max(0, m.start() - 80)
                    end = min(len(text), m.end() + 120)
                    snippet = text[start:end].replace("\n", "↵")
                    print(f"  ...{snippet}...")

                print(f"\n--- parse_detail_text result ---")
                result = parse_detail_text(text)
                print(f"  floor={result.get('floor')}  floors_in_building={result.get('floors_in_building')}")

                await asyncio.sleep(2)
            except Exception as e:
                print(f"[{token}] ERROR: {e}")

        await ctx.close()
        await browser.close()

    print(f"\nDone. {success_count} successful pages loaded.")

asyncio.run(main())
