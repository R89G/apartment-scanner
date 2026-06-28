import logging

from playwright.async_api import Page

from models.listing import Listing
from scrapers.base_scraper import BaseScraper
from scrapers.utils import extract_property_status

logger = logging.getLogger(__name__)

BLOCK_SIGNALS = ["sorry for the interruption", "סליחה על ההפרעה", "captcha", "robot", "cloudflare"]


class MadlanScraper(BaseScraper):
    site_name = "Madlan"
    use_stealth = True

    async def scrape(self, page: Page) -> list[Listing]:
        url = "https://www.madlan.co.il/for-rent/apartments-tel-aviv-yafo?price_max=8000&minRooms=2"
        await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        await self.random_delay()

        content = (await page.content()).lower()
        if any(sig in content for sig in BLOCK_SIGNALS):
            logger.warning(
                "Madlan: bot-protection page detected (Imperva). "
                "Madlan actively blocks automated scrapers — skipping."
            )
            return []

        await self.human_scroll(page, steps=8)

        listings: list[Listing] = []
        page_num = 1
        while True:
            cards = await page.query_selector_all(
                '[class*="listing-item"], [class*="ListingCard"], '
                '[data-testid*="listing"], article[class*="card"]'
            )
            for card in cards:
                try:
                    from datetime import date
                    import re

                    link_el = await card.query_selector("a")
                    href = await link_el.get_attribute("href") if link_el else None
                    if not href:
                        continue
                    url_item = href if href.startswith("http") else f"https://www.madlan.co.il{href}"

                    async def text(sel: str) -> str:
                        el = await card.query_selector(sel)
                        return (await el.inner_text()).strip() if el else ""

                    price_raw = await text('[class*="price"], [class*="Price"]')
                    price = int(re.sub(r"[^\d]", "", price_raw)) if re.sub(r"[^\d]", "", price_raw) else None
                    rooms_raw = await text('[class*="room"]')
                    m = re.search(r"[\d.]+", rooms_raw)
                    rooms = float(m.group()) if m else None
                    floor_raw = await text('[class*="floor"]')
                    floor_m = re.search(r"(\d+)", floor_raw)
                    floor = int(floor_m.group(1)) if floor_m else None
                    neighborhood = await text('[class*="neighborhood"], [class*="area"]')
                    street = await text('[class*="street"], [class*="address"]')

                    from models.listing import Listing as L
                    listings.append(L(
                        url=url_item,
                        source_site="Madlan",
                        date_found=date.today().isoformat(),
                        neighborhood=neighborhood or None,
                        street=street or None,
                        floor=floor,
                        rooms=rooms,
                        size_sqm=None,
                        price_nis=price,
                        property_status=None,
                        notes=[],
                    ))
                except Exception as exc:
                    logger.debug("Madlan: card parse error: %s", exc)

            load_more = await page.query_selector('[class*="load-more"], button[class*="more"]')
            if load_more:
                await load_more.click()
                await self.random_delay()
                page_num += 1
            else:
                next_btn = await page.query_selector('[aria-label*="next"], [class*="next-page"]')
                if next_btn:
                    await next_btn.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await self.random_delay()
                    page_num += 1
                else:
                    break

            if page_num > 20:
                break

        return listings
