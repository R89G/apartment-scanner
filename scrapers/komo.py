import logging
import re
from datetime import date

from playwright.async_api import Page

from models.listing import Listing
from scrapers.base_scraper import BaseScraper
from scrapers.utils import (
    apply_detail_fields,
    detail_page_blocked,
    extract_elevator,
    extract_floors_in_building,
    extract_parking,
    extract_property_status,
    parse_detail_text,
    quick_passes,
)

logger = logging.getLogger(__name__)

# Tel Aviv Yafo rentals on Komo
KOMO_URL = (
    "https://www.komo.co.il/code/nadlan/apartments-for-rent.asp"
    "?nehes=1&cityName=%D7%AA%D7%9C+%D7%90%D7%91%D7%99%D7%91+%D7%99%D7%A4%D7%95"
)
BASE = "https://www.komo.co.il"


class KomoScraper(BaseScraper):
    site_name = "Komo"
    max_detail_pages: int | None = None

    async def scrape(self, page: Page) -> list[Listing]:
        listings: list[Listing] = []
        await page.goto(KOMO_URL, wait_until="domcontentloaded", timeout=30000)
        await self.random_delay()
        await self.human_scroll(page, steps=5)

        page_num = 1
        while True:
            cards = await page.query_selector_all("div.modaaRow")
            logger.debug("Komo page %d: found %d cards", page_num, len(cards))

            for card in cards:
                try:
                    listing = await _parse_card(card)
                    if listing:
                        listings.append(listing)
                except Exception as exc:
                    logger.debug("Komo: failed to parse card: %s", exc)

            # Pagination: numeric links at the bottom
            next_btn = await page.query_selector(
                f'a[href*="pg={page_num + 1}"], '
                f'a.nextPage, a[title="הבא"]'
            )
            if not next_btn:
                break

            page_num += 1
            if page_num > 20:
                break

            await next_btn.click()
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await self.random_delay()
            await self.human_scroll(page, steps=3)

        # ── Detail page enrichment ────────────────────────────────────────────
        candidates = [l for l in listings if quick_passes(l)]
        to_enrich = candidates[: self.max_detail_pages] if self.max_detail_pages else candidates
        logger.info("Komo: enriching %d detail pages", len(to_enrich))
        for listing in to_enrich:
            detail = await page.context.new_page()
            try:
                await detail.goto(listing.url, wait_until="domcontentloaded", timeout=30000)
                await detail.wait_for_timeout(1500)
                text = await detail.inner_text("body")
                if detail_page_blocked(text):
                    continue
                detail_data = parse_detail_text(text)
                # Komo amenity icons: active features carry class "add" on their <li>.
                # inner_text cannot distinguish active vs inactive, so use DOM evaluation.
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
                    # Merge: DOM-sourced values override None, but don't overwrite text-sourced data
                    for key, val in komo_amenities.items():
                        if val is not None and detail_data.get(key) is None:
                            detail_data[key] = val
                except Exception as exc:
                    logger.debug("Komo: JS evaluate error for %s: %s", listing.url, exc)
                apply_detail_fields(listing, detail_data)
            except Exception as exc:
                logger.debug("Komo: detail page error for %s: %s", listing.url, exc)
            finally:
                await detail.close()
            await self.random_delay()

        return listings


async def _parse_card(card) -> Listing | None:
    today = date.today().isoformat()

    # Link
    link_el = await card.query_selector("a.tdKotarotInner")
    href = await link_el.get_attribute("href") if link_el else None
    if not href:
        return None
    url = href if href.startswith("http") else f"{BASE}{href}"

    # Address: "תל אביב יפו, הצפון החדש, חוני המעגל 2"
    # initaddr attribute on the inner div gives a cleaner version
    addr_div = await card.query_selector("div[initaddr]")
    full_address = (await addr_div.get_attribute("initaddr") or "").strip() if addr_div else ""

    # Title span has "תל אביב יפו, {neighborhood}, {street}"
    title_el = await card.query_selector("span.LinkModaaTitle")
    title_text = (await title_el.inner_text()).strip() if title_el else ""
    # Remove the big-title span from the text (it's a duplicate)
    # title_text looks like: "תל אביב יפו, הצפון החדש, חוני המעגל 2\nלדירה2.0 חדרים..."
    title_text = title_text.split("\n")[0].strip()

    city, neighborhood, street = _parse_address(title_text, full_address)

    # Price: "5,900 ₪"
    price_el = await card.query_selector("td.tdPrice")
    price_raw = (await price_el.inner_text()).strip() if price_el else ""
    price = _parse_price(price_raw)

    # More details: "דירה 2.0 חדרים (45 מ\"ר) \n קומה:3 מתוך 3"
    details_el = await card.query_selector("td.tdMoreDetails")
    details_text = (await details_el.inner_text()).strip() if details_el else ""
    rooms = _parse_rooms(details_text)
    size = _parse_size(details_text)
    floor = _parse_floor(details_text)
    floors_in_building = extract_floors_in_building(details_text)

    # Description from bigtitle attribute
    big_div = await card.query_selector("div[bigtitle]")
    description = (await big_div.get_attribute("bigtitle")) or "" if big_div else ""
    description = re.sub(r"^ל\s*", "", description).strip()

    property_status = extract_property_status(description)
    has_elevator = extract_elevator(description)
    has_parking = extract_parking(description)

    return Listing(
        url=url,
        source_site="Komo",
        date_found=today,
        neighborhood=neighborhood or None,
        street=street or None,
        floor=floor,
        rooms=rooms,
        size_sqm=size,
        price_nis=price,
        property_status=property_status,
        city=city or None,
        floors_in_building=floors_in_building,
        has_elevator=has_elevator,
        has_parking=has_parking,
        notes=[],
    )


def _parse_address(title: str, initaddr: str) -> tuple[str | None, str | None, str | None]:
    # title: "תל אביב יפו, הצפון החדש, חוני המעגל 2"
    # Returns (city, neighborhood, street)
    parts = [p.strip() for p in title.split(",")]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        return parts[0], None, parts[1]
    # Fallback: use initaddr
    addr_parts = [p.strip() for p in initaddr.split(",")]
    if len(addr_parts) >= 2:
        return addr_parts[0], None, addr_parts[-1]
    return None, None, initaddr or None


def _parse_price(raw: str) -> int | None:
    c = re.sub(r"[^\d]", "", raw)
    return int(c) if c else None


def _parse_rooms(text: str) -> float | None:
    # "דירה 2.0 חדרים" or "2 חדרים"
    m = re.search(r"([\d.]+)\s*חדרים", text)
    return float(m.group(1)) if m else None


def _parse_size(text: str) -> int | None:
    # "(45 מ\"ר)" or "45מ\"ר"
    m = re.search(r"\((\d+)\s*מ", text)
    if not m:
        m = re.search(r"(\d+)\s*מ[\"״]ר", text)
    return int(m.group(1)) if m else None


def _parse_floor(text: str) -> int | None:
    # "קומה:3 מתוך 3" or "קומה 3"
    m = re.search(r"קומה[:\s]+(\d+)", text)
    if m:
        return int(m.group(1))
    if "קרקע" in text:
        return 0
    if "מרתף" in text:
        return -1
    return None
