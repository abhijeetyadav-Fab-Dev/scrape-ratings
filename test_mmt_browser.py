import sys, os, io, re, time, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

hotel_id = "202108201551263611"

# Use a real browser with network interception to catch API calls
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled'])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    page = context.new_page()

    captured_responses = []

    def handle_response(response):
        url = response.url
        if 'review' in url.lower() or 'rating' in url.lower() or 'hotel' in url.lower():
            try:
                if 'json' in response.headers.get('content-type', ''):
                    captured_responses.append({'url': url, 'status': response.status})
            except:
                pass

    page.on("response", handle_response)

    # Navigate to hotel page with proper format
    url = f"https://www.makemytrip.com/hotels/hotel-details/?hotelId={hotel_id}&checkin=07202026&checkout=07212026&roomStayQualifier=2e0e&locusId=CTDEL&locusType=city&city=CTDEL&country=IN&currency=INR"
    print(f"Loading: {url[:80]}...")

    try:
        page.goto(url, timeout=30000, wait_until="networkidle")
    except:
        pass
    time.sleep(5)

    print(f"Title: {page.title()}")
    print(f"Current URL: {page.url[:80]}")

    # Check page content for ratings
    content = page.content()
    print(f"\nPage length: {len(content)}")

    # Search for rating patterns in page
    patterns = [
        (r'"overallRating"[:\s]*"?(\d+\.?\d*)', 'overallRating'),
        (r'"ratingValue"[:\s]*"?(\d+\.?\d*)', 'ratingValue'),
        (r'"rating"[:\s]*(\d+\.?\d*)', 'rating'),
        (r'"reviewRating"[:\s]*"?(\d+\.?\d*)', 'reviewRating'),
        (r'(\d\.\d)\s*/\s*5', 'X/5'),
        (r'"userRating"[:\s]*"?(\d+\.?\d*)', 'userRating'),
        (r'"guestRating"[:\s]*"?(\d+\.?\d*)', 'guestRating'),
    ]
    for pat, name in patterns:
        matches = re.findall(pat, content)
        if matches:
            print(f"  {name}: {matches[:3]}")

    review_patterns = [
        (r'"reviewCount"[:\s]*"?(\d+)', 'reviewCount'),
        (r'"totalReviews?"[:\s]*"?(\d+)', 'totalReviews'),
        (r'"ratingCount"[:\s]*"?(\d+)', 'ratingCount'),
        (r'(\d[\d,]*)\s*ratings?', 'X ratings'),
        (r'(\d[\d,]*)\s*reviews?', 'X reviews'),
    ]
    for pat, name in review_patterns:
        matches = re.findall(pat, content, re.IGNORECASE)
        if matches:
            print(f"  {name}: {matches[:3]}")

    print(f"\nCaptured {len(captured_responses)} JSON responses:")
    for r in captured_responses[:10]:
        print(f"  [{r['status']}] {r['url'][:100]}")

    # Save page for analysis
    with open("C:/Users/CS05180/Desktop/scrape-ratings/mmt_page.html", "w", encoding="utf-8") as f:
        f.write(content[:50000])

    time.sleep(2)
    browser.close()
