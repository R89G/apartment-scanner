"""Run Homeless scraper with DOM debug dump on first detail page — avoids rate limits
by using the exact same browser flow as production (search page first, then detail)."""
import asyncio
import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from scrapers.homeless import HOMELESS_URL, _HOMELESS_DETAIL_JS
from scrapers.utils import detail_page_blocked

OUT_DIR = os.path.join(os.path.dirname(__file__), "data")

# Extended JS that also returns diagnostic info
_DEBUG_JS = """() => {
    const r = {};
    const diag = {iconCount: 0, onCount: 0, offCount: 0, imgCount: 0, h3Count: 0, items: []};

    for (const el of document.querySelectorAll('div.IconOption')) {
        diag.iconCount++;
        const isOn = el.classList.contains('on');
        const isOff = el.classList.contains('off');
        if (isOn) diag.onCount++;
        if (isOff) diag.offCount++;

        const img = el.querySelector('img.itemsAd');
        const h3 = el.querySelector('h3');
        if (img) {
            diag.imgCount++;
            const src = img.getAttribute('src') || '';
            const item = {type: 'img', isOn, src, text: el.innerText.trim().substring(0,80)};
            diag.items.push(item);
            if (src.includes('Elevators')) {
                r.has_elevator = isOn;
            } else if (src.includes('parking') || src.includes('Parking')) {
                r.has_parking = isOn;
            } else if ((src.includes('Renovated') || src.includes('renovated')) && isOn) {
                r.property_status = el.textContent.trim().substring(0,40);
            }
        } else if (h3) {
            diag.h3Count++;
            const label = h3.textContent;
            const valEl = el.lastElementChild;
            const val = valEl ? valEl.textContent.trim() : '';
            diag.items.push({type: 'h3', label, val, fullText: el.innerText.trim().substring(0,80)});
            if (label.includes('קומה')) {
                const m = val.match(/(\\d+)/);
                const m2 = val.match(/מתוך\\s*(\\d+)/);
                if (m) r.floor = parseInt(m[1], 10);
                if (m2) r.floors_in_building = parseInt(m2[1], 10);
            } else if (/מ.ר/.test(label)) {
                const m = val.match(/(\\d+)/);
                if (m) r.size_sqm = parseInt(m[1], 10);
            } else if (label.includes('מחיר')) {
                const m = val.match(/(\\d+)/);
                if (m) r.price_nis = parseInt(m[1], 10);
            }
        } else {
            diag.items.push({type: 'other', text: el.innerText.trim().substring(0,80), classes: el.className});
        }
    }
    return {result: r, diag};
}"""

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="he-IL",
            viewport={"width": 1280, "height": 900},
        )

        # Visit search page first (same as production) to get cookies
        search_page = await ctx.new_page()
        await search_page.goto(HOMELESS_URL, wait_until="domcontentloaded", timeout=30000)
        await search_page.wait_for_timeout(3000)

        rows = await search_page.query_selector_all('tr[type="ad"]')
        print(f"Search page: found {len(rows)} rows")

        urls = []
        for row in rows:
            details_td = await row.query_selector("td.details")
            link_el = await details_td.query_selector("a") if details_td else None
            if link_el:
                href = await link_el.get_attribute("href") or ""
                url = href if href.startswith("http") else f"https://www.homeless.co.il{href}"
                urls.append(url)
            if len(urls) >= 6:
                break
        await search_page.close()
        print(f"URLs: {urls}\n")

        saved = 0
        for i, url in enumerate(urls):
            await asyncio.sleep(4 + i * 2)  # increasing delay
            p = await ctx.new_page()
            try:
                await p.goto(url, wait_until="domcontentloaded", timeout=30000)
                await p.wait_for_timeout(2500)

                body_text = await p.inner_text("body")
                if detail_page_blocked(body_text):
                    print(f"[{i+1}] BLOCKED: {url}")
                    continue

                print(f"[{i+1}] LOADED: {url}")

                # Save HTML
                html = await p.content()
                path = os.path.join(OUT_DIR, f"homeless_live_{i+1}.html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"    HTML saved: {path} ({len(html)} bytes)")

                # Print page text (first 3000 chars)
                print(f"    Body text (first 3000):")
                print(body_text[:3000])
                print()

                # Run debug JS
                out = await p.evaluate(_DEBUG_JS)
                result = out["result"]
                diag = out["diag"]
                print(f"    RESULT: {result}")
                print(f"    DIAG: iconCount={diag['iconCount']} on={diag['onCount']} off={diag['offCount']} img={diag['imgCount']} h3={diag['h3Count']}")
                print(f"    ITEMS:")
                for item in diag["items"]:
                    print(f"      {item}")
                print()

                saved += 1
                if saved >= 2:
                    break

            except Exception as e:
                print(f"[{i+1}] ERROR {url}: {e}")
            finally:
                await p.close()

        await ctx.close()
        await browser.close()
        print(f"Done. Loaded {saved} pages.")

if __name__ == "__main__":
    asyncio.run(main())
