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
    
    def __init__(self, query: str, platform_filter: str = 'any', deep_extract: bool = False, items_context: list = None, find_parallel: bool = False):
        super().__init__()
        self.query = query
        self.platform_filter = platform_filter
        self.deep_extract = deep_extract
        self.items_context = items_context or []
        self.find_parallel = find_parallel
        self.signals = DeepResearchSignals()
        self.daemon = True

    def run(self):
        def extract_coordinates(p_obj):
            try:
                content = p_obj.content()
                import re
                lat_m = re.search(r'b_map_center_latitude\s*=\s*([\d.\-]+)', content)
                lng_m = re.search(r'b_map_center_longitude\s*=\s*([\d.\-]+)', content)
                if lat_m and lng_m:
                    return float(lat_m.group(1)), float(lng_m.group(1))

                coords = p_obj.evaluate('''() => {
                    let latMeta = document.querySelector('meta[itemprop="latitude"]');
                    let lonMeta = document.querySelector('meta[itemprop="longitude"]');
                    if (latMeta && lonMeta) {
                        return {lat: latMeta.content, lon: lonMeta.content};
                    }
                    let mapEl = document.querySelector('[data-atlas-latlng]');
                    if (mapEl) {
                        let parts = mapEl.getAttribute('data-atlas-latlng').split(',');
                        if (parts.length === 2) {
                            return {lat: parts[0], lon: parts[1]};
                        }
                    }
                    for (let script of document.querySelectorAll('script[type="application/ld+json"]')) {
                        try {
                            let json = JSON.parse(script.textContent);
                            if (json && json.geo) {
                                return {lat: json.geo.latitude, lon: json.geo.longitude};
                            }
                            if (json && json['@graph']) {
                                for (let item of json['@graph']) {
                                    if (item.geo) {
                                        return {lat: item.geo.latitude, lon: item.geo.longitude};
                                    }
                                }
                            }
                        } catch(e) {}
                    }
                    let match = document.body.innerHTML.match(/"latitude":\s*(-?\d+\.\d+),\s*"longitude":\s*(-?\d+\.\d+)/);
                    if (match) {
                        return {lat: match[1], lon: match[2]};
                    }
                    return null;
                }''')
                if coords and coords.get('lat') and coords.get('lon'):
                    return float(coords['lat']), float(coords['lon'])
            except Exception as ce:
                self.signals.log.emit(f"    ⚠️ Failed to extract page coordinates: {ce}")
            return None, None

        def get_distance_km(lat1, lon1, lat2, lon2):
            import math
            try:
                R = 6371.0
                dlat = math.radians(lat2 - lat1)
                dlon = math.radians(lon2 - lon1)
                a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                return R * c
            except Exception:
                return None

        # Split query by lines or commas for bulk search
        if self.items_context:
            raw_queries = [q.strip() for q in self.query.split('\n')]
        else:
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
        for i, q in enumerate(raw_queries):
            q_lower = q.lower()
            is_filler = False
            for phrase in conversational_phrases:
                if q_lower == phrase or q_lower == phrase + " ?" or q_lower == phrase + " -":
                    is_filler = True
                    break
            if is_filler:
                if self.items_context:
                    # Keep as empty to preserve index/1-to-1 mapping
                    valid_queries.append((i, ""))
                else:
                    pass
            else:
                # Clean inline parts
                for phrase in conversational_phrases:
                    q = re.sub(rf'(?i)\b{re.escape(phrase)}\b', '', q).strip()
                q = q.replace('-', '').strip()
                valid_queries.append((i, q))

        if not any(target for idx, target in valid_queries):
            self.signals.log.emit("❌ No valid hotel names found in query after sanitization.")
            self.signals.finished.emit({'error': 'No valid queries'})
            return

        self.signals.log.emit(f"🤖 Agent Initiated: Batch Deep Research on {len(valid_queries)} target(s)...")
        
        browser = None
        try:
            browser = _get_headless_browser()
            
            for step_num, (orig_idx, target) in enumerate(valid_queries, 1):
                if step_num > 1:
                    self.signals.log.emit("  ⏳ Waiting to prevent rate limits...")
                    time.sleep(3.5)
                
                if not target:
                    self.signals.finished.emit({
                        'query_index': orig_idx,
                        'url': '',
                        'hotel_id': '',
                        'name': '',
                        'platform': ''
                    })
                    continue
                
                # Launch clean page tab context for each query to bypass anti-bot track checks
                context = browser.new_context(
                    viewport={'width': 1280, 'height': 900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    locale="en-US",
                    timezone_id="Asia/Kolkata"
                )
                page = context.new_page()
                page.set_extra_http_headers({
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                })
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ("image", "stylesheet", "font", "media") else route.continue_())
                
                # Get item context for this query
                item_info = None
                if self.items_context and orig_idx < len(self.items_context):
                    item_info = self.items_context[orig_idx]
                
                search_query = target
                
                target_lat_val = None
                target_lng_val = None
                if item_info:
                    try:
                        lat_str = str(item_info.get('latitude', '')).strip()
                        lng_str = str(item_info.get('longitude', '')).strip()
                        if lat_str and lng_str:
                            target_lat_val = float(lat_str)
                            target_lng_val = float(lng_str)
                    except ValueError:
                        pass
                
                # Inject city and country for India restriction
                if item_info and item_info.get('city'):
                    city_str = item_info.get('city')
                    if city_str.lower() not in search_query.lower():
                        search_query += f" {city_str}"
                
                if "india" not in search_query.lower():
                    search_query += " India"
                
                # Help parallel search with coordinates
                if self.find_parallel and target_lat_val and target_lng_val:
                    search_query += f" {target_lat_val} {target_lng_val}"

                
                if self.platform_filter:
                    if self.platform_filter == 'mmt':
                        search_query += " site:makemytrip.com/hotels/"
                    elif self.platform_filter == 'booking':
                        search_query += " site:booking.com/hotel/in/"
                    elif self.platform_filter == 'agoda':
                        search_query += " site:agoda.com/"
                    elif self.platform_filter == 'goibibo':
                        search_query += " site:goibibo.com/hotels/"
                    elif self.platform_filter == 'expedia':
                        search_query += " site:expedia.com/"
                        
                self.signals.log.emit(f"[{step_num}/{len(valid_queries)}] 🔍 Searching Index for: '{target[:30]}'...")
                
                target_link = None
                links = []
                
                # Fast path: Construct direct URLs from IDs if available
                if item_info:
                    bcom_id = item_info.get('bcom_id', '').strip()
                    mmt_id = item_info.get('mmt_id', '').strip()
                    if bcom_id and (not self.platform_filter or self.platform_filter == 'booking' or self.platform_filter == 'any'):
                        direct_url = f"https://www.booking.com/hotel/in/{bcom_id}.html"
                        links.append({'href': direct_url, 'text': 'Direct B.com ID Link'})
                    if mmt_id and (not self.platform_filter or self.platform_filter == 'mmt' or self.platform_filter == 'any'):
                        direct_url = f"https://www.makemytrip.com/hotels/hotel-details/?hotelId={mmt_id}"
                        links.append({'href': direct_url, 'text': 'Direct MMT ID Link'})
                
                # 1. Yahoo (Fastest, High Resilience)
                if not links:
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
                    'booking': 'booking.com/hotel/in/',
                    'mmt': 'makemytrip.com/hotels/',
                    'goibibo': 'goibibo.com/hotels/',
                    'agoda': 'agoda.com/',
                    'expedia': 'expedia.com/Hotels'
                }
                
                domains_patterns = {
                    'booking': ['booking.com/hotel/in/'],
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

                matched_listings = []

                for orig_href, decoded_href, expected_plat in filtered_candidates:
                    self.signals.log.emit(f"  🔗 Resolving redirect for: {decoded_href[:60]}...")
                    resolved_url = decoded_href
                    html_content = ""
                    
                    # Try resolving redirect using curl_cffi first (super fast and bypasses most blocks)
                    try:
                        from curl_cffi import requests as curl_requests
                        from curl_cffi.const import CurlHttpVersion
                        
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                            "Accept-Language": "en-US,en;q=0.5",
                        }
                        # We use HTTP/1.1 for MMT / Goibibo to bypass potential Akamai HTTP/2 stream errors
                        http_ver = CurlHttpVersion.V1_1 if 'makemytrip' in decoded_href or 'goibibo' in decoded_href else CurlHttpVersion.NONE
                        
                        r_res = curl_requests.get(
                            decoded_href,
                            headers=headers,
                            http_version=http_ver,
                            timeout=10,
                            allow_redirects=True,
                            impersonate="chrome120"
                        )
                        resolved_url = r_res.url
                        html_content = r_res.text
                    except Exception as e:
                        self.signals.log.emit(f"  ⚠️ Redirect resolution via curl_cffi failed: {e}")
                        # Fallback to Playwright page.goto if curl_cffi fails
                        try:
                            page.goto(decoded_href, timeout=20000, wait_until="load")
                            try:
                                page.wait_for_load_state("networkidle", timeout=3000)
                            except:
                                pass
                            resolved_url = page.url
                            html_content = page.content()
                        except Exception as e2:
                            self.signals.log.emit(f"  ⚠️ Redirect resolution fallback failed: {e2}")
                            if orig_href != decoded_href:
                                try:
                                    page.goto(orig_href, timeout=20000, wait_until="load")
                                    try:
                                        page.wait_for_load_state("networkidle", timeout=3000)
                                    except:
                                        pass
                                    resolved_url = page.url
                                    html_content = page.content()
                                except Exception as e3:
                                    self.signals.log.emit(f"  ⚠️ Redirect resolution orig_href fallback failed: {e3}")
                    
                    # Verify resolved URL matches domain patterns
                    final_plat = None
                    for plat_key, patterns in domains_patterns.items():
                        if any(pat in resolved_url.lower() for pat in patterns):
                            final_plat = plat_key
                            break
                    
                    # Ensure it is a details page for MMT to prevent general homepage/landing page redirects from registering as resolved
                    if final_plat == 'mmt':
                        if not ('-details-' in resolved_url.lower() or 'hotel-details' in resolved_url.lower()):
                            final_plat = None
                    
                    # Enforce platform filter on final resolved URL
                    if self.platform_filter and self.platform_filter != 'any':
                        if final_plat != self.platform_filter:
                            continue
                    else:
                        if not final_plat:
                            continue

                    # ── COORDINATE VERDICT ──
                    coord_passed = None
                    if target_lat_val is not None and target_lng_val is not None:
                        cand_lat, cand_lng = None, None
                        
                        # 1. Try to extract coordinates directly from html fetched via curl_cffi
                        if html_content:
                            try:
                                lat_m = re.search(r'b_map_center_latitude\s*=\s*([\d.\-]+)', html_content)
                                lng_m = re.search(r'b_map_center_longitude\s*=\s*([\d.\-]+)', html_content)
                                if lat_m and lng_m:
                                    cand_lat, cand_lng = float(lat_m.group(1)), float(lng_m.group(1))
                                
                                if cand_lat is None:
                                    lat_meta = re.search(r'<meta[^>]*itemprop="latitude"[^>]*content="([^"]+)"', html_content)
                                    lon_meta = re.search(r'<meta[^>]*itemprop="longitude"[^>]*content="([^"]+)"', html_content)
                                    if lat_meta and lon_meta:
                                        cand_lat, cand_lng = float(lat_meta.group(1)), float(lon_meta.group(1))
                                        
                                if cand_lat is None:
                                    atlas_m = re.search(r'data-atlas-latlng="([^"]+)"', html_content)
                                    if atlas_m:
                                        parts = atlas_m.group(1).split(',')
                                        if len(parts) == 2:
                                            cand_lat, cand_lng = float(parts[0]), float(parts[1])
                                            
                                if cand_lat is None:
                                    ld_geo = re.findall(r'"geo"\s*:\s*\{\s*"@type"\s*:\s*"GeoCoordinates"\s*,\s*"latitude"\s*:\s*"([^"]+)"\s*,\s*"longitude"\s*:\s*"([^"]+)"', html_content)
                                    if ld_geo:
                                        cand_lat, cand_lng = float(ld_geo[0][0]), float(ld_geo[0][1])
                                        
                                if cand_lat is None:
                                    lat_lon_m = re.search(r'"latitude":\s*(-?\d+\.\d+),\s*"longitude":\s*(-?\d+\.\d+)', html_content)
                                    if lat_lon_m:
                                        cand_lat, cand_lng = float(lat_lon_m.group(1)), float(lat_lon_m.group(2))
                            except Exception as ce:
                                self.signals.log.emit(f"    ⚠️ Failed to parse coordinates from html: {ce}")
                        
                        # 2. Fallback to Playwright if coordinates not extracted from static html
                        if cand_lat is None or cand_lng is None:
                            try:
                                if page.url != resolved_url:
                                    page.goto(resolved_url, timeout=20000, wait_until="domcontentloaded")
                                try:
                                    page.evaluate("window.scrollBy(0, 400)")
                                    page.wait_for_timeout(1000)
                                except:
                                    pass
                                cand_lat, cand_lng = extract_coordinates(page)
                            except Exception as e:
                                self.signals.log.emit(f"    ⚠️ Fallback coordinates extraction failed: {e}")

                        if cand_lat is not None and cand_lng is not None:
                            dist_km = get_distance_km(target_lat_val, target_lng_val, cand_lat, cand_lng)
                            if dist_km is not None:
                                self.signals.log.emit(f"    📍 Candidate Coordinates: ({cand_lat}, {cand_lng}) -> Distance: {dist_km:.2f} km")
                                if dist_km <= 3.0:
                                    self.signals.log.emit(f"    ✅ Coordinate Verification Passed ({dist_km:.2f} km <= 3.0 km)")
                                    coord_passed = True
                                else:
                                    self.signals.log.emit(f"    ❌ Coordinate Verification Failed ({dist_km:.2f} km > 3.0 km)")
                                    coord_passed = False
                            else:
                                coord_passed = None
                        else:
                            self.signals.log.emit("    ⚠️ Candidate page coordinates could not be extracted.")
                            coord_passed = None

                    if coord_passed is False:
                        continue

                    # --- AI VERIFICATION STEP ---
                    verification_passed = None
                    import os
                    api_key = os.environ.get("GEMINI_API_KEY")
                    
                    if api_key or True: # Force enter block even if no api key so we check Ollama
                        self.signals.log.emit(f"  🧠 AI Verification active for: {resolved_url[:60]}...")
                        page_title = ""
                        try:
                            page_title = page.title()
                        except:
                            pass
                        
                        if item_info:
                            try:
                                prompt = f"""
                                You are an expert Hotel verifier. 
                                Verify if the target hotel matches the Web search result PERFECTLY.
                                
                                CRITERIA:
                                - Hotel Name Match: Must be fundamentally the same hotel.
                                - City Match: Must be in the exact same city.
                                - Pincode Match: If a zipcode is present in BOTH the target and the result, they MUST match.
                                - Image Match / Branding: The result must represent the true brand of the hotel.
                                
                                TARGET HOTEL:
                                - Name: {item_info.get('name', 'N/A')}
                                - City: {item_info.get('city', 'N/A')}
                                - Address: {item_info.get('address', 'N/A')}
                                - Zipcode: {item_info.get('zipcode', 'N/A')}
                                
                                CANDIDATE LISTING:
                                - URL: {resolved_url}
                                - Page Title: {page_title if 'page_title' in locals() else 'N/A'}
                                
                                Is this candidate URL highly likely to be the correct, dedicated listing page for this specific target hotel?
                                If city mismatches, name is a different branch, or it's an index/list page, reply NO. 
                                If it's a perfect match for the specific hotel listing, reply YES.
                                ONLY reply with YES or NO.
                                """
                                
                                # 1. Try Ollama first
                                ollama_model = None
                                try:
                                    import urllib.request, json
                                    req = urllib.request.Request("http://localhost:11434/api/tags")
                                    with urllib.request.urlopen(req, timeout=2) as response:
                                        data = json.loads(response.read().decode())
                                        if data.get("models"):
                                            models = [m["name"] for m in data["models"]]
                                            nemotron = next((m for m in models if "nemotron-ultra" in m.lower() or "nemotron" in m.lower()), None)
                                            ollama_model = nemotron if nemotron else "nemotron-ultra:latest"
                                        else:
                                            ollama_model = "nemotron-ultra:latest"
                                except Exception:
                                    pass
                                
                                ai_reply = None
                                if ollama_model:
                                    self.signals.log.emit(f"  🧠 AI Verification using local Ollama ({ollama_model})...")
                                    req_data = json.dumps({
                                        "model": ollama_model,
                                        "prompt": prompt,
                                        "stream": False
                                    }).encode('utf-8')
                                    req = urllib.request.Request("http://localhost:11434/api/generate", data=req_data, headers={'Content-Type': 'application/json'})
                                    with urllib.request.urlopen(req, timeout=10) as response:
                                        res_data = json.loads(response.read().decode())
                                        ai_reply = res_data.get("response", "").strip().upper()
                                
                                # 2. Fallback to Gemini if API key is provided and Ollama is not available
                                elif api_key:
                                    import google.generativeai as genai
                                    genai.configure(api_key=api_key)
                                    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                                    target_model = "gemini-1.5-flash"
                                    if "models/gemini-1.5-flash" not in available_models and "gemini-1.5-flash" not in available_models:
                                        if "models/gemini-1.5-flash-latest" in available_models:
                                            target_model = "gemini-1.5-flash-latest"
                                        elif "models/gemini-pro" in available_models:
                                            target_model = "gemini-pro"
                                        elif "models/gemini-1.0-pro" in available_models:
                                            target_model = "gemini-1.0-pro"
                                        elif available_models:
                                            target_model = available_models[-1].replace("models/", "")
                                            
                                    model = genai.GenerativeModel(target_model)
                                    response = model.generate_content(prompt)
                                    ai_reply = response.text.strip().upper()

                                if ai_reply:
                                    if "NO" in ai_reply:
                                        self.signals.log.emit(f"  ❌ AI Rejected URL: Model determined this is not the right hotel.")
                                        verification_passed = False
                                    else:
                                        self.signals.log.emit(f"  ✅ AI Approved URL.")
                                        verification_passed = True
                            except Exception as e:
                                self.signals.log.emit(f"  ⚠️ AI Verification error: {e}")
                                verification_passed = None

                    # --- HEURISTIC FALLBACK ---
                    if verification_passed is None:
                        self.signals.log.emit(f"  ⚙️ Using Heuristic Verification for: {resolved_url[:60]}...")
                        verification_passed = True
                        
                        if "booking.com" in resolved_url:
                            if "/hotel/index.html" in resolved_url or "/searchresults" in resolved_url or "/city/" in resolved_url or "/hotel/in/" not in resolved_url:
                                self.signals.log.emit(f"  ❌ Heuristic Rejected: Generic Booking.com search URL or Non-India URL.")
                                verification_passed = False
                            else:
                                if item_info and item_info.get('name'):
                                    name = item_info.get('name').lower()
                                    match = re.search(r'/hotel/[^/]+/([^.]+)', resolved_url)
                                    if match:
                                        url_slug = match.group(1).replace('-', ' ')
                                        words = [w for w in re.split(r'\W+', name) if len(w) > 3]
                                        if words:
                                            # If NO words from the hotel name are in the URL slug, reject it
                                            if not any(w in url_slug for w in words):
                                                self.signals.log.emit(f"  ❌ Heuristic Rejected: URL slug '{url_slug}' doesn't match hotel '{name}'.")
                                                verification_passed = False

                    if not verification_passed:
                        continue

                    # ── Extract Hotel ID for MakeMyTrip (MMT) ──
                    detected = detect_input_type(resolved_url)
                    plat = detected.get('platform') if detected else final_plat
                    hid = detected.get('hotel_id', '') if detected else ''
                    
                    if plat == 'mmt' and not hid and self.deep_extract:
                        self.signals.log.emit("  🕵️ Deep extracting MMT Hotel ID...")
                        try:
                            url_parts = urlparse(resolved_url)
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
                        
                        if not hid:
                            try:
                                if page:
                                    try:
                                        page.wait_for_load_state("load", timeout=3000)
                                    except Exception:
                                        pass
                                    
                                    try:
                                        p_title = page.title()
                                        self.signals.log.emit(f"  📄 Loaded Title: '{p_title}'")
                                        if "access denied" in p_title.lower() or "security check" in p_title.lower() or "bot" in p_title.lower():
                                            self.signals.log.emit("  ⚠️ Headless session blocked by Akamai bot detection.")
                                    except Exception:
                                        pass
                                    
                                    js_eval_code = """() => {
                                        try {
                                            if (window.__INITIAL_STATE__) {
                                                const state = window.__INITIAL_STATE__;
                                                if (state.requestInfo && state.requestInfo.query && state.requestInfo.query.hotelId) {
                                                    return String(state.requestInfo.query.hotelId);
                                                }
                                                if (state.requestInfo && state.requestInfo.pwaQuery && state.requestInfo.pwaQuery.hotelId) {
                                                    return String(state.requestInfo.pwaQuery.hotelId);
                                                }
                                                if (state.requestInfo && state.requestInfo.globalSettings && state.requestInfo.globalSettings.seoQuery && state.requestInfo.globalSettings.seoQuery.hotelId) {
                                                    return String(state.requestInfo.globalSettings.seoQuery.hotelId);
                                                }
                                                if (state.hotelDetail && state.hotelDetail.staticDetail && state.hotelDetail.staticDetail.hotelId) {
                                                    return String(state.hotelDetail.staticDetail.hotelId);
                                                }
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
                                            const scripts = document.querySelectorAll('script');
                                            for (let script of scripts) {
                                                let text = script.textContent || '';
                                                let m = text.match(/"hotelId"\\s*:\\s*"?(\\d+)"?/i) || text.match(/hotelId\\s*=\\s*"?(\\d+)"?/i) || text.match(/"mtxHotelId"\\s*:\\s*"?(\\d+)"?/i);
                                                if (m) return m[1];
                                            }
                                            let meta = document.querySelector('meta[property="og:url"]') || document.querySelector('link[rel="canonical"]');
                                            if (meta) {
                                                let url = meta.content || meta.href || '';
                                                let m = url.match(/hotelId=(\\d+)/i) || url.match(/topHtlId=(\\d+)/i);
                                                if (m) return m[1];
                                            }
                                        } catch(e) {}
                                        return "";
                                    }"""
                                    try:
                                        page.wait_for_timeout(2000)
                                        evaluated_id = page.evaluate(js_eval_code)
                                        if evaluated_id:
                                            hid = evaluated_id
                                            self.signals.log.emit(f"  ✓ Found ID via page evaluation: {hid}")
                                    except Exception as e:
                                        if "destroyed" in str(e).lower() or "navigation" in str(e).lower():
                                            try:
                                                page.wait_for_timeout(2500)
                                                evaluated_id = page.evaluate(js_eval_code)
                                                if evaluated_id:
                                                    hid = evaluated_id
                                                    self.signals.log.emit(f"  ✓ Found ID via page evaluation retry: {hid}")
                                            except Exception as retry_e:
                                                self.signals.log.emit(f"⚠️ Page evaluation retry failed: {retry_e}")
                                        else:
                                            self.signals.log.emit(f"⚠️ Page evaluation failed: {e}")
                                    
                                    if not hid:
                                        try:
                                            html = page.content()
                                        except Exception:
                                            page.wait_for_timeout(2000)
                                            html = page.content()
                            except Exception as e:
                                self.signals.log.emit(f"⚠️ Deep ID extraction failed: {e}")
                                
                        if not hid:
                            try:
                                m = re.search(r'"hotelId"\s*:\s*"?(\d+)"?', html) or re.search(r'"mtxHotelId"\s*:\s*"?(\d+)"?', html) or re.search(r'hotelId\s*=\s*"?(\d+)"?', html) or re.search(r'hotelId(?:["\':\s]*)([a-zA-Z0-9_]+)', html)
                                if m:
                                    hid = m.group(1)
                                    self.signals.log.emit(f"  ✓ Found ID from page source regex: {hid}")
                            except Exception:
                                pass

                    # ── Inject Optimal Future Date (45 days out) ──
                    try:
                        parsed = urlparse(resolved_url)
                        query_params = parse_qs(parsed.query)
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
                        new_query = urlencode(query_params, doseq=True)
                        resolved_url = urlunparse(parsed._replace(query=new_query))
                    except Exception as e:
                        print(f"Date injection failed: {e}")

                    matched_listings.append({
                        'url': resolved_url,
                        'hotel_id': hid,
                        'name': detected.get('name', target) if detected else target,
                        'platform': plat
                    })
                    
                    if not self.find_parallel:
                        break

                if matched_listings:
                    if self.find_parallel:
                        urls = [m['url'] for m in matched_listings]
                        hids = [m['hotel_id'] for m in matched_listings if m['hotel_id']]
                        combined_url = "\n".join(urls)
                        combined_hid = ", ".join(hids)
                        
                        self.signals.log.emit(f"  🎉 Resolved {len(matched_listings)} Parallel Listings.")
                        for m in matched_listings:
                            self.signals.log.emit(f"    ↳ {m['url'][:60]}...")
                            
                        self.signals.finished.emit({
                            'query_index': orig_idx,
                            'url': combined_url,
                            'hotel_id': combined_hid,
                            'name': matched_listings[0].get('name', target),
                            'platform': matched_listings[0].get('platform')
                        })
                    else:
                        m = matched_listings[0]
                        output_link = f"{m['url']} | {m['hotel_id']}" if m['hotel_id'] else m['url']
                        self.signals.log.emit(f"  🎉 Resolved: {m['url'][:60]}...")
                        self.signals.finished.emit({
                            'query_index': orig_idx,
                            'url': output_link,
                            'hotel_id': m['hotel_id'],
                            'name': m['name'],
                            'platform': m['platform']
                        })
                else:
                    self.signals.log.emit(f"  ❌ Failed to resolve footprint for '{target}'.")
                    self.signals.finished.emit({
                        'query_index': orig_idx,
                        'url': '',
                        'hotel_id': '',
                        'name': target,
                        'platform': ''
                    })
                
                try:
                    ctx = page.context
                    page.close()
                    ctx.close()
                except:
                    pass
            
            self.signals.log.emit(f"\n✅ Batch Deep Research Completed on {len(valid_queries)} targets.")
            self.signals.finished.emit({'batch_finished': True})
                    
        except Exception as e:
            self.signals.log.emit(f"❌ Research failed: {e}")
        finally:
            if page:
                try:
                    ctx = page.context
                    page.close()
                    ctx.close()
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

        # General fallback -> Try Ollama/Gemini first!
        import os
        api_key = os.environ.get("GEMINI_API_KEY")
        
        # 1. Try Ollama first
        ollama_model = None
        try:
            import urllib.request, json
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=1.5) as response:
                data = json.loads(response.read().decode())
                if data.get("models"):
                    models = [m["name"] for m in data["models"]]
                    nemotron = next((m for m in models if "nemotron-ultra" in m.lower() or "nemotron" in m.lower()), None)
                    ollama_model = nemotron if nemotron else models[0]
        except Exception:
            pass
            
        ai_reply = None
        system_prompt = "You are Antigravity, a helpful assistant built into a Hotel Ratings Scraper application. Keep responses concise and focused on helping the user scrape hotel ratings, reviews, manage listing links, or general assistance."
        prompt = f"User asks: {self.query}"
        
        if ollama_model:
            try:
                self.signals.log.emit(f"🧠 Querying local Ollama ({ollama_model})...")
                req_data = json.dumps({
                    "model": ollama_model,
                    "prompt": f"{system_prompt}\n\n{prompt}",
                    "stream": False
                }).encode('utf-8')
                req = urllib.request.Request("http://localhost:11434/api/generate", data=req_data, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=15) as response:
                    res_data = json.loads(response.read().decode())
                    ai_reply = res_data.get("response", "").strip()
            except Exception as e:
                self.signals.log.emit(f"⚠️ Ollama query failed: {e}")
                
        elif api_key:
            try:
                self.signals.log.emit(f"🧠 Querying Gemini Core...")
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                
                # Check models dynamically
                available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                target_model = "gemini-1.5-flash"
                if "models/gemini-1.5-flash" not in available_models and "gemini-1.5-flash" not in available_models:
                    if "models/gemini-1.5-flash-latest" in available_models:
                        target_model = "gemini-1.5-flash-latest"
                    elif "models/gemini-pro" in available_models:
                        target_model = "gemini-pro"
                    elif available_models:
                        target_model = available_models[-1].replace("models/", "")
                
                model = genai.GenerativeModel(target_model, system_instruction=system_prompt)
                response = model.generate_content(prompt)
                ai_reply = response.text.strip()
            except Exception as e:
                self.signals.log.emit(f"⚠️ Gemini query failed: {e}")

        if ai_reply:
            self.signals.finished.emit(f"🤖 **Antigravity AI Agent**:\n{ai_reply}")
        else:
            self.signals.finished.emit(
                f"🤖 **Antigravity Agent (Offline fallback)**:\n"
                f"I processed your query: *\"{self.query}\"*.\n\n"
                f"I could not connect to a local Ollama server or Gemini API to generate a response. "
                f"Please ensure Ollama is running (`ollama serve`) or configure your `GEMINI_API_KEY` to talk to me! "
                f"You can also click **🔍 Deep Research** to search listings for this hotel."
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
        
        # Start minimized by default
        self.chat_display.setVisible(False)
        self.input_field.setVisible(False)
        self.ask_btn.setVisible(False)
        self.research_btn.setVisible(False)
        self.min_btn.setText("▲")
        self.title_lbl.setText("🤖 Antigravity Agent")
        self.resize(180, 42)
        
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
        layout.setContentsMargins(12, 10, 12, 10)

        # Title / Handle bar
        title_row = QHBoxLayout()
        
        self.title_lbl = QLabel("🤖 Antigravity Agent")
        self.title_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet("color: #e94560;")
        title_row.addWidget(self.title_lbl)
        
        # Minimize button
        self.min_btn = QPushButton("▲")
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
            self.min_btn.setText("▲")
            self.title_lbl.setText("🤖 Antigravity Agent")
            self.resize(180, 42)
        else:
            self.chat_display.setVisible(True)
            self.input_field.setVisible(True)
            self.ask_btn.setVisible(True)
            self.research_btn.setVisible(True)
            self.min_btn.setText("—")
            self.title_lbl.setText(f"Antigravity Agent ({self.default_context})")
            self.resize(320, 420)
            
        if self.parent():
            margin = 30
            pw = self.parent().width()
            ph = self.parent().height()
            self.move(pw - self.width() - margin, ph - self.height() - margin)

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
        if not isinstance(result, dict):
            self.chat_display.append(f"\n🎉 Research finished:\n{result}")
            return
            
        if 'error' in result:
            self.chat_display.append(f"\n❌ Research Finished with error: {result['error']}")
            return
        
        # Feed back directly to the active scraping queue
        self.chat_display.append(
            f"\n🎉 Research complete!\n"
            f"  Name: {result.get('name', 'N/A')}\n"
            f"  URL: {result.get('url', '')[:60]}\n"
            f"  ID: {result.get('hotel_id') or 'N/A'}\n"
            f"  Platform: {result.get('platform', 'N/A')}"
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
