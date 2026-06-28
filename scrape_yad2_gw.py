import json
import sys
import io
import ssl
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Skip SSL verification
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# Get token
map_url = (
    "https://gw.yad2.co.il/realestate-feed/rent/map"
    "?city=5000&area=1&region=3&property=1"
    "&bBox=32.03,34.74,32.12,34.83&zoom=13"
)
req = urllib.request.Request(map_url, headers={
    "User-Agent": UA,
    "Accept": "application/json",
})
with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
    data = json.loads(resp.read().decode('utf-8'))
markers = data.get("data", {}).get("markers", [])
print(f"Total markers: {len(markers)}")
if markers:
    print(f"First marker keys: {list(markers[0].keys())}")
    print(f"First marker sample: {json.dumps(markers[0], ensure_ascii=False)[:500]}")

token = markers[0].get("token") if markers else None
print(f"\nToken: {token}")

# Try various GW API endpoints with skip SSL
endpoints = [
    f"https://gw.yad2.co.il/realestate-feed/rent/item?token={token}",
    f"https://gw.yad2.co.il/realestate-feed/item?token={token}",
    f"https://gw.yad2.co.il/item?token={token}",
    f"https://gw.yad2.co.il/realestate-feed/rent/{token}",
    f"https://gw.yad2.co.il/feed-search-legacy/realestate/items?token={token}",
]

for ep in endpoints:
    try:
        req2 = urllib.request.Request(ep, headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Referer": "https://www.yad2.co.il/",
        })
        with urllib.request.urlopen(req2, timeout=10, context=ctx) as resp:
            raw = resp.read()
        item = json.loads(raw.decode('utf-8'))
        print(f"\n=== SUCCESS: {ep} ===")
        print(json.dumps(item, ensure_ascii=False)[:3000])
        break
    except Exception as e:
        print(f"FAIL {ep}: {e}")
