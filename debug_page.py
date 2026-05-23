import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright
import time

url = "https://www.booking.com/hotel/in/capital-o-84509-ritz-plaza.en-gb.html?aid=964694&app_hotel_id=8062182"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(5)
    title = page.title()
    print(f"Title: {title}")
    print(f"URL: {page.url}")
    # Save snippet of page
    content = page.content()
    # Look for rating patterns
    import re
    ratings = re.findall(r'(\d\.\d)\s*/?\s*(?:10|5)', content)
    print(f"Ratings found in HTML: {ratings[:5]}")
    reviews = re.findall(r'([\d,]+)\s*reviews?', content, re.IGNORECASE)
    print(f"Review counts found: {reviews[:5]}")
    # Save first 5000 chars for inspection
    with open("C:/Users/CS05180/Desktop/scrape-ratings/page_debug.html", "w", encoding="utf-8") as f:
        f.write(content[:20000])
    print("Saved page_debug.html")
    browser.close()
