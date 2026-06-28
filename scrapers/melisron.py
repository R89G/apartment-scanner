import logging
import re
from datetime import date

from playwright.async_api import Page

from models.listing import Listing
from scrapers.base_scraper import BaseScraper
from scrapers.utils import extract_elevator, extract_parking, extract_property_status

logger = logging.getLogger(__name__)

MELISRON_URL = "https://www.melisron.co.il/apartments/?city=tel-aviv"


class MelisronScraper(BaseScraper):
    site_name = "Melisron"

    async def scrape(self, page: Page) -> list[Listing]:
        listings: list[Listing] = []
        await page.goto(MELISRON_URL, wait_until="networkidle", timeout=35000)
        await self.random_delay()
        await self.human_scroll(page)

        cards = await page.query_selector_all('[class*="apartment"], [class*="listing"], .property-card')
        for card in cards:
            try:
                listing = await _parse_card(card)
                if listing:
                    listings.append(listing)
            except Exception as exc:
                logger.debug("Melisron: failed to parse card: %s", exc)

        # Melisron typically shows all units on one page (small inventory)
        return listings


async def _parse_card(card) -> Listing | None:
    today = date.today().isoformat()

    async def text(sel: str) -> str:
        el = await card.query_selector(sel)
        return (await el.inner_text()).strip() if el else ""

    link_el = await card.query_selector("a")
    href = await link_el.get_attribute("href") if link_el else None
    if not href:
        return None
    url = href if href.startswith("http") else f"https://www.melisron.co.il{href}"

    price_raw = await text("[class*='price']")
    price = _p(price_raw)
    rooms_raw = await text("[class*='room']")
    rooms = _f(rooms_raw)
    floor_raw = await text("[class*='floor']")
    floor = _fl(floor_raw)
    size_raw = await text("[class*='size'], [class*='sqm'], [class*='area']")
    size = _i(re.sub(r"[^\d]", "", size_raw)) if size_raw else None
    neighborhood = await text("[class*='neighborhood'], [class*='location']")
    street = await text("[class*='street'], [class*='address']")
    desc_el = await card.query_selector("[class*='description'], [class*='title'], h3, h2")
    description = (await desc_el.inner_text()).strip() if desc_el else ""
    property_status = extract_property_status(description)
    has_elevator = extract_elevator(description)
    has_parking = extract_parking(description)

    return Listing(
        url=url, source_site="Melisron", date_found=today,
        neighborhood=neighborhood or None, street=street or None,
        floor=floor, rooms=rooms, size_sqm=size, price_nis=price,
        property_status=property_status,
        has_elevator=has_elevator,
        has_parking=has_parking,
        notes=[],
    )


def _p(raw: str) -> int | None:
    c = re.sub(r"[^\d]", "", raw); return int(c) if c else None

def _f(raw: str) -> float | None:
    m = re.search(r"[\d.]+", raw); return float(m.group()) if m else None

def _i(raw: str) -> int | None:
    c = re.sub(r"[^\d]", "", raw); return int(c) if c else None

def _fl(raw: str) -> int | None:
    if not raw: return None
    if "קרקע" in raw: return 0
    if "מרתף" in raw: return -1
    m = re.search(r"(\d+)", raw); return int(m.group(1)) if m else None
