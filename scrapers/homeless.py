import logging
import re
from datetime import date

from playwright.async_api import Page

from models.listing import Listing
from scrapers.base_scraper import BaseScraper
from scrapers.utils import (
    detail_page_blocked,
    extract_elevator,
    extract_parking,
    extract_property_status,
    quick_passes,
)

logger = logging.getLogger(__name__)

# JS to extract all structured fields from a Homeless detail page.
# div.IconOption elements carry class "on" (active) or "off" (inactive/greyed).
# Structured fields (floor, size, price) use an <h3> label + last-child <span> value.
_HOMELESS_DETAIL_JS = """() => {
    const r = {};
    for (const el of document.querySelectorAll("div.IconOption")) {
        const img = el.querySelector("img.itemsAd");
        const h3 = el.querySelector("h3");
        if (img) {
            const isOn = el.classList.contains("on");
            const src = img.getAttribute("src") || "";
            if (src.includes("Elevators")) {
                r.has_elevator = isOn;
            } else if (src.includes("parking")) {
                r.has_parking = isOn;
            } else if (src.includes("Renovated") && isOn) {
                r.property_status = el.textContent.trim();
            }
        } else if (h3) {
            const label = h3.textContent;
            const valEl = el.lastElementChild;
            const val = valEl ? valEl.textContent.trim() : "";
            if (label.includes("קומה")) {
                const m = val.match(/(\\d+)/);
                const m2 = val.match(/מתוך\\s*(\\d+)/);
                if (m) r.floor = parseInt(m[1], 10);
                if (m2) r.floors_in_building = parseInt(m2[1], 10);
            } else if (/מ.ר/.test(label)) {
                const m = val.match(/(\\d+)/);
                if (m) r.size_sqm = parseInt(m[1], 10);
            } else if (label.includes("מחיר")) {
                const m = val.match(/(\\d+)/);
                if (m) r.price_nis = parseInt(m[1], 10);
            }
        }
    }
    return r;
}"""

# Tel Aviv city filter; the site also shows other cities, so we pass city name.
# Price and rooms filters applied via URL params.
HOMELESS_URL = (
    "https://www.homeless.co.il/rent/apartments/"
    "?city=%D7%AA%D7%9C+%D7%90%D7%91%D7%99%D7%91"  # תל אביב
    "&rooms=2&price_max=8000"
)
# Fallback URL without city encoding issues
HOMELESS_URL_FALLBACK = (
    "https://www.homeless.co.il/rent/apartments/"
    "?rooms=2&price_max=8000"
)


class HomelessScraper(BaseScraper):
    site_name = "Homeless"

    async def scrape(self, page: Page) -> list[Listing]:
        listings: list[Listing] = []
        await page.goto(HOMELESS_URL, wait_until="domcontentloaded", timeout=30000)
        await self.random_delay()
        await self.human_scroll(page, steps=4)

        page_num = 1
        while True:
            # Each listing is a <tr type="ad"> row
            rows = await page.query_selector_all('tr[type="ad"]')
            logger.debug("Homeless page %d: found %d rows", page_num, len(rows))

            for row in rows:
                try:
                    listing = await _parse_row(row)
                    if listing:
                        listings.append(listing)
                except Exception as exc:
                    logger.debug("Homeless: failed to parse row: %s", exc)

            # Pagination: look for next-page link
            next_btn = await page.query_selector('a[title="עמוד הבא"], a.nextPage, a[rel="next"]')
            if not next_btn:
                # Try finding a numeric next page link
                current_page_el = await page.query_selector('.currentPage, .activePage, [class*="current"]')
                if current_page_el:
                    current_text = (await current_page_el.inner_text()).strip()
                    try:
                        current_n = int(current_text)
                        next_btn = await page.query_selector(f'a[title="{current_n + 1}"]')
                    except ValueError:
                        pass

            if not next_btn:
                break

            page_num += 1
            if page_num > 20:
                break

            await next_btn.click()
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await self.random_delay()

        # ── Detail page enrichment ────────────────────────────────────────────
        candidates = [l for l in listings if quick_passes(l)]
        logger.info("Homeless: enriching %d detail pages", len(candidates))
        blocked_count = 0
        consecutive_blocks = 0
        for listing in candidates:
            # If first 3 pages in a row are CF-blocked, the whole site is blocked — stop early.
            if consecutive_blocks >= 3:
                logger.info(
                    "Homeless: 3 consecutive CF blocks — skipping remaining %d detail pages",
                    len(candidates) - blocked_count,
                )
                break
            detail = await page.context.new_page()
            try:
                await detail.goto(listing.url, wait_until="domcontentloaded", timeout=30000)
                await detail.wait_for_timeout(2500)
                text = await detail.inner_text("body")
                if detail_page_blocked(text):
                    blocked_count += 1
                    consecutive_blocks += 1
                    logger.debug("Homeless: detail blocked (%d so far): %s", blocked_count, listing.url)
                    continue
                consecutive_blocks = 0
                extracted = await detail.evaluate(_HOMELESS_DETAIL_JS)
                logger.debug("Homeless: extracted %s -> %s", listing.url, extracted)
                _apply_homeless_fields(listing, extracted)
            except Exception as exc:
                logger.debug("Homeless: detail page error for %s: %s", listing.url, exc)
            finally:
                await detail.close()
            await self.random_delay()
        if blocked_count:
            logger.info("Homeless: %d/%d detail pages were CF-blocked", blocked_count, len(candidates))

        return listings


