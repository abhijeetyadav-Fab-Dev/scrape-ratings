import sys
sys.path.insert(0, 'C:/Users/CS05180/Desktop/scrape-ratings')
from scrape_ratings import scrape_booking
from playwright.sync_api import sync_playwright
import time

url = "https://www.booking.com/hotel/in/capital-o-84509-ritz-plaza.en-gb.html?aid=964694&app_hotel_id=8062182&checkin=2022-05-13&checkout=2022-05-14&from_sn=android&group_adults=2&group_children=0&label=Share-UzbwYX%401652419581&no_rooms=1&req_adults=2&req_children=0&room1=A%2CA"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    print("Scraping first link...")
    rating, count = scrape_booking(page, url)
    print(f"Rating: {rating}, Reviews: {count}")
    browser.close()
