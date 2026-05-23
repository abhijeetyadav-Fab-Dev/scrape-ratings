import sys, os, io, re, time, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import requests

hotel_id = "202108201551263611"

# MMT internal API endpoints to try
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# Try 1: MMT hotel detail API
urls_to_try = [
    f"https://www.makemytrip.com/api/hotel/details?hotelId={hotel_id}",
    f"https://hbe.makemytrip.com/api/hotel/details?hotelId={hotel_id}",
    f"https://www.makemytrip.com/hotels/hotel_review/ajax/getReviewRating?hotelId={hotel_id}",
    f"https://hbe.makemytrip.com/api/hotelReview?hotelId={hotel_id}",
    f"https://www.makemytrip.com/api/hotels/review/summary/{hotel_id}",
]

for url in urls_to_try:
    print(f"\nTrying: {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 200:
            try:
                data = resp.json()
                print(f"  JSON keys: {list(data.keys())[:10]}")
                print(f"  Sample: {json.dumps(data, indent=2)[:500]}")
            except:
                print(f"  Not JSON. First 200 chars: {resp.text[:200]}")
        else:
            print(f"  Response: {resp.text[:200]}")
    except Exception as e:
        print(f"  Error: {e}")

# Try 2: POST request like mobile app
print("\n\n--- POST approach ---")
post_url = "https://www.makemytrip.com/hotels/hotel-details/"
payload = {
    "hotelId": hotel_id,
    "checkin": "07202026",
    "checkout": "07212026",
    "roomStayQualifier": "2e0e",
    "city": "CTDEL",
    "country": "IN"
}
try:
    resp = requests.post(post_url, json=payload, headers=headers, timeout=10)
    print(f"POST Status: {resp.status_code}")
    if resp.status_code == 200:
        text = resp.text[:1000]
        # Look for rating in response
        m = re.search(r'"rating"[:\s]*"?(\d+\.?\d*)', text)
        if m:
            print(f"  Rating found: {m.group(1)}")
        m = re.search(r'"reviewCount"[:\s]*"?(\d+)', text)
        if m:
            print(f"  Review count: {m.group(1)}")
        print(f"  First 300: {text[:300]}")
except Exception as e:
    print(f"  Error: {e}")
