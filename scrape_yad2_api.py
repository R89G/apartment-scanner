import json
import sys
import io
import urllib.request
import urllib.parse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# First get a token from the map API
map_url = (
    "https://gw.yad2.co.il/realestate-feed/rent/map"
    "?city=5000&area=1&region=3&property=1"
    "&bBox=32.03,34.74,32.12,34.83&zoom=13"
)

req = urllib.request.Request(map_url, headers={"User-Agent": UA, "Accept": "application/json"})
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read().decode('utf-8'))

markers = data.get("data", {}).get("markers", [])
token = markers[0].get("token") if markers else None
print(f"Token: {token}")

# Try various Yad2 API endpoints
endpoints = [
    f"https://gw.yad2.co.il/item/{token}",
    f"https://gw.yad2.co.il/realestate-feed/rent/item/{token}",
    f"https://gw.yad2.co.il/feed-search-legacy/item/{token}",
    f"https://api.yad2.co.il/api/1/realestate/rent/{token}",
    f"https://gw.yad2.co.il/realestate-feed/item/{token}",
]

for ep in endpoints:
    try:
        req2 = urllib.request.Request(ep, headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Referer": "https://www.yad2.co.il/",
            "Origin": "https://www.yad2.co.il",
        })
        with urllib.request.urlopen(req2, timeout=10) as resp:
            raw = resp.read()
        item = json.loads(raw.decode('utf-8'))
        print(f"\n=== SUCCESS: {ep} ===")
        print(json.dumps(item, ensure_ascii=False)[:3000])
        break
    except Exception as e:
        print(f"FAIL {ep}: {e}")
