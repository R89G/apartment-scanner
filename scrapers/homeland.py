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
    extract_parking,
    extract_property_status,
    parse_detail_text,
    quick_passes,
)

logger = logging.getLogger(__name__)

# Location archive for Tel Aviv Yafo — contains both rent and sale listings.
# We filter to rent-only by checking the property URL slug for "להשכרה".
HOMELAND_URL = "https://www.homeland.co.il/location/%D7%AA%D7%9C-%D7%90%D7%91%D7%99%D7%91-%D7%99%D7%A4%D7%95/"

# Card container selector confirmed from HTML inspection
CARD_SEL = ".col-post"


class HomelandScraper(BaseScraper):
    site_name = "Homeland"
    max_detail_pages: int | None = None

    async def scrape(self, page: Page) -> list[Listing]:
        listings: list[Listing] = []
        page_num = 1

        while True:
            if page_num == 1:
                url = HOMELAND_URL
            else:
                url = f"{HOMELAND_URL}page/{page_num}/"

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self.random_delay()
            await self.human_scroll(page, steps=4)

            cards = await page.query_selector_all(CARD_SEL)
            logger.debug("Homeland page %d: found %d cards", page_num, len(cards))

            if not cards:
                break

            for card in cards:
                try:
                    listing = await _parse_card(card)
                    if listing:
                        listings.append(listing)
                except Exception as exc:
                    logger.debug("Homeland: card parse error: %s", exc)

            # Check for next page
            next_link = await page.query_selector('a.next.page-numbers, a[rel="next"]')
            if not next_link:
                break

            page_num += 1
            if page_num > 10:
                break

        # ── Detail page enrichment ────────────────────────────────────────────
        candidates = [l for l in listings if quick_passes(l)]
        to_enrich = candidates[: self.max_detail_pages] if self.max_detail_pages else candidates
        logger.info("Homeland: enriching %d detail pages", len(to_enrich))
        for listing in to_enrich:
            detail = await page.context.new_page()
            try:
                await detail.goto(listing.url, wait_until="networkidle", timeout=40000)
                await detail.wait_for_timeout(500)
                text = await detail.inner_text("body")
                if not detail_page_blocked(text):
                    apply_detail_fields(listing, parse_detail_text(text))
            except Exception as exc:
                logger.debug("Homeland: detail page error for %s: %s", listing.url, exc)
            finally:
                await detail.close()
            await self.random_delay()

        return listings


async def _parse_card(card) -> Listing | None:
    today = date.today().isoformat()

    # Get URL from card-link anchor
    link_el = await card.query_selector("a.card-link")
    href = (await link_el.get_attribute("href")) if link_el else None
    if not href:
        return None

    # Only include rental listings
    href_decoded = _url_decode(href).lower()
    if "למכירה" in href_decoded or "for-sale" in href_decoded:
        return None
    # If not explicitly "rental", still include (could be neutral slug)

    url = href if href.startswith("http") else f"https://www.homeland.co.il{href}"

    # Price — data-shekel-price attribute gives clean integer
    price_el = await card.query_selector(".property-price")
    price: int | None = None
    if price_el:
        raw_price = await price_el.get_attribute("data-shekel-price")
        if raw_price:
            price = _parse_int(re.sub(r"[^\d]", "", raw_price))
        else:
            price_text = (await price_el.inner_text()).strip()
            price = _parse_int(re.sub(r"[^\d]", "", price_text))

    # Title
    title_el = await card.query_selector(".content_props_title")
    title = (await title_el.inner_text()).strip() if title_el else ""

    # Address: "זבולון 25, Tel Aviv-Yafo, Israel"
    addr_el = await card.query_selector(".property-address")
    addr_text = ""
    if addr_el:
        raw = await addr_el.inner_text()
        addr_text = re.sub(r"\s+", " ", raw.replace("\n", " ")).strip()

    city_name, street, neighborhood = _parse_address(addr_text)

    # Rooms
    rooms: float | None = None
    room_el = await card.query_selector(".prop_room")
    if room_el:
        ps = await room_el.query_selector_all("p")
        if ps:
            rooms_text = (await ps[0].inner_text()).strip()
            m = re.search(r"[\d.]+", rooms_text)
            rooms = float(m.group()) if m else None

    # Size (מ״ר) — the sibling div after prop_room
    size_sqm: int | None = None
    room_parent = await card.query_selector(".roomandM")
    if room_parent:
        size_div = await room_parent.query_selector("div:not(.prop_room)")
        if size_div:
            ps = await size_div.query_selector_all("p")
            if ps:
                size_text = (await ps[0].inner_text()).strip()
                m = re.search(r"\d+", size_text)
                size_sqm = int(m.group()) if m else None

    # Floor — not available in the card view
    floor: int | None = None

    property_status = extract_property_status(title)
    has_elevator = extract_elevator(title)
    has_parking = extract_parking(title)

    return Listing(
        url=url,
        source_site="Homeland",
        date_found=today,
        neighborhood=neighborhood or None,
        street=street or None,
        floor=floor,
        rooms=rooms,
        size_sqm=size_sqm,
        price_nis=price,
        property_status=property_status,
        city=city_name or None,
        has_elevator=has_elevator,
        has_parking=has_parking,
        notes=[],
    )


def _parse_address(addr_text: str) -> tuple[str, str, str]:
    """Parse 'Street 25, Tel Aviv-Yafo, Israel' into (city, street, neighborhood)."""
    addr_text = re.sub(r"[^\w\s,.-]", "", addr_text).strip()
    parts = [p.strip() for p in addr_text.split(",")]
    street = parts[0] if parts else ""
    city = parts[1] if len(parts) >= 2 else ""
    return city, street, ""


def _url_decode(url: str) -> str:
    try:
        from urllib.parse import unquote
        return unquote(url)
    except Exception:
        return url


def _parse_int(raw: str) -> int | None:
    cleaned = re.sub(r"[^\d]", "", raw)
    return int(cleaned) if cleaned else None
