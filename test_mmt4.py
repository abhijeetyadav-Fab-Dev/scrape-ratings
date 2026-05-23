import sys, os, io, re, time, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

hotel_id = "202108201551263611"

with sync_playwright() as p:
    # Emulate mobile device - MMT mobile site often has less protection
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        viewport={"width": 412, "height": 915},
        is_mobile=True,
    )
    page = context.new_page()

    api_data = []
    def capture(response):
        try:
            url = response.url
            if response.status == 200 and len(response.url) > 50:
                ct = response.headers.get('content-type', '')
                if 'json' in ct or 'javascript' in ct:
                    try:
                        body = response.text()
                        if 'rating' in body.lower() or 'review' in body.lower():
                            api_data.append({'url': url, 'body': body[:5000]})
                    except:
                        pass
        except:
            pass

    page.on("response", capture)

    # Try mobile MMT URL
    url = f"https://www.makemytrip.com/hotels/hotel-details/?hotelId={hotel_id}&_uCurrency=INR&checkin=07202026&checkout=07212026&city=CTDEL&country=IN&roomStayQualifier=2e0e&locusId=CTDEL&locusType=city"
    print(f"Loading mobile MMT...")
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"Navigation: {e}")

    time.sleep(8)
    print(f"Title: {page.title()}")
    content = page.content()
    print(f"Page length: {len(content)}")

    # Check if page has any visible content
    if len(content) > 500:
        for pat, name in [(r'(\d\.\d)\s*/\s*5', 'X/5'), (r'"rating"[:\s]*"?(\d+\.?\d*)', 'rating'), (r'"reviewCount"[:\s]*"?(\d+)', 'reviewCount')]:
            m = re.findall(pat, content)
            if m:
                print(f"  {name}: {m[:5]}")

    print(f"\nCaptured {len(api_data)} relevant API responses")
    for d in api_data[:5]:
        print(f"\n  URL: {d['url'][:100]}")
        print(f"  Body snippet: {d['body'][:300]}")

    # Also try: direct Google search for this hotel's MMT rating
    print("\n\n--- Google fallback ---")
    page.goto(f"https://www.google.com/search?q=makemytrip+hotel+{hotel_id}+rating+reviews", timeout=20000, wait_until="domcontentloaded")
    time.sleep(3)
    gcontent = page.content()
    m = re.search(r'(\d\.\d)\s*/\s*5', gcontent)
    if m:
        print(f"Google found rating: {m.group(1)}/5")
    m = re.search(r'([\d,]+)\s*reviews?', gcontent, re.IGNORECASE)
    if m:
        print(f"Google found reviews: {m.group(1)}")

    browser.close()
