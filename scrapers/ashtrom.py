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

BASE_URL = "https://www.ashtromresidencesforrent.co.il"
LISTINGS_URL = f"{BASE_URL}/apartments-4-rent"

# Each accordion item on the page = one apartment unit.
# TopContent: "דירה בניין B משה וילנסקי 13 תל אביב 2"
# StyledFlex blocks: pairs of (label, value) for floor/sqm/price
CONTENT_PART_SEL = '[class*="RentAccordion-ContentPart"]'
TOP_CONTENT_SEL = '[class*="RentAccordion-TopContent"]'
FLEX_SEL = '[class*="RentAccordion-StyledFlex"]'
STYLEDLINK_SEL = '[class*="RentAccordionInner-StyledLink"]'
ACCORDION_SUMMARY_SEL = '[class*="RentAccordion-StyledAccordionSummary"]'

KNOWN_LABELS = frozenset({"חדרים", "קומה", 'מ"ר', "מ״ר", "שכר דירה", "מועד כניסה", "סוג"})


class AshtromScraper(BaseScraper):
    site_name = "Ashtrom"

    async def scrape(self, page: Page) -> list[Listing]:
        listings: list[Listing] = []

        await page.goto(LISTINGS_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Expand all project accordions to ensure all content is visible
        summaries = await page.query_selector_all(ACCORDION_SUMMARY_SEL)
        logger.debug("Ashtrom: found %d accordion summaries", len(summaries))
        for summary in summaries:
            try:
                await summary.click()
                await page.wait_for_timeout(600)
            except Exception:
                pass

        await page.wait_for_timeout(1000)

        # Each ContentPart = one apartment unit
        content_parts = await page.query_selector_all(CONTENT_PART_SEL)
        logger.debug("Ashtrom: found %d content parts", len(content_parts))

        for part in content_parts:
            try:
                listing = await _parse_content_part(part)
                if listing:
                    listings.append(listing)
            except Exception as exc:
                logger.debug("Ashtrom: content part parse error: %s", exc)

        # ── Detail page enrichment ────────────────────────────────────────────
        seen_urls: set[str] = set()
        candidates = [l for l in listings if quick_passes(l) and l.url not in seen_urls and not seen_urls.add(l.url)]  # type: ignore[func-returns-value]
        logger.info("Ashtrom: enriching %d detail pages", len(candidates))
        for listing in candidates:
            detail = await page.context.new_page()
            try:
                await detail.goto(listing.url, wait_until="domcontentloaded", timeout=30000)
                await detail.wait_for_timeout(1500)
                text = await detail.inner_text("body")
                if not detail_page_blocked(text):
                    apply_detail_fields(listing, parse_detail_text(text))
            except Exception as exc:
                logger.debug("Ashtrom: detail page error for %s: %s", listing.url, exc)
            finally:
                await detail.close()
            await self.random_delay()

        return listings


async def _parse_content_part(part) -> Listing | None:
    today = date.today().isoformat()

    # TopContent has format: "דירה {building} {street} {house_no} {city} {rooms}"
    top_el = await part.query_selector(TOP_CONTENT_SEL)
    top_text = ""
    if top_el:
        top_text = re.sub(r"\s+", " ", (await top_el.inner_text()).strip())

    street, city_name, rooms_from_top = _parse_top_content(top_text)

    # Ashtrom's TopContent always includes the city name.
    # Skip if it's not Tel Aviv (catches Jerusalem, Or Yehuda, Haifa, etc.)
    if top_text and "תל אביב" not in top_text:
        return None

    # Project URL from StyledLink
    link_el = await part.query_selector(STYLEDLINK_SEL)
    project_href = (await link_el.get_attribute("href")) if link_el else None
    if project_href:
        url = (
            project_href
            if project_href.startswith("http")
            else f"{BASE_URL}/{project_href.lstrip('/')}"
        )
    else:
        url = LISTINGS_URL

    # StyledFlex pairs for floor/sqm/price
    flex_blocks = await part.query_selector_all(FLEX_SEL)
    pairs = await _extract_pairs(flex_blocks)
    pair_dict = {label: value for label, value in pairs}

    rooms = rooms_from_top or _parse_float(pair_dict.get("חדרים", ""))
    floor = _parse_floor(pair_dict.get("קומה", ""))
    size_str = pair_dict.get("מ״ר") or pair_dict.get('מ"ר') or pair_dict.get("מ״ר") or ""
    size_sqm = _parse_int(re.sub(r"[^\d]", "", size_str))
    price_str = pair_dict.get("שכר דירה", "")
    price = _parse_int(re.sub(r"[^\d]", "", price_str))

    neighborhood = _neighborhood_from_href(project_href or "")

    return Listing(
        url=url,
        source_site="Ashtrom",
        date_found=today,
        neighborhood=neighborhood or None,
        street=street or None,
        floor=floor,
        rooms=rooms,
        size_sqm=size_sqm,
        price_nis=price,
        property_status=None,
        city=city_name or None,
        notes=[],
    )


async def _extract_pairs(flex_blocks) -> list[tuple[str, str]]:
    """Extract (label, value) from StyledFlex elements, normalising RTL swap."""
    pairs: list[tuple[str, str]] = []
    for flex in flex_blocks:
        ps = await flex.query_selector_all("p")
        if len(ps) >= 2:
            t0 = (await ps[0].inner_text()).strip()
            t1 = (await ps[1].inner_text()).strip()
            if t0 in KNOWN_LABELS:
                pairs.append((t0, t1))
            elif t1 in KNOWN_LABELS:
                pairs.append((t1, t0))
            else:
                # Fallback: second is more likely to be label in Hebrew RTL
                pairs.append((t1, t0))
    return pairs


def _parse_top_content(text: str) -> tuple[str, str, float | None]:
    """Parse 'דירה בניין B משה וילנסקי 13 תל אביב 2' → (street, city, rooms)."""
    if not text:
        return "", "", None

    # City detection
    city = ""
    city_match = re.search(r"(תל אביב|ירושלים|חיפה|באר שבע|ראשון לציון|פתח תקווה)", text)
    if city_match:
        city = city_match.group(1)
        # Street is everything between type/building info and city
        before_city = text[: city_match.start()].strip()
        # Remove leading type words like "דירה", "בניין X"
        before_city = re.sub(r"^(דירה|דירות|פנטהאוז)\s*", "", before_city).strip()
        before_city = re.sub(r"^בניין\s+\S+\s*", "", before_city).strip()
        before_city = re.sub(r"^רחוב\s+", "", before_city).strip()
        street = before_city
    else:
        street = text

    # Rooms: trailing digit(s) at end of text or before known suffix
    rooms: float | None = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:חדרים?)?\s*$", text)
    if m:
        try:
            rooms = float(m.group(1))
        except ValueError:
            pass

    return street, city, rooms


def _neighborhood_from_href(href: str) -> str:
    slug = href.strip("/").split("/")[-1].lower()
    mapping = {
        "hamishtala": "המשתלה",
        "hamistala": "המשתלה",
        "neveh-ofer": "נווה אופר",
        "neve-ofer": "נווה אופר",
        "ramat-pinkas": "רמת פינקס",
        "kiryat-hayovel": "קריית יובל",
    }
    for key, nbhd in mapping.items():
        if key in slug:
            return nbhd
    return ""


def _parse_float(raw: str) -> float | None:
    m = re.search(r"[\d.]+", raw)
    return float(m.group()) if m else None


def _parse_int(raw: str) -> int | None:
    cleaned = re.sub(r"[^\d]", "", raw)
    return int(cleaned) if cleaned else None


def _parse_floor(raw: str) -> int | None:
    if not raw:
        return None
    if "קרקע" in raw:
        return 0
    if "מרתף" in raw:
        return -1
    m = re.search(r"(\d+)", raw)
    return int(m.group(1)) if m else None
