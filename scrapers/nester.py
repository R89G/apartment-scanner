import logging

from playwright.async_api import Page

from models.listing import Listing
from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class NesterScraper(BaseScraper):
    site_name = "Nester"

    async def scrape(self, page: Page) -> list[Listing]:
        logger.warning(
            "Nester (nester.co.il) is a mobile-app-only platform with no public web "
            "search interface. Skipping."
        )
        return []

    async def run(self) -> list[Listing]:
        # Override run() to skip browser launch entirely
        return await self.scrape(None)  # type: ignore[arg-type]
