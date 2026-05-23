import sys, os, io, csv, time, re
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
from playwright.sync_api import sync_playwright

INPUT_CSV = Path("C:/Users/CS05180/Desktop/scrape-ratings/input.csv")
OUTPUT_CSV = Path.home() / "Downloads" / f"ratings_output_{int(time.time())}.csv"

def clean_booking_url(url):
    match = re.match(r'(https://www\.booking\.com/hotel/[^?;]+)', url)
    return match.group(1) if match else url

def scrape_booking(page, url):
    clean_url = clean_booking_url(url)
    page.goto(clean_url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(4)
    rating, review_count = None, None
    content = page.content()
    if '/hotel/' not in page.url:
        return None, None
    for pat in [r'"ratingValue"[:\s]*"?(\d+\.?\d*)', r'Scored\s+(\d+\.?\d*)', r'"score":(\d+\.?\d*)']:
        m = re.search(pat, content)
        if m:
            val = float(m.group(1))
            if 1 <= val <= 10:
                rating = str(val)
                break
    for pat in [r'"reviewCount"[:\s]*"?(\d+)', r'([\d,]+)\s*reviews?']:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            review_count = m.group(1).replace(",", "")
            if int(review_count) > 0:
                break
    return rating, review_count

links = []
with open(INPUT_CSV, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        url = row.get('Link', '').strip()
        name = row.get('Hotel Name', '').strip()
        if url:
            links.append({'name': name, 'url': url})

print(f"Total links: {len(links)}, testing first 5")
links = links[:5]

results = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_extra_http_headers({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    })
    for i, item in enumerate(links):
        print(f"[{i+1}/5] {item['name']}...", end=" ", flush=True)
        try:
            rating, count = scrape_booking(page, item['url'])
        except Exception as e:
            rating, count = None, None
            print(f"ERR:{e}", end=" ")
        print(f"Rating:{rating or 'N/A'} Reviews:{count or 'N/A'}")
        results.append({'name': item['name'], 'url': item['url'], 'rating': rating or 'N/A', 'review_count': count or 'N/A'})
        time.sleep(1)
    browser.close()

with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['name', 'url', 'rating', 'review_count'])
    writer.writeheader()
    writer.writerows(results)
print(f"\nSaved: {OUTPUT_CSV}")
