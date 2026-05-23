import sys, os, io, re, time, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

hotel_id = "202108201551263611"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        viewport={"width": 412, "height": 915},
        is_mobile=True,
    )
    page = context.new_page()

    url = f"https://www.makemytrip.com/hotels/hotel-details/?hotelId={hotel_id}&_uCurrency=INR&checkin=07202026&checkout=07212026&city=CTDEL&country=IN&roomStayQualifier=2e0e&locusId=CTDEL&locusType=city"
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
    except:
        pass
    time.sleep(6)

    content = page.content()
    print(f"Page length: {len(content)}")

    # More specific patterns for MMT
    # Overall rating is usually like "4.2" displayed prominently
    # Look for ratingValue in JSON-LD or structured data
    patterns = [
        (r'"ratingValue"\s*:\s*"?(\d+\.?\d*)"?', 'ratingValue (JSON-LD)'),
        (r'"overallRating"\s*:\s*"?(\d+\.?\d*)"?', 'overallRating'),
        (r'"hotelRating"\s*:\s*"?(\d+\.?\d*)"?', 'hotelRating'),
        (r'"userRating"\s*:\s*"?(\d+\.?\d*)"?', 'userRating'),
        (r'"guestRating"\s*:\s*"?(\d+\.?\d*)"?', 'guestRating'),
        (r'"avgRating"\s*:\s*"?(\d+\.?\d*)"?', 'avgRating'),
        (r'"reviewRating"\s*:\s*"?(\d+\.?\d*)"?', 'reviewRating'),
        (r'"mmtRating"\s*:\s*"?(\d+\.?\d*)"?', 'mmtRating'),
        (r'"ratingScore"\s*:\s*"?(\d+\.?\d*)"?', 'ratingScore'),
    ]
    for pat, name in patterns:
        m = re.findall(pat, content)
        if m:
            # Filter to reasonable values (1-5 range for MMT)
            valid = [x for x in m if 1 <= float(x) <= 5]
            if valid:
                print(f"  {name}: {valid[:5]}")

    # Review count
    review_patterns = [
        (r'"reviewCount"\s*:\s*"?(\d+)"?', 'reviewCount'),
        (r'"ratingCount"\s*:\s*"?(\d+)"?', 'ratingCount'),
        (r'"totalRatingCount"\s*:\s*"?(\d+)"?', 'totalRatingCount'),
        (r'"totalReview"\s*:\s*"?(\d+)"?', 'totalReview'),
    ]
    for pat, name in review_patterns:
        m = re.findall(pat, content)
        if m:
            valid = [x for x in m if int(x) > 0]
            if valid:
                print(f"  {name}: {valid[:5]}")

    # Also look for the hotel name to confirm we're on the right page
    title_match = re.search(r'"hotelName"\s*:\s*"([^"]+)"', content)
    if title_match:
        print(f"\n  Hotel name: {title_match.group(1)}")

    browser.close()
