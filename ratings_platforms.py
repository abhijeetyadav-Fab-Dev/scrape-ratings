"""
Rating Platform Abstraction
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Each platform knows:
  - How to scrape ratings (headless vs visible browser)
  - How to build front-end URLs from partial data
  - What input types it accepts
  - Its rating scale (/10 or /5)

Architecture:
  RatingPlatform (ABC)
  ├── BookingPlatform   (headless, scale /10)
  ├── MMTPlatform       (visible browser + login, scale /5)
  ├── AgodaPlatform     (TBD, scale /10)
  └── ExpediaPlatform   (TBD, scale /10)
"""

import sys, re, os, time, pickle, threading, json, subprocess
from abc import ABC, abstractmethod
from pathlib import Path


# Set Playwright browser path to the user's local ms-playwright folder if running as a frozen executable
if getattr(sys, 'frozen', False):
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path.home() / "AppData" / "Local" / "ms-playwright")

COOKIES_DIR = Path.home() / ".scrape-ratings"
COOKIES_DIR.mkdir(exist_ok=True)
MMT_COOKIES = COOKIES_DIR / "mmt_cookies.pkl"


# ── Thread-local browser pool for concurrent headless scraping ──────────────

_browser_lock = threading.Lock()
_thread_local = threading.local()
_all_thread_browsers = []
_all_thread_pw_managers = []


def _get_headless_browser():
    """Get or create thread-local Playwright browser for headless scraping."""
    from playwright.sync_api import sync_playwright
    global _all_thread_browsers, _all_thread_pw_managers
    
    if not hasattr(_thread_local, 'pw_manager') or _thread_local.pw_manager is None:
        pw = sync_playwright().start()
        _thread_local.pw_manager = pw
        with _browser_lock:
            _all_thread_pw_managers.append(pw)
            
    if not hasattr(_thread_local, 'browser') or _thread_local.browser is None or not _thread_local.browser.is_connected():
        b = _thread_local.pw_manager.chromium.launch(headless=True)
        _thread_local.browser = b
        with _browser_lock:
            _all_thread_browsers.append(b)
            
    return _thread_local.browser


# ── Rating Platform Base ──────────────────────────────────

class RatingPlatform(ABC):
    """Abstract base for all rating scraping platforms."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable platform name, e.g. 'Booking.com'"""
        ...

    @property
    @abstractmethod
    def short_name(self) -> str:
        """Short key, e.g. 'booking', 'mmt', 'agoda'"""
        ...

    @property
    @abstractmethod
    def supports_headless(self) -> bool:
        """Can scrape without a visible browser window."""
        ...

    @property
    def needs_login(self) -> bool:
        """Does scraping require a logged-in session?"""
        return False

    @property
    @abstractmethod
    def scale(self) -> str:
        """Rating scale indicator, e.g. '/10' or '/5'"""
        ...

    @property
    def accepts(self) -> list[str]:
        """Input types this platform can handle: 'url', 'name', 'id', 'any'"""
        return ['url', 'name']

    @abstractmethod
    def scrape(self, page, input_data: dict) -> tuple:
        """
        Scrape rating and review count.
        input_data: {'url': ..., 'name': ..., 'city': ..., 'hotel_id': ...}
        Returns: (rating_str, review_count_str, status_str)
          status: 'ok', 'partial', 'no_data', 'redirected', 'timeout', 'not_found'
        """
        ...

    @abstractmethod
    def build_url(self, input_data: dict) -> str | None:
        """
        Build a front-end URL from partial data.
        input_data: {'name': ..., 'city': ..., 'hotel_id': ..., 'url': ...}
        Returns a working URL or None if not enough data.
        """
        ...

    def login(self, parent_widget=None) -> bool:
        """Optional: perform platform login. Return True if session saved."""
        return True

    def has_session(self) -> bool:
        """Check if a login session exists."""
        return True

    def new_page(self):
        """Create a new page from the headless browser pool."""
        browser = _get_headless_browser()
        page = browser.new_page()
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        # Block images, stylesheets, fonts, and media to speed up loads by up to 500%
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ("image", "stylesheet", "font", "media") else route.continue_())
        return page


