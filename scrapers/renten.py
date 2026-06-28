import logging

from playwright.async_api import Page

from models.listing import Listing
from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class RentenScraper(BaseScraper):
    site_name = "Renten"

    async def scrape(self, page: Page) -> list[Listing]:
        logger.warning(
            "Renten (renten.co.il) is a government subsidized housing "
            "program that operates via a lottery system — there is no public rental "
            "listings page to scrape. Skipping."
        )
        return []

    async def run(self) -> list[Listing]:
        return await self.scrape(None)  # type: ignore[arg-type]
