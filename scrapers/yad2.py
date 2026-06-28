import asyncio
import logging
import random
import re
from datetime import date

import aiohttp

from models.listing import Listing
from scrapers.base_scraper import BaseScraper, HAS_STEALTH, USER_AGENTS, _stealth_instance
from scrapers.utils import (
    apply_detail_fields,
    detail_page_blocked,
    parse_detail_text,
    quick_passes,
)

logger = logging.getLogger(__name__)

# Yad2 property condition ID → Hebrew label mapping (from Yad2's taxonomy)
_CONDITION_ID_MAP: dict[int, str] = {
    1: "חדש מקבלן",
    2: "משופץ",
    3: "שמור",
    4: "ישן",
    5: "לשיפוץ",
}

# Yad2 map API — returns up to 200 markers per bBox call.
# Filters (rooms/price) are not passed to avoid 400 errors; filter client-side in main.py.
YAD2_MAP_URL = "https://gw.yad2.co.il/realestate-feed/rent/map"

# Tel Aviv bounding box split into 4 quadrants: (lat_min, lon_min, lat_max, lon_max)
TEL_AVIV_BOXES = [
    (32.03, 34.74, 32.12, 34.83),  # NW — Old North, HaYarkon, Ramat Aviv
    (32.03, 34.83, 32.12, 34.92),  # NE — Ramat HaHayal, eastern TA
    (31.94, 34.74, 32.03, 34.83),  # SW — Florentin, Neve Tzedek, Jaffa
    (31.94, 34.83, 32.03, 34.92),  # SE — southern Jaffa, near Bat Yam
]

_MOBILE_UAS = [
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]


def _make_headers() -> dict:
    return {
        "User-Agent": random.choice(_MOBILE_UAS),
        "Referer": "https://www.yad2.co.il/realestate/rent",
        "Origin": "https://www.yad2.co.il",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }


class Yad2Scraper(BaseScraper):
    site_name = "Yad2"
    max_detail_pages: int | None = None  # None = no limit; set to small N for testing

    async def scrape(self, page) -> list[Listing]:
        listings: list[Listing] = []
        seen_tokens: set[str] = set()

        # Vary timing to avoid identical request patterns
        await asyncio.sleep(random.uniform(1.0, 3.0))

        async with aiohttp.ClientSession(headers=_make_headers()) as session:
            for lat_min, lon_min, lat_max, lon_max in TEL_AVIV_BOXES:
                bbox = f"{lat_min},{lon_min},{lat_max},{lon_max}"
                params = {
                    "city": "5000",
                    "area": "1",
                    "region": "3",
                    "property": "1",
                    "bBox": bbox,
                    "zoom": "13",
                }

                data = None
                for attempt in range(3):
                    try:
                        async with session.get(
                            YAD2_MAP_URL,
                            params=params,
                            timeout=aiohttp.ClientTimeout(total=20),
                        ) as resp:
                            if resp.status == 429:
                                wait = 5 * (attempt + 1)
                                logger.warning(
                                    "Yad2 API rate-limited (429) for bBox %s, waiting %ds (attempt %d/3)",
                                    bbox, wait, attempt + 1,
                                )
                                await asyncio.sleep(wait)
                                continue
                            if resp.status != 200:
                                logger.warning(
                                    "Yad2 map API: HTTP %d for bBox %s", resp.status, bbox
                                )
                                break
                            data = await resp.json(content_type=None)
                            break
                    except Exception as exc:
                        wait = 2 ** (attempt + 1)
                        if attempt < 2:
                            logger.warning(
                                "Yad2 bBox %s error (attempt %d/3): %s — retrying in %ds",
                                bbox, attempt + 1, exc, wait,
                            )
                            await asyncio.sleep(wait)
                        else:
                            logger.warning("Yad2 map API error for bBox %s: %s", bbox, exc)

                if data is None:
                    continue

                # Response: {"data": {"markers": [...]}, "message": "..."}
                if isinstance(data, list):
                    markers = data
                elif isinstance(data, dict):
                    inner = data.get("data") or {}
                    markers = inner.get("markers", []) if isinstance(inner, dict) else inner
                else:
                    markers = []
                logger.debug("Yad2 bBox %s: %d markers", bbox, len(markers))

                for marker in markers:
                    try:
                        token = str(marker.get("token") or marker.get("id") or "")
                        if not token or token in seen_tokens:
                            continue
                        seen_tokens.add(token)

                        listing = _parse_marker(marker, token)
                        if listing:
                            listings.append(listing)
                    except Exception as exc:
                        logger.debug("Yad2: marker parse error: %s", exc)

                await self.random_delay()

        logger.debug("Yad2: %d listings collected (%d unique tokens)", len(listings), len(seen_tokens))
        return listings

    async def run(self) -> list[Listing]:
        listings = await self.scrape(None)
        if not listings:
            return listings

        candidates = [l for l in listings if quick_passes(l)]
        to_enrich = candidates[: self.max_detail_pages] if self.max_detail_pages else candidates
        if not to_enrich:
            return listings

        logger.info("Yad2: visiting detail pages for %d/%d candidates", len(to_enrich), len(candidates))
        await self._enrich_with_detail_pages(to_enrich)
        return listings

    async def _enrich_with_detail_pages(self, listings: list[Listing]) -> None:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale="he-IL",
                viewport={"width": 1280, "height": 800},
            )
            detail_page = await ctx.new_page()
            if HAS_STEALTH:
                await _stealth_instance.apply_stealth_async(detail_page)
            site_blocked = False
            try:
                for listing in listings:
                    if site_blocked:
                        break
                    try:
                        await detail_page.goto(
                            listing.url, wait_until="domcontentloaded", timeout=30000
                        )
                        await detail_page.wait_for_timeout(2000)
                        text = await detail_page.inner_text("body")
                        if detail_page_blocked(text):
                            logger.warning(
                                "Yad2: detail pages blocked (PerimeterX). "
                                "Skipping detail enrichment for all %d listings.",
                                len(listings),
                            )
                            site_blocked = True
                            continue
                        detail_data = parse_detail_text(text)
                        # property_status is authoritative from the map API condition id.
                        # has_elevator / has_parking are not present on Yad2 detail pages.
                        for _k in ("property_status", "has_elevator", "has_parking"):
                            detail_data.pop(_k, None)
                        # floors_in_building: only trust "קומה X/Y" or "קומה X מתוך Y".
                        # The generic fallback patterns match building IDs / postal codes.
                        detail_data.pop("floors_in_building", None)
                        m = re.search(
                            r"קומה\s+\d+\s+מתוך\s+(\d+)|קומה\s*:?\s*\d+\s*/\s*(\d+)",
                            text,
                        )
                        if m:
                            val = int(m.group(1) or m.group(2))
                            if 1 <= val <= 50:
                                detail_data["floors_in_building"] = val
                        apply_detail_fields(listing, detail_data)
                    except Exception as exc:
                        logger.debug("Yad2: detail page error for %s: %s", listing.url, exc)
                    await asyncio.sleep(random.uniform(2.0, 3.5))
            finally:
                await ctx.close()
                await browser.close()


