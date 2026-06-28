"""Inspect OnMap API slug/id fields and test URL formats."""
import asyncio
import ssl
import sys
sys.stdout.reconfigure(encoding="utf-8")
import aiohttp

_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl.CERT_NONE

ONMAP_API = "https://phoenix.onmap.co.il/v1/properties/mixed_search"
PARAMS = {
    "option": "rent,rent-short",
    "section": "residence",
    "city": "tel-aviv-yafo",
    "is_mobile": "false",
    "$sort": "-search_date",
    "$limit": "5",
    "country": "Israel",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.onmap.co.il/",
    "Origin": "https://www.onmap.co.il",
}

URL_FORMATS = [
    "https://www.onmap.co.il/property/{slug}",
    "https://www.onmap.co.il/properties/{slug}",
    "https://www.onmap.co.il/rent/{slug}",
    "https://www.onmap.co.il/ad/{slug}",
    "https://www.onmap.co.il/{slug}",
]

async def main():
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        # Fetch 5 listings
        async with session.get(ONMAP_API, params=PARAMS, ssl=_SSL_CONTEXT, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            data = await resp.json(content_type=None)

        items = data.get("data", []) if isinstance(data, dict) else data
        print(f"Got {len(items)} items\n")

        for i, item in enumerate(items[:3]):
            slug = item.get("slug")
            prop_id = item.get("id")
            short_id = item.get("short_id")
            print(f"--- Item {i+1} ---")
            print(f"  id:       {prop_id}")
            print(f"  slug:     {slug}")
            print(f"  short_id: {short_id}")
            print(f"  all keys: {list(item.keys())}")
            print()

            # Test each URL format
            test_slug = slug or prop_id
            for fmt in URL_FORMATS:
                url = fmt.format(slug=test_slug)
                try:
                    async with session.get(url, ssl=_SSL_CONTEXT, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=False) as r:
                        final = r.headers.get("Location", "")
                        print(f"  {r.status} {url}")
                        if final:
                            print(f"       -> redirects to: {final}")
                except Exception as e:
                    print(f"  ERR {url}: {e}")
            print()

if __name__ == "__main__":
    asyncio.run(main())
