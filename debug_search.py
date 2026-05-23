import sys, os, io, re, time
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

query = "FabHotel Marble Arch Karol Bagh"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_extra_http_headers({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    })

    # Test booking.com search
    search_url = f"https://www.booking.com/searchresults.en-gb.html?ss={query.replace(' ', '+')}"
    print(f"Searching: {search_url}")
    page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
    time.sleep(4)
    print(f"Final URL: {page.url}")
    print(f"Title: {page.title()}")

    # Check for property cards
    cards = page.query_selector_all('[data-testid="property-card"]')
    print(f"Property cards found: {len(cards)}")

    # Try title links
    links = page.query_selector_all('a[data-testid="title-link"]')
    print(f"Title links: {len(links)}")
    for l in links[:3]:
        href = l.get_attribute('href')
        text = l.inner_text().strip()
        print(f"  {text}: {href[:80] if href else 'None'}")

    # Try any hotel link
    hotel_links = page.query_selector_all('a[href*="/hotel/"]')
    print(f"\nAll /hotel/ links: {len(hotel_links)}")
    for l in hotel_links[:5]:
        href = l.get_attribute('href')
        print(f"  {href[:100] if href else 'None'}")

    browser.close()