# ── Helper: extract rating & review count from HTML ───────

def extract_rating_review_count(content, scale_10=True):
    """Extract rating and review count from page HTML.
    scale_10=True: filter 1-10 range, scale_10=False: filter 1-5 range.
    """
    rating, review_count = None, None

    # Goibibo specific extraction (highly precise overall ratings/reviews block)
    if 'goibibo.com' in content or 'AvgReviewTextWrapper' in content:
        go_rating = re.search(r'AvgReviewTextWrapper[^>]*>([\d.]+)', content)
        if go_rating:
            rating = go_rating.group(1).strip()
        go_reviews = re.search(r'ReviewCountTextWrapper[^>]*>([\d,]+)', content)
        if go_reviews:
            # Strip "Ratings" or "Reviews" text
            review_count = re.sub(r'[^\d]', '', go_reviews.group(1)).strip()
        if not review_count:
            # Fallback to reviews count
            go_reviews_fallback = re.search(r'RatingsCountTextWrapper[^>]*>([\d,]+)', content)
            if go_reviews_fallback:
                review_count = re.sub(r'[^\d]', '', go_reviews_fallback.group(1)).strip()
                
        if rating:
            return rating, review_count

    # Rating patterns
    rating_patterns = [
        r'\"ratingValue\"[\s:]*\"?(\d+\.?\d*)',
        r'ratingValue[\s:>]+(\d+\.?\d*)',
        r'Scored\s+(\d+\.?\d*)',
        r'\"score\"[\s:]+(\d+\.?\d*)',
        r'review_score[\s:=]+(\d+\.?\d*)',
        r'\"averageScore\"[\s:]+(\d+\.?\d*)',
        r'(\d+\.\d)\s*/\s*10',
        r'\"reviewScore\">(\d+\.?\d*)<',
        r'<strong[^>]*>(\d+\.\d)</strong>',
        r'itemprop=\"ratingValue\"[^>]*>(\d+\.?\d*)<',
        r'\"userRating\"\s*:\s*\"?(\d+\.?\d*)\"?',
        r'\"overallRating\"\s*:\s*\"?(\d+\.?\d*)\"?',
        r'(\d\.\d)\s*/\s*5',
        r'\"rating\"[\s:]+(\d+\.?\d*)',
    ]
    for pat in rating_patterns:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1))
                if scale_10:
                    if 1 <= val <= 10:
                        rating = str(val)
                        break
                else:
                    if 1 <= val <= 5:
                        rating = str(val)
                        break
            except ValueError:
                continue

    # Review count patterns
    count_patterns = [
        r'\"reviewCount\"[\s:]*\"?(\d+)',
        r'\"numberOfReviews\"[\s:]+(\d+)',
        r'([\d,]+)\s*reviews?',
        r'([\d,]+)\s*ratings?',
        r'\"reviewCount\">(\d+)<',
        r'\((\d+)\s*RATINGS?\)',
        r'(\d+)\s*Ratings',
        r'\"ratingCount\"\s*:\s*\"?(\d+)\"?',
    ]
    for pat in count_patterns:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            raw_count = m.group(1).replace(",", "")
            try:
                if int(raw_count) > 0:
                    review_count = raw_count
                    break
            except ValueError:
                review_count = None

    return rating, review_count


# ── Booking.com Platform ──────────────────────────────────

