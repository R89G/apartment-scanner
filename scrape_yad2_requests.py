import json
import sys
import io
import urllib.request
import urllib.parse
import http.cookiejar

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Create a cookie jar
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# Get token
map_url = (
    "https://gw.yad2.co.il/realestate-feed/rent/map"
    "?city=5000&area=1&region=3&property=1"
    "&bBox=32.03,34.74,32.12,34.83&zoom=13"
)
req = urllib.request.Request(map_url, headers={
    "User-Agent": UA,
    "Accept": "application/json",
    "Referer": "https://www.yad2.co.il/",
})
with opener.open(req, timeout=15) as resp:
    data = json.loads(resp.read().decode('utf-8'))
markers = data.get("data", {}).get("markers", [])
token = markers[0].get("token") if markers else None
print(f"Token: {token}")

listing_url = f"https://www.yad2.co.il/item/{token}"
print(f"Fetching: {listing_url}")

# Try to get listing page directly
req2 = urllib.request.Request(listing_url, headers={
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Referer": "https://www.yad2.co.il/realestate/rent",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-dest": "document",
})
try:
    with opener.open(req2, timeout=15) as resp:
        html = resp.read().decode('utf-8', errors='replace')
    print(f"Got {len(html)} chars")

    # Find __NEXT_DATA__
    import re
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        nd = m.group(1)
        print(f"\n__NEXT_DATA__ first 3000:\n{nd[:3000]}")
    else:
        print("No __NEXT_DATA__ found in HTML")

    # Look for captcha
    if "captcha" in html.lower() or "ShieldSquare" in html:
        print("CAPTCHA in HTML response")

    print(f"\nHTML snippet (first 2000):\n{html[:2000]}")
except Exception as e:
    print(f"Error: {e}")
