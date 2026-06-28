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
sslctx = ssl.create_default_context()
sslctx.check_hostname = False
sslctx.verify_mode = ssl.CERT_NONE

# Get full marker data
map_url = (
    "https://gw.yad2.co.il/realestate-feed/rent/map"
    "?city=5000&area=1&region=3&property=1"
    "&bBox=32.03,34.74,32.12,34.83&zoom=13"
)
req = urllib.request.Request(map_url, headers={
    "User-Agent": UA,
    "Accept": "application/json",
})
with urllib.request.urlopen(req, timeout=15, context=sslctx) as resp:
    data = json.loads(resp.read().decode('utf-8'))

markers = data.get("data", {}).get("markers", [])
print(f"Total markers: {len(markers)}")

first = markers[0] if markers else {}
print(f"\n=== FIRST MARKER FULL DATA ===")
print(json.dumps(first, ensure_ascii=False, indent=2))
token = first.get("token")
print(f"\nToken: {token}")

# Print all keys and nested keys
def print_keys(d, prefix=""):
    if isinstance(d, dict):
        for k, v in d.items():
            print_keys(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(d, list):
        if d:
            print_keys(d[0], f"{prefix}[0]")
    else:
        print(f"  {prefix}: {repr(str(d)[:60])}")

print("\n=== MARKER FIELD PATHS ===")
print_keys(first)

# Try the listings feed (not map feed)
print("\n\n=== TRYING LISTINGS FEED ===")
list_url = (
    "https://gw.yad2.co.il/realestate-feed/rent"
    "?city=5000&area=1&region=3&property=1&page=1&pageSize=5"
)
req2 = urllib.request.Request(list_url, headers={
    "User-Agent": UA,
    "Accept": "application/json",
    "Referer": "https://www.yad2.co.il/realestate/rent",
})
try:
    with urllib.request.urlopen(req2, timeout=15, context=sslctx) as resp:
        list_data = json.loads(resp.read().decode('utf-8'))
    print(f"Listings API keys: {list(list_data.keys()) if isinstance(list_data, dict) else type(list_data)}")
    print(json.dumps(list_data, ensure_ascii=False)[:3000])
except Exception as e:
    print(f"Listings feed error: {e}")

# Try the feed-search-legacy endpoint
print("\n\n=== TRYING FEED-SEARCH-LEGACY ===")
fs_url = (
    "https://gw.yad2.co.il/feed-search-legacy/realestate/rent"
    "?city=5000&area=1&region=3&property=1&page=1&rows=5"
)
req3 = urllib.request.Request(fs_url, headers={
    "User-Agent": UA,
    "Accept": "application/json",
    "Referer": "https://www.yad2.co.il/realestate/rent",
})
try:
    with urllib.request.urlopen(req3, timeout=15, context=sslctx) as resp:
        fs_data = json.loads(resp.read().decode('utf-8'))
    print(f"Feed-search-legacy keys: {list(fs_data.keys()) if isinstance(fs_data, dict) else type(fs_data)}")

    # Try to get a token from this data and then fetch item
    items = fs_data.get("data", {}).get("feed", {}).get("feed_items", []) or \
            fs_data.get("data", {}).get("items", []) or \
            fs_data.get("feed", {}).get("feed_items", []) or []
    print(f"Items found: {len(items)}")
    if items:
        item0 = items[0]
        print(f"First item keys: {list(item0.keys()) if isinstance(item0, dict) else item0}")
        item_token = item0.get("token") or item0.get("id")
        if item_token:
            # Try to get full item
            print(f"\nItem token from feed: {item_token}")
            item_url = f"https://gw.yad2.co.il/feed-search-legacy/realestate/item/{item_token}"
            try:
                req4 = urllib.request.Request(item_url, headers={
                    "User-Agent": UA,
                    "Accept": "application/json",
                    "Referer": f"https://www.yad2.co.il/item/{item_token}",
                })
                with urllib.request.urlopen(req4, timeout=15, context=sslctx) as resp:
                    item_data = json.loads(resp.read().decode('utf-8'))
                print(f"Item detail keys: {list(item_data.keys())}")
                print(json.dumps(item_data, ensure_ascii=False)[:3000])
            except Exception as e:
                print(f"Item detail error: {e}")
    print(json.dumps(fs_data, ensure_ascii=False)[:2000])
except Exception as e:
    print(f"Feed-search-legacy error: {e}")
