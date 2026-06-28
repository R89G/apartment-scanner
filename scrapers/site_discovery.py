import json
import logging
import re
from pathlib import Path

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

PRIMARY_DOMAINS = {
    "yad2.co.il",
    "madlan.co.il",
    "homeless.co.il",
    "nester.co.il",
    "melisron.co.il",
    "komo.co.il",
    "renten.co.il",
    "azrielitown.com",
}

DISCOVERY_FILE = Path(__file__).parent.parent / "discovered_sites.json"

SEARCH_QUERIES = [
    '"דירות להשכרה תל אביב" site:.co.il',
    '"השכרת דירות תל אביב" 2024',
]


def _load_known() -> set[str]:
    if DISCOVERY_FILE.exists():
        data = json.loads(DISCOVERY_FILE.read_text(encoding="utf-8"))
        return set(data.get("discovered", []))
    return set()


def _save_discovered(domains: set[str]) -> None:
    DISCOVERY_FILE.write_text(
        json.dumps({"discovered": sorted(domains)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def discover_new_sites() -> list[str]:
    known = _load_known()
    all_known = PRIMARY_DOMAINS | known
    newly_found: set[str] = set()

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(locale="he-IL")
            page = await context.new_page()

            for query in SEARCH_QUERIES:
                try:
                    search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}&hl=he"
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)

                    links = await page.query_selector_all("a[href]")
                    for link in links:
                        href = await link.get_attribute("href") or ""
                        m = re.search(r"https?://(?:www\.)?([a-z0-9\-]+\.co\.il)", href)
                        if m:
                            domain = m.group(1)
                            if domain not in all_known:
                                newly_found.add(domain)
                                logger.info("Site discovery: found new domain: %s", domain)

                except Exception as exc:
                    logger.warning("Site discovery: search query failed: %s — %s", query, exc)

            await context.close()
            await browser.close()

    except Exception as exc:
        logger.error("Site discovery: browser failed: %s", exc)
        return []

    if newly_found:
        _save_discovered(known | newly_found)
        logger.info("Site discovery: %d new domains found and saved", len(newly_found))

    return sorted(newly_found)
