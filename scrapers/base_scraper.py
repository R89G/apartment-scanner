import asyncio
import logging
import random
from abc import ABC, abstractmethod

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

try:
    from playwright_stealth import Stealth as _StealthCls
    _stealth_instance = _StealthCls()
    HAS_STEALTH = True
except ImportError:
    _stealth_instance = None
    HAS_STEALTH = False

from models.listing import Listing

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]


class BaseScraper(ABC):
    site_name: str = "Unknown"
    use_stealth: bool = False

    def __init__(self) -> None:
        self.max_retries = 3
        self.delay_min = 2.0
        self.delay_max = 4.0

    async def random_delay(self) -> None:
        await asyncio.sleep(random.uniform(self.delay_min, self.delay_max))

    async def launch_browser(self, playwright) -> tuple[Browser, BrowserContext, Page]:
        ua = random.choice(USER_AGENTS)
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=ua,
            viewport={"width": 1280, "height": 800},
            locale="he-IL",
        )
        page = await context.new_page()
        if self.use_stealth and HAS_STEALTH:
            await _stealth_instance.apply_stealth_async(page)
        return browser, context, page

    async def human_scroll(self, page: Page, steps: int = 8) -> None:
        for _ in range(steps):
            await page.mouse.wheel(0, random.randint(300, 600))
            await asyncio.sleep(random.uniform(0.3, 0.8))

    @abstractmethod
    async def scrape(self, page: Page) -> list[Listing]:
        ...

    async def run(self) -> list[Listing]:
        attempt = 0
        while attempt < self.max_retries:
            try:
                async with async_playwright() as pw:
                    browser, context, page = await self.launch_browser(pw)
                    try:
                        results = await self.scrape(page)
                        logger.info("%s: scraped %d raw listings", self.site_name, len(results))
                        return results
                    finally:
                        await context.close()
                        await browser.close()
            except Exception as exc:
                attempt += 1
                wait = 2 ** attempt
                logger.warning(
                    "%s: attempt %d/%d failed (%s). Retrying in %ds…",
                    self.site_name, attempt, self.max_retries, exc, wait,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(wait)
        logger.error("%s: all %d retries exhausted — skipping site", self.site_name, self.max_retries)
        return []
