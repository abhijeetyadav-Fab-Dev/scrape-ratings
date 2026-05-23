import sys, os, io, re, time, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

# Try the proper MMT hotel page URL format
hotel_id = "202108232109222620"
# MMT uses this format for direct hotel pages
url = f"https://www.makemytrip.com/hotels/hotel-listing?checkin=07192026&checkout=07202026&roomStayQualifier=2e0e&locusId=CTDEL&locusType=city&city=CTDEL&country=IN&hotelId={hotel_id}"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_extra_http_headers({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    })
    # Try Google search for MMT hotel
    search_url = f"https://www.google.com/search?q=site:makemytrip.com+hotel+{hotel_id}"
    page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
    time.sleep(2)
    print(f"Google results for MMT hotel ID {hotel_id}:")
    links = page.query_selector_all('a[href*="makemytrip.com"]')
    for l in links[:3]:
        print(f"  {l.get_attribute('href')}")

    # Alternative: search hotel name on MMT
    page.goto("https://www.makemytrip.com/hotels/", timeout=20000, wait_until="domcontentloaded")
    time.sleep(3)
    print(f"\nMMT home title: {page.title()}")
    print(f"MMT home URL: {page.url}")

    browser.close()
