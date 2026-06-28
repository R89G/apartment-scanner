"""Inspect real Homeless detail page DOM — saves full HTML to file for inspection."""
import asyncio
import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from scrapers.homeless import HOMELESS_URL, _HOMELESS_DETAIL_JS

OUT_DIR = os.path.join(os.path.dirname(__file__), "data")

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)  # visible to avoid CF block
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="he-IL",
            viewport={"width": 1280, "height": 900},
        )

        # Collect URLs from search page
        page = await ctx.new_page()
        await page.goto(HOMELESS_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        rows = await page.query_selector_all('tr[type="ad"]')
        urls = []
        for row in rows:
            details_td = await row.query_selector("td.details")
            link_el = await details_td.query_selector("a") if details_td else None
            if link_el:
                href = await link_el.get_attribute("href") or ""
                url = href if href.startswith("http") else f"https://www.homeless.co.il{href}"
                urls.append(url)
            if len(urls) >= 4:
                break
        await page.close()
        print(f"Got {len(urls)} URLs\n")

        tested = 0
        for url in urls:
            if tested >= 2:
                break
            await asyncio.sleep(5)
            p = await ctx.new_page()
            try:
                await p.goto(url, wait_until="domcontentloaded", timeout=30000)
                await p.wait_for_timeout(3000)

                body_text = await p.inner_text("body")
                if "cloudflare" in body_text.lower() or "אימות אבטחה" in body_text:
                    print(f"BLOCKED: {url}")
                    await p.close()
                    continue

                print(f"=== URL: {url} ===")

                # Save full HTML
                html = await p.content()
                html_path = os.path.join(OUT_DIR, f"homeless_detail_{tested+1}.html")
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"HTML saved to: {html_path}")

                # Print first 4000 chars of body text
                print("--- BODY TEXT (first 4000 chars) ---")
                print(body_text[:4000])
                print()

                # Count key selectors
                counts = await p.evaluate("""() => ({
                    IconOption: document.querySelectorAll('div.IconOption').length,
                    IconOptionOn: document.querySelectorAll('div.IconOption.on').length,
                    IconOptionOff: document.querySelectorAll('div.IconOption.off').length,
                    imgItemsAd: document.querySelectorAll('img.itemsAd').length,
                    h3_all: document.querySelectorAll('h3').length,
                })""")
                print(f"Selector counts: {counts}")
                print()

                # Dump all IconOption elements
                icon_data = await p.evaluate("""() => {
                    return Array.from(document.querySelectorAll('div.IconOption')).map((el, i) => ({
                        index: i,
                        classes: el.className,
                        text: el.innerText.trim().substring(0, 80),
                        outerHTML: el.outerHTML.substring(0, 400)
                    }));
                }""")
                print(f"--- All div.IconOption ({len(icon_data)} found) ---")
                for el in icon_data:
                    print(f"  [{el['index']}] classes={el['classes']!r} text={el['text']!r}")
                    print(f"       html: {el['outerHTML']}")
                print()

                # Run our actual extraction JS
                result = await p.evaluate(_HOMELESS_DETAIL_JS)
                print(f"--- _HOMELESS_DETAIL_JS result ---")
                print(f"  {result}")
                print()

                # Find floor/size keywords anywhere
                kw_hits = await p.evaluate("""() => {
                    const hits = [];
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let n;
                    while (n = walker.nextNode()) {
                        const t = n.textContent.trim();
                        if (!t) continue;
                        if (/קומה|מ"ר|מ'ר|מרתף|מתוך|מעלית|חניה|משופצ/.test(t)) {
                            const p = n.parentElement;
                            const gp = p && p.parentElement;
                            hits.push({
                                text: t,
                                parentTag: p ? p.tagName : '',
                                parentClass: p ? p.className : '',
                                gpTag: gp ? gp.tagName : '',
                                gpClass: gp ? gp.className : '',
                                gpHTML: gp ? gp.outerHTML.substring(0, 300) : ''
                            });
                        }
                    }
                    return hits;
                }""")
                print(f"--- Text nodes with floor/size/amenity keywords ({len(kw_hits)} found) ---")
                for h in kw_hits:
                    print(f"  text={h['text']!r}")
                    print(f"    parent: <{h['parentTag']} class={h['parentClass']!r}>")
                    print(f"    grandparent: <{h['gpTag']} class={h['gpClass']!r}>")
                    print(f"    gpHTML: {h['gpHTML']}")
                    print()

                tested += 1

            except Exception as e:
                print(f"ERROR for {url}: {e}")
            finally:
                await p.close()

        await ctx.close()
        await browser.close()
        print(f"\nDone. Tested {tested} pages.")

if __name__ == "__main__":
    asyncio.run(main())
