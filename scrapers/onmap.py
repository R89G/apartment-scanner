import asyncio
import logging
import re
import ssl
from datetime import date

import aiohttp

from models.listing import Listing
from scrapers.base_scraper import BaseScraper
from scrapers.utils import (
    apply_detail_fields,
    extract_elevator,
    extract_floors_in_building,
    extract_parking,
    extract_property_status,
    parse_detail_text,
    quick_passes,
)

logger = logging.getLogger(__name__)

# phoenix.onmap.co.il uses a self-signed certificate chain
_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl.CERT_NONE

ONMAP_API = "https://phoenix.onmap.co.il/v1/properties/mixed_search"
ONMAP_DETAIL_API = "https://phoenix.onmap.co.il/v1/properties/{prop_id}"
ONMAP_PARAMS_BASE = {
    "option": "rent,rent-short",
    "section": "residence",
    "city": "tel-aviv-yafo",
    "is_mobile": "false",
    "$sort": "-search_date",
    "$limit": "24",
    "country": "Israel",
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.onmap.co.il/",
    "Origin": "https://www.onmap.co.il",
}


class OnMapScraper(BaseScraper):
    site_name = "OnMap"

    async def scrape(self, page) -> list[Listing]:
        listings: list[Listing] = []
        skip = 0
        page_num = 0

        async with aiohttp.ClientSession(headers=HEADERS) as session:
            while True:
                params = {**ONMAP_PARAMS_BASE, "$skip": str(skip)}
                try:
                    async with session.get(
                        ONMAP_API,
                        params=params,
                        ssl=_SSL_CONTEXT,
                        timeout=aiohttp.ClientTimeout(total=20),
                    ) as resp:
                        if resp.status != 200:
                            logger.warning("OnMap API: HTTP %d at skip=%d", resp.status, skip)
                            break
                        data = await resp.json(content_type=None)
                except Exception as exc:
                    logger.warning("OnMap API request failed (skip=%d): %s", skip, exc)
                    break

                hits = data.get("data", []) if isinstance(data, dict) else data
                if not hits:
                    break

                for item in hits:
                    try:
                        listing = _parse_item(item)
                        if listing:
                            listings.append(listing)
                    except Exception as exc:
                        logger.debug("OnMap: parse error: %s", exc)

                page_num += 1
                if page_num >= 30 or len(hits) < 24:
                    break
                skip += 24
                await self.random_delay()

        logger.debug("OnMap: %d listings collected", len(listings))
        return listings

    async def run(self) -> list[Listing]:
        listings = await self.scrape(None)
        if not listings:
            return listings

        candidates = [l for l in listings if quick_passes(l)]
        if candidates:
            logger.info("OnMap: enriching %d candidates via detail API", len(candidates))
            await self._enrich_with_detail_api(candidates)
        return listings

    async def _enrich_with_detail_api(self, listings: list[Listing]) -> None:
        """Call v1/properties/{id} per listing to get description → elevator/status."""
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            for listing in listings:
                prop_id = listing.url.split("?property=")[-1]
                url = ONMAP_DETAIL_API.format(prop_id=prop_id)
                try:
                    async with session.get(
                        url,
                        ssl=_SSL_CONTEXT,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        if resp.status != 200:
                            continue
                        item = await resp.json(content_type=None)
                except Exception as exc:
                    logger.debug("OnMap: detail API error for %s: %s", prop_id, exc)
                    continue

                description = item.get("description") or ""
                detail: dict = {}
                if description:
                    detail["property_status"] = extract_property_status(description)
                    detail["has_elevator"] = extract_elevator(description)
                    if listing.has_parking is None:
                        detail["has_parking"] = extract_parking(description)

                # date_published from search_date or created_at
                for date_key in ("search_date", "created_at"):
                    raw_date = item.get(date_key)
                    if raw_date:
                        detail["date_published"] = str(raw_date)[:10]
                        break

                apply_detail_fields(listing, detail)
                await asyncio.sleep(0.5)


def _parse_item(item: dict) -> Listing | None:
    today = date.today().isoformat()

    # Address — Hebrew fields under item["address"]["he"]
    addr = item.get("address") or {}
    he_addr = addr.get("he") or {}
    neighborhood = he_addr.get("neighborhood") or ""
    street = he_addr.get("street_name") or ""
    house_num = he_addr.get("house_number") or ""
    if house_num:
        street = f"{street} {house_num}".strip()

    # Additional info for rooms/floor/size/parking
    add = item.get("additional_info") or {}
    rooms = _to_float(add.get("rooms"))
    floor_info = add.get("floor") or {}
    floor = _to_int(floor_info.get("on_the") if isinstance(floor_info, dict) else floor_info)
    # "out_of" is total floors in building (was incorrectly "total" before)
    floors_in_building = _to_int(floor_info.get("out_of") if isinstance(floor_info, dict) else None)
    area_info = add.get("area") or {}
    size_sqm = _to_int(area_info.get("base") if isinstance(area_info, dict) else area_info)

    # Parking from structured field
    parking_info = add.get("parking") or {}
    has_parking: bool | None = None
    if isinstance(parking_info, dict):
        above = parking_info.get("aboveground") or "none"
        below = parking_info.get("underground") or "none"
        if above not in ("none", "0", "", None) or below not in ("none", "0", "", None):
            has_parking = True
        else:
            has_parking = False

    price = _to_int(item.get("price"))

    # URL: use slug which contains the full readable path
    prop_id = item.get("id") or item.get("slug")
    if not prop_id:
        return None
    slug = item.get("slug") or prop_id
    url = f"https://www.onmap.co.il/search/homes/rent/tel-aviv-yafo/c_32.089280,34.818400/t_32.141950,34.924480/z_12?property={slug}"

    # Description available in mixed_search? (usually not — enriched via detail API)
    description = item.get("description") or ""
    property_status = extract_property_status(description) if description else None
    has_elevator = extract_elevator(description) if description else None
    if has_elevator is None and description:
        pass  # keep None; detail API will enrich

    return Listing(
        url=url,
        source_site="OnMap",
        date_found=today,
        neighborhood=neighborhood or None,
        street=street or None,
        floor=floor,
        rooms=rooms,
        size_sqm=size_sqm,
        price_nis=price,
        property_status=property_status,
        floors_in_building=floors_in_building,
        has_elevator=has_elevator,
        has_parking=has_parking,
        notes=[],
    )


def _to_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(re.sub(r"[^\d]", "", str(val))) or None
    except (ValueError, TypeError):
        return None


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        m = re.search(r"[\d.]+", str(val))
        return float(m.group()) if m else None
    except (ValueError, TypeError):
        return None
