"""
Deep Research AI Agent Overlay & Web Crawler Widget
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This module implements:
  1. A floating, futuristic AI Agent helper (Draggable, beautiful glassmorphism style).
  2. Integrated Deep Research query crawler utilizing a headless search/evaluation engine.
  3. Context-aware help for Ratings Scraper, God Mode, and Universal Scraper.
  4. Feeds verified URL results, numeric IDs, or listings directly back to the active scraping queue.
"""

import re, time, threading
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTextEdit, QFrame, QScrollArea, QGraphicsDropShadowEffect, QApplication
)
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor

from ratings_platforms import _get_headless_browser, detect_input_type, get_platform

# Simple thread-safe bridge to notify GUI thread from web crawler
class DeepResearchSignals(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(dict)  # returns {'url': ..., 'hotel_id': ..., 'name': ...}

class DeepResearchWorker(threading.Thread):
    """Crawl the web to identify listing codes, official pages or details for a hotel name/query."""
    
    def __init__(self, query: str, platform_filter: str = 'any', deep_extract: bool = False):
        super().__init__()
        self.query = query
        self.platform_filter = platform_filter
        self.deep_extract = deep_extract
        self.signals = DeepResearchSignals()
        self.daemon = True

    def run(self):
        # Split query by lines or commas for bulk search
        raw_queries = [q.strip() for q in re.split(r'\n|,', self.query) if q.strip()]
        
        conversational_phrases = [
            "get me frontend links for these hotels",
            "get me frontend links",
            "get me links",
            "find links for",
            "is this hotel still live and running",
            "is this hotel live and running",
            "is this hotel still live",
            "is this hotel live",
            "and running",
            "running",
            "live",
            "still",
            "?",
            "please",
            "check if"
        ]
        
        valid_queries = []
        for q in raw_queries:
            q_lower = q.lower()
            is_filler = False
            for phrase in conversational_phrases:
                if q_lower == phrase or q_lower == phrase + " ?" or q_lower == phrase + " -":
                    is_filler = True
                    break
            if not is_filler:
                # Clean inline parts
                for phrase in conversational_phrases:
                    q = re.sub(rf'(?i)\b{re.escape(phrase)}\b', '', q).strip()
                q = q.replace('-', '').strip()
                if q:
                    valid_queries.append(q)

        if not valid_queries:
            self.signals.log.emit("❌ No valid hotel names found in query after sanitization.")
            self.signals.finished.emit({'error': 'No valid queries'})
            return

        self.signals.log.emit(f"🤖 Agent Initiated: Batch Deep Research on {len(valid_queries)} target(s)...")
        
        browser = None
        page = None
        try:
            browser = _get_headless_browser()
            page = browser.new_page()
            page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            
            for i, target in enumerate(valid_queries, 1):
                search_query = f"{target}"
                if self.platform_filter:
                    if self.platform_filter == 'mmt':
                        search_query += " site:makemytrip.com/hotels/"
                    elif self.platform_filter == 'booking':
                        search_query += " site:booking.com/hotel/"
                    elif self.platform_filter == 'agoda':
                        search_query += " site:agoda.com/"
                    elif self.platform_filter == 'goibibo':
                        search_query += " site:goibibo.com/hotels/"
                    elif self.platform_filter == 'expedia':
                        search_query += " site:expedia.com/"
                        
                self.signals.log.emit(f"[{i}/{len(valid_queries)}] 🔍 Searching Index for: '{target[:30]}'...")
                
                target_link = None
                links = []
                
                # 1. Yahoo (Fastest, High Resilience)
                try:
                    yahoo_url = f"https://search.yahoo.com/search?q={search_query.replace(' ', '+')}"
                    page.goto(yahoo_url, timeout=12000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    links = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(el => ({href: el.href, text: el.innerText || el.textContent || ''}))")
                except Exception:
                    pass

                # 2. Bing
                if not links:
                    try:
                        bing_url = f"https://www.bing.com/search?q={search_query.replace(' ', '+')}"
                        page.goto(bing_url, timeout=12000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)
                        links = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(el => ({href: el.href, text: el.innerText || el.textContent || ''}))")
                    except Exception:
                        pass
                
                # 3. DuckDuckGo
                if not links:
                    try:
                        ddg_url = f"https://html.duckduckgo.com/html/?q={search_query.replace(' ', '+')}"
                        page.goto(ddg_url, timeout=15000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)
                        links = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(el => ({href: el.href, text: el.innerText || el.textContent || ''}))")
                    except Exception:
                        pass

                # 4. Google (Last Resort due to Captchas)
                if not links:
                    google_url = f"https://www.google.com/search?q={search_query.replace(' ', '+')}"
                    try:
                        page.goto(google_url, timeout=12000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)
                        raw_links = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(el => ({href: el.href, text: el.innerText || el.textContent || ''}))")
                        if raw_links and not any('sorry/index' in l.get('href', '') for l in raw_links):
                            links = raw_links
                        else:
                            self.signals.log.emit("  ⚠️ Google bot detection on final fallback.")
                    except Exception:
                        pass

                domains = {
                    'booking': 'booking.com/hotel/',
                    'mmt': 'makemytrip.com/hotels/',
                    'goibibo': 'goibibo.com/hotels/',
                    'agoda': 'agoda.com/',
                    'expedia': 'expedia.com/Hotels'
                }
                
                domains_patterns = {
                    'booking': ['booking.com/hotel/'],
                    'mmt': ['makemytrip.com/hotels/', 'makemytrip.com/hotels-international/'],
                    'goibibo': ['goibibo.com/hotels/'],
                    'agoda': ['agoda.com/'],
                    'expedia': ['expedia.com/']
                }

                # Helper to extract statically wrapped URLs (Yahoo RU=, Google url=, etc.)
                def extract_wrapped_url(url_str):
                    if not url_str or not url_str.startswith('http'):
                        return url_str
                    try:
                        parsed = urlparse(url_str)
                        query_params = parse_qs(parsed.query)
                        for param in ['ru', 'url', 'q', 'dest', 'redirect', 'target']:
                            for k, vals in query_params.items():
                                if k.lower() == param:
                                    val = vals[0]
                                    if val.startswith('http'):
                                        return val
                    except Exception:
                        pass
                    return url_str

                # Candidates check
                candidates = []
                for link in links:
                    href = link.get('href', '') if isinstance(link, dict) else ''
                    if not href or not href.startswith('http'):
                        continue
                    if any(x in href.lower() for x in ('google.com/search', 'webcache', 'duckduckgo.com', 'yahoo.com/search', 'bing.com/search', 'yimg.com', 'microsoft.com')):
                        continue
                    
                    # Decoded candidate
                    decoded_href = extract_wrapped_url(href)
                    candidates.append((href, decoded_href))

                # Filter candidates by domain patterns
                filtered_candidates = []
                for orig_href, decoded_href in candidates:
                    matched_plat = None
                    for plat_key, patterns in domains_patterns.items():
                        if any(pat in decoded_href.lower() for pat in patterns):
                            matched_plat = plat_key
                            break
                    
                    if self.platform_filter and self.platform_filter != 'any':
                        if matched_plat == self.platform_filter:
                            filtered_candidates.append((orig_href, decoded_href, matched_plat))
                    else:
                        if matched_plat:
                            filtered_candidates.append((orig_href, decoded_href, matched_plat))

                # If we don't have direct pattern matches, consider external tracker/redirect links
                if not filtered_candidates:
                    for orig_href, decoded_href in candidates:
                        exclude_domains = ('reviewcentre.com', 'tripadvisor.com', 'facebook.com', 'twitter.com', 'youtube.com', 'instagram.com', 'linkedin.com')
                        if not any(x in decoded_href.lower() for x in exclude_domains):
                            filtered_candidates.append((orig_href, decoded_href, None))

                for orig_href, decoded_href, expected_plat in filtered_candidates:
                    self.signals.log.emit(f"  🔗 Resolving redirect for: {decoded_href[:60]}...")
                    resolved_url = decoded_href
                    try:
                        page.goto(decoded_href, timeout=10000, wait_until="domcontentloaded")
                        resolved_url = page.url
                    except Exception:
                        if orig_href != decoded_href:
                            try:
                                page.goto(orig_href, timeout=10000, wait_until="domcontentloaded")
                                resolved_url = page.url
                            except Exception:
                                pass
                    
                    # Verify resolved URL matches domain patterns
                    final_plat = None
                    for plat_key, patterns in domains_patterns.items():
                        if any(pat in resolved_url.lower() for pat in patterns):
                            final_plat = plat_key
                            break
                    
                    # Enforce platform filter on final resolved URL
                    if self.platform_filter and self.platform_filter != 'any':
                        if final_plat == self.platform_filter:
                            target_link = resolved_url
                            break
                    else:
                        if final_plat:
                            target_link = resolved_url
                            break

                if target_link:
                    detected = detect_input_type(target_link)
                    plat = detected.get('platform')
                    hid = detected.get('hotel_id', '')
                    
                    # ── Extract Hotel ID for MakeMyTrip (MMT) ──
                    if plat == 'mmt' and not hid and self.deep_extract:
                        self.signals.log.emit("  🕵️ Deep extracting MMT Hotel ID...")
                        # First, try to get hotel_id from URL query parameters (case-insensitive)
                        try:
                            url_parts = urlparse(target_link)
                            query = parse_qs(url_parts.query)
                            query_lower = {k.lower(): v for k, v in query.items()}
                            if 'hotelid' in query_lower:
                                hid = query_lower['hotelid'][0]
                                self.signals.log.emit(f"  ✓ Found ID in URL query: {hid}")
                            elif 'tophtlid' in query_lower:
                                hid = query_lower['tophtlid'][0]
                                self.signals.log.emit(f"  ✓ Found ID in URL query (topHtlId): {hid}")
                        except Exception as e:
                            self.signals.log.emit(f"⚠️ URL query parsing failed: {e}")
                        # If still not found, fetch page content and search for common patterns
                        if not hid:
                            try:
                                if page:
                                    try:
                                        page.wait_for_load_state("load", timeout=3000)
                                    except Exception:
                                        pass
                                    
                                    # 1. Try to evaluate JavaScript to extract ID dynamically
                                    try:
                                        evaluated_id = page.evaluate("""() => {
                                            try {
                                                // Check __INITIAL_STATE__
                                                if (window.__INITIAL_STATE__) {
                                                    const state = window.__INITIAL_STATE__;
                                                    if (state.hotelDetail && state.hotelDetail.hotelId) {
                                                        return String(state.hotelDetail.hotelId);
                                                    }
                                                    if (state.hotelDetail && state.hotelDetail.hotelid) {
                                                        return String(state.hotelDetail.hotelid);
                                                    }
                                                    const findId = (obj) => {
                                                        if (!obj || typeof obj !== 'object') return null;
                                                        if (obj.hotelId) return String(obj.hotelId);
                                                        if (obj.hotelid) return String(obj.hotelid);
                                                        for (let k in obj) {
                                                            if (obj.hasOwnProperty(k)) {
                                                                let res = findId(obj[k]);
                                                                if (res) return res;
                                                            }
                                                        }
                                                        return null;
                                                    };
                                                    let res = findId(state);
                                                    if (res) return res;
                                                }
                                                // Check script tags text patterns
                                                const scripts = document.querySelectorAll('script');
                                                for (let script of scripts) {
                                                    let text = script.textContent || '';
                                                    let m = text.match(/"hotelId"\\s*:\\s*"?(\\d+)"?/i) || text.match(/hotelId\\s*=\\s*"?(\\d+)"?/i) || text.match(/"mtxHotelId"\\s*:\\s*"?(\\d+)"?/i);
                                                    if (m) return m[1];
                                                }
                                                // Meta/link tag canonical url
                                                let meta = document.querySelector('meta[property="og:url"]') || document.querySelector('link[rel="canonical"]');
                                                if (meta) {
                                                    let url = meta.content || meta.href || '';
                                                    let m = url.match(/hotelId=(\\d+)/i) || url.match(/topHtlId=(\\d+)/i);
                                                    if (m) return m[1];
                                                }
                                            } catch(e) {}
                                            return "";
                                        }""")
                                        if evaluated_id:
                                            hid = evaluated_id
                                            self.signals.log.emit(f"  ✓ Found ID via page evaluation: {hid}")
                                    except Exception as e:
                                        self.signals.log.emit(f"⚠️ Page evaluation failed: {e}")

                                    if not hid:
                                        try:
                                            html = page.content()
                                        except Exception:
                                            page.wait_for_timeout(2000)
                                            html = page.content()
                                else:
                                    import urllib.request
                                    req = urllib.request.Request(target_link, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                                    html = urllib.request.urlopen(req, timeout=5).read().decode('utf-8')
                                
                                if not hid:
                                    # Look for JSON field mtxHotelId or simple hotelId parameter in HTML source
                                    m = re.search(r'"mtxHotelId"\s*:\s*"?(\d+)"?', html) or re.search(r'hotelId\s*=\s*"?(\d+)"?', html) or re.search(r'hotelId(?:["\':\s]*)([a-zA-Z0-9_]+)', html)
                                    if m:
                                        hid = m.group(1)
                                        self.signals.log.emit(f"  ✓ Found ID from page source regex: {hid}")
                            except Exception as e:
                                self.signals.log.emit(f"⚠️ Deep ID extraction failed: {e}")

                    # ── Inject Optimal Future Date (45 days out) ──
                    try:
                        parsed = urlparse(target_link)
                        query_params = parse_qs(parsed.query)
                        
                        # Strip existing date parameters to prevent conflicts
                        for key in ['checkin', 'checkout', 'checkIn', 'checkOut']:
                            if key in query_params:
                                del query_params[key]
                                
                        future_in = datetime.now() + timedelta(days=45)
                        future_out = future_in + timedelta(days=1)
                        
                        if plat == 'mmt':
                            query_params['checkin'] = [future_in.strftime("%m%d%Y")]
                            query_params['checkout'] = [future_out.strftime("%m%d%Y")]
                        elif plat in ('booking', 'agoda', 'expedia', 'goibibo'):
                            query_params['checkin'] = [future_in.strftime("%Y-%m-%d")]
                            query_params['checkout'] = [future_out.strftime("%Y-%m-%d")]
                            
                        # Reconstruct URL
                        new_query = urlencode(query_params, doseq=True)
                        target_link = urlunparse(parsed._replace(query=new_query))
                    except Exception as e:
                        print(f"Date injection failed: {e}")

                    # Combine URL and Hotel ID for the bulk scraper text box
                    output_link = f"{target_link} | {hid}" if hid else target_link

                    self.signals.log.emit(f"  🎉 Resolved: {target_link[:60]}...")
                    self.signals.finished.emit({
                        'url': output_link,
                        'hotel_id': hid,
                        'name': detected.get('name', target) if detected else target,
                        'platform': plat
                    })
                else:
                    self.signals.log.emit(f"  ❌ Failed to resolve footprint for '{target}'.")
            
            self.signals.log.emit(f"\n✅ Batch Deep Research Completed on {len(valid_queries)} targets.")
            self.signals.finished.emit({'batch_finished': True})
                    
        except Exception as e:
            self.signals.log.emit(f"❌ Research failed: {e}")
        finally:
            if page:
                try: page.close()
                except: pass

class AgentReasoningSignals(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(str)

class AgentReasoningWorker(threading.Thread):
    def __init__(self, query: str):
        super().__init__()
        self.query = query
        self.signals = AgentReasoningSignals()
        self.daemon = True

    def run(self):
        query = self.query.lower()
        
        if any(x in query for x in ('hi', 'hello', 'hey', 'active', 'assist')):
            self.signals.finished.emit(
                "🤖 **Antigravity Agent (Gemini Core)**:\n"
                "I am online and synchronized with your scraping engine! I have access to deep context about your scraping modules:\n"
                "  • **Booking.com**: Scrapes headlessly with strict zero-tolerance property card selectors (`[data-testid=\"property-card\"]`).\n"
                "  • **MakeMyTrip (MMT)**: Direct API extraction using viewport configuration emulation to prevent auth blocks.\n"
                "  • **Goibibo & Agoda**: Live footprint resolvers.\n\n"
                "👉 Ask me a question about a hotel (e.g. 'How many ratings does Hotel XYZ have?'), and I'll scrape it live for you!"
            )
            return
            
        elif "what can you do" in query or "capabilities" in query:
            self.signals.finished.emit(
                "🤖 **Antigravity Agent Capabilities**:\n"
                "I am an active reasoning engine! Here is what I can do:\n"
                "  1. **Answer live questions**: Ask me about a hotel's ratings or reviews, and I will crawl the web to answer it instantly.\n"
                "  2. **Deep Research**: Click the search button below to crawl search indexes to find direct listing URLs.\n"
                "  3. **Auto-Injection**: I automatically feed resolved links to your active scraper workspace.\n"
                "  4. **Context Analysis**: I can diagnose errors and guide you to bypass Captchas or auth blocks."
            )
            return
            
        elif "booking" in query:
            self.signals.finished.emit(
                "🤖 **Booking.com Expert Context**:\n"
                "Our Booking scraper is optimized for headless mode. We resolved previous lenient search issues by enforcing rigid selector matching on listing titles:\n"
                "  1. It ignores general town/city cards.\n"
                "  2. If the user query is 'FabHotel Roomers', it matches exact text titles rather than picking the closest popular destination.\n"
                "  3. If you encounter incorrect listings, try searching the exact name with the location, or trigger **Deep Research** to fetch the direct URL."
            )
            return

        elif "mmt" in query or "makemytrip" in query:
            self.signals.finished.emit(
                "🤖 **MakeMyTrip (MMT) Expert Context**:\n"
                "MMT has aggressive bot protection. Our scraper is equipped with:\n"
                "  • **Direct API Probe**: Extracts JSON configurations directly bypassing the standard web UI.\n"
                "  • **CDP Capture**: Intercepts active network calls synchronously.\n"
                "  • **Cookie Session Persistence**: Saves cookies locally under `.scrape-ratings/mmt_cookies.pkl`.\n"
                "💡 *Tip*: If MMT ratings fail, ensure your Chrome session has cookies saved or run in visible mode once to log in."
            )
            return

        elif "error" in query or "fail" in query or "incorrect" in query:
            self.signals.finished.emit(
                "🤖 **Error Resolution Guide**:\n"
                "If a ratings query returns an incorrect hotel or fails to fetch:\n"
                "  • **For search queries**: The search engine might return destination lists rather than the hotel. Use the **Deep Research** button to auto-crawl Yahoo/Bing indexes to find the direct listing page.\n"
                "  • **For URL inputs**: Ensure the input URL is fully-formed (e.g. starts with `https://www.booking.com/hotel/...`)."
            )
            return
            
        # Check if query asks for ratings/reviews of a specific hotel
        if any(x in query for x in ('rating', 'review', 'how many', 'status', 'live')):
            self.signals.log.emit(f"🧠 Agent Reasoning: Extracting hotel intent from '{self.query}'...")
            
            # Simple keyword extraction (remove stop words)
            stop_words = ["how", "many", "ratings", "and", "reviews", "are", "there", "on", "this", "hotel", "what", "is", "the", "status", "of", "?", "-", "live"]
            hotel_name = self.query
            for w in stop_words:
                hotel_name = re.sub(rf'\b{w}\b', '', hotel_name, flags=re.IGNORECASE)
            hotel_name = hotel_name.replace('?', '').replace('-', '').strip()
            
            if not hotel_name:
                hotel_name = self.query
                
            self.signals.log.emit(f"🔍 Agent Reasoning: Searching Yahoo Index for '{hotel_name}'...")
            
            # Run DeepResearch equivalent specifically for Yahoo
            browser = None
            page = None
            try:
                browser = _get_headless_browser()
                page = browser.new_page()
                page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                
                yahoo_url = f"https://search.yahoo.com/search?q={hotel_name.replace(' ', '+')}"
                page.goto(yahoo_url, timeout=15000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                links = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(el => ({href: el.href, text: el.innerText || el.textContent || ''}))")
                
                target_link = None
                domains = ['booking.com/hotel/', 'makemytrip.com/hotels/', 'goibibo.com/hotels/', 'agoda.com/', 'expedia.com/Hotels']
                
                for link in links:
                    href = link.get('href', '') if isinstance(link, dict) else ''
                    if any(dom in href.lower() for dom in domains):
                        target_link = href
                        # Resolve possible Yahoo redirect to final URL
                        try:
                            page.goto(target_link, timeout=15000, wait_until="domcontentloaded")
                            target_link = page.url
                            self.signals.log.emit(f"✅ Resolved final URL: {target_link[:60]}...")
                        except Exception as e:
                            self.signals.log.emit(f"⚠️ Redirect resolution failed: {e}")
                        break
                        
                if target_link:
                    self.signals.log.emit(f"✅ Footprint identified: {target_link[:60]}...\nExtracting live ratings from platform...")
                    detected = detect_input_type(target_link)
                    if detected and 'platform' in detected:
                        plat_name = detected['platform']
                        plat = get_platform(plat_name)
                        if plat:
                            rating, review_count, status = plat.scrape(page, {'url': target_link, 'hotel_id': detected.get('hotel_id', '')})
                            
                            ans = f"🤖 **Live Reasoning Result for '{hotel_name}'**:\n"
                            ans += f"Platform: {plat.name}\n"
                            ans += f"URL: {target_link}\n\n"
                            if rating and review_count:
                                ans += f"⭐ **Rating**: {rating}{plat.scale}\n"
                                ans += f"📝 **Reviews**: {review_count}\n"
                            else:
                                ans += f"⚠️ Could not extract exact ratings. Status: {status}\n"
                                
                            self.signals.finished.emit(ans)
                            return
                            
                self.signals.finished.emit(f"🤖 Agent Reasoning: I crawled the web for '{hotel_name}' but could not definitively extract its ratings. Try clicking **Deep Research** for a manual URL injection!")
                
            except Exception as e:
                self.signals.finished.emit(f"🤖 Agent Reasoning Error: Failed to live-crawl data ({e}).")
            finally:
                if page:
                    try: page.close()
                    except: pass
            return

        # General fallback
        self.signals.finished.emit(
            f"🤖 **Antigravity Agent (Gemini Core)**:\n"
            f"I processed your query: *\"{self.query}\"*.\n\n"
            f"If you want to know about a hotel's ratings or live status, ask me explicitly! (e.g., 'How many reviews does Hotel XYZ have?'). Or click **🔍 Deep Research** to inject its link directly to the scraper queue."
        )

# ── Floating Glassmorphic AI Chat Agent Widget ──────────────────────

class FloatingAgentWidget(QWidget):
    """Futuristic Floating Agent placed in the corner of the application."""

    def __init__(self, parent=None, default_context="Ratings Scraper"):
        super().__init__(parent)
        self.default_context = default_context
        self.drag_pos = QPoint()
        self._active_reasoning_workers = []
        self._setup_ui()
        self.resize(320, 420)
        
        # Futuristic visual styling: Dark Glassmorphic with Neon Border
        self.setStyleSheet("""
            QWidget#mainFrame {
                background-color: rgba(22, 33, 62, 0.95);
                border: 2px solid #e94560;
                border-radius: 12px;
            }
            QLabel {
                color: #e0e0e0;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            QLineEdit {
                background-color: #1a1a2e;
                color: white;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 8px;
            }
            QTextEdit {
                background-color: #0f3460;
                color: #a0e0a0;
                border: 1px solid #333;
                border-radius: 6px;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
            QPushButton {
                background-color: #e94560;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ff5e7e;
            }
        """)

        # Drop shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(233, 69, 96, 180))
        shadow.setOffset(0, 0)
        self.setGraphicsEffect(shadow)

    def _setup_ui(self):
        self.container_layout = QVBoxLayout(self)
        self.container_layout.setContentsMargins(0, 0, 0, 0)

        main_frame = QFrame()
        main_frame.setObjectName("mainFrame")
        self.container_layout.addWidget(main_frame)

        layout = QVBoxLayout(main_frame)
        layout.setContentsMargins(12, 12, 12, 12)

        # Title / Handle bar
        title_row = QHBoxLayout()
        avatar = QLabel("🤖")
        avatar.setFont(QFont("Segoe UI", 16))
        title_row.addWidget(avatar)

        self.title_lbl = QLabel(f"Antigravity Agent ({self.default_context})")
        self.title_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet("color: #e94560;")
        title_row.addWidget(self.title_lbl)
        
        # Minimize button
        self.min_btn = QPushButton("—")
        self.min_btn.setMaximumWidth(26)
        self.min_btn.setStyleSheet("background-color: #333; padding: 2px;")
        self.min_btn.clicked.connect(self.toggle_size)
        title_row.addWidget(self.min_btn)
        
        layout.addLayout(title_row)

        # Chat display area
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setPlainText(
            f"Agent Active! How can I assist you with {self.default_context} today?\n\n"
            "💡 TIP: Type a hotel name below and click 'Deep Research' to crawl the web, identify its listing page and feed it directly into the scraper queue!"
        )
        layout.addWidget(self.chat_display)

        # Input Row
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Enter hotel name, query, or question...")
        self.input_field.returnPressed.connect(self.handle_message)
        layout.addWidget(self.input_field)

        # Button Row
        btn_row = QHBoxLayout()
        self.ask_btn = QPushButton("Ask Agent")
        self.ask_btn.clicked.connect(self.handle_message)
        btn_row.addWidget(self.ask_btn)

        self.research_btn = QPushButton("🔍 Deep Research")
        self.research_btn.setStyleSheet("background-color: #3498db;")
        self.research_btn.clicked.connect(self.trigger_deep_research)
        btn_row.addWidget(self.research_btn)

        layout.addLayout(btn_row)

    def toggle_size(self):
        if self.chat_display.isVisible():
            self.chat_display.setVisible(False)
            self.input_field.setVisible(False)
            self.ask_btn.setVisible(False)
            self.research_btn.setVisible(False)
            self.min_btn.setText("❑")
            self.resize(320, 50)
        else:
            self.chat_display.setVisible(True)
            self.input_field.setVisible(True)
            self.ask_btn.setVisible(True)
            self.research_btn.setVisible(True)
            self.min_btn.setText("—")
            self.resize(320, 420)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def handle_message(self):
        text = self.input_field.text().strip()
        if not text:
            return
        self.input_field.clear()
        self.chat_display.append(f"\n👤 You: {text}")
        
        worker = AgentReasoningWorker(text)
        worker.signals.log.connect(self.chat_display.append)
        worker.signals.finished.connect(self.chat_display.append)
        worker.start()
        self._active_reasoning_workers.append(worker)

    def trigger_deep_research(self):
        text = self.input_field.text().strip()
        if not text:
            self.chat_display.append("\n🤖 Agent: Please type a hotel name in the input box first so I can initiate deep research!")
            return
        
        self.input_field.clear()
        self.chat_display.append(f"\n👤 You: [Trigger Deep Research] '{text}'")
        
        # Detect active platform
        plat = 'any'
        if 'booking' in self.default_context.lower():
            plat = 'booking'
        elif 'mmt' in self.default_context.lower() or 'makemytrip' in self.default_context.lower():
            plat = 'mmt'
        elif 'goibibo' in self.default_context.lower():
            plat = 'goibibo'
        
        worker = DeepResearchWorker(text, plat)
        worker.signals.log.connect(self.chat_display.append)
        worker.signals.finished.connect(self.on_research_finished)
        worker.start()

    def on_research_finished(self, result):
        if 'error' in result:
            self.chat_display.append(f"\n❌ Research Finished with error: {result['error']}")
            return
        
        # Feed back directly to the active scraping queue
        self.chat_display.append(
            f"\n🎉 Research complete!\n"
            f"  Name: {result['name']}\n"
            f"  URL: {result['url'][:60]}\n"
            f"  ID: {result['hotel_id'] or 'N/A'}\n"
            f"  Platform: {result['platform']}"
        )
        
        # Locate RatingsTab parent and insert resolved listing item
        parent_tab = self.window()
        if parent_tab:
            # Look inside tab structures
            ratings_tab = parent_tab.findChild(QWidget)
            # Find the bulk input box to feed the resolved item directly
            bulk_input = parent_tab.findChild(QTextEdit)
            if bulk_input:
                current_text = bulk_input.toPlainText().strip()
                new_line = result['url']
                if current_text:
                    bulk_input.setPlainText(f"{current_text}\n{new_line}")
                else:
                    bulk_input.setPlainText(new_line)
                self.chat_display.append("📥 Resolved listing URL injected into scraper bulk input area!")
