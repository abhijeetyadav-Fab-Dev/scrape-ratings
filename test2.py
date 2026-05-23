import sys, io, os
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.insert(0, 'C:/Users/CS05180/Desktop/scrape-ratings')
from scrape_ratings import scrape_booking, clean_booking_url
from playwright.sync_api import sync_playwright

url = "https://www.booking.com/hotel/in/capital-o-84509-ritz-plaza.en-gb.html?aid=964694&app_hotel_id=8062182"
print(f"Clean URL: {clean_booking_url(url)}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_extra_http_headers({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    })
    rating, count = scrape_booking(page, url)
    print(f"Rating: {rating}, Reviews: {count}")
    print(f"Final URL: {page.url}")
    browser.close()
