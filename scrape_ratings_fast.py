import sys, os, io, csv, time, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright

# If running as a PyInstaller bundle, force Playwright to use the system-wide browser installation
if getattr(sys, 'frozen', False):
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

INPUT_CSV = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("C:/Users/CS05180/Desktop/scrape-ratings/input.csv")
OUTPUT_CSV = Path.home() / "Downloads" / f"ratings_output_{int(time.time())}.csv"
NUM_WORKERS = 5


def clean_booking_url(url):
    match = re.match(r'(https://www\.booking\.com/hotel/[^?;]+)', url)
    return match.group(1) if match else url


def scrape_one(url):
    clean_url = clean_booking_url(url)
    rating, review_count = None, None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9"
            })
            page.goto(clean_url, timeout=20000, wait_until="domcontentloaded")
            time.sleep(3)
            if '/hotel/' not in page.url:
                browser.close()
                return None, None
            content = page.content()
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
            browser.close()
    except Exception:
        pass
    return rating, review_count


def main():
    if not INPUT_CSV.exists():
        print(f"ERROR: CSV not found: {INPUT_CSV}")
        sys.exit(1)

    links = []
    with open(INPUT_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get('Link', '').strip()
            name = row.get('Hotel Name', '').strip()
            if url:
                links.append({'name': name, 'url': url})

    total = len(links)
    print(f"Scraping {total} hotels with {NUM_WORKERS} parallel workers...")
    print(f"Estimated time: ~{(total * 4) // NUM_WORKERS // 60} minutes\n")

    results = [None] * total
    done = [0]

    def process(idx, item):
        rating, count = scrape_one(item['url'])
        done[0] += 1
        status = f"[{done[0]}/{total}] {item['name'][:30]:30s} | Rating: {rating or 'N/A':5s} | Reviews: {count or 'N/A'}"
        print(status, flush=True)
        return idx, {'name': item['name'], 'url': item['url'], 'rating': rating or 'N/A', 'review_count': count or 'N/A'}

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = {executor.submit(process, i, item): i for i, item in enumerate(links)}
        for future in as_completed(futures):
            try:
                idx, result = future.result()
                results[idx] = result
            except Exception as e:
                idx = futures[future]
                results[idx] = {'name': links[idx]['name'], 'url': links[idx]['url'], 'rating': 'ERROR', 'review_count': 'ERROR'}

        # Save progress every 50
        completed = [r for r in results if r is not None]
        if len(completed) % 50 == 0 and completed:
            with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['name', 'url', 'rating', 'review_count'])
                writer.writeheader()
                writer.writerows([r for r in results if r])

    # Final save
    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['name', 'url', 'rating', 'review_count'])
        writer.writeheader()
        writer.writerows([r for r in results if r])

    success = sum(1 for r in results if r and r['rating'] != 'N/A')
    print(f"\n{'='*50}")
    print(f"DONE! {success}/{total} hotels scraped successfully")
    print(f"Output: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
