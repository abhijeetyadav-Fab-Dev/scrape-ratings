import sys, os, io, re, time, pickle
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
from playwright.sync_api import sync_playwright

COOKIES_DIR = Path.home() / ".scrape-ratings"
MMT_COOKIES = COOKIES_DIR / "mmt_cookies.pkl"

hotel_id = "202108201551263611"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled'])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
    )
    with open(MMT_COOKIES, 'rb') as f:
        cookies = pickle.load(f)
    context.add_cookies(cookies)

    page = context.new_page()
    page.add_init_script("delete Object.getPrototypeOf(navigator).webdriver")

    url = f"https://www.makemytrip.com/hotels/hotel-details/?hotelId={hotel_id}&_uCurrency=INR&checkin=05192026&checkout=05202026&city=CTDEL&country=IN&roomStayQualifier=2e0e"
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
    except:
        pass
    time.sleep(4)
    for _ in range(3):
        page.evaluate("window.scrollBy(0, 800)")
        time.sleep(1)

    content = page.content()
    print(f"Page length: {len(content)}")

    # Look for 3.4 pattern in various forms
    patterns = [
        (r'3\.4', '3.4 literal'),
        (r'615', '615 literal'),
        (r'"userRating"', 'userRating key'),
        (r'"ratingValue"', 'ratingValue key'),
        (r'"overallRating"', 'overallRating key'),
        (r'"guestRating"', 'guestRating key'),
        (r'"reviewCount"', 'reviewCount key'),
        (r'"ratingCount"', 'ratingCount key'),
        (r'rating', 'rating anywhere'),
    ]
    for pat, name in patterns:
        m = re.findall(pat, content, re.IGNORECASE)
        print(f"  {name}: {len(m)} matches")

    # Find context around "3.4"
    for m in re.finditer(r'3\.4', content):
        start = max(0, m.start() - 80)
        end = min(len(content), m.end() + 80)
        snippet = content[start:end].replace('\n', ' ')
        print(f"\n  Context: ...{snippet}...")

    # Find context around "615"
    for m in re.finditer(r'615', content):
        start = max(0, m.start() - 80)
        end = min(len(content), m.end() + 80)
        snippet = content[start:end].replace('\n', ' ')
        if 'rating' in snippet.lower() or 'review' in snippet.lower():
            print(f"\n  615 Context: ...{snippet}...")

    browser.close()
