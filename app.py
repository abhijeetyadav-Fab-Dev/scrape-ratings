import sys, os, io, csv, time, re, threading, pickle, json, argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QProgressBar, QTextEdit, QSpinBox,
    QLineEdit, QFrame, QTabWidget
)

from universal_scraper import UniversalScraperTab
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QDragEnterEvent, QDropEvent, QIcon

NUM_WORKERS = 5
COOKIES_DIR = Path.home() / ".scrape-ratings"
COOKIES_DIR.mkdir(exist_ok=True)
MMT_COOKIES = COOKIES_DIR / "mmt_cookies.pkl"


# ── Shared Playwright browser (pool) ─────────────────────────

_browser_pool_lock = threading.Lock()
_browser_pool = None
_pw_manager = None


def get_shared_browser():
    """Get or create a shared Playwright browser instance.
    All Booking.com scrapes reuse this browser instead of launching a new one each time.
    """
    global _browser_pool, _pw_manager
    with _browser_pool_lock:
        if _browser_pool is None or not _browser_pool.is_connected():
            if _pw_manager is None:
                _pw_manager = sync_playwright().start()
            _browser_pool = _pw_manager.chromium.launch(headless=True)
        return _browser_pool


def close_shared_browser():
    global _browser_pool, _pw_manager
    with _browser_pool_lock:
        if _browser_pool:
            try:
                _browser_pool.close()
            except:
                pass
            _browser_pool = None
        if _pw_manager:
            try:
                _pw_manager.stop()
            except:
                pass
            _pw_manager = None


def clean_booking_url(url):
    match = re.match(r'(https://www\.booking\.com/hotel/[^?;]+)', url)
    return match.group(1) if match else url


def search_booking_hotel(page, hotel_name, city=""):
    query = f"{hotel_name} {city}".strip()
    query = re.sub(r'[^\w\s]', ' ', query).strip()
    search_url = f"https://www.booking.com/searchresults.en-gb.html?ss={query.replace(' ', '+')}"
    page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
    try:
        page.wait_for_selector('a[href*="/hotel/"]', timeout=8000)
    except:
        pass
    links = page.query_selector_all('a[href*="/hotel/"]')
    for link in links[:5]:
        href = link.get_attribute('href')
        if href and '/hotel/' in href:
            return href
    return None


def _extract_rating_review_count(content):
    """Extract rating and review count from page HTML content.
    Uses multiple patterns to handle different Booking.com page layouts.
    """
    rating, review_count = None, None

    # Rating patterns (on a 1-10 scale)
    rating_patterns = [
        r'"ratingValue"[\s:]*"?(\d+\.?\d*)',
        r'ratingValue[\s:>]+(\d+\.?\d*)',
        r'Scored\s+(\d+\.?\d*)',
        r'"score"[\s:]+(\d+\.?\d*)',
        r'review_score[\s:=]+(\d+\.?\d*)',
        r'"averageScore"[\s:]+(\d+\.?\d*)',
        r'(\d+\.\d)\s*/\s*10',
        r'"reviewScore">(\d+\.?\d*)<',
        r'<strong[^>]*>(\d+\.\d)</strong>',
    ]
    for pat in rating_patterns:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1))
                if 1 <= val <= 10:
                    rating = str(val)
                    break
            except ValueError:
                continue

    # Review count patterns
    count_patterns = [
        r'"reviewCount"[\s:]*"?(\d+)',
        r'"numberOfReviews"[\s:]+(\d+)',
        r'([\d,]+)\s*reviews?',
        r'([\d,]+)\s*ratings?',
        r'"reviewCount">(\d+)<',
    ]
    for pat in count_patterns:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            review_count = m.group(1).replace(",", "")
            try:
                if int(review_count) > 0:
                    break
            except ValueError:
                review_count = None

    return rating, review_count


