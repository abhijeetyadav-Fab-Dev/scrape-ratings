"""
MMT API-Based Scraper
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Intercepts MMT's internal API calls to extract hotel ratings.
Works by:
  1. Connecting to a real Chrome session via CDP (with MMT cookies)
  2. Setting up response interception for relevant API endpoints
  3. Navigating to the hotel details page
  4. Waiting for React to render (rating elements in DOM)
  5. Extracting rating from intercepted API responses OR from rendered DOM
  
This replaces the old Selenium-based HTML parsing approach.
"""

import json, os, time, subprocess, pickle, re, threading
from pathlib import Path
from typing import Optional

COOKIES_DIR = Path.home() / ".scrape-ratings"
MMT_COOKIES = COOKIES_DIR / "mmt_cookies.pkl"
CHROME_USER_DATA = str(COOKIES_DIR / "chrome_scrape")
CDP_PORT = 9222


# ── Chrome process management ─────────────────────────────

def _find_chrome() -> Optional[str]:
    """Find Chrome executable."""
    paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    return next((p for p in paths if os.path.exists(p)), None)


def _kill_chrome_on_port(port: int = CDP_PORT):
    """Kill any existing Chrome instances on the debug port."""
    try:
        result = subprocess.run(
            f'netstat -ano | findstr :{port}',
            capture_output=True, text=True, shell=True, timeout=5
        )
        for line in result.stdout.strip().split('\n'):
            if 'LISTENING' in line:
                parts = line.strip().split()
                if parts:
                    pid = parts[-1]
                    try:
                        subprocess.run(['taskkill', '/F', '/PID', pid],
                                       capture_output=True, timeout=5)
                    except:
                        pass
    except:
        pass
    time.sleep(0.5)


def _start_chrome_cdp() -> Optional[subprocess.Popen]:
    """Start Chrome with CDP enabled for remote debugging."""
    chrome = _find_chrome()
    if not chrome:
        return None
    
    _kill_chrome_on_port(CDP_PORT)
    
    proc = subprocess.Popen([
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={CHROME_USER_DATA}",
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--window-size=1280,900",
        "about:blank",
    ])
    time.sleep(3)  # Wait for Chrome to start
    return proc


# ── MMT API Scraper ───────────────────────────────────────

