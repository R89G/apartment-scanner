"""
One-shot inspection script: visits one detail page per site, dumps page text
and __NEXT_DATA__ so we can choose correct selectors/regex.
Output saved to _inspect_detail/ folder.
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import aiohttp
from playwright.async_api import async_playwright

OUT_DIR = Path(__file__).parent / "_inspect_detail"
OUT_DIR.mkdir(exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def dump(name: str, url: str, text: str, extra: str = "") -> None:
    out = OUT_DIR / f"{name}.txt"
    content = f"URL: {url}\n\n{'='*60}\n{text[:8000]}\n"
    if extra:
        content += f"\n{'='*60}\n__NEXT_DATA__ / extra:\n{extra[:4000]}\n"
    out.write_text(content, encoding="utf-8")
    print(f"  [{name}] saved {len(text)} chars -> {out}")


async def get_page_text(page, url: str, wait_ms: int = 3000) -> tuple[str, str]:
    await page.goto(url, wait_until="domcontentloaded", timeout=35000)
    await page.wait_for_timeout(wait_ms)
    text = await page.inner_text("body")
    # Try to grab __NEXT_DATA__
    nd = await page.evaluate("""() => {
        const el = document.getElementById('__NEXT_DATA__');
        return el ? el.textContent : '';
    }""")
    return text, nd or ""


# ── Yad2 ──────────────────────────────────────────────────────────────────────
async def inspect_yad2(pw) -> None:
    print("\n[Yad2] fetching map API for a token...")
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.yad2.co.il/realestate/rent",
        "Accept": "application/json",
    }
    token = None
    async with aiohttp.ClientSession(headers=headers) as session:
        params = {
            "city": "5000", "area": "1", "region": "3", "property": "1",
            "bBox": "32.03,34.74,32.12,34.83", "zoom": "13",
        }
        async with session.get(
            "https://gw.yad2.co.il/realestate-feed/rent/map",
            params=params,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                inner = data.get("data") or {}
                markers = inner.get("markers", []) if isinstance(inner, dict) else []
                if markers:
                    token = str(markers[0].get("token") or markers[0].get("id") or "")

    if not token:
        print("  [Yad2] could not get token — skipping")
        return

    url = f"https://www.yad2.co.il/item/{token}"
    print(f"  [Yad2] visiting {url}")
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(user_agent=UA, locale="he-IL")
    page = await ctx.new_page()
    try:
        text, nd = await get_page_text(page, url, wait_ms=4000)
        await dump("yad2_detail", url, text, nd)
    finally:
        await ctx.close()
        await browser.close()


# ── Homeless ──────────────────────────────────────────────────────────────────
async def inspect_homeless(pw) -> None:
    print("\n[Homeless] visiting search page...")
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(user_agent=UA, locale="he-IL")
    page = await ctx.new_page()
    try:
        search_url = (
            "https://www.homeless.co.il/rent/apartments/"
            "?city=%D7%AA%D7%9C+%D7%90%D7%91%D7%99%D7%91&rooms=2&price_max=8000"
        )
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # get first listing href
        href = None
        rows = await page.query_selector_all('tr[type="ad"]')
        for row in rows:
            details_td = await row.query_selector("td.details")
            if details_td:
                link = await details_td.query_selector("a")
                if link:
                    href = await link.get_attribute("href")
                    break

        if not href:
            print("  [Homeless] no listing link found")
            return

        url = href if href.startswith("http") else f"https://www.homeless.co.il{href}"
        print(f"  [Homeless] visiting {url}")
        text, nd = await get_page_text(page, url, wait_ms=2000)
        await dump("homeless_detail", url, text, nd)
    finally:
        await ctx.close()
        await browser.close()


# ── Komo ──────────────────────────────────────────────────────────────────────
async def inspect_komo(pw) -> None:
    print("\n[Komo] visiting search page...")
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(user_agent=UA, locale="he-IL")
    page = await ctx.new_page()
    try:
        search_url = (
            "https://www.komo.co.il/code/nadlan/apartments-for-rent.asp"
            "?nehes=1&cityName=%D7%AA%D7%9C+%D7%90%D7%91%D7%99%D7%91+%D7%99%D7%A4%D7%95"
        )
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        link_el = await page.query_selector("a.tdKotarotInner")
        href = await link_el.get_attribute("href") if link_el else None
        if not href:
            print("  [Komo] no listing link found")
            return

        url = href if href.startswith("http") else f"https://www.komo.co.il{href}"
        print(f"  [Komo] visiting {url}")
        text, nd = await get_page_text(page, url, wait_ms=2000)
        await dump("komo_detail", url, text, nd)
    finally:
        await ctx.close()
        await browser.close()


# ── Homeland ──────────────────────────────────────────────────────────────────
async def inspect_homeland(pw) -> None:
    print("\n[Homeland] visiting search page...")
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(user_agent=UA, locale="he-IL")
    page = await ctx.new_page()
    try:
        search_url = (
            "https://www.homeland.co.il/location/"
            "%D7%AA%D7%9C-%D7%90%D7%91%D7%99%D7%91-%D7%99%D7%A4%D7%95/"
        )
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        link_el = await page.query_selector("a.card-link")
        href = await link_el.get_attribute("href") if link_el else None
        if not href:
            print("  [Homeland] no card-link found")
            return

        url = href if href.startswith("http") else f"https://www.homeland.co.il{href}"
        print(f"  [Homeland] visiting {url}")
        text, nd = await get_page_text(page, url, wait_ms=2000)
        await dump("homeland_detail", url, text, nd)
    finally:
        await ctx.close()
        await browser.close()


# ── Ashtrom ───────────────────────────────────────────────────────────────────
async def inspect_ashtrom(pw) -> None:
    print("\n[Ashtrom] visiting listings page...")
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(user_agent=UA, locale="he-IL")
    page = await ctx.new_page()
    try:
        await page.goto(
            "https://www.ashtromresidencesforrent.co.il/apartments-4-rent",
            wait_until="domcontentloaded", timeout=30000,
        )
        await page.wait_for_timeout(3000)

        # expand accordions
        for s in await page.query_selector_all('[class*="RentAccordion-StyledAccordionSummary"]'):
            try:
                await s.click()
                await page.wait_for_timeout(500)
            except Exception:
                pass
        await page.wait_for_timeout(1000)

        link_el = await page.query_selector('[class*="RentAccordionInner-StyledLink"]')
        href = await link_el.get_attribute("href") if link_el else None
        if not href:
            print("  [Ashtrom] no StyledLink found")
            return

        url = href if href.startswith("http") else f"https://www.ashtromresidencesforrent.co.il/{href.lstrip('/')}"
        print(f"  [Ashtrom] visiting {url}")
        text, nd = await get_page_text(page, url, wait_ms=3000)
        await dump("ashtrom_detail", url, text, nd)
    finally:
        await ctx.close()
        await browser.close()


async def main() -> None:
    async with async_playwright() as pw:
        for fn in [inspect_yad2, inspect_homeless, inspect_komo, inspect_homeland, inspect_ashtrom]:
            try:
                await fn(pw)
            except Exception as exc:
                print(f"  ERROR in {fn.__name__}: {exc}")

    print(f"\nAll output saved to: {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