def _parse_marker(marker: dict, token: str) -> Listing | None:
    today = date.today().isoformat()

    addr = marker.get("address") or {}
    house = addr.get("house") or {}

    city_obj = addr.get("city") or {}
    city = (
        city_obj.get("text", city_obj.get("name", ""))
        if isinstance(city_obj, dict) else str(city_obj or "")
    ) or None

    neighborhood_obj = addr.get("neighborhood") or {}
    neighborhood = (
        neighborhood_obj.get("text", neighborhood_obj.get("name", ""))
        if isinstance(neighborhood_obj, dict) else ""
    )

    street_obj = addr.get("street") or {}
    street = (
        street_obj.get("text", street_obj.get("name", ""))
        if isinstance(street_obj, dict) else ""
    )
    house_num = house.get("number")
    if house_num:
        street = f"{street} {house_num}".strip()

    floor = _to_int(house.get("floor"))

    details = marker.get("additionalDetails") or {}
    rooms = _to_float(details.get("roomsCount") or marker.get("roomsCount"))
    size_sqm = _to_int(details.get("squareMeter") or marker.get("squareMeter"))
    price = _to_int(marker.get("price"))

    url = f"https://www.yad2.co.il/item/{token}"

    # Property condition: map API provides a structured id — use only that, never free text
    cond_obj = details.get("propertyCondition") or {}
    cond_id = cond_obj.get("id") if isinstance(cond_obj, dict) else None
    property_status = _CONDITION_ID_MAP.get(cond_id)

    # Date published: map API has no date field; best proxy is the cover image upload path.
    # e.g. https://img.yad2.co.il/Pic/202504/24/... → "2025-04-24"
    cover = (marker.get("metaData") or {}).get("coverImage") or ""
    date_m = re.search(r"/Pic/(\d{4})(\d{2})/(\d{2})/", cover)
    date_published = (
        f"{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}" if date_m else None
    )

    # floors_in_building: not in map API; extracted from detail page "קומה X/Y" text if unblocked.
    # has_elevator / has_parking: not present on Yad2 pages — leave None.

    return Listing(
        url=url,
        source_site="Yad2",
        date_found=today,
        city=city,
        neighborhood=neighborhood or None,
        street=street or None,
        floor=floor,
        rooms=rooms,
        size_sqm=size_sqm,
        price_nis=price,
        property_status=property_status,
        floors_in_building=None,
        has_elevator=None,
        has_parking=None,
        date_published=date_published,
        notes=[],
    )


def _to_int(val) -> int | None:
    if val is None:
        return None
    try:
        cleaned = re.sub(r"[^\d]", "", str(val))
        return int(cleaned) if cleaned else None
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