class MMTAPIScraper:
    """
    Scrapes MMT hotel ratings by intercepting internal API calls.
    
    Usage:
        scraper = MMTAPIScraper()
        result = scraper.scrape("32775")
        # Returns: {"rating": "4.2", "review_count": "10998", "status": "ok"}
        scraper.close()
    """
    
    def __init__(self):
        self._chrome_proc: Optional[subprocess.Popen] = None
        self._pw = None
        self._browser = None
        self._intercepted_data = []
    
    def _ensure_browser(self):
        """Start Chrome + Playwright CDP connection if not already running."""
        if self._browser and self._browser.is_connected():
            return True
        
        self._chrome_proc = _start_chrome_cdp()
        if not self._chrome_proc:
            return False
        
        from playwright.sync_api import sync_playwright
        
        self._pw = sync_playwright().start()
        
        try:
            self._browser = self._pw.chromium.connect_over_cdp(
                f"http://localhost:{CDP_PORT}", timeout=10000
            )
        except Exception as e:
            print(f"CDP connect error: {e}")
            return False
        
        # Add MMT cookies if available
        if MMT_COOKIES.exists():
            try:
                with open(MMT_COOKIES, 'rb') as f:
                    cookies = pickle.load(f)
                context = self._browser.contexts[0]
                context.add_cookies(cookies)
            except Exception as e:
                print(f"Cookie load error: {e}")
        
        return True
    
    def scrape(self, hotel_id: str) -> dict:
        """
        Scrape rating and review count for a given MMT hotel ID.
        
        Returns:
            {"rating": str|None, "review_count": str|None, 
             "status": str, "source": str}
        
        Status values: 'ok', 'partial', 'no_data', 'no_id', 'browser_error',
                       'timeout', 'not_found'
        Source: 'api' (from intercepted API), 'dom' (from rendered page)
        """
        if not hotel_id:
            return {"rating": None, "review_count": None,
                    "status": "no_id", "source": ""}
        
        if not self._ensure_browser():
            return {"rating": None, "review_count": None,
                    "status": "browser_error", "source": ""}
        
        self._intercepted_data = []
        
        # Build the hotel URL with proper params for search-rooms API
        hotel_url = (
            f"https://www.makemytrip.com/hotels/hotel-details/"
            f"?hotelId={hotel_id}"
            f"&checkin=07202026&checkout=07212026"
            f"&city=CTDEL&country=IN"
            f"&roomStayQualifier=2e0e"
            f"&locusId=CTDEL&locusType=city"
            f"&_uCurrency=INR"
        )
        
        try:
            context = self._browser.contexts[0]
            page = context.new_page()
            
            # ── Set up response interception ──
            captured = {
                'api_responses': [],
                'mob_config': None,
                'rating_found': False,
                'rating_source': None,
            }
            
            def on_response(response):
                url = response.url
                status = response.status
                ct = response.headers.get('content-type', '') or ''
                
                if status != 200 or 'json' not in ct:
                    return
                
                # Only capture mapi endpoints
                if 'mapi.makemytrip.com' not in url:
                    return
                
                try:
                    data = response.json()
                    url_short = url.split('?')[0][:150]
                    
                    # Try to parse rating data from JSON response
                    data_str = json.dumps(data, default=str)
                    
                    record = {
                        'url': url_short,
                        'body': data_str[:20000],
                        'full_len': len(data_str),
                    }
                    captured['api_responses'].append(record)
                    
                    # Save specific endpoints
                    if 'getMobConfig' in url:
                        captured['mob_config'] = data
                    
                except:
                    pass
            
            page.on("response", on_response)
            
            # ── Navigate to hotel page ──
            try:
                page.goto(hotel_url, timeout=25000, wait_until="domcontentloaded")
            except Exception as e:
                pass  # Navigation may timeout, that's OK
            
            # ── Wait for rating to appear in DOM ──
            rating_from_dom = None
            review_count_from_dom = None
            
            try:
                page.wait_for_function(
                    """() => {
                        const text = document.body.innerText;
                        return /\\d+\\.\\d\\s*\\/?\\s*5/.test(text);
                    }""",
                    timeout=12000
                )
            except:
                pass  # Timeout waiting for rating
            
            page.wait_for_timeout(2000)  # Extra settle time
            
            # ── Extract rating from DOM ──
            try:
                dom_data = page.evaluate("""() => {
                    const text = document.body.innerText;
                    const results = {};
                    
                    // Find rating pattern: "X.Y /5" or "X.Y/5"
                    const ratingMatch = text.match(/(\\d+\\.\\d)\\s*\\/?\\s*5/);
                    if (ratingMatch) results.rating = ratingMatch[1];
                    
                    // Find review count: "XXXXX Ratings"
                    const countMatch = text.match(/([\\d,]+)\\s*Ratings/);
                    if (countMatch) results.reviewCount = countMatch[1].replace(',', '');
                    
                    // Find hotel name in h1
                    const h1 = document.querySelector('h1');
                    if (h1) results.hotelName = h1.innerText.trim().slice(0,100);
                    
                    // Try to read from __INITIAL_STATE__ - might have the data after API response
                    try {
                        const state = window.__INITIAL_STATE__;
                        if (state && state.hotelDetail && state.hotelDetail.topHotel && 
                            state.hotelDetail.topHotel.length > 0) {
                            const hotel = state.hotelDetail.topHotel[0];
                            results.initialStateHotel = hotel;
                        }
                    } catch(e) {}
                    
                    return results;
                }""")
                
                rating_from_dom = dom_data.get('rating')
                review_count_from_dom = dom_data.get('reviewCount')
                
            except Exception as e:
                print(f"DOM extraction error: {e}")
            
            # ── Check if initial state now has hotel data ──
            initial_state_hotel = dom_data.get('initialStateHotel') if dom_data else None
            
            # ── Try to get rating from getMobConfig if available ──
            rating_from_api = None
            review_count_from_api = None
            
            if captured.get('mob_config'):
                try:
                    config_str = json.dumps(captured['mob_config'], default=str)
                    # Search for rating patterns in config
                    m = re.search(r'\"userRating\"\\s*:\\s*\"?([0-9]+\\.?[0-9]*)\"?', config_str)
                    if m:
                        rating_from_api = m.group(1)
                except:
                    pass
            
            # ── Also try to extract from initial state hotel data ──
            if initial_state_hotel and isinstance(initial_state_hotel, dict):
                for key in initial_state_hotel:
                    kl = key.lower()
                    if any(x in kl for x in ['rating', 'review', 'score', 'userrating']):
                        if not rating_from_dom:
                            rating_from_dom = str(initial_state_hotel[key])
            
            # ── Parse page content with regex as final fallback ──
            if not rating_from_dom:
                try:
                    content = page.content()
                    for pat in [
                        r'(\\d+\\.\\d)\\s*/\\s*5',
                        r'\"userRating\"\\s*:\\s*\"?([0-9]+\\.?[0-9]*)\"?',
                        r'\"rating\"\\s*:\\s*\"?([0-9]+\\.?[0-9]*)\"?',
                    ]:
                        m = re.search(pat, content)
                        if m:
                            val = float(m.group(1))
                            if 1 <= val <= 5:
                                rating_from_dom = str(val)
                                break
                except:
                    pass
            
            page.close()
            
            # ── Determine result ──
            rating = rating_from_dom or rating_from_api
            review_count = review_count_from_dom
            
            if rating and review_count:
                return {
                    "rating": rating,
                    "review_count": review_count,
                    "status": "ok",
                    "source": "dom" if rating_from_dom else "api",
                    "hotel_name": dom_data.get('hotelName', '') if dom_data else '',
                    "num_api_calls": len(captured['api_responses']),
                }
            elif rating:
                return {
                    "rating": rating,
                    "review_count": review_count or "N/A",
                    "status": "partial",
                    "source": "dom",
                    "hotel_name": dom_data.get('hotelName', '') if dom_data else '',
                    "num_api_calls": len(captured['api_responses']),
                }
            else:
                return {
                    "rating": None,
                    "review_count": None,
                    "status": "no_data",
                    "source": "",
                    "hotel_name": dom_data.get('hotelName', '') if dom_data else '',
                    "num_api_calls": len(captured['api_responses']),
                }
                
        except Exception as e:
            return {
                "rating": None,
                "review_count": None,
                "status": "exception",
                "source": "",
                "error": str(e)[:200],
            }
    
    def close(self):
        """Clean up browser resources."""
        try:
            if self._browser:
                self._browser.close()
        except:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except:
            pass
        try:
            if self._chrome_proc:
                self._chrome_proc.terminate()
        except:
            pass
        self._browser = None
        self._pw = None
        self._chrome_proc = None


# ── Convenience function ──────────────────────────────────

def scrape_mmt_via_api(hotel_id: str) -> dict:
    """Simple one-shot function to scrape MMT hotel rating."""
    scraper = MMTAPIScraper()
    try:
        result = scraper.scrape(hotel_id)
        return result
    finally:
        scraper.close()


# ── CLI test ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    hotel_id = sys.argv[1] if len(sys.argv) > 1 else "32775"
    result = scrape_mmt_via_api(hotel_id)
    print(json.dumps(result, indent=2))
