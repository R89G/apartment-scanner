"""
Inspect Yad2 detail page amenities HTML.
Fetches 3 real listing tokens from the map API, visits each with stealth Playwright,
captures the full inner HTML of the features/amenities section so we can see
active vs greyed-out icon CSS patterns.
"""
import asyncio
import json
import re
import sys
from pathlib import Path

import aiohttp
from playwright.async_api import async_playwright

try:
    from playwright_stealth import Stealth as _StealthCls
    _stealth = _StealthCls()
    HAS_STEALTH = True
except ImportError:
    _stealth = None
    HAS_STEALTH = False
    print("[WARN] playwright_stealth not available -- captcha likely")

OUT = Path(__file__).parent / "_inspect_detail"
OUT.mkdir(exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": UA,
    "Referer": "https://www.yad2.co.il/realestate/rent",
    "Accept": "application/json",
}


async def get_tokens(n: int = 5) -> list[str]:
    tokens = []
    boxes = [
        "32.03,34.74,32.12,34.83",
        "32.03,34.83,32.12,34.92",
    ]
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for bbox in boxes:
            if len(tokens) >= n:
                break
            params = {
                "city": "5000", "area": "1", "region": "3", "property": "1",
                "bBox": bbox, "zoom": "13",
            }
            async with session.get(
                "https://gw.yad2.co.il/realestate-feed/rent/map",
                params=params,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json(content_type=None)
                inner = data.get("data") or {}
                markers = inner.get("markers", []) if isinstance(inner, dict) else []
                for m in markers:
                    t = str(m.get("token") or m.get("id") or "")
                    if t and t not in tokens:
                        tokens.append(t)
                    if len(tokens) >= n:
                        break
    return tokens


async def inspect_listing(page, token: str, idx: int) -> None:
    url = f"https://www.yad2.co.il/item/{token}"
    print(f"\n[{idx}] {url}")

    # Intercept API responses the React app makes while loading the listing
    captured_api: list[dict] = []

    async def on_response(response):
        if "gw.yad2.co.il" in response.url and response.status == 200:
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    body = await response.json()
                    txt = str(body)
                    if any(kw in txt for kw in ("מעלית", "elevator", "parking", "floor", "condition")):
                        captured_api.append({"url": response.url, "body": body})
            except Exception:
                pass

    page.on("response", on_response)

    await page.goto(url, wait_until="domcontentloaded", timeout=35000)
    await page.wait_for_timeout(3500)

    page.remove_listener("response", on_response)

    body_text = await page.inner_text("body")
    if any(kw in body_text.lower() for kw in ("captcha", "are you for real", "אנו מניחים")):
        print("  BLOCKED (captcha)")
        return

    print(f"  Page loaded. Captured {len(captured_api)} API responses with relevant data.")
    for entry in captured_api:
        out_path = OUT / f"yad2_api_{idx}_{token}_{entry['url'].split('/')[-1][:30]}.json"
        import json
        out_path.write_text(json.dumps(entry["body"], ensure_ascii=False, indent=2)[:12000], encoding="utf-8")
        print(f"  API: {entry['url']} -> {out_path.name}")

    # Also find the amenities section via DOM
    result = await page.evaluate(r"""() => {
        // Walk every leaf text node; find ones containing מעלית
        // then walk up to find a container that holds multiple feature items
        function findAmenitiesContainer() {
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) {
                if (node.textContent.includes('מעלית')) {  // מעלית
                    let el = node.parentElement;
                    for (let i = 0; i < 8; i++) {
                        if (!el) break;
                        // Found a container with multiple items?
                        const childCount = el.querySelectorAll('[class]').length;
                        if (childCount >= 3) {
                            return {html: el.outerHTML.slice(0, 6000), selector: el.tagName + '.' + el.className.slice(0,60)};
                        }
                        el = el.parentElement;
                    }
                }
            }
            return null;
        }
        return findAmenitiesContainer();
    }""")

    if result:
        out_path = OUT / f"yad2_amenities_{idx}_{token}.html"
        out_path.write_text(result["html"], encoding="utf-8")
        print(f"  Amenities container found via DOM walk: {result['selector']}")
        print(f"  Saved {len(result['html'])} chars -> {out_path.name}")
        print("  HTML snippet (first 800 chars):")
        print("  " + result["html"][:800].replace("\n", "\n  "))
    else:
        # Fallback: save body HTML slice around 'מה יש'
        body_html = await page.inner_html("body")
        start = body_html.find("מה יש")
        snippet = body_html[max(0, start - 100): start + 5000] if start != -1 else body_html[:5000]
        out_path = OUT / f"yad2_body_{idx}_{token}.html"
        out_path.write_text(snippet, encoding="utf-8")
        print(f"  No amenities container found. Saved body slice -> {out_path.name}")

    # Plain text context for each keyword
    for keyword in ["מעלית", "חניה", "חנייה", "משופצת", "מה יש"]:
        ki = body_text.find(keyword)
        if ki != -1:
            ctx = body_text[max(0, ki - 80): ki + 150]
            print(f"\n  Context '{keyword}': {repr(ctx)}")


async def main() -> None:
    print("Fetching Yad2 tokens...")
    tokens = await get_tokens(5)
    print(f"Got {len(tokens)} tokens: {tokens}")

    if not tokens:
        print("No tokens — aborting")
        return

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=UA, locale="he-IL", viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()
        if HAS_STEALTH:
            await _stealth.apply_stealth_async(page)
            print("Stealth mode active")
        try:
            for i, token in enumerate(tokens[:5], 1):
                await inspect_listing(page, token, i)
                await asyncio.sleep(2)
        finally:
            await ctx.close()
            await browser.close()

    print(f"\nDone. Output in: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
