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
    search_url = "https://www.ashtromresidencesforrent.co.il/apartments-4-rent"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="he-IL", user_agent=UA, viewport={"width": 1366, "height": 768})
        page = await ctx.new_page()

        print(f"[ASHTROM] Fetching search page...")
        await page.goto(search_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        title = await page.title()
        print(f"[ASHTROM] Search title: {title}")

        # Try clicking accordion summaries
        accordion_sel = '[class*="RentAccordion-StyledAccordionSummary"]'
        accordions = await page.query_selector_all(accordion_sel)
        print(f"[ASHTROM] Found {len(accordions)} accordion summaries")

        for acc in accordions:
            try:
                await acc.click()
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"  Click error: {e}")

        await asyncio.sleep(1)

        # Try to find the first StyledLink
        link_sel = '[class*="RentAccordionInner-StyledLink"]'
        link_el = await page.query_selector(link_sel)

        detail_url = None
        if link_el:
            href = await link_el.get_attribute("href")
            print(f"[ASHTROM] Found StyledLink: {href}")
            detail_url = href
        else:
            print("[ASHTROM] StyledLink not found, trying alternatives...")
            # Try alternate selectors
            for sel in ["a[href*='/apartment/']", "a[href*='/listing/']", ".apartment-card a", ".rent-card a", "a[href*='ashtrom']"]:
                el = await page.query_selector(sel)
                if el:
                    href = await el.get_attribute("href")
                    if href:
                        detail_url = href
                        print(f"[ASHTROM] Found with '{sel}': {href}")
                        break

            if not detail_url:
                print("[ASHTROM] Dumping all links:")
                links = await page.query_selector_all("a[href]")
                for lnk in links[:30]:
                    href = await lnk.get_attribute("href")
                    text = (await lnk.inner_text())[:30]
                    print(f"  [{text}] {href}")

                # Print all class names to understand structure
                classes = await page.evaluate("""() => {
                    const els = document.querySelectorAll('[class]');
                    const cls = new Set();
                    els.forEach(e => e.className.split(' ').forEach(c => cls.add(c)));
                    return [...cls].filter(c => c.length > 0).slice(0, 100);
                }""")
                print(f"\n[ASHTROM] Classes found: {classes}")

                body = await page.inner_text("body")
                print(f"\n[ASHTROM] Body (2000):\n{body[:2000]}")
                await browser.close()
                return

        if not detail_url:
            print("[ASHTROM] No detail URL")
            await browser.close()
            return

        if not detail_url.startswith("http"):
            if not detail_url.startswith("/"):
                detail_url = "/" + detail_url
            detail_url = "https://www.ashtromresidencesforrent.co.il" + detail_url

        print(f"\n[ASHTROM] Detail URL: {detail_url}")
        await page.goto(detail_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        title = await page.title()
        print(f"[ASHTROM] Detail title: {title}")

        body_text = await page.inner_text("body")
        print(f"\n[ASHTROM] Body (3000):\n{body_text[:3000]}")

        fields = {"קומה": [], "פורסם": [], "מצב": [], "מעלית": [], "חני": []}
        lines = body_text.split("\n")
        for i, line in enumerate(lines):
            for key in fields:
                if key in line:
                    start = max(0, i-2)
                    end = min(len(lines), i+3)
                    fields[key].append((i, lines[start:end]))

        print("\n[ASHTROM] Fields:")
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
