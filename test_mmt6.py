import sys, os, io, re, time, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

hotel_id = "202108201551263611"

with sync_playwright() as p:
    # Use new headless mode (not old headless) - looks more like real browser
    browser = p.chromium.launch(
        headless=True,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
        ]
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        viewport={"width": 412, "height": 915},
        is_mobile=True,
        java_script_enabled=True,
    )
    page = context.new_page()

    # Remove webdriver flag
    page.add_init_script("delete Object.getPrototypeOf(navigator).webdriver")

    url = f"https://www.makemytrip.com/hotels/hotel-details/?hotelId={hotel_id}&_uCurrency=INR&checkin=07202026&checkout=07212026&city=CTDEL&country=IN&roomStayQualifier=2e0e&locusId=CTDEL&locusType=city"
    print(f"Loading...")
    try:
        page.goto(url, timeout=30000, wait_until="networkidle")
    except:
        pass
    time.sleep(6)

    content = page.content()
    print(f"Page length: {len(content)}")

    if len(content) > 500:
        # Search for rating data
        for pat, name in [
            (r'"ratingValue"\s*:\s*"?(\d+\.?\d*)"?', 'ratingValue'),
            (r'"overallRating"\s*:\s*"?(\d+\.?\d*)"?', 'overallRating'),
            (r'"userRating"\s*:\s*"?(\d+\.?\d*)"?', 'userRating'),
            (r'"guestRating"\s*:\s*"?(\d+\.?\d*)"?', 'guestRating'),
        ]:
            m = re.findall(pat, content)
            valid = [x for x in m if 1 <= float(x) <= 5]
            if valid:
                print(f"  {name}: {valid[:3]}")

        for pat, name in [
            (r'"reviewCount"\s*:\s*"?(\d+)"?', 'reviewCount'),
            (r'"ratingCount"\s*:\s*"?(\d+)"?', 'ratingCount'),
        ]:
            m = re.findall(pat, content)
            valid = [x for x in m if int(x) > 0]
            if valid:
                print(f"  {name}: {valid[:3]}")

        title_match = re.search(r'"hotelName"\s*:\s*"([^"]+)"', content)
        if title_match:
            print(f"  Hotel: {title_match.group(1)}")
    else:
        print("Page blocked - trying headed mode as fallback...")
        browser.close()
        # Headed mode works
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            viewport={"width": 412, "height": 915},
            is_mobile=True,
        )
        page = context.new_page()
        page.add_init_script("delete Object.getPrototypeOf(navigator).webdriver")
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
        except:
            pass
        time.sleep(6)
        content = page.content()
        print(f"Headed page length: {len(content)}")
        for pat, name in [
            (r'"ratingValue"\s*:\s*"?(\d+\.?\d*)"?', 'ratingValue'),
            (r'"userRating"\s*:\s*"?(\d+\.?\d*)"?', 'userRating'),
            (r'"reviewCount"\s*:\s*"?(\d+)"?', 'reviewCount'),
        ]:
            m = re.findall(pat, content)
            valid = [x for x in m if float(x) >= 1]
            if valid:
                print(f"  {name}: {valid[:5]}")
        title_match = re.search(r'"hotelName"\s*:\s*"([^"]+)"', content)
        if title_match:
            print(f"  Hotel: {title_match.group(1)}")

    browser.close()