class BookingPlatform(RatingPlatform):
    name = "Booking.com"
    short_name = "booking"
    supports_headless = True
    needs_login = False
    scale = "/10"
    accepts = ['url', 'name']

    def _clean_url(self, url):
        match = re.match(r'(https://www\.booking\.com/hotel/[^?;]+)', url)
        return match.group(1) if match else url

    def _search_hotel(self, page, hotel_name, city=""):
        """Search Booking.com for a hotel by name + city. Returns first matching URL or None."""
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

    def _scrape_current_page(self, page):
        if '/hotel/' not in page.url:
            return None, None, 'redirected'
        try:
            page.evaluate("window.scrollBy(0, 500)")
        except Exception:
            if '/hotel/' not in page.url:
                return None, None, 'redirected'
        try:
            page.wait_for_timeout(800)
        except Exception:
            pass
        try:
            content = page.content()
        except Exception:
            return None, None, 'redirected'
        rating, review_count = extract_rating_review_count(content, scale_10=True)
        if rating and review_count:
            return rating, review_count, 'ok'
        elif rating:
            return rating, review_count, 'partial'
        return None, None, 'no_data'

    def scrape(self, page, input_data: dict) -> tuple:
        url = input_data.get('url', '').strip()
        name = input_data.get('name', '')
        city = input_data.get('city', '')
        fail_reason = 'unknown'

        if url and 'booking.com' in url:
            clean_url = self._clean_url(url)
            try:
                page.goto(clean_url, timeout=25000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
            except Exception:
                return None, None, 'timeout'

            if '/hotel/' in page.url:
                rating, review_count, fail_reason = self._scrape_current_page(page)
            else:
                fail_reason = 'redirected'

            if fail_reason == 'redirected' and name:
                try:
                    found_url = self._search_hotel(page, name, city)
                    if found_url:
                        if found_url.startswith('/'):
                            found_url = "https://www.booking.com" + found_url
                        clean_found = self._clean_url(found_url)
                        page.goto(clean_found, timeout=25000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)
                        rating, review_count, fail_reason = self._scrape_current_page(page)
                    else:
                        fail_reason = 'redirected_not_found'
                except Exception:
                    fail_reason = 'redirected_search_error'
            elif fail_reason == 'redirected' and not name:
                fail_reason = 'redirected'

            return rating, review_count, fail_reason
        else:
            # Name-based search
            try:
                found_url = self._search_hotel(page, name, city)
                if not found_url:
                    return None, None, 'not_found'
                if found_url.startswith('/'):
                    found_url = "https://www.booking.com" + found_url
                clean_url = self._clean_url(found_url)
                page.goto(clean_url, timeout=25000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                rating, review_count, fail_reason = self._scrape_current_page(page)
                return rating, review_count, fail_reason
            except Exception:
                return None, None, 'exception'

    def build_url(self, input_data: dict) -> str | None:
        url = input_data.get('url', '')
        if url and 'booking.com' in url:
            return self._clean_url(url)
        name = input_data.get('name', '')
        city = input_data.get('city', '')
        if name:
            query = f"{name} {city}".strip()
            query = re.sub(r'[^\w\s]', ' ', query).strip()
            return f"https://www.booking.com/searchresults.en-gb.html?ss={query.replace(' ', '+')}"
        return None


# ── MMT (MakeMyTrip) Platform ────────────────────────────

class MMTPlatform(RatingPlatform):
    name = "MakeMyTrip"
    short_name = "mmt"
    supports_headless = False
    needs_login = True
    scale = "/5"
    accepts = ['url', 'id']

    @property
    def cookies_path(self):
        return MMT_COOKIES

    def has_session(self):
        return MMT_COOKIES.exists()

    def login(self, parent_widget=None) -> bool:
        """Open real Chrome for MMT login, grab cookies."""
        import subprocess
        from playwright.sync_api import sync_playwright

        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        chrome = next((p for p in chrome_paths if os.path.exists(p)), None)

        debug_port = 9222
        user_data = str(COOKIES_DIR / "chrome_scrape")

        if chrome:
            proc = subprocess.Popen([
                chrome,
                f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={user_data}",
                "https://www.makemytrip.com/hotels/"
            ])
            proc.wait()
        else:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(channel="chrome", headless=False,
                                         args=[f"--remote-debugging-port={debug_port}",
                                               f"--user-data-dir={user_data}"])
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://www.makemytrip.com/hotels/", timeout=30000)
            input("Press Enter after logging in and closing Chrome...")
            browser.close()
            pw.stop()
            return True

        # Grab cookies via CDP
        try:
            proc2 = subprocess.Popen([
                chrome,
                f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={user_data}",
                "--headless=new",
                "about:blank"
            ])
            time.sleep(3)
            pw = sync_playwright().start()
            browser = pw.chromium.connect_over_cdp(f"http://localhost:{debug_port}")
            context = browser.contexts[0]
            cookies = context.cookies(["https://www.makemytrip.com"])
            with open(MMT_COOKIES, 'wb') as f:
                pickle.dump(cookies, f)
            browser.close()
            pw.stop()
            proc2.terminate()
        except Exception:
            pass
        return True

    def _get_mmt_browser(self):
        """Connect to the MMT Chrome instance with cookies loaded (Thread-safe)."""
        from playwright.sync_api import sync_playwright
        import subprocess, socket
        
        # 1. Ensure Chrome is running on 9222 (Only one thread starts it)
        with _browser_lock:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            res = sock.connect_ex(('127.0.0.1', 9222))
            sock.close()
            if res != 0:
                chrome_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                ]
                chrome = next((p for p in chrome_paths if os.path.exists(p)), None)
                if chrome:
                    user_data = str(COOKIES_DIR / "chrome_scrape")
                    subprocess.Popen([
                        chrome,
                        "--remote-debugging-port=9222",
                        f"--user-data-dir={user_data}",
                        "--no-first-run",
                        "--window-size=1280,800",
                        "about:blank"
                    ])
                    time.sleep(3)

        # 2. Get thread-local playwright manager
        if not hasattr(_thread_local, 'pw_manager') or _thread_local.pw_manager is None:
            pw = sync_playwright().start()
            _thread_local.pw_manager = pw
            with _browser_lock:
                _all_thread_pw_managers.append(pw)

        # 3. Connect thread-local manager to CDP
        if not hasattr(_thread_local, 'mmt_browser') or _thread_local.mmt_browser is None or not _thread_local.mmt_browser.is_connected():
            try:
                b = _thread_local.pw_manager.chromium.connect_over_cdp("http://localhost:9222")
                _thread_local.mmt_browser = b
                if MMT_COOKIES.exists():
                    with open(MMT_COOKIES, 'rb') as f:
                        cookies = pickle.load(f)
                    b.contexts[0].add_cookies(cookies)
            except Exception:
                return None
                
        return _thread_local.mmt_browser

    def scrape(self, page, input_data: dict) -> tuple:
        hotel_id = input_data.get('hotel_id', '')
        url = input_data.get('url', '')

        # Extract hotel ID from URL if not provided
        if not hotel_id and url:
            m = re.search(r'hotelId=(\w+)', url)
            if m:
                hotel_id = m.group(1)

        if not hotel_id:
            return None, None, 'no_id'

        # MMT requires visible browser with cookies — we use CDP connection
        browser = self._get_mmt_browser()
        if not browser:
            return None, None, 'browser_error'

        try:
            context = browser.contexts[0]
            mmt_page = context.new_page()
            url = f"https://www.makemytrip.com/hotels/hotel-details/?hotelId={hotel_id}&_uCurrency=INR&checkin=07202026&checkout=07212026&city=CTDEL&country=IN&roomStayQualifier=2e0e&locusId=CTDEL&locusType=city"
            try:
                mmt_page.goto(url, timeout=20000, wait_until="domcontentloaded")
            except:
                pass
            try:
                mmt_page.wait_for_timeout(1000)
            except:
                pass
            try:
                mmt_page.evaluate("window.scrollBy(0, 1000)")
            except:
                pass
            try:
                mmt_page.wait_for_timeout(800)
            except:
                pass

            content = mmt_page.content()
            mmt_page.close()

            if len(content) < 500:
                return None, None, 'no_data'

            rating, review_count = extract_rating_review_count(content, scale_10=False)
            if rating:
                return rating, review_count or 'N/A', 'ok'
            return rating or 'N/A', review_count or 'N/A', 'no_data'

        except Exception:
            return None, None, 'exception'

    def build_url(self, input_data: dict) -> str | None:
        hotel_id = input_data.get('hotel_id', '')
        url = input_data.get('url', '')
        if url and 'makemytrip' in url:
            return url
        if hotel_id:
            return f"https://www.makemytrip.com/hotels/hotel-details/?hotelId={hotel_id}"
        name = input_data.get('name', '')
        if name:
            query = name.replace(' ', '+')
            return f"https://www.makemytrip.com/hotels/?search={query}"
        return None


# ── Agoda Platform (stub for now) ─────────────────────────

class AgodaPlatform(RatingPlatform):
    name = "Agoda"
    short_name = "agoda"
    supports_headless = False
    needs_login = False
    scale = "/10"
    accepts = ['url', 'name']

    def scrape(self, page, input_data: dict) -> tuple:
        url = input_data.get('url', '')
        if not url or 'agoda.com' not in url:
            name = input_data.get('name', '')
            if name:
                query = name.replace(' ', '+')
                url = f"https://www.agoda.com/search?text={query}"
            else:
                return None, None, 'no_url'

        try:
            page.goto(url, timeout=25000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
        except Exception:
            return None, None, 'timeout'

        content = page.content()
        rating, review_count = extract_rating_review_count(content, scale_10=True)
        if rating:
            return rating, review_count or 'N/A', 'ok'
        return None, None, 'no_data'

    def build_url(self, input_data: dict) -> str | None:
        url = input_data.get('url', '')
        if url and 'agoda.com' in url:
            return url
        name = input_data.get('name', '')
        if name:
            query = name.replace(' ', '+')
            return f"https://www.agoda.com/search?text={query}"
        return None


# ── Expedia Platform (stub for now) ───────────────────────

class ExpediaPlatform(RatingPlatform):
    name = "Expedia"
    short_name = "expedia"
    supports_headless = False
    needs_login = False
    scale = "/10"
    accepts = ['url', 'name']

    def scrape(self, page, input_data: dict) -> tuple:
        url = input_data.get('url', '')
        if not url or 'expedia.com' not in url:
            name = input_data.get('name', '')
            if name:
                query = name.replace(' ', '+')
                url = f"https://www.expedia.com/hotels/search?text={query}"
            else:
                return None, None, 'no_url'

        try:
            page.goto(url, timeout=25000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
        except Exception:
            return None, None, 'timeout'

        content = page.content()
        rating, review_count = extract_rating_review_count(content, scale_10=True)
        if rating:
            return rating, review_count or 'N/A', 'ok'
        return None, None, 'no_data'

    def build_url(self, input_data: dict) -> str | None:
        url = input_data.get('url', '')
        if url and 'expedia.com' in url:
            return url
        name = input_data.get('name', '')
        if name:
            query = name.replace(' ', '+')
            return f"https://www.expedia.com/hotels/search?text={query}"
        return None


# ── Goibibo Platform ──────────────────────────────────────

class GoibiboPlatform(RatingPlatform):
    name = "Goibibo"
    short_name = "goibibo"
    supports_headless = False
    needs_login = False
    scale = "/5"
    accepts = ['url', 'name']

    def scrape(self, page, input_data: dict) -> tuple:
        url = input_data.get('url', '').strip()
        if not url:
            name = input_data.get('name', '')
            city = input_data.get('city', '')
            if name:
                query = f"{name} {city}".strip().replace(' ', '+')
                url = f"https://www.goibibo.com/hotels/find-hotels-in-india/?searchText={query}"
            else:
                return None, None, 'no_url'

        # Goibibo blocks headless, we reuse the MMT Chrome instance over CDP on 9222
        mmt = MMTPlatform()
        browser = mmt._get_mmt_browser()
        if not browser:
            return None, None, 'browser_error'

        try:
            context = browser.contexts[0]
            gi_page = context.new_page()
            try:
                gi_page.goto(url, timeout=25000, wait_until="domcontentloaded")
            except:
                pass
            try:
                gi_page.wait_for_timeout(2000)
            except:
                pass
            try:
                gi_page.evaluate("window.scrollBy(0, 600)")
            except:
                pass
            try:
                gi_page.wait_for_timeout(1000)
            except:
                pass

            content = gi_page.content()
            gi_page.close()

            if len(content) < 500:
                return None, None, 'no_data'

            rating, review_count = extract_rating_review_count(content, scale_10=False)
            if rating:
                return rating, review_count or 'N/A', 'ok'
            return rating or 'N/A', review_count or 'N/A', 'no_data'

        except Exception:
            return None, None, 'exception'

    def build_url(self, input_data: dict) -> str | None:
        url = input_data.get('url', '')
        if url and 'goibibo.com' in url:
            return url
        name = input_data.get('name', '')
        if name:
            query = name.replace(' ', '+')
            return f"https://www.goibibo.com/hotels/find-hotels-in-india/?searchText={query}"
        return None


# ── Shared browser pool management ────────────────────────

def _close_headless_browser():
    """Close all thread-local browsers and managers."""
    global _all_thread_browsers, _all_thread_pw_managers
    with _browser_lock:
        for b in _all_thread_browsers:
            try:
                b.close()
            except:
                pass
        _all_thread_browsers.clear()
        
        for pw in _all_thread_pw_managers:
            try:
                pw.stop()
            except:
                pass
        _all_thread_pw_managers.clear()


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


# ── Windows notification helper ──────────────────────────────

def notify_complete(message):
    """Play a sound and show a native Windows toast notification."""
    # Escape single quotes for PowerShell safety
    msg_escaped = message.replace("'", "''").replace('\n', ' — ')
    # Play system notification sound
    try:
        import winsound
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


# ── Platform Registry ─────────────────────────────────────

AVAILABLE_PLATFORMS: dict[str, RatingPlatform] = {
    'booking': BookingPlatform(),
    'mmt': MMTPlatform(),
    'goibibo': GoibiboPlatform(),
    'agoda': AgodaPlatform(),
    'expedia': ExpediaPlatform(),
}


def get_platform(short_name: str) -> RatingPlatform | None:
    return AVAILABLE_PLATFORMS.get(short_name)


def get_platform_by_url(url: str) -> RatingPlatform | None:
    """Detect which platform can handle a given URL."""
    url_lower = url.lower()
    for key, plat in AVAILABLE_PLATFORMS.items():
        if key in url_lower:
            return plat
    return None


def detect_input_type(text: str) -> dict:
    """
    Analyse input text and return structured data.
    Returns {'type': ..., 'platform': ..., 'name': ..., 'city': ..., 'url': ..., 'hotel_id': ...}
    """
    text = text.strip()
    result = {'type': 'unknown', 'platform': None, 'name': text, 'city': '', 'url': '', 'hotel_id': ''}

    # URL detection
    if 'booking.com/hotel/' in text:
        result['type'] = 'url'
        result['url'] = text
        result['platform'] = 'booking'
        # Extract hotel name from URL if possible
        m = re.search(r'/hotel/(?:in/)?([^/.?]+)', text)
        if m:
            result['name'] = m.group(1).replace('-', ' ').title()

    elif 'makemytrip.com' in text:
        result['type'] = 'url'
        result['url'] = text
        result['platform'] = 'mmt'
        m = re.search(r'hotelId=(\w+)', text)
        if m:
            result['hotel_id'] = m.group(1)

    elif 'agoda.com' in text:
        result['type'] = 'url'
        result['url'] = text
        result['platform'] = 'agoda'

    elif 'expedia.com' in text or 'expedia' in text:
        result['type'] = 'url'
        result['url'] = text
        result['platform'] = 'expedia'

    elif 'goibibo.com' in text:
        result['type'] = 'url'
        result['url'] = text
        result['platform'] = 'goibibo'
        # Goibibo ID can be in giHotelId or digits at the end of path
        m = re.search(r'giHotelId=(\w+)', text)
        if m:
            result['hotel_id'] = m.group(1)
        else:
            m2 = re.search(r'-(\d+)/?$', text)
            if m2:
                result['hotel_id'] = m2.group(1)

    elif 'http' in text:
        result['type'] = 'url'
        result['url'] = text

    # Numeric ID detection (FH ID / hotel ID)
    elif text.replace('#', '').strip().isdigit():
        result['type'] = 'id'
        result['hotel_id'] = text.replace('#', '').strip()
        result['platform'] = 'mmt'  # FH IDs are usually MMT

    # Default: treat as hotel name
    else:
        result['type'] = 'name'
        result['name'] = text
        # Try to detect "name, city" format
        if ',' in text:
            parts = [p.strip() for p in text.split(',', 1)]
            result['name'] = parts[0]
            result['city'] = parts[1] if len(parts) > 1 else ''

    return result


# ── Legacy wrapper functions (for backward compat with ratings_tab.py) ────
# These delegate to the platform instances so callers don't need to import app.py

def clean_booking_url(url):
    plat = get_platform('booking')
    if plat:
        return plat._clean_url(url)
    match = re.match(r'(https://www\.booking\.com/hotel/[^?;]+)', url)
    return match.group(1) if match else url


def search_booking_hotel(page, hotel_name, city=""):
    plat = get_platform('booking')
    if plat:
        return plat._search_hotel(page, hotel_name, city)
    return None


def scrape_hotel(url, name=None, city=None):
    """Scrape a Booking.com hotel for rating and reviews."""
    plat = get_platform('booking')
    if not plat:
        return None, None, 'no_platform'
    page = plat.new_page()
    try:
        rating, review_count, fail_reason = plat.scrape(page, {
            'url': url, 'name': name or '', 'city': city or ''
        })
        return rating, review_count, fail_reason
    finally:
        try:
            page.close()
        except:
            pass


def search_and_scrape(hotel_name, city=""):
    """Search Booking.com by name and scrape."""
    plat = get_platform('booking')
    if not plat:
        return None, None, None, 'no_platform'
    page = plat.new_page()
    try:
        found_url = plat._search_hotel(page, hotel_name, city)
        if not found_url:
            page.close()
            return None, None, None, 'not_found'
        if found_url.startswith('/'):
            found_url = "https://www.booking.com" + found_url
        clean_url = plat._clean_url(found_url)
        try:
            page.goto(clean_url, timeout=25000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
        except:
            page.close()
            return None, None, clean_url, 'timeout'
        rating, review_count, fail_reason = plat._scrape_current_page(page)
        page.close()
        return rating, review_count, clean_url, fail_reason
    except:
        try:
            page.close()
        except:
            pass
        return None, None, None, 'exception'


def mmt_login():
    """Open real Chrome for MMT login, grab cookies when user closes it."""
    plat = get_platform('mmt')
    if plat:
        return plat.login()
    return False


def mmt_has_session():
    """Check if MMT login session exists."""
    plat = get_platform('mmt')
    if plat:
        return plat.has_session()
    return False


def scrape_mmt_hotel(hotel_id):
    """Scrape MMT hotel using real Chrome via CDP."""
    plat = get_platform('mmt')
    if not plat or not plat.has_session():
        return None, None
    rating, review_count, _ = plat.scrape(None, {'hotel_id': hotel_id})
    return rating, review_count


def _start_mmt_chrome():
    """Start a Chrome instance connected to MMT's CDP."""
    plat = get_platform('mmt')
    if plat:
        return plat._get_mmt_browser()
    return None


def get_shared_browser():
    """Get the shared headless Playwright browser."""
    return _get_headless_browser()


def close_shared_browser():
    """Close the shared headless Playwright browser."""
    _close_headless_browser()


def scrape_goibibo_hotel(url, name="", city=""):
    """Scrape Goibibo hotel using Chrome via CDP."""
    plat = get_platform('goibibo')
    if not plat:
        return None, None
    rating, review_count, _ = plat.scrape(None, {'url': url, 'name': name, 'city': city})
    return rating, review_count
