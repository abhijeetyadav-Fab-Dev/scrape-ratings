import sys, os, io, re, time, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

hotel_id = "202108201551263611"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled'])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"}
    )
    page = context.new_page()

    api_data = []

    def capture(response):
        try:
            ct = response.headers.get('content-type', '')
            if 'json' in ct and response.status == 200:
                body = response.text()
                if len(body) > 100:
                    api_data.append({'url': response.url, 'body': body})
        except:
            pass

    page.on("response", capture)

    # Try the actual MMT detail page URL format used in production
    url = f"https://www.makemytrip.com/hotels/hotel-details/?hotelId={hotel_id}&checkin=07202026&checkout=07212026&city=CTDEL&country=IN&roomStayQualifier=2e0e&locusId=CTDEL&locusType=city&currency=INR&source=explore"

    try:
        page.goto(url, timeout=30000)
    except:
        pass

    time.sleep(8)

    print(f"Captured {len(api_data)} JSON responses")
    for i, d in enumerate(api_data):
        print(f"\n--- Response {i+1}: {d['url'][:100]} ---")
        body = d['body']
        # Look for rating/review info
        if 'rating' in body.lower() or 'review' in body.lower():
            print(f"  Contains rating/review data! Length: {len(body)}")
            # Try to parse
            try:
                j = json.loads(body)
                # Search recursively for rating
                def find_ratings(obj, path=""):
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            kl = k.lower()
                            if 'rating' in kl or 'review' in kl or 'score' in kl:
                                print(f"  {path}.{k} = {v}")
                            if isinstance(v, (dict, list)):
                                find_ratings(v, f"{path}.{k}")
                    elif isinstance(obj, list):
                        for idx, item in enumerate(obj[:3]):
                            find_ratings(item, f"{path}[{idx}]")
                find_ratings(j)
            except:
                # Search with regex
                for pat in [r'"rating"[:\s]*"?(\d+\.?\d*)', r'"reviewCount"[:\s]*(\d+)', r'"ratingCount"[:\s]*(\d+)']:
                    m = re.findall(pat, body)
                    if m:
                        print(f"  Regex match: {pat} -> {m[:3]}")

    browser.close()