async def _parse_row(row) -> Listing | None:
    today = date.today().isoformat()

    # Column layout (0-indexed tds in the row):
    # 0: checkbox (selectionarea)
    # 1: image
    # 2: property type
    # 3: city
    # 4: neighborhood
    # 5: street
    # 6: rooms
    # 7: floor
    # 8: price
    # 9: available date
    # 10: post date
    # 11: details link

    tds = await row.query_selector_all("td")
    if len(tds) < 9:
        return None

    async def cell(idx: int) -> str:
        if idx >= len(tds):
            return ""
        return (await tds[idx].inner_text()).strip()

    # URL from the details cell (last td with class "details")
    details_td = await row.query_selector("td.details")
    link_el = await details_td.query_selector("a") if details_td else None
    if not link_el:
        # Fall back to onclick on the row itself
        onclick = await row.get_attribute("onclick") or ""
        m = re.search(r"openPopup\('([^']+)'\)", onclick)
        if m:
            href = m.group(1)
        else:
            return None
    else:
        href = await link_el.get_attribute("href") or ""

    if not href:
        return None
    url = href if href.startswith("http") else f"https://www.homeless.co.il{href}"

    city = await cell(3)
    neighborhood = await cell(4)
    street = await cell(5)
    rooms = _parse_float(await cell(6))
    floor_raw = await cell(7)
    floor = _parse_floor(floor_raw)
    floors_in_building = _parse_floors_in_building(floor_raw)
    price = _parse_price(await cell(8))
    date_published = _parse_post_date(await cell(10))

    img_el = await row.query_selector("img.PictureDisplayOnBoard")
    description = ""
    if img_el:
        description = (await img_el.get_attribute("alt")) or ""

    property_status = extract_property_status(description)
    has_elevator = extract_elevator(description)
    has_parking = extract_parking(description)

    return Listing(
        url=url,
        source_site="Homeless",
        date_found=today,
        neighborhood=neighborhood or None,
        street=street or None,
        floor=floor,
        floors_in_building=floors_in_building,
        rooms=rooms,
        size_sqm=None,
        price_nis=price,
        property_status=property_status,
        city=city or None,
        has_elevator=has_elevator,
        has_parking=has_parking,
        date_published=date_published,
        notes=[],
    )


def _apply_homeless_fields(listing, extracted: dict) -> None:
    """Apply JS-extracted detail fields to a listing; never clears an existing value."""
    for field in ("floor", "floors_in_building", "property_status",
                  "has_elevator", "has_parking", "size_sqm"):
        val = extracted.get(field)
        if val is not None and getattr(listing, field, None) is None:
            setattr(listing, field, val)
    # Price: fill in if missing from card parse
    price = extracted.get("price_nis")
    if price is not None and listing.price_nis is None:
        listing.price_nis = price


def _parse_price(raw: str) -> int | None:
    c = re.sub(r"[^\d]", "", raw)
    return int(c) if c else None


def _parse_float(raw: str) -> float | None:
    m = re.search(r"[\d.]+", raw)
    return float(m.group()) if m else None


def _parse_floor(raw: str) -> int | None:
    if not raw:
        return None
    if "קרקע" in raw:
        return 0
    if "מרתף" in raw:
        return -1
    m = re.search(r"(\d+)", raw)
    return int(m.group(1)) if m else None


def _parse_floors_in_building(raw: str) -> int | None:
    """Extract total floors from strings like '3 מתוך 6' or '3/6'."""
    if not raw:
        return None
    m = re.search(r"מתוך\s*(\d+)", raw)
    if m:
        return int(m.group(1))
    m = re.search(r"\d+\s*/\s*(\d+)", raw)
    if m:
        return int(m.group(1))
    return None


def _parse_post_date(raw: str) -> str | None:
    """Convert Homeless post date 'DD/MM/YYYY' to 'YYYY-MM-DD'."""
    if not raw:
        return None
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw.strip())
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return None
