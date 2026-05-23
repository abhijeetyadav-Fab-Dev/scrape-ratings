import sys, os, io, re, time, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import requests

hotel_id = "202108201551263611"

session = requests.Session()

# Emulate the XHR call that MMT's React app makes
headers = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.makemytrip.com/hotels/hotel-details/",
    "Origin": "https://www.makemytrip.com",
    "X-Requested-With": "XMLHttpRequest",
}

# MMT uses this endpoint for hotel details (found in network tab)
api_urls = [
    f"https://mapi.makemytrip.com/clientbackend/entity/api/hotel/detail/v2?hotelId={hotel_id}&checkin=20260720&checkout=20260721&roomStayQualifier=2e0e&city=CTDEL&country=IN&currency=INR",
    f"https://mapi.makemytrip.com/clientbackend/entity/api/hotel/reviewRating?hotelId={hotel_id}",
    f"https://mapi.makemytrip.com/clientbackend/entity/api/hotel/detail?hotelId={hotel_id}&city=CTDEL&country=IN",
]

for url in api_urls:
    print(f"\nTrying: {url[:80]}...")
    try:
        resp = session.get(url, headers=headers, timeout=15)
        print(f"  Status: {resp.status_code}, Length: {len(resp.text)}")
        if resp.status_code == 200 and len(resp.text) > 100:
            try:
                data = resp.json()
                print(f"  Keys: {list(data.keys())[:10]}")
                # Search for rating
                text = json.dumps(data)
                for pat, name in [
                    (r'"userRating"\s*:\s*"?(\d+\.?\d*)"?', 'userRating'),
                    (r'"ratingValue"\s*:\s*"?(\d+\.?\d*)"?', 'ratingValue'),
                    (r'"overallRating"\s*:\s*"?(\d+\.?\d*)"?', 'overallRating'),
                    (r'"rating"\s*:\s*"?(\d+\.?\d*)"?', 'rating'),
                    (r'"reviewCount"\s*:\s*"?(\d+)"?', 'reviewCount'),
                    (r'"hotelName"\s*:\s*"([^"]+)"', 'hotelName'),
                ]:
                    m = re.search(pat, text)
                    if m:
                        print(f"  {name}: {m.group(1)}")
            except:
                print(f"  Not JSON: {resp.text[:200]}")
        elif resp.status_code != 200:
            print(f"  Body: {resp.text[:200]}")
    except Exception as e:
        print(f"  Error: {e}")
