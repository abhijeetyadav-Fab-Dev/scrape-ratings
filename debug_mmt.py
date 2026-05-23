import sys, os, io, re, time
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

url = "https://www.makemytrip.com/hotels/hotel-details/?hotelId=202108232109222620&city=abc&country=in&roomStayQualifier=2e0e&locusId=abc&locusType=city&currency=INR"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.set_extra_http_headers({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    })
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(5)
    print(f"Title: {page.title()}")
    print(f"URL: {page.url}")
    content = page.content()

    # Look for rating patterns
    ratings = re.findall(r'"ratingValue"[:\s]*"?(\d+\.?\d*)', content)
    print(f"ratingValue: {ratings}")

    # MMT specific patterns
    mmt_rating = re.findall(r'"overallRating"[:\s]*"?(\d+\.?\d*)', content)
    print(f"overallRating: {mmt_rating}")

    scored = re.findall(r'(\d\.\d)\s*/\s*5', content)
    print(f"X/5 ratings: {scored}")

    reviews = re.findall(r'(\d[\d,]*)\s*(?:Rating|Review)s?', content, re.IGNORECASE)
    print(f"Review counts: {reviews[:5]}")

    # Save snippet
    with open("C:/Users/CS05180/Desktop/scrape-ratings/mmt_debug.html", "w", encoding="utf-8") as f:
        f.write(content[:30000])
    print("Saved mmt_debug.html")

    time.sleep(3)
    browser.close()
