import sys, os
os.environ['PYTHONIOENCODING'] = 'utf-8'
from playwright.sync_api import sync_playwright
import re, time

# Try using B.com ID directly
bcom_id = "8062182"
url = f"https://www.booking.com/hotel/in/.en-gb.html?aid=304142&label=gen173nr-1FCAEoggI46AdIM1gEaFCIAQGYAQm4ARfIAQzYAQHoAQH4AQuIAgGoAgO4AqTXtbwGwAIB0gIkMjVjODVkMTMtMGI5YS00ZDViLWJhNjgtYzgxMWRlOTk4N2Rm2AIG4AIB&sid=test&dest_id={bcom_id}&dest_type=hotel"

# Actually try the hotel page with ID approach
url2 = f"https://www.booking.com/hotel/in/index.html?hotel_id={bcom_id}"

# Try third link from CSV which has a simpler URL
url3 = "https://www.booking.com/hotel/in/oyo-79963-collection-o-tisya.html"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_extra_http_headers({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    })

    print(f"Testing: {url3}")
    page.goto(url3, timeout=30000, wait_until="domcontentloaded")
    time.sleep(4)
    print(f"Final URL: {page.url}")
    content = page.content()

    # Check for rating in JSON-LD or meta
    ratings = re.findall(r'"ratingValue"[:\s]*"?(\d+\.?\d*)', content)
    print(f"ratingValue: {ratings}")
    scores = re.findall(r'"reviewScore"[:\s]*"?(\d+\.?\d*)', content)
    print(f"reviewScore: {scores}")
    counts = re.findall(r'"reviewCount"[:\s]*"?(\d+)', content)
    print(f"reviewCount: {counts}")

    # Also try generic
    scored = re.findall(r'Scored\s+(\d+\.?\d*)', content)
    print(f"Scored: {scored}")

    browser.close()
