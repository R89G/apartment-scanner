"""
Verification test: detail-page enrichment for Komo, Homeland, and OnMap.
Run: python test_detail_enrichment.py
"""
import asyncio
import sys
import ssl
import aiohttp

from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8")

try:
    from playwright_stealth import Stealth as _StealthCls
    _stealth = _StealthCls()
    HAS_STEALTH = True
except ImportError:
    _stealth = None
    HAS_STEALTH = False

from scrapers.utils import parse_detail_text, detail_page_blocked, extract_elevator, extract_parking, extract_property_status
from scrapers.onmap import _parse_item, ONMAP_API, ONMAP_DETAIL_API, HEADERS as ONMAP_HEADERS, _SSL_CONTEXT

FIELDS = ["floor", "floors_in_building", "property_status", "date_published", "has_elevator", "has_parking"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"


def _fmt(val) -> str:
    if val is None:
        return "None"
    if isinstance(val, bool):
        return "YES" if val else "NO"
    return str(val)


def _report(url: str, extracted: dict) -> None:
    print(f"  URL: {url}")
    all_none = all(extracted.get(f) is None for f in FIELDS)
    for f in FIELDS:
        marker = " <-- MISSING" if extracted.get(f) is None else ""
        print(f"    {f:25s} = {_fmt(extracted.get(f))}{marker}")
    if all_none:
        print("    *** ALL FIELDS NONE — extraction failed ***")


# ── Komo ─────────────────────────────────────────────────────────────────────

KOMO_SEARCH = (
    "https://www.komo.co.il/code/nadlan/apartments-for-rent.asp"
    "?nehes=1&cityName=%D7%AA%D7%9C+%D7%90%D7%91%D7%99%D7%91+%D7%99%D7%A4%D7%95"
)
KOMO_BASE = "https://www.komo.co.il"


async def test_komo(pw) -> None:
    print("\n" + "=" * 60)
    print("KOMO — 3 listing detail pages")
    print("=" * 60)

    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(user_agent=UA, locale="he-IL", viewport={"width": 1280, "height": 800})
    page = await ctx.new_page()
    if HAS_STEALTH:
        await _stealth.apply_stealth_async(page)

    try:
        await page.goto(KOMO_SEARCH, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)

        cards = await page.query_selector_all("div.modaaRow")
        print(f"  Search page: {len(cards)} cards")

        urls = []
        for card in cards:
            link_el = await card.query_selector("a.tdKotarotInner")
            href = await link_el.get_attribute("href") if link_el else None
            if href:
                urls.append(href if href.startswith("http") else f"{KOMO_BASE}{href}")
            if len(urls) >= 3:
                break

        if not urls:
            print("  No URLs found")
            return

        for url in urls:
            detail = await ctx.new_page()
            try:
                await detail.goto(url, wait_until="domcontentloaded", timeout=30000)
                await detail.wait_for_timeout(1500)
                text = await detail.inner_text("body")
                if detail_page_blocked(text):
                    print(f"\n  BLOCKED: {url}")
                    continue

                detail_data = parse_detail_text(text)

                # JS evaluate for amenity active/inactive state
                try:
                    komo_amenities = await detail.evaluate("""() => {
                        const r = {};
                        const elev = document.querySelector('li.maalit');
                        if (elev !== null) r.has_elevator = elev.classList.contains('add');
                        const renov = document.querySelector('li.renovated');
                        if (renov !== null && renov.classList.contains('add'))
                            r.property_status = 'משופצת';
                        for (const el of document.querySelectorAll('.secondInfoElement')) {
                            const title = el.querySelector('.secondInfoElementTitle');
                            const val = el.querySelector('.secondInfoElementContent');
                            if (title && title.textContent.includes('חניות')) {
                                const n = parseInt((val ? val.textContent.trim() : '') || '0');
                                r.has_parking = n > 0;
                                break;
                            }
                        }
                        return r;
                    }""")
                    for key, val in komo_amenities.items():
                        if val is not None and detail_data.get(key) is None:
                            detail_data[key] = val
                except Exception as e:
                    print(f"  JS error: {e}")

                print()
                _report(url, detail_data)
            except Exception as e:
                print(f"\n  ERROR: {url}: {e}")
            finally:
                await detail.close()
            await asyncio.sleep(2)
    finally:
        await ctx.close()
        await browser.close()


# ── Homeland ──────────────────────────────────────────────────────────────────

HOMELAND_SEARCH = "https://www.homeland.co.il/location/%D7%AA%D7%9C-%D7%90%D7%91%D7%99%D7%91-%D7%99%D7%A4%D7%95/"


async def test_homeland(pw) -> None:
    print("\n" + "=" * 60)
    print("HOMELAND — 3 listing detail pages")
    print("=" * 60)

    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(user_agent=UA, locale="he-IL", viewport={"width": 1280, "height": 800})
    page = await ctx.new_page()
    if HAS_STEALTH:
        await _stealth.apply_stealth_async(page)

    try:
        await page.goto(HOMELAND_SEARCH, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)

        cards = await page.query_selector_all(".col-post")
        print(f"  Search page: {len(cards)} cards")

        urls = []
        for card in cards:
            link_el = await card.query_selector("a.card-link")
            href = await link_el.get_attribute("href") if link_el else None
            if href:
                from urllib.parse import unquote
                if "למכירה" in unquote(href).lower() or "for-sale" in href.lower():
                    continue
                url = href if href.startswith("http") else f"https://www.homeland.co.il{href}"
                urls.append(url)
            if len(urls) >= 3:
                break

        if not urls:
            print("  No URLs found")
            return

        for url in urls:
            detail = await ctx.new_page()
            try:
                await detail.goto(url, wait_until="networkidle", timeout=40000)
                await detail.wait_for_timeout(500)
                text = await detail.inner_text("body")
                if detail_page_blocked(text):
                    print(f"\n  BLOCKED: {url}")
                    continue
                extracted = parse_detail_text(text)
                print()
                _report(url, extracted)
            except Exception as e:
                print(f"\n  ERROR: {url}: {e}")
            finally:
                await detail.close()
            await asyncio.sleep(2)
    finally:
        await ctx.close()
        await browser.close()


# ── OnMap ─────────────────────────────────────────────────────────────────────

async def test_onmap() -> None:
    print("\n" + "=" * 60)
    print("ONMAP — 3 listings (mixed_search API + detail API enrichment)")
    print("=" * 60)

    async with aiohttp.ClientSession(headers=ONMAP_HEADERS) as session:
        params = {**{"option": "rent", "section": "residence", "city": "tel-aviv-yafo",
                     "is_mobile": "false", "$sort": "-search_date", "$limit": "5", "country": "Israel"}}
        try:
            async with session.get(ONMAP_API, params=params, ssl=_SSL_CONTEXT,
                                   timeout=aiohttp.ClientTimeout(total=20)) as resp:
                data = await resp.json(content_type=None)
        except Exception as e:
            print(f"  API failed: {e}")
            return

        hits = (data.get("data", []) if isinstance(data, dict) else data)[:3]
        print(f"  API returned {len(hits)} items\n")

        for item in hits:
            listing = _parse_item(item)
            if not listing:
                continue

            prop_id = item.get("id") or ""
            extracted = {f: getattr(listing, f) for f in FIELDS}

            # Enrich from detail API
            if prop_id:
                detail_url = ONMAP_DETAIL_API.format(prop_id=prop_id)
                try:
                    async with session.get(detail_url, ssl=_SSL_CONTEXT,
                                           timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            detail_item = await resp.json(content_type=None)
                            description = detail_item.get("description") or ""
                            if description and extracted["property_status"] is None:
                                extracted["property_status"] = extract_property_status(description)
                            if description and extracted["has_elevator"] is None:
                                extracted["has_elevator"] = extract_elevator(description)
                            if listing.has_parking is None and description:
                                extracted["has_parking"] = extract_parking(description)
                            for date_key in ("search_date", "created_at"):
                                raw = detail_item.get(date_key)
                                if raw and extracted["date_published"] is None:
                                    extracted["date_published"] = str(raw)[:10]
                                    break
                except Exception as e:
                    print(f"  Detail API error for {prop_id}: {e}")

            _report(listing.url, extracted)
            print()
            await asyncio.sleep(0.5)


async def main() -> None:
    async with async_playwright() as pw:
        await test_komo(pw)
        await test_homeland(pw)
    await test_onmap()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
