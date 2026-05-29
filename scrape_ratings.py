import csv
import sys
import os
import io
import time
import re
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
import requests

# If running as a PyInstaller bundle, force Playwright to use the system-wide browser installation
if getattr(sys, 'frozen', False):
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'

# Ensure stdout can handle Unicode characters
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

INPUT_CSV = Path(" ".join(sys.argv[1:])) if len(sys.argv) > 1 else Path("links.csv")
OUTPUT_CSV = Path.home() / "Downloads" / f"ratings_output_{int(time.time())}.csv"

# ---------- Helper Functions ----------

def clean_booking_url(url: str) -> str:
    """Strip tracking params, keep just the hotel path for Booking.com URLs."""
    match = re.match(r'(https://www\.booking\.com/hotel/[^?;]+)', url)
    return match.group(1) if match else url

def fast_requests_scrape(url: str) -> tuple:
    """Fallback fast scraper using requests for non‑JavaScript pages.
    Returns (rating, review_count) or (None, None) if parsing fails.
    """
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        })
        if resp.status_code != 200:
            return None, None
        html = resp.text
        # Very generic regex – look for a rating like 4.5/5 or a JSON field "ratingValue":"4.5"
        rating_match = re.search(r'"ratingValue"\s*[:=]\s*"?(\d+\.?\d*)', html)
        review_match = re.search(r'"reviewCount"\s*[:=]\s*"?(\d+)', html)
        rating = rating_match.group(1) if rating_match else None
        review = review_match.group(1) if review_match else None
        return rating, review
    except Exception:
        return None, None

# ---------- Playwright Scrapers ----------

async def scrape_booking(page, url: str):
    clean_url = clean_booking_url(url)
    await page.goto(clean_url, timeout=30000, wait_until="domcontentloaded")
    await asyncio.sleep(4)  # give the page time to render dynamic parts

    # Verify we are on a proper hotel page
    if '/hotel/' not in page.url:
        return None, None

    rating = None
    review_count = None
    content = await page.content()

    # Try the official review score component first
    try:
        el = await page.query_selector('[data-testid="review-score-component"]')
        if el:
            text = await el.inner_text()
            m = re.search(r'(\d+\.?\d*)', text)
            if m:
                rating = m.group(1)
    except Exception:
        pass

    # Fallback regex on raw HTML
    if not rating:
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

    # Review count extraction
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

async def scrape_mmt(page, url: str):
    await page.goto(url, timeout=30000, wait_until="domcontentloaded")
    await asyncio.sleep(4)
    rating = None
    review_count = None
    content = await page.content()

    # Rating patterns – JSON fields or visible "X.X/5"
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

    # Review count patterns
    m = re.search(r'([\d,]+)\s*(?:rating|review)s?', content, re.IGNORECASE)
    if m:
        review_count = m.group(1).replace(",", "")

    return rating, review_count

# ---------- Async Runner ----------

async def process_item(semaphore, page, item, idx, total):
    async with semaphore:
        url = item['url']
        name = item['name'] or f"Property {idx+1}"
        print(f"[{idx+1}/{total}] {name}...", end=" ")
        # Fast‑path for non‑JS pages
        if not any(host in url for host in ["booking.com", "makemytrip", "mmt"]):
            rating, review_count = await asyncio.get_running_loop().run_in_executor(None, fast_requests_scrape, url)
        else:
            try:
                if 'booking.com' in url:
                    rating, review_count = await scrape_booking(page, url)
                elif 'makemytrip' in url or 'mmt' in url:
                    rating, review_count = await scrape_mmt(page, url)
                else:
                    rating, review_count = None, None
            except Exception as e:
                rating, review_count = None, None
                print(f"ERROR: {e}")
        print(f"Rating: {rating or 'N/A'}, Reviews: {review_count or 'N/A'}")
        return {
            'name': name,
            'url': url,
            'rating': rating or 'N/A',
            'review_count': review_count or 'N/A'
        }

async def main_async():
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
    semaphore = asyncio.Semaphore(15)  # parallel workers

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        })

        tasks = [process_item(semaphore, page, item, i, len(links)) for i, item in enumerate(links)]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
        await browser.close()

    # Write CSV output
    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['name', 'url', 'rating', 'review_count'])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nDone! Results saved to: {OUTPUT_CSV}")

if __name__ == "__main__":
    asyncio.run(main_async())
