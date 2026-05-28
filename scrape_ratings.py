import csv
import sys
import os
import io
import time
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

# If running as a PyInstaller bundle, force Playwright to use the system-wide browser installation
if getattr(sys, 'frozen', False):
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

INPUT_CSV = Path(" ".join(sys.argv[1:])) if len(sys.argv) > 1 else Path("links.csv")
OUTPUT_CSV = Path.home() / "Downloads" / f"ratings_output_{int(time.time())}.csv"


def clean_booking_url(url):
    """Strip tracking params, keep just the hotel path"""
    match = re.match(r'(https://www\.booking\.com/hotel/[^?;]+)', url)
    if match:
        return match.group(1)
    return url


def scrape_booking(page, url):
    clean_url = clean_booking_url(url)
    page.goto(clean_url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(4)

    rating = None
    review_count = None
    content = page.content()

    # Check if we landed on the actual hotel page
    current_url = page.url
    if '/hotel/' not in current_url:
        return None, None

    # Try selectors first
    try:
        el = page.query_selector('[data-testid="review-score-component"]')
        if el:
            text = el.inner_text()
            m = re.search(r'(\d+\.?\d*)', text)
            if m:
                rating = m.group(1)
    except:
        pass

    # Fallback: regex on page content for review score
    if not rating:
        # Look for "Scored X.X" or review score patterns
        patterns = [
            r'Scored\s+(\d+\.?\d*)',
            r'"reviewScore":(\d+\.?\d*)',
            r'"score":(\d+\.?\d*)',
            r'review_score.*?(\d+\.?\d+)',
        ]
        for pat in patterns:
            m = re.search(pat, content)
            if m:
                val = float(m.group(1))
                if 1 <= val <= 10:
                    rating = str(val)
                    break

    # Review count
    patterns_count = [
        r'"reviewCount":(\d+)',
        r'"numberOfReviews":(\d+)',
        r'([\d,]+)\s*reviews?',
        r'([\d,]+)\s*ratings?',
    ]
    for pat in patterns_count:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            review_count = m.group(1).replace(",", "")
            if int(review_count) > 0:
                break

    return rating, review_count


def scrape_mmt(page, url):
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(4)
    rating = None
    review_count = None
    content = page.content()

    patterns = [
        r'"ratingValue"[:\s]+"?(\d+\.?\d*)',
        r'"overallRating"[:\s]+"?(\d+\.?\d*)',
        r'(\d\.\d)/5',
    ]
    for pat in patterns:
        m = re.search(pat, content)
        if m:
            rating = m.group(1)
            break

    m = re.search(r'([\d,]+)\s*(?:rating|review)s?', content, re.IGNORECASE)
    if m:
        review_count = m.group(1).replace(",", "")

    return rating, review_count


def main():
    if not INPUT_CSV.exists():
        print(f"ERROR: Input CSV not found: {INPUT_CSV}")
        print("Usage: python scrape_ratings.py <path_to_csv>")
        sys.exit(1)

    links = []
    with open(INPUT_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        link_col = None
        for h in reader.fieldnames:
            if h.lower().strip() in ('link', 'url', 'links', 'urls'):
                link_col = h
                break
        if not link_col:
            link_col = reader.fieldnames[0]

        name_col = None
        for h in reader.fieldnames:
            if h.lower().strip() in ('hotel name', 'name', 'hotel', 'property'):
                name_col = h
                break

        for row in reader:
            url = row[link_col].strip()
            if url:
                name = row.get(name_col, '').strip() if name_col else ''
                links.append({'name': name, 'url': url})

    print(f"Found {len(links)} links to scrape")

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        })

        for i, item in enumerate(links):
            url = item['url']
            name = item['name'] or f"Property {i+1}"
            print(f"[{i+1}/{len(links)}] {name}...", end=" ")

            try:
                if 'booking.com' in url:
                    rating, review_count = scrape_booking(page, url)
                elif 'makemytrip' in url or 'mmt' in url:
                    rating, review_count = scrape_mmt(page, url)
                else:
                    rating, review_count = None, None
            except Exception as e:
                rating, review_count = None, None
                print(f"ERROR: {e}")

            print(f"Rating: {rating or 'N/A'}, Reviews: {review_count or 'N/A'}")
            results.append({
                'name': name,
                'url': url,
                'rating': rating or 'N/A',
                'review_count': review_count or 'N/A'
            })
            time.sleep(1)

        browser.close()

    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['name', 'url', 'rating', 'review_count'])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nDone! Results saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
