import logging

from playwright.async_api import Page

from models.listing import Listing
from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class AzrieliTownScraper(BaseScraper):
    site_name = "Azrieli Town"

    async def scrape(self, page: Page) -> list[Listing]:
        logger.warning(
            "Azrieli Town (azrielitown.com) does not publish individual apartment "
            "listings online — only floor-plan PDFs and a contact form are available. "
            "Skipping."
        )
        return []

    async def run(self) -> list[Listing]:
        return await self.scrape(None)  # type: ignore[arg-type]