def _new_booking_page():
    """Create a new page from the shared browser with standard headers."""
    browser = get_shared_browser()
    page = browser.new_page()
    page.set_extra_http_headers({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return page


def scrape_hotel(url):
    rating, review_count = None, None
    try:
        page = _new_booking_page()
        clean_url = clean_booking_url(url)
        try:
            page.goto(clean_url, timeout=25000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass
        if '/hotel/' not in page.url:
            page.close()
            return None, None
        page.evaluate("window.scrollBy(0, 500)")
        try:
            page.wait_for_timeout(800)
        except:
            pass
        content = page.content()
        rating, review_count = _extract_rating_review_count(content)
        page.close()
    except:
        pass
    return rating, review_count


def search_and_scrape(hotel_name, city=""):
    try:
        page = _new_booking_page()
        url = search_booking_hotel(page, hotel_name, city)
        if not url:
            page.close()
            return None, None, None
        if url.startswith('/'):
            url = "https://www.booking.com" + url
        clean_url = clean_booking_url(url)
        try:
            page.goto(clean_url, timeout=25000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass
        if '/hotel/' not in page.url:
            page.close()
            return None, None, clean_url
        page.evaluate("window.scrollBy(0, 500)")
        try:
            page.wait_for_timeout(800)
        except:
            pass
        content = page.content()
        rating, review_count = _extract_rating_review_count(content)
        page.close()
        return rating, review_count, clean_url
    except:
        return None, None, None





def mmt_login():
    """Open real Chrome for MMT login, grab cookies when user closes it"""
    import subprocess
    chrome_paths = [
        r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe"),
    ]
    chrome = None
    for p in chrome_paths:
        if os.path.exists(p):
            chrome = p
            break

    debug_port = 9222
    user_data = str(COOKIES_DIR / "chrome_scrape")

    if chrome:
        proc = subprocess.Popen([
            chrome,
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={user_data}",
            "https://www.makemytrip.com/hotels/"
        ])
        # Wait for Chrome to close (user logs in then closes browser)
        proc.wait()
    else:
        # Fallback: Playwright with installed Chrome
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=False,
                                         args=[f"--remote-debugging-port={debug_port}",
                                               f"--user-data-dir={user_data}"])
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://www.makemytrip.com/hotels/", timeout=30000)
            input()  # block until closed
            browser.close()
        return True

    # Now connect via CDP to grab cookies from the debug port
    # Chrome closed, but we can read cookies from the profile using a quick relaunch
    try:
        proc2 = subprocess.Popen([
            chrome,
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={user_data}",
            "--headless=new",
            "about:blank"
        ])
        time.sleep(3)
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://localhost:{debug_port}")
            context = browser.contexts[0]
            cookies = context.cookies(["https://www.makemytrip.com"])
            with open(MMT_COOKIES, 'wb') as f:
                pickle.dump(cookies, f)
            browser.close()
        proc2.terminate()
    except Exception:
        pass
    return True


def mmt_has_session():
    return MMT_COOKIES.exists()


_mmt_browser = None
_mmt_pw_manager = None  # Track Playwright manager so we can clean it up
_mmt_lock = threading.Lock()
MMT_DEBUG_PORT = 9222


# ── Checkpoint system for auto-resume ──────────────────────

def _checkpoint_path(input_path):
    """Generate a unique checkpoint file path for a given input CSV."""
    safe = str(input_path).replace(':', '_').replace('\\', '_').replace('/', '_')
    return COOKIES_DIR / f"checkpoint_{safe}.json"


def save_checkpoint(input_file, output_file, results, total, processed_count):
    """Save a checkpoint so the scrape can be resumed after a crash."""
    cp = {
        "input_file": str(input_file),
        "output_file": str(output_file),
        "total": total,
        "processed_count": processed_count,
        "results": {str(i): r for i, r in enumerate(results) if r is not None},
        "timestamp": time.time()
    }
    with open(_checkpoint_path(input_file), 'w') as f:
        json.dump(cp, f, indent=2)


def load_checkpoint(input_file):
    """Load a checkpoint if one exists.
    Returns (results_list, output_file, processed_count, total) or None.
    """
    cp_path = _checkpoint_path(input_file)
    if not cp_path.exists():
        return None
    try:
        with open(cp_path) as f:
            cp = json.load(f)
        results = [None] * cp["total"]
        for idx_str, r in cp["results"].items():
            results[int(idx_str)] = r
        return results, cp["output_file"], cp["processed_count"], cp["total"]
    except Exception:
        return None


def clear_checkpoint(input_file):
    """Remove the checkpoint for a completed scrape."""
    cp_path = _checkpoint_path(input_file)
    if cp_path.exists():
        cp_path.unlink()



def _kill_chrome_on_port(port):
    """Kill any Chrome process listening on the given port."""
    import subprocess
    try:
        result = subprocess.run(
            ["netstat", "-ano", "|", "findstr", f":{port}"],
            capture_output=True, text=True, shell=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            parts = line.strip().split()
            if len(parts) >= 5 and "LISTENING" in line:
                pid = parts[-1]
                try:
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True, timeout=5)
                except:
                    pass
    except:
        pass
    time.sleep(1)


def _start_mmt_chrome():
    """Kill old Chrome on debug port, then launch fresh Chrome for MMT scraping"""
    global _mmt_browser, _mmt_pw_manager

    # Kill any existing Chrome on our debug port
    _kill_chrome_on_port(MMT_DEBUG_PORT)

    # Close any stale Playwright browser reference and manager
    if _mmt_browser:
        try:
            _mmt_browser.close()
        except:
            pass
        _mmt_browser = None
    if _mmt_pw_manager:
        try:
            _mmt_pw_manager.stop()
        except:
            pass
        _mmt_pw_manager = None

    import subprocess
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    chrome = None
    for p in chrome_paths:
        if os.path.exists(p):
            chrome = p
            break
    if not chrome:
        return None

    user_data = str(COOKIES_DIR / "chrome_scrape")
    subprocess.Popen([
        chrome,
        f"--remote-debugging-port={MMT_DEBUG_PORT}",
        f"--user-data-dir={user_data}",
        "--no-first-run",
        "--window-size=1280,800",
        "about:blank"
    ])
    time.sleep(3)
    pw = sync_playwright().start()
    _mmt_pw_manager = pw
    _mmt_browser = pw.chromium.connect_over_cdp(f"http://localhost:{MMT_DEBUG_PORT}")
    # Load cookies into the Chrome context
    context = _mmt_browser.contexts[0]
    with open(MMT_COOKIES, 'rb') as f:
        cookies = pickle.load(f)
    context.add_cookies(cookies)
    return _mmt_browser


def _get_mmt_browser():
    global _mmt_browser
    if _mmt_browser is None or not _mmt_browser.is_connected():
        _start_mmt_chrome()
    return _mmt_browser


def scrape_mmt_hotel(hotel_id):
    """Scrape MMT hotel using real Chrome via CDP"""
    if not MMT_COOKIES.exists():
        return None, None
    try:
        with _mmt_lock:
            browser = _get_mmt_browser()
            if not browser:
                return None, None
            context = browser.contexts[0]
            page = context.new_page()

        url = f"https://www.makemytrip.com/hotels/hotel-details/?hotelId={hotel_id}&_uCurrency=INR&checkin=07202026&checkout=07212026&city=CTDEL&country=IN&roomStayQualifier=2e0e&locusId=CTDEL&locusType=city"
        try:
            page.goto(url, timeout=20000, wait_until="domcontentloaded")
        except:
            pass
        try:
            page.wait_for_timeout(1000)
        except:
            pass
        page.evaluate("window.scrollBy(0, 1000)")
        try:
            page.wait_for_timeout(800)
        except:
            pass

        content = page.content()
        rating, review_count = None, None

        if len(content) > 500:
            # Rating patterns for MMT (on a 1-5 scale)
            for pat in [
                r'itemprop="ratingValue"[^>]*>(\d+\.?\d*)<',
                r'"ratingValue"\s*:\s*"?(\d+\.?\d*)"?',
                r'"userRating"\s*:\s*"?(\d+\.?\d*)"?',
                r'"overallRating"\s*:\s*"?(\d+\.?\d*)"?',
                r'(\d\.\d)\s*/\s*5',
            ]:
                matches = re.findall(pat, content)
                valid = [x for x in matches if 1 <= float(x) <= 5]
                if valid:
                    rating = valid[0]
                    break

            # Review count patterns for MMT
            for pat in [
                r'\((\d+)\s*RATINGS?\)',
                r'(\d+)\s*Ratings',
                r'"reviewCount"\s*:\s*"?(\d+)"?',
                r'"ratingCount"\s*:\s*"?(\d+)"?',
                r'([\d,]+)\s*(?:rating|review)s?',
            ]:
                matches = re.findall(pat, content, re.IGNORECASE)
                valid = [x for x in matches if x.replace(',', '').isdigit() and int(x.replace(',', '')) > 0]
                if valid:
                    review_count = valid[0].replace(',', '')
                    break

        page.close()
        return rating, review_count
    except:
        return None, None


# ── Windows notification helper ──────────────────────────────

def notify_complete(message):
    """Play a sound and show a native Windows toast notification."""
    import subprocess, winsound
    # Escape single quotes for PowerShell safety
    msg_escaped = message.replace("'", "''").replace('\n', ' — ')
    # Play system notification sound
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass
    # Show native Windows 10/11 toast notification via PowerShell
    try:
        ps = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName("text")
$textNodes.Item(0).AppendChild($template.CreateTextNode("Ratings Scraper")) > $null
$textNodes.Item(1).AppendChild($template.CreateTextNode("{msg_escaped}")) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Ratings Scraper").Show($toast)
'''
        subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=15)
    except Exception:
        pass


class ScrapeWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str, int, int)

    def __init__(self, items, num_workers, original_rows=None, original_headers=None,
                 existing_results=None, resume_output_path=None, input_file=None):
        super().__init__()
        self.items = items
        self.num_workers = num_workers
        self.original_rows = original_rows or []
        self.original_headers = original_headers or []
        self.existing_results = existing_results
        self.resume_output_path = resume_output_path
        self.input_file = input_file
        self._stop = False
        self._pause = False

    def stop(self):
        self._stop = True

    def pause(self):
        self._pause = True

    def resume(self):
        self._pause = False

    def run(self):
        total = len(self.items)
        SAVE_INTERVAL = 50

        # --- Initialise: fresh or from checkpoint ---
        if self.existing_results is not None and self.resume_output_path:
            results = list(self.existing_results)  # copy to avoid mutation
            processed_count = [sum(1 for r in results if r is not None)]
            output_path = self.resume_output_path
            remaining = {i for i in range(total) if results[i] is None}
            self.progress.emit(processed_count[0], total,
                               f"Resuming \u2014 {processed_count[0]}/{total} already done, {len(remaining)} remaining")
        else:
            results = [None] * total
            processed_count = [0]
            if self.input_file:
                stem = Path(self.input_file).stem
                output_path = str(Path.home() / "Downloads" / f"{stem}_scraped.csv")
            else:
                output_path = str(Path.home() / "Downloads" / f"ratings_output_{int(time.time())}.csv")
            remaining = set(range(total))
            # Write CSV header immediately
            if self.original_rows and self.original_headers:
                out_headers = self.original_headers + ['Scraped_Rating', 'Scraped_Reviews', 'Scraped_Source']
                with open(output_path, 'w', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerow(out_headers)
            else:
                with open(output_path, 'w', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=['name', 'city', 'url', 'rating', 'review_count', 'source'])
                    w.writeheader()

        def scrape_one(i, item):
            if self._stop:
                return i, None
            url = item.get('url', '').strip()
            name = item.get('name', '')
            city = item.get('city', '')
            source = item.get('source', '')
            hotel_id = item.get('hotel_id', '')
            try:
                if source == 'mmt' and hotel_id:
                    rating, review_count = scrape_mmt_hotel(hotel_id)
                elif url and 'makemytrip' in url:
                    m = re.search(r'hotelId=(\w+)', url)
                    if m:
                        rating, review_count = scrape_mmt_hotel(m.group(1))
                    else:
                        rating, review_count = None, None
                elif url and ('booking.com' in url or 'http' in url):
                    rating, review_count = scrape_hotel(url)
                else:
                    rating, review_count, _ = search_and_scrape(name, city)
            except:
                rating, review_count = None, None
            src = 'MMT' if (source == 'mmt' or 'makemytrip' in (url or '')) else 'Booking.com'
            return i, {'rating': rating or 'N/A', 'review_count': review_count or 'N/A', 'source': src}

        def save_incremental():
            with open(output_path + '.tmp', 'w', newline='', encoding='utf-8') as f:
                if self.original_rows and self.original_headers:
                    out_headers = self.original_headers + ['Scraped_Rating', 'Scraped_Reviews', 'Scraped_Source']
                    writer = csv.writer(f)
                    writer.writerow(out_headers)
                    for idx, orig_row in enumerate(self.original_rows):
                        r = results[idx] if idx < len(results) and results[idx] else {'rating': '', 'review_count': '', 'source': ''}
                        writer.writerow(orig_row + [r['rating'], r['review_count'], r['source']])
                else:
                    writer = csv.DictWriter(f, fieldnames=['name', 'city', 'url', 'rating', 'review_count', 'source'])
                    writer.writeheader()
                    for idx, item in enumerate(self.items):
                        r = results[idx] if results[idx] else {'rating': 'N/A', 'review_count': 'N/A', 'source': ''}
                        writer.writerow({'name': item.get('name', ''), 'city': item.get('city', ''),
                                         'url': item.get('url', ''), **r})
            if os.path.exists(output_path):
                os.remove(output_path)
            os.rename(output_path + '.tmp', output_path)

        def save_and_checkpoint():
            save_incremental()
            if self.input_file:
                save_checkpoint(self.input_file, output_path, results, total, processed_count[0])

        def emit_status(i, result):
            item = self.items[i]
            src = 'MMT' if (item.get('source') == 'mmt' or 'makemytrip' in item.get('url', '')) else 'Booking.com'
            status = f"{item.get('name', '')[:35]} -> Rating: {result.get('rating', 'N/A') if result else 'N/A'}, Reviews: {result.get('review_count', 'N/A') if result else 'N/A'}"
            self.progress.emit(processed_count[0], total, status)

        # Separate remaining items into non-MMT (parallel) and MMT (sequential via shared browser)
        non_mmt_indices = [i for i in range(total)
                           if i in remaining and not (self.items[i].get('source') == 'mmt' or 'makemytrip' in self.items[i].get('url', ''))]
        mmt_indices = [i for i in range(total)
                       if i in remaining and (self.items[i].get('source') == 'mmt' or 'makemytrip' in self.items[i].get('url', ''))]

        # Process non-MMT items in TRUE parallel
        if non_mmt_indices:
            pending = set()
            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                futures = {executor.submit(scrape_one, i, self.items[i]): i for i in non_mmt_indices}
                pending = set(futures.keys())
                for future in as_completed(futures):
                    pending.discard(future)
                    if self._stop:
                        for f in pending:
                            f.cancel()
                        break
                    while self._pause and not self._stop:
                        time.sleep(0.5)
                    if self._stop:
                        for f in pending:
                            f.cancel()
                        break
                    i, result = future.result()
                    results[i] = result
                    processed_count[0] += 1
                    emit_status(i, result or {'rating': 'CANCELLED', 'review_count': '', 'source': ''})
                    if processed_count[0] % SAVE_INTERVAL == 0:
                        save_and_checkpoint()

        # Process MMT items sequentially (shared browser via lock)
        if mmt_indices and not self._stop:
            for i in mmt_indices:
                if self._stop:
                    break
                while self._pause:
                    time.sleep(0.5)
                    if self._stop:
                        break
                i, result = scrape_one(i, self.items[i])
                results[i] = result
                processed_count[0] += 1
                emit_status(i, result or {'rating': 'CANCELLED', 'review_count': '', 'source': ''})
                if processed_count[0] % SAVE_INTERVAL == 0:
                    save_and_checkpoint()

        # Final save and clean up checkpoint
        save_incremental()
        if self.input_file:
            clear_checkpoint(self.input_file)

        success = sum(1 for r in results if r and r['rating'] not in ('N/A', 'ERROR', 'CANCELLED'))
        self.finished.emit(output_path, success, total)


class MainWindow(QMainWindow):
    log_signal = pyqtSignal(str)
    ui_signal = pyqtSignal(object)

    def __init__(self, csv_path=None, workers=10):
        super().__init__()
        self.setWindowTitle("Hotel Data Tools — Ratings Scraper & Universal Scraper")
        icon_path = str(Path(__file__).parent / "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setFixedSize(750, 750)
        self.setStyleSheet("""
            QMainWindow { background-color: #1a1a2e; }
            QLabel { color: #e0e0e0; }
            QPushButton { background-color: #0f3460; color: white; border: none; padding: 12px 24px; border-radius: 6px; font-size: 14px; }
            QPushButton:hover { background-color: #16213e; }
            QPushButton:disabled { background-color: #333; color: #666; }
            QProgressBar { border: 1px solid #333; border-radius: 4px; text-align: center; color: white; }
            QProgressBar::chunk { background-color: #e94560; border-radius: 3px; }
            QTextEdit { background-color: #16213e; color: #a0e0a0; border: 1px solid #333; border-radius: 4px; font-family: Consolas; font-size: 11px; }
        """)
        self.setAcceptDrops(True)

        # ── Tabbed interface ─────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background: #1a1a2e; }
            QTabBar::tab { background: #0f3460; color: #888; padding: 8px 20px;
                          margin-right: 2px; border-top-left-radius: 6px;
                          border-top-right-radius: 6px; font-size: 12px; }
            QTabBar::tab:selected { background: #16213e; color: white; }
        """)
        self.setCentralWidget(self.tabs)

        # ════════════════ Tab 1: Ratings Scraper ════════════
        ratings_tab = QWidget()
        layout = QVBoxLayout(ratings_tab)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Hotel Ratings & Reviews Scraper")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Drop a CSV with hotel links OR hotel names — or just type a hotel name below")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(subtitle)

        # Quick search bar
        quick_row = QHBoxLayout()
        self.quick_input = QLineEdit()
        self.quick_input.setPlaceholderText("Type hotel name or paste a link (Booking.com, MMT, etc.)...")
        self.quick_input.setStyleSheet("background: #16213e; color: white; border: 1px solid #444; border-radius: 6px; padding: 10px; font-size: 13px;")
        self.quick_input.returnPressed.connect(self.quick_search)
        quick_row.addWidget(self.quick_input)

        self.quick_btn = QPushButton("Search")
        self.quick_btn.clicked.connect(self.quick_search)
        self.quick_btn.setStyleSheet("background-color: #e94560; font-weight: bold; padding: 10px 20px;")
        quick_row.addWidget(self.quick_btn)
        layout.addLayout(quick_row)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #333;")
        layout.addWidget(separator)

        bulk_label = QLabel("— Bulk scrape: paste links/names OR load CSV —")
        bulk_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bulk_label.setStyleSheet("color: #555; font-size: 11px;")
        layout.addWidget(bulk_label)

        self.bulk_input = QTextEdit()
        self.bulk_input.setPlaceholderText("Paste links or hotel names here (one per line)...\nSupports: Booking.com links, MMT links, or hotel names")
        self.bulk_input.setMaximumHeight(80)
        self.bulk_input.setStyleSheet("background: #16213e; color: white; border: 1px solid #444; border-radius: 6px; font-size: 12px;")
        layout.addWidget(self.bulk_input)

        btn_row = QHBoxLayout()
        self.browse_btn = QPushButton("Browse CSV")
        self.browse_btn.clicked.connect(self.browse_file)
        btn_row.addWidget(self.browse_btn)

        btn_row.addWidget(QLabel("Workers:"))
        self.worker_spin = QSpinBox()
        self.worker_spin.setRange(1, 20)
        self.worker_spin.setValue(workers)
        self.worker_spin.setStyleSheet("background: #16213e; color: white; border: 1px solid #333; padding: 4px;")
        btn_row.addWidget(self.worker_spin)

        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_scraping)
        self.start_btn.setStyleSheet("background-color: #e94560; font-weight: bold;")
        btn_row.addWidget(self.start_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.pause_scraping)
        self.pause_btn.setStyleSheet("background-color: #f5a623; font-weight: bold;")
        self.pause_btn.setEnabled(False)
        btn_row.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_scraping)
        self.stop_btn.setStyleSheet("background-color: #c0392b; font-weight: bold;")
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.stop_btn)

        layout.addLayout(btn_row)

        btn_row2 = QHBoxLayout()
        self.download_btn = QPushButton("Download CSV")
        self.download_btn.clicked.connect(self.download_csv)
        self.download_btn.setStyleSheet("background-color: #27ae60; font-weight: bold;")
        self.download_btn.setEnabled(False)
        btn_row2.addWidget(self.download_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_all)
        self.clear_btn.setStyleSheet("background-color: #555; font-weight: bold;")
        btn_row2.addWidget(self.clear_btn)

        self.output_path = None
        layout.addLayout(btn_row2)

        # MMT session row
        mmt_row = QHBoxLayout()
        mmt_status = "MMT session active" if mmt_has_session() else "MMT: No session"
        self.mmt_label = QLabel(mmt_status)
        self.mmt_label.setStyleSheet("color: #888; font-size: 11px;")
        mmt_row.addWidget(self.mmt_label)
        self.mmt_login_btn = QPushButton("Login to MMT")
        self.mmt_login_btn.setStyleSheet("background-color: #0a7; padding: 8px 16px; font-size: 12px;")
        self.mmt_login_btn.clicked.connect(self.do_mmt_login)
        mmt_row.addWidget(self.mmt_login_btn)
        layout.addLayout(mmt_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        layout.addWidget(self.log)

        self.csv_path = None
        self.items = []
        self.original_rows = []
        self.original_headers = []

        self.log_signal.connect(self.log.append)
        self.ui_signal.connect(lambda fn: fn())

        # Register tabs
        self.tabs.addTab(ratings_tab, "Ratings Scraper")
        self.tabs.addTab(UniversalScraperTab(), "Universal Scraper")

        # Load CSV if provided via --csv argument
        if csv_path:
            self.load_csv(csv_path)

    def do_mmt_login(self):
        self.log.append("\nOpening Chrome — log in to MMT, then CLOSE Chrome...")
        self.mmt_login_btn.setEnabled(False)

        def login_thread():
            try:
                mmt_login()
                self.log_signal.emit("MMT session saved! You can now scrape MMT hotels.")
                self.ui_signal.emit(lambda: self.mmt_label.setText("MMT session active"))
            except Exception as e:
                self.log_signal.emit(f"MMT login failed: {e}")
            self.ui_signal.emit(lambda: self.mmt_login_btn.setEnabled(True))

        threading.Thread(target=login_thread, daemon=True).start()

    def quick_search(self):
        query = self.quick_input.text().strip()
        if not query:
            return
        self.quick_btn.setEnabled(False)
        self.quick_input.setEnabled(False)
        self.log.append(f"\nSearching: {query}...")

        def do_search():
            if 'http' in query and 'booking.com' in query:
                rating, review_count = scrape_hotel(query)
                return query, rating, review_count, "booking"
            elif 'http' in query and 'makemytrip' in query:
                # Extract hotelId from MMT link
                m = re.search(r'hotelId=(\w+)', query)
                if m and mmt_has_session():
                    hotel_id = m.group(1)
                    rating, review_count = scrape_mmt_hotel(hotel_id)
                    return query, rating, review_count, "mmt"
                else:
                    if not mmt_has_session():
                        return query, None, None, "mmt_no_session"
                    return query, None, None, "mmt"
            else:
                rating, review_count, found_url = search_and_scrape(query)
                return found_url, rating, review_count, "booking"

        def run():
            url, rating, count, source = do_search()
            self.ui_signal.emit(lambda: self.quick_btn.setEnabled(True))
            self.ui_signal.emit(lambda: self.quick_input.setEnabled(True))
            if source == "mmt_no_session":
                self.log_signal.emit("MMT requires login first. Click 'Login to MMT' button.")
            elif rating:
                scale = "/5" if source == "mmt" else "/10"
                self.log_signal.emit(f"  {query}")
                self.log_signal.emit(f"  Rating: {rating}{scale} | Reviews: {count}")
                self.log_signal.emit(f"  Source: {'MakeMyTrip' if source == 'mmt' else 'Booking.com'}")
                if url and url != query:
                    self.log_signal.emit(f"  Found at: {url[:80]}")
            else:
                self.log_signal.emit(f"  Could not find ratings for: {query}")
            self.log_signal.emit("")

        threading.Thread(target=run, daemon=True).start()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files and files[0].endswith('.csv'):
            self.load_csv(files[0])

    def browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select CSV", "", "CSV Files (*.csv)")
        if path:
            self.load_csv(path)

    def load_csv(self, path):
        self.csv_path = path
        self.items = []
        self.original_rows = []
        self.original_headers = []
        try:
            with open(path, newline='', encoding='utf-8') as f:
                rows = list(csv.reader(f))

            # Find the header row (first row with 'Name' or 'Hotel Name' in it)
            header_idx = 0
            headers = []
            for i, row in enumerate(rows[:5]):
                lower_row = [c.lower().strip() for c in row]
                if 'name' in lower_row or 'hotel name' in lower_row:
                    header_idx = i
                    headers = [c.strip() for c in row]
                    break

            if not headers:
                headers = [c.strip() for c in rows[0]]

            lower_headers = [h.lower() for h in headers]

            # Find column indices
            def find_col(*names):
                for n in names:
                    for i, h in enumerate(lower_headers):
                        if n in h:
                            return i
                return None

            name_idx = find_col('name', 'hotel')
            city_idx = find_col('city', 'location')
            link_idx = find_col('mmt', 'link', 'url')
            # Be specific: only match columns that contain BOTH 'hotel' and 'id' or specific known names
            id_idx = find_col('front-end id', 'mmt id', 'fh', 'hotel id', 'hotel_id')

            # If link_idx points to a column header that's also "MMT" but is the link column,
            # check which column actually has URLs in the data
            if link_idx is not None and header_idx + 1 < len(rows):
                test_row = rows[header_idx + 1]
                if link_idx < len(test_row) and 'http' not in test_row[link_idx]:
                    for i, cell in enumerate(test_row):
                        if 'makemytrip.com' in cell or 'booking.com' in cell:
                            link_idx = i
                            break

            self.original_headers = headers

            for row in rows[header_idx + 1:]:
                if len(row) <= (name_idx or 0):
                    continue
                name = row[name_idx].strip() if name_idx is not None and name_idx < len(row) else ''
                city = row[city_idx].strip() if city_idx is not None and city_idx < len(row) else ''
                url = row[link_idx].strip() if link_idx is not None and link_idx < len(row) else ''
                hotel_id = row[id_idx].strip() if id_idx is not None and id_idx < len(row) else ''

                if not name or name.lower() in ('name', 'hotel name', 'hotel'):
                    continue

                self.original_rows.append(row)

                if url and 'makemytrip' in url:
                    m = re.search(r'hotelId=(\w+)', url)
                    hid = m.group(1) if m else hotel_id
                    self.items.append({'name': name, 'city': city, 'url': url, 'source': 'mmt', 'hotel_id': hid})
                elif url and 'booking.com' in url:
                    self.items.append({'name': name, 'city': city, 'url': url, 'source': 'booking'})
                elif hotel_id and hotel_id.replace('#', '').strip().isdigit():
                    self.items.append({'name': name, 'city': city, 'url': '', 'source': 'mmt', 'hotel_id': hotel_id.replace('#', '').strip()})
                elif name:
                    self.items.append({'name': name, 'city': city, 'url': url, 'source': 'search'})

            has_links = sum(1 for i in self.items if i['url'] and 'http' in i['url'])
            names_only = len(self.items) - has_links
            self.bulk_input.setPlainText(f"Loaded: {Path(path).name} \u2014 {len(self.items)} hotels ({has_links} links, {names_only} name-only)")
            self.log.append(f"Loaded {len(self.items)} hotels from {Path(path).name}")
        except Exception as e:
            self.log.append(f"ERROR loading CSV: {e}")

    def start_scraping(self):
        # Check paste area first (only if CSV wasn't already loaded)
        bulk_text = self.bulk_input.toPlainText().strip()
        if bulk_text and not self.items:
            lines = [l.strip() for l in bulk_text.split('\n') if l.strip()]
            self.items = []
            for line in lines:
                if 'makemytrip' in line:
                    m = re.search(r'hotelId=(\w+)', line)
                    hotel_id = m.group(1) if m else ''
                    self.items.append({'name': line[:50], 'city': '', 'url': line, 'source': 'mmt', 'hotel_id': hotel_id})
                elif 'booking.com' in line:
                    self.items.append({'name': line[:50], 'city': '', 'url': line, 'source': 'booking'})
                else:
                    self.items.append({'name': line, 'city': '', 'url': '', 'source': 'search'})

        if not self.items:
            self.log.append("Nothing to scrape. Paste links/names above or load a CSV.")
            return

        # --- Check for checkpoint to auto-resume (only for CSV files) ---
        existing_results = None
        resume_output_path = None
        resume_total = 0
        if self.csv_path:
            checkpoint = load_checkpoint(self.csv_path)
            if checkpoint is not None:
                chk_results, chk_output, chk_processed, chk_total = checkpoint
                if chk_total == len(self.items) and chk_processed < chk_total:
                    existing_results = chk_results
                    resume_output_path = chk_output
                    resume_total = chk_total

        self.start_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setMaximum(len(self.items))

        if existing_results is not None:
            self.progress.setValue(sum(1 for r in existing_results if r is not None))
            self.log.append(f"\nAuto-resuming from checkpoint \u2014 {sum(1 for r in existing_results if r is not None)}/{resume_total} already scraped...")
        else:
            self.progress.setValue(0)
            self.log.append(f"\nStarting scrape of {len(self.items)} hotels with {self.worker_spin.value()} workers...")

        # MMT items are processed sequentially (shared browser via lock).
        # Non-MMT items run in the ThreadPoolExecutor in parallel — keep the user's worker count.
        num_workers = self.worker_spin.value()

        self.worker = ScrapeWorker(
            self.items, num_workers, self.original_rows, self.original_headers,
            existing_results=existing_results,
            resume_output_path=resume_output_path,
            input_file=self.csv_path
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)

    def pause_scraping(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            if self.worker._pause:
                self.worker.resume()
                self.pause_btn.setText("Pause")
                self.log.append("Resumed")
            else:
                self.worker.pause()
                self.pause_btn.setText("Resume")
                self.log.append("Paused")

    def stop_scraping(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
            self.log.append("Stopping...")

    def download_csv(self):
        if self.output_path and os.path.exists(self.output_path):
            os.startfile(self.output_path)

    def clear_all(self):
        # If a CSV was loaded with a checkpoint, clear it so next start is fresh
        if self.csv_path:
            clear_checkpoint(self.csv_path)
        self.log.clear()
        self.bulk_input.clear()
        self.items = []
        self.original_rows = []
        self.original_headers = []
        self.csv_path = None
        self.output_path = None
        self.download_btn.setEnabled(False)
        self.progress.setVisible(False)
        self.progress.setValue(0)

    def on_progress(self, current, total, status):
        self.progress.setValue(current)
        self.log.append(f"[{current}/{total}] {status}")
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def on_finished(self, output_path, success, total):
        self.progress.setValue(self.progress.maximum())
        self.log.append(f"\n{'='*40}")
        self.log.append(f"DONE! {success}/{total} hotels scraped successfully")
        self.log.append(f"Output: {output_path}")
        self.start_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setText("Pause")
        self.output_path = output_path
        self.download_btn.setEnabled(True)
        self.bulk_input.setPlainText(f"Done! {success}/{total} scraped -> {Path(output_path).name}")
        # Notify user (toast + sound) in a background thread so it doesn't block the UI
        threading.Thread(target=notify_complete, args=(
            f"Scraping complete! {success}/{total} hotels done.\nClick Downloads to open."
        ), daemon=True).start()


def main():
    parser = argparse.ArgumentParser(description="Hotel Ratings & Reviews Scraper")
    parser.add_argument('--csv', type=str, help='Path to a CSV file to load on launch')
    parser.add_argument('--workers', type=int, default=10, help='Number of parallel workers (default: 10)')
    args, _ = parser.parse_known_args()
    app = QApplication(sys.argv)
    window = MainWindow(csv_path=args.csv, workers=args.workers)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
