"""
God Mode Scraper
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Three tools in one:
  1. Page Scanner   – Visit any URL, auto-detect all scrapeable data
  2. Element Picker – Let user select which fields to extract
  3. Link Builder   – Build front-end URLs from partial hotel data
"""

import os, re, csv, json, time, io
from pathlib import Path
from collections import Counter
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QLineEdit, QFrame, QCheckBox, QGroupBox,
    QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QTabWidget, QGridLayout, QListWidget, QListWidgetItem,
    QMessageBox, QComboBox, QSpinBox, QProgressBar, QFileDialog,
    QDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QImage


import asyncio
from playwright.async_api import async_playwright

from ratings_platforms import (
    AVAILABLE_PLATFORMS, detect_input_type, _get_headless_browser,
    extract_rating_review_count,
)


# ── Page Scanner Engine ───────────────────────────────────

class PageScanner:
    """Core scanning engine — visits a page and detects all scrapeable data."""

    def _get_cdp_page(self):
        """Connect to real Chrome via CDP for Akamai-protected sites. Returns (browser, page, True) or (None, None, False)."""
        from playwright.sync_api import sync_playwright
        import socket, subprocess, time as _time
        from pathlib import Path
        COOKIES_DIR = Path.home() / '.scrape-ratings'
        COOKIES_DIR.mkdir(exist_ok=True)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        res = sock.connect_ex(('127.0.0.1', 9222))
        sock.close()
        if res != 0:
            chrome_paths = [
                r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
                os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
            ]
            chrome = next((cp for cp in chrome_paths if os.path.exists(cp)), None)
            if chrome:
                user_data = str(COOKIES_DIR / 'chrome_scrape')
                subprocess.Popen([
                    chrome,
                    '--remote-debugging-port=9222',
                    f'--user-data-dir={user_data}',
                    '--headless=new',
                    '--disable-gpu',
                    '--no-first-run',
                    '--window-size=1280,800',
                    'about:blank'
                ])
                _time.sleep(3)
        try:
            if not hasattr(self, '_cdp_pw') or self._cdp_pw is None:
                self._cdp_pw = sync_playwright().start()
            browser = self._cdp_pw.chromium.connect_over_cdp('http://127.0.0.1:9222')
            context = browser.contexts[0]
            page = context.new_page()
            return browser, page, True
        except Exception:
            return None, None, False

    def scan(self, url: str, timeout=30) -> dict:
        """
        Visit a URL and return a structured scan result.
        Returns:
          {
            'url': str,
            'title': str,
            'tables': [{'id': int, 'headers': [str], 'row_count': int, 'sample': [dict]}],
            'lists':  [{'id': int, 'item_count': int, 'sample': [str]}],
            'cards':  [{'id': int, 'tag': str, 'class': str, 'count': int, 'sample': [dict]}],
            'jsonld': [{'type': str, 'data': dict}],
            'ratings': [{'rating': str, 'count': str}],
            'all_text_length': int,
            'links': [{'text': str, 'href': str}],
          }
        """
        browser_cdp = None
        is_cdp = False
        # Use CDP Chrome for MMT/Goibibo to bypass Akamai bot detection
        if "makemytrip" in url.lower() or "goibibo" in url.lower():
            browser_cdp, page, is_cdp = self._get_cdp_page()
        
        if not is_cdp:
            browser = _get_headless_browser()
            page = browser.new_page()
            page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            })

        result = {
            'url': url,
            'title': '',
            'tables': [],
            'lists': [],
            'cards': [],
            'jsonld': [],
            'ratings': [],
            'all_text_length': 0,
            'links': [],
        }

        try:
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            # MMT/Goibibo are React SPAs that need extra time to hydrate
            if is_cdp:
                page.wait_for_timeout(5000)
            else:
                page.wait_for_timeout(3000)
        except Exception as e:
            result['error'] = str(e)
            page.close()
            return result

        # Extract title
        try:
            result['title'] = page.evaluate("document.title") or ''
        except:
            pass

        # Extract all page text for rating detection
        try:
            all_text = page.evaluate("document.body.innerText") or ''
            result['all_text_length'] = len(all_text)

            # Detect ratings in text
            rating_matches = re.findall(r'(?:rating|score|review)[^\d]*(\d+\.?\d*)[^\d]*(?:/10|/5)?', all_text[:10000], re.IGNORECASE)
            review_matches = re.findall(r'(\d[\d,]*)\s*(?:reviews?|ratings?)', all_text[:10000], re.IGNORECASE)
            if rating_matches:
                for r in rating_matches[:3]:
                    try:
                        result['ratings'].append({'rating': r})
                    except:
                        pass
            if review_matches:
                for i, rc in enumerate(review_matches[:3]):
                    if i < len(result['ratings']):
                        result['ratings'][i]['count'] = rc.replace(',', '')
                    else:
                        result['ratings'].append({'count': rc.replace(',', '')})
        except:
            pass

        # Extract JSON-LD
        try:
            jsonld_data = page.evaluate("""() => {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                return Array.from(scripts).map(s => {
                    try { return JSON.parse(s.textContent); }
                    catch(e) { return null; }
                }).filter(d => d !== null);
            }""")
            for item in jsonld_data:
                item_type = ''
                if isinstance(item, dict):
                    item_type = item.get('@type', item.get('@graph', [{}])[0].get('@type', '')) if isinstance(item, dict) else ''
                    if isinstance(item_type, list):
                        item_type = item_type[0] if item_type else ''
                result['jsonld'].append({'type': item_type, 'data': item})
        except:
            pass

        # Extract tables
        try:
            table_count = page.evaluate("document.querySelectorAll('table').length")
            for i in range(table_count):
                try:
                    headers = page.evaluate(f"""(i) => {{
                        const table = document.querySelectorAll('table')[i];
                        if (!table) return [];
                        const ths = table.querySelectorAll('th');
                        if (ths.length > 0) return Array.from(ths).map(th => th.textContent.trim()).filter(t => t);
                        // Use first row as headers
                        const firstRow = table.querySelector('tr');
                        if (firstRow) return Array.from(firstRow.querySelectorAll('td')).map(td => td.textContent.trim()).filter(t => t);
                        return [];
                    }}""", i)
                    row_count = page.evaluate(f"""(i) => {{
                        const table = document.querySelectorAll('table')[i];
                        if (!table) return 0;
                        return table.querySelectorAll('tbody tr, tr:not(:has(th))').length || table.querySelectorAll('tr').length - 1;
                    }}""", i)
                    sample_rows = page.evaluate(f"""(i) => {{
                        const table = document.querySelectorAll('table')[i];
                        if (!table) return [];
                        const rows = table.querySelectorAll('tbody tr, tr:not(:has(th))');
                        const r = [];
                        for (let j = 0; j < Math.min(3, rows.length); j++) {{
                            const cells = rows[j].querySelectorAll('td');
                            const row = {{}};
                            cells.forEach((cell, k) => {{
                                row['col_' + k] = cell.textContent.trim().substring(0, 100);
                            }});
                            r.push(row);
                        }}
                        return r;
                    }}""", i)
                    result['tables'].append({
                        'id': i,
                        'headers': headers if isinstance(headers, list) else [],
                        'row_count': row_count if isinstance(row_count, (int, float)) else 0,
                        'sample': sample_rows if isinstance(sample_rows, list) else [],
                    })
                except:
                    pass
        except:
            pass

        # Extract lists (ul/ol)
        try:
            list_data = page.evaluate("""() => {
                const lists = document.querySelectorAll('ul, ol');
                const result = [];
                for (let i = 0; i < Math.min(lists.length, 50); i++) {
                    const items = lists[i].querySelectorAll('li');
                    if (items.length >= 3 && items.length <= 200) {
                        const sample = [];
                        for (let j = 0; j < Math.min(5, items.length); j++) {
                            sample.push(items[j].textContent.trim().substring(0, 150));
                        }
                        result.push({id: i, item_count: items.length, sample: sample, tag: lists[i].tagName});
                    }
                }
                return result;
            }""")
            if isinstance(list_data, list):
                result['lists'] = list_data
        except:
            pass

        # Extract repeated card-like structures
        try:
            card_data = page.evaluate("""() => {
                const result = [];
                // Find repeated child elements of container divs
                const containers = document.querySelectorAll('div[class], section[class], main');
                for (const container of containers) {
                    const children = container.children;
                    if (children.length < 3 || children.length > 200) continue;
                    const tagCounts = {};
                    const classCounts = {};
                    for (const child of children) {
                        const tag = child.tagName;
                        tagCounts[tag] = (tagCounts[tag] || 0) + 1;
                        const cls = child.className;
                        if (cls && typeof cls === 'string') {
                            const mainClass = cls.split(' ')[0];
                            classCounts[mainClass] = (classCounts[mainClass] || 0) + 1;
                        }
                    }
                    // Find the most common tag/class combo
                    for (const [tag, count] of Object.entries(tagCounts)) {
                        if (count >= 3 && count >= children.length * 0.5) {
                            const sample = [];
                            const els = container.querySelectorAll(':scope > ' + tag);
                            for (let j = 0; j < Math.min(3, els.length); j++) {
                                const el = els[j];
                                const fields = {};
                                const textEls = el.querySelectorAll('h1, h2, h3, h4, h5, h6, p, span, a, strong, em');
                                textEls.forEach((te, k) => {
                                    const txt = te.textContent.trim();
                                    if (txt && txt.length < 200) {
                                        fields['field_' + k] = txt;
                                    }
                                });
                                if (Object.keys(fields).length === 0) {
                                    fields['text'] = el.textContent.trim().substring(0, 200);
                                }
                                sample.push(fields);
                            }
                            // Find best class name
                            let bestClass = '';
                            for (const [cls, cnt] of Object.entries(classCounts)) {
                                if (cnt >= count * 0.5) {
                                    bestClass = cls;
                                    break;
                                }
                            }
                            result.push({tag: tag, class: bestClass, count: count, sample: sample});
                            break; // One structure per container
                        }
                    }
                }
                return result;
            }""")
            if isinstance(card_data, list):
                result['cards'] = card_data
        except:
            pass

        # Extract links (hotel-related links)
        try:
            link_data = page.evaluate("""() => {
                const links = document.querySelectorAll('a[href]');
                const result = [];
                for (const link of links) {
                    const text = link.textContent.trim();
                    const href = link.getAttribute('href');
                    if (text && href && text.length < 200 && !href.startsWith('javascript:') && !href.startsWith('#')) {
                        result.push({text: text.substring(0, 100), href: href.substring(0, 300)});
                    }
                }
                return result.slice(0, 100);
            }""")
            if isinstance(link_data, list):
                result['links'] = link_data
        except:
            pass

        page.close()
        if is_cdp and browser_cdp:
            try:
                browser_cdp.close()
            except:
                pass
        return result


# ── Google Maps Detail Parser ─────────────────────────────

async def extract_google_maps_details(html_content, text_content, page):
    soup = BeautifulSoup(html_content, "html.parser")
    details = {}

    # 1. Title
    title = ""
    try:
        h1_el = await page.query_selector("h1")
        title = (await h1_el.inner_text()).strip() if h1_el else ""
    except:
        pass
    if not title or title.lower() == "google maps":
        title_tag = soup.find("h1")
        title = title_tag.text.strip() if title_tag else ""
    if not title or title.lower() == "google maps":
        try:
            pt = await page.title() or ""
            if pt.lower() != "google maps":
                title = pt.split('-')[0].strip()
        except:
            pass
    # Clean Title
    title = re.sub(r'\s*-\s*Google Maps\s*$', '', title, flags=re.I).strip()
    if not title or title.lower() == "google maps":
        # Extract from URL if all else fails
        try:
            url = page.url
            if "/place/" in url:
                title = url.split("/place/")[1].split("/")[0].replace("+", " ")
        except:
            pass
    details['title'] = title

    # 2. Rating
    rating = ""
    f7nice = soup.find(class_="F7nice")
    if f7nice:
        rating_match = re.search(r'(\d\.\d)', f7nice.text)
        rating = rating_match.group(1) if rating_match else f7nice.text.strip()
    if not rating:
        font_large = soup.find(class_="fontDisplayLarge")
        rating = font_large.text.strip() if font_large else ""
    if not rating:
        rating_match = re.search(r'\b([3-5]\.\d)\b', text_content[:5000])
        rating = rating_match.group(1) if rating_match else ""
    details['rating'] = rating

    # 3. Review Count
    review_count = ""
    review_btn = soup.find("button", attrs={"jsaction": re.compile(r'pane\.rating\.moreReviews')})
    if review_btn:
        review_text = review_btn.text.strip()
        review_match = re.search(r'([\d,]+)', review_text)
        review_count = review_match.group(1).replace(",", "") if review_match else ""
    if not review_count:
        review_el = soup.find(attrs={"aria-label": re.compile(r'([\d,]+)\s+reviews', re.I)})
        if review_el:
            m = re.search(r'([\d,]+)\s+reviews', review_el.get('aria-label'), re.I)
            review_count = m.group(1).replace(",", "") if m else ""
    if not review_count:
        m = re.search(r'\((\d+)\)\s*(?:·|Hotel|Restaurant|reviews)?', text_content)
        review_count = m.group(1) if m else ""
    details['review_count'] = review_count

    # 4. Category
    category = ""
    category_btn = soup.find("button", attrs={"jsaction": re.compile(r'pane\.rating\.category')})
    if category_btn:
        category = category_btn.text.strip()
    if not category:
        lines = [line.strip() for line in text_content.split('\n') if line.strip()]
        for idx, line in enumerate(lines):
            if line == details.get('rating') and idx + 1 < len(lines):
                category = lines[idx+1]
                break
    # Clean Category: strip things like "(49)Â·Hotel", "(431)Hotel", or leading ratings
    category = re.sub(r'^\([\d,]+\)\s*[^a-zA-Z]*', '', category)
    category = re.sub(r'^[\d.]+\s*[^a-zA-Z]*', '', category)
    if not category:
        category = ""
    details['category'] = category.strip()

    # 5. Address
    address = ""
    address_el = soup.find(attrs={"data-item-id": "address"})
    if address_el:
        text_el = address_el.find(class_="Io6YTe")
        address = text_el.text.strip() if text_el else address_el.text.strip()
    if not address:
        pin_match = re.search(r'([^\n\r]+,\s*\d{6})', text_content)
        address = pin_match.group(1).strip() if pin_match else ""
    details['address'] = address

    # 6. Website (Proper Excel Hyperlink)
    website_url = ""
    try:
        web_btn = await page.query_selector('[data-item-id="authority"]')
        if web_btn:
            a_el = await web_btn.query_selector('a')
            if a_el:
                website_url = await a_el.get_attribute('href') or ""
            else:
                website_url = await web_btn.get_attribute('href') or ""
    except:
        pass
    if not website_url:
        website_el = soup.find(attrs={"data-item-id": "authority"})
        if website_el:
            a_tag = website_el.find("a")
            website_url = a_tag.get("href") if a_tag else website_el.text.strip()
        else:
            # We will ONLY rely on the authority button instead of blindly searching text
            website_url = ""
            
            if website_url and not website_url.startswith("http"):
                website_url = "http://" + website_url

    # Clean Google redirects
    if "google.com/url" in website_url:
        try:
            parsed = urlparse(website_url)
            q_params = parse_qs(parsed.query)
            if 'q' in q_params:
                website_url = q_params['q'][0]
        except:
            pass

    # Clean special character icons
    website_url = re.sub(r'[^\x20-\x7E]', '', website_url).strip()
    
    if website_url:
        if not website_url.startswith("http"):
            website_url = "http://" + website_url
        display_name = urlparse(website_url).netloc.replace("www.", "")
        details['website'] = f'=HYPERLINK("{website_url}", "{display_name}")'
    else:
        details['website'] = ""

    # 7. Phone
    phone = ""
    phone_el = soup.find(lambda tag: tag.name == "button" and tag.get("data-item-id", "").startswith("phone:tel:"))
    if phone_el:
        text_el = phone_el.find(class_="Io6YTe")
        phone = text_el.text.strip() if text_el else phone_el.text.strip()
    if not phone:
        phone_match = re.search(r'(\+?\d{2,4}[-\s]?\d{3,5}[-\s]?\d{3,5})', text_content)
        phone = phone_match.group(1) if phone_match else ""
    if phone and "Check-in" in phone:
        phone = ""
    
    if phone:
        phone = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").strip()
        if len(phone) == 10:
            phone = f"0{phone[:5]} {phone[5:]}"
        # Use Excel formula format to display string without visible quote
        details['phone'] = f'="{phone}"'
    else:
        details['phone'] = ""

    # 8. Plus Code
    plus_code = ""
    plus_el = soup.find(attrs={"data-item-id": "oloc"})
    if plus_el:
        text_el = plus_el.find(class_="Io6YTe")
        plus_code = text_el.text.strip() if text_el else plus_el.text.strip()
    if not plus_code:
        plus_match = re.search(r'([A-Z0-9]{4}\+[A-Z0-9]{2,}\s*[a-zA-Z\s,]+)', text_content)
        plus_code = plus_match.group(1).strip() if plus_match else ""
    details['plus_code'] = plus_code

    # 9. Check-in / Check-out
    cin_match = re.search(r'Check-in time:\s*([^\n\r]+)', text_content, re.I)
    details['check_in_time'] = cin_match.group(1).replace('\u202f', ' ').strip() if cin_match else ""
    
    cout_match = re.search(r'Check-out time:\s*([^\n\r]+)', text_content, re.I)
    details['check_out_time'] = cout_match.group(1).replace('\u202f', ' ').strip() if cout_match else ""

    # 10. Price
    price = ""
    price_match = re.search(r'(?:₹|Rs\.?)\s*([\d,]+)', text_content)
    if price_match:
        price = price_match.group(1).strip()
    details['price'] = price

    # 11. Booking Options
    options = []
    lines = [line.strip() for line in text_content.split('\n') if line.strip()]
    platforms = ['agoda', 'makemytrip', 'oyo', 'booking.com', 'expedia', 'official site', 'fabhotels']
    for idx, line in enumerate(lines):
        line_lower = line.lower()
        if any(p in line_lower for p in platforms) and idx + 1 < len(lines):
            next_line = lines[idx+1]
            if re.match(r'^(?:₹|Rs\.?)\s*[\d,]+$', next_line):
                options.append(f"{line}: {next_line.replace('₹', '').replace('Rs.', '').strip()}")
    details['booking_options'] = ' | '.join(options)

    # 12. Amenities
    amenities = []
    if "Hotel details" in text_content:
        parts = text_content.split("Hotel details")
        if len(parts) > 1:
            sublines = [l.strip() for l in parts[1].split('\n') if l.strip()]
            for sl in sublines:
                if sl in ["Write a review", "About this data", "Vacation rentals nearby"]:
                    break
                if len(sl) > 2 and not sl.startswith('©'):
                    amenities.append(sl)
    details['amenities'] = '; '.join(amenities)

    return details


# ── Scrape Worker for God Mode ────────────────────────────

class GodModeWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str, int, int)

    def __init__(self, urls, field_config, output_path):
        super().__init__()
        self.urls = urls
        self.field_config = field_config or []  # list of {'name': ..., 'selector': ..., 'attribute': ...}
        self.output_path = output_path
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import requests
        from bs4 import BeautifulSoup
        total = len(self.urls)
        results = [None] * total

        # Detect Google Maps URLs
        is_any_maps = any("google.com/maps" in u.lower() or "goo.gl" in u.lower() or "maps.google" in u.lower() or "g.page" in u.lower() for u in self.urls)

        def scrape_one(idx, url):
            if self._stop:
                return idx, {'url': url, 'error': 'Stopped'}

            row = {'url': url}
            is_google = "google.com" in url.lower() or "goo.gl" in url.lower() or "g.page" in url.lower()

            # Fast path for generic pages using requests
            if not is_google and self.field_config:
                try:
                    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
                    resp.raise_for_status()
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    for field in self.field_config:
                        name = field['name']
                        selector = field['selector']
                        attr = field.get('attribute', 'text')
                        multiple = field.get('multiple', False)
                        if multiple:
                            els = soup.select(selector)
                            vals = []
                            for el in els[:50]:
                                v = el.get_text(strip=True) if attr == 'text' else el.get(attr, '')
                                if v: vals.append(v)
                            row[name] = ' | '.join(vals[:10])
                        else:
                            el = soup.select_one(selector)
                            if el:
                                row[name] = el.get_text(strip=True) if attr == 'text' else el.get(attr, '')
                            else:
                                row[name] = ''
                    return idx, row
                except Exception:
                    pass

            # Playwright async path (run in isolated event loop)
            async def _run_async():
                import random
                import asyncio
                import socket, subprocess, time as _time
                from pathlib import Path
                from playwright.async_api import async_playwright
                # Prevent parallel threads from launching chromium at the exact same millisecond
                await asyncio.sleep(random.uniform(0.2, 2.0))

                async def _get_cdp_browser(p):
                    COOKIES_DIR = Path.home() / '.scrape-ratings'
                    COOKIES_DIR.mkdir(exist_ok=True)
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    res = sock.connect_ex(('127.0.0.1', 9222))
                    sock.close()
                    if res != 0:
                        chrome_paths = [
                            r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                            r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
                            os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
                        ]
                        chrome = next((cp for cp in chrome_paths if os.path.exists(cp)), None)
                        if chrome:
                            user_data = str(COOKIES_DIR / 'chrome_scrape')
                            subprocess.Popen([
                                chrome,
                                '--remote-debugging-port=9222',
                                f'--user-data-dir={user_data}',
                                '--headless=new',
                                '--disable-gpu',
                                '--no-first-run',
                                '--window-size=1280,800',
                                'about:blank'
                            ])
                            _time.sleep(3)
                    try:
                        browser = await p.chromium.connect_over_cdp('http://127.0.0.1:9222')
                        return browser, True  # browser, is_cdp
                    except Exception:
                        return None, False

                async with async_playwright() as p:
                    is_cdp = False
                    if "makemytrip" in url.lower() or "goibibo" in url.lower():
                        browser, is_cdp = await _get_cdp_browser(p)
                        if browser:
                            context = browser.contexts[0]
                        else:
                            browser = await p.chromium.launch(headless=False, args=["--headless=new", "--disable-blink-features=AutomationControlled"])
                            context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/120.0.0.0")
                    else:
                        browser = await p.chromium.launch(headless=False, args=["--headless=new", "--disable-blink-features=AutomationControlled"])
                        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/120.0.0.0")

                    # Block heavy items (skip route on CDP shared context to avoid conflicts)
                    if not is_cdp:
                        await context.route("**/*", lambda route: route.abort() if route.request.resource_type in ("image", "font", "media") else route.continue_())
                    page = await context.new_page()
                    page.set_default_timeout(25000)
                    await page.goto(url, wait_until="domcontentloaded")
                    # Wait extra for JS-rendered pages like MMT
                    if "makemytrip" in url.lower() or "goibibo" in url.lower():
                        await page.wait_for_timeout(4000)
                    current_url = page.url.lower()
                    is_maps = "google.com/maps" in current_url or "maps.app.goo.gl" in current_url or "maps.google" in current_url or "/maps/" in current_url
                    if is_maps:
                        # Use existing sync extraction for maps (calls function defined elsewhere)
                        html_content = await page.content()
                        text_content = await page.evaluate("document.body.innerText") or ""
                        details = await extract_google_maps_details(html_content, text_content, page)
                        details['url'] = url
                        details['platform'] = 'Google Maps'
                        return idx, details
                    # Generic page scraping using selectors (still sync BeautifulSoup path earlier)
                    await page.wait_for_timeout(1500)
                    row = {}
                    for field in self.field_config:
                        name = field['name']
                        selector = field['selector']
                        attr = field.get('attribute', 'text')
                        multiple = field.get('multiple', False)
                        if multiple:
                            elements = await page.query_selector_all(selector)
                            values = []
                            for el in elements[:50]:
                                if attr == 'text':
                                    v = (await el.inner_text()).strip()
                                elif attr == 'href':
                                    v = await el.get_attribute('href') or ''
                                else:
                                    v = await el.get_attribute(attr) or ''
                                if v:
                                    values.append(v)
                            row[name] = ' | '.join(values[:10])
                        else:
                            el = await page.query_selector(selector)
                            if el:
                                if attr == 'text':
                                    row[name] = (await el.inner_text()).strip()
                                elif attr == 'href':
                                    row[name] = await el.get_attribute('href') or ''
                                else:
                                    row[name] = await el.get_attribute(attr) or ''
                            else:
                                row[name] = ''
                    await page.close()
                    if is_cdp:
                        await browser.close()
                    else:
                        await context.close()
                        await browser.close()
                    return idx, row
            try:
                idx, row = asyncio.run(_run_async())
                return idx, row
            except Exception as e:
                err_msg = str(e)[:100]
                if is_any_maps:
                    return idx, {
                        'url': url, 'title': f'[ERROR: {err_msg}]', 'rating': '', 'review_count': '', 
                        'price': '', 'category': '', 'address': '', 'phone': '', 'website': '', 
                        'plus_code': '', 'check_in_time': '', 'check_out_time': '', 
                        'booking_options': '', 'amenities': '', 'platform': 'Google Maps'
                    }
                else:
                    err_row = {'url': url}
                    for field in self.field_config:
                        err_row[field['name']] = f'[ERROR: {err_msg}]'
                    return idx, err_row

        # Run scraping concurrently using ThreadPoolExecutor
        max_workers = min(8, total) if total > 0 else 1
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {executor.submit(scrape_one, idx, url): idx for idx, url in enumerate(self.urls)}
            for future in as_completed(future_to_idx):
                if self._stop:
                    break
                idx, row = future.result()
                results[idx] = row
                
                completed = sum(1 for r in results if r is not None)
                title_val = row.get('title', row.get('url', ''))[:40]
                self.progress.emit(completed, total, f"Scraped: {title_val}...")

        # Write CSV
        clean_results = [r for r in results if r is not None]
        if clean_results:
            if is_any_maps:
                fieldnames = [
                    'url', 'title', 'rating', 'review_count', 'price', 'category', 'address', 
                    'phone', 'website', 'plus_code', 'check_in_time', 'check_out_time', 
                    'booking_options', 'amenities', 'platform'
                ]
            else:
                fieldnames = ['url'] + [f['name'] for f in self.field_config]
                
            with open(self.output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(clean_results)

        success = sum(1 for r in clean_results if any(v for k, v in r.items() if k != 'url'))
        self.finished.emit(self.output_path, success, total)



# ── Haversine Distance Helper ─────────────────────────────

import math as _math

def haversine_km(lat1, lon1, lat2, lon2):
    """Return great-circle distance in kilometres between two lat/lon points."""
    R = 6371.0
    dlat = _math.radians(lat2 - lat1)
    dlon = _math.radians(lon2 - lon1)
    a = (_math.sin(dlat / 2) ** 2
         + _math.cos(_math.radians(lat1)) * _math.cos(_math.radians(lat2))
         * _math.sin(dlon / 2) ** 2)
    return R * 2 * _math.asin(_math.sqrt(a))


# ── Bulk Parallel Listing Finder Worker ───────────────────

class BulkParallelFinderWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list, str) # results list, output file path

    def __init__(self, items, platforms, headers=None):
        super().__init__()
        self.items = items # list of dicts with name, city, latitude, longitude, address, row_data keys
        self.platforms = platforms
        self.headers = headers
        self._stop = False
        self._pause = False
        self.results = []

    def stop(self):
        self._stop = True

    def pause(self):
        self._pause = True

    def resume(self):
        self._pause = False

    def run(self):
        from playwright.sync_api import sync_playwright
        import urllib.parse
        import difflib

        total = len(self.items)
        self.results = []

        # Determine max cols
        max_parts = max([len(item.get('row_data', [])) for item in self.items]) if self.items else 2

        with sync_playwright() as p:
            try:
                try:
                    from settings_dialog import load_settings
                    import random
                    import time
                    settings = load_settings()
                    ua = settings.get("user_agent", "").strip()
                    if not ua:
                        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    
                    proxy_config = None
                    if settings.get("enable_proxies"):
                        proxies = [p.strip() for p in settings.get("proxy_list", "").split('\n') if p.strip()]
                        if proxies:
                            sel = random.choice(proxies)
                            proxy_config = {}
                            if "@" in sel:
                                proto_part, rest = sel.split("://") if "://" in sel else ("http", sel)
                                up, hp = rest.split("@")
                                u, p_wd = up.split(":")
                                proxy_config['server'] = f"{proto_part}://{hp}"
                                proxy_config['username'] = u
                                proxy_config['password'] = p_wd
                            else:
                                proxy_config['server'] = sel
                except Exception:
                    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    proxy_config = None

                # CDP logic for bulk finder
                import socket, os, subprocess, time
                from pathlib import Path
                COOKIES_DIR = Path.home() / '.scrape-ratings'
                COOKIES_DIR.mkdir(exist_ok=True)
                
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                res = sock.connect_ex(('127.0.0.1', 9222))
                sock.close()
                if res != 0:
                    chrome_paths = [
                        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
                        os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
                    ]
                    chrome = next((path for path in chrome_paths if os.path.exists(path)), None)
                    if chrome:
                        user_data = str(COOKIES_DIR / 'chrome_scrape')
                        subprocess.Popen([
                            chrome,
                            '--remote-debugging-port=9222',
                            f'--user-data-dir={user_data}',
                            '--headless=new',
                            '--disable-gpu',
                            '--no-first-run',
                            '--window-size=1280,800',
                            'about:blank'
                        ])
                        time.sleep(3)
                        
                try:
                    browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
                    context = browser.contexts[0]
                    is_cdp_bulk = True
                except:
                    browser = p.chromium.launch(headless=False, args=["--headless=new", "--disable-blink-features=AutomationControlled"])
                    context = browser.new_context(
                        user_agent=ua,
                        proxy=proxy_config
                    )
                    is_cdp_bulk = False
                if not is_cdp_bulk:
                    context.route("**/*", lambda route: route.abort() if route.request.resource_type in ("font", "media") else route.continue_())
                page = context.new_page()
            except Exception as e:
                self.progress.emit(0, total, f"Failed to launch browser: {e}")
                self.finished.emit([], "")
                return

            for idx, item in enumerate(self.items):
                while self._pause and not self._stop:
                    self.msleep(100)
                if self._stop:
                    break

                target_name = item.get('name', '')
                city = item.get('city', '')
                target_address = item.get('address', '')
                target_lat = item.get('latitude', '')
                target_lng = item.get('longitude', '')
                row_data = item.get('row_data', [])

                while len(row_data) < max_parts:
                    row_data.append('')

                cleaned_target = clean_hotel_name(target_name)
                
                self.progress.emit(idx + 1, total, f"Searching for: {target_name} ({city})")

                query = f"{cleaned_target} {city}".strip()
                query_encoded = urllib.parse.quote_plus(query)

                import db_cache
                cached_res = db_cache.get_cached_parallel_finder(query, target_lat, target_lng)
                if cached_res is not None:
                    self.progress.emit(idx + 1, total, f"Cache Hit: {target_name} ({city})")
                    for suffix in cached_res:
                        res = list(row_data)
                        res.extend(suffix)
                        self.results.append(res)
                    try:
                        db_cache.update_batch_run('parallel_finder_batch', 'bulk_input', idx + 1, total, 'RUNNING', '')
                    except Exception:
                        pass
                    continue

                try:
                    from settings_dialog import load_settings
                    import random
                    import time
                    settings = load_settings()
                    if settings.get("enable_jitter"):
                        time.sleep(random.uniform(settings.get("jitter_min", 1), settings.get("jitter_max", 3)))
                except Exception:
                    pass

                initial_results_len = len(self.results)
                found_match = False

                for platform in self.platforms:
                    if self._stop:
                        break

                    try:
                        if platform == 'booking':
                            # Restrict to India: add ss=<city> + cc=in so Booking only returns Indian properties
                            city_encoded = urllib.parse.quote_plus(city) if city else ''
                            search_url = (
                                f"https://www.booking.com/searchresults.html"
                                f"?ss={query_encoded}&ssne={city_encoded}&ssne_untouched={city_encoded}&cc=in"
                            )
                            page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
                            page.wait_for_timeout(2000)
                            cards = page.query_selector_all('[data-testid="property-card"]')[:5]

                            for card in cards:
                                name_el = card.query_selector('[data-testid="title"]')
                                name = name_el.inner_text().strip() if name_el else ''
                                if not name:
                                    continue

                                loc_el = card.query_selector(
                                    '[data-testid="address"], [data-testid="location"], '
                                    'span[data-testid="address"], [class*="address"]'
                                )
                                location = loc_el.inner_text().strip() if loc_el else ''

                                link_el = card.query_selector('a[data-testid="title-link"], a[href*="/hotel/in/"]')
                                url = link_el.get_attribute('href') if link_el else ''
                                if url and url.startswith('/'):
                                    url = 'https://www.booking.com' + url

                                # REJECT hotels outside India (URL must contain /hotel/in/)
                                if url and '/hotel/in/' not in url:
                                    self.progress.emit(idx + 1, total, f"  ↳ Skipped (non-India URL): {name}")
                                    continue

                                # ── DEFINITIVE MATCH: extract lat/long + hotel_id from detail page ──
                                # booking.env.b_map_center_latitude / b_map_center_longitude / b_hotel_id
                                cand_lat = None
                                cand_lng = None
                                booking_hotel_id = ''
                                first_photo = ''

                                try:
                                    detail_page = context.new_page()
                                    detail_page.goto(url, timeout=25000, wait_until="domcontentloaded")
                                    detail_page.wait_for_timeout(1500)

                                    content = detail_page.content()

                                    import re
                                    lat_m = re.search(r'b_map_center_latitude\s*=\s*([\d.\-]+)', content)
                                    lng_m = re.search(r'b_map_center_longitude\s*=\s*([\d.\-]+)', content)
                                    id_m  = re.search(r"b_hotel_id\s*=\s*'?(\d+)'?", content)

                                    if lat_m: cand_lat = float(lat_m.group(1))
                                    if lng_m: cand_lng = float(lng_m.group(1))
                                    if id_m:  booking_hotel_id = id_m.group(1)

                                    # Get first real hotel photo from detail page
                                    for img_el in detail_page.query_selector_all(
                                        '[data-testid="photo-image"] img, .bh-photo-strip img, '
                                        'img[class*="photo"], img[class*="hotel"]'
                                    )[:5]:
                                        src = img_el.get_attribute('src') or img_el.get_attribute('data-src') or ''
                                        if is_valid_hotel_photo_url(src):
                                            first_photo = src
                                            break

                                    detail_page.close()
                                except Exception as de:
                                    try: detail_page.close()
                                    except Exception: pass
                                    self.progress.emit(idx + 1, total, f"  ↳ Detail page error for {name}: {de}")

                                # ── COORDINATE VERDICT ──
                                dist_km = None
                                coord_verdict = None

                                try:
                                    if (cand_lat and cand_lng and target_lat and target_lng
                                            and str(target_lat).strip() and str(target_lng).strip()):
                                        t_lat = float(str(target_lat).strip())
                                        t_lng = float(str(target_lng).strip())
                                        dist_km = haversine_km(t_lat, t_lng, cand_lat, cand_lng)

                                        if dist_km <= 0.3:
                                            coord_verdict = f"EXACT MATCH ({dist_km:.2f} km)"
                                        elif dist_km <= 1.0:
                                            coord_verdict = f"Very Close ({dist_km:.2f} km)"
                                        elif dist_km <= 3.0:
                                            coord_verdict = f"Nearby ({dist_km:.2f} km)"
                                        else:
                                            self.progress.emit(idx + 1, total,
                                                f"  ↳ REJECTED by coordinates ({dist_km:.1f} km away): {name}")
                                            continue
                                except Exception:
                                    pass  # Fallback to name+city if coords unavailable

                                cleaned_cand = clean_hotel_name(name)
                                ratio, addr_score, city_match = verify_candidate_enhanced(
                                    cleaned_target, city, target_address, cleaned_cand, location)

                                if not city_match and ratio < 0.80:
                                    self.progress.emit(idx + 1, total,
                                        f"  ↳ Rejected (city mismatch, {int(ratio*100)}%): {name}")
                                    continue
                                if city_match and ratio < 0.50:
                                    self.progress.emit(idx + 1, total,
                                        f"  ↳ Rejected (too dissimilar, {int(ratio*100)}%): {name}")
                                    continue

                                similarity = compute_unified_confidence(ratio, addr_score, dist_km)
                                is_fab = 'fab' in name.lower()
                                if is_fab:
                                    verdict = 'FabHotel Chain'
                                elif coord_verdict:
                                    verdict = coord_verdict
                                else:
                                    verdict = 'Potential Duplicate (Non-Fab)' if city_match else 'City Mismatch Warning'
                                coord_info = f"{dist_km:.2f} km" if dist_km is not None else f"No coords | {int(ratio*100)}% name match"

                                if not location and url:
                                    slug_match = re.search(r'/hotel/in/([^.?]+)', url)
                                    if slug_match:
                                        location = slug_match.group(1).replace('-', ' ').title()

                                self.progress.emit(idx + 1, total,
                                    f"  ✓ MATCH: {clean_hotel_name(name)} | BookingID={booking_hotel_id} | {coord_info if 'coord_info' in dir() else ''}")

                                res = list(row_data)
                                res.extend([
                                    clean_hotel_name(name),
                                    'Booking.com',
                                    location or city,
                                    f"{similarity}%",
                                    verdict,
                                    url,
                                    first_photo,
                                    booking_hotel_id,
                                    f"{cand_lat},{cand_lng}" if cand_lat else '',
                                ])
                                self.results.append(res)
                                found_match = True

                        elif platform == 'agoda':
                            search_url = f"https://www.agoda.com/search?text={query_encoded}"
                            page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
                            page.wait_for_timeout(2000)
                            cards = page.query_selector_all('li[data-selenium="property-item"], [data-selenium="hotel-item"], .PropertyCard')[:3]
                            
                            for card in cards:
                                name_el = card.query_selector('[data-selenium="hotel-name"], h3, h4, .property-card-title')
                                name = name_el.inner_text().strip() if name_el else ''
                                if not name:
                                    continue

                                loc_el = card.query_selector('[data-selenium="area-city-name"], .property-card-location')
                                location = loc_el.inner_text().strip() if loc_el else ''
                                
                                link_el = card.query_selector('a[href*="/hotel/"], a')
                                url = link_el.get_attribute('href') if link_el else ''
                                if url and url.startswith('/'):
                                    url = "https://www.agoda.com" + url
                                    
                                img_el = card.query_selector('img')
                                first_photo = img_el.get_attribute('src') if img_el else ''
                                if not is_valid_hotel_photo_url(first_photo):
                                    first_photo = ''

                                cleaned_cand = clean_hotel_name(name)
                                ratio, addr_score, city_match = verify_candidate_enhanced(cleaned_target, city, target_address, cleaned_cand, location)
                                
                                if not city_match and ratio < 0.8:
                                    continue
                                if city_match and ratio < 0.5:
                                    continue
                                
                                similarity = compute_unified_confidence(ratio, addr_score)
                                is_fab = 'fab' in name.lower()
                                verdict = 'FabHotel Chain' if is_fab else ('Potential Duplicate (Non-Fab)' if city_match else 'City Mismatch Warning')

                                res = list(row_data)
                                res.extend([name, 'Agoda', location, f"{similarity}%", verdict, url, first_photo, '', ''])
                                self.results.append(res)
                                found_match = True
                                found_match = True

                        elif platform == 'expedia':
                            search_url = f"https://www.expedia.com/Hotel-Search?destination={query_encoded}"
                            page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
                            page.wait_for_timeout(2000)
                            cards = page.query_selector_all('[data-stid="property-card"], .uitk-card')[:3]
                            
                            for card in cards:
                                name_el = card.query_selector('h3, h4')
                                name = name_el.inner_text().strip() if name_el else ''
                                if not name:
                                    continue

                                loc_el = card.query_selector('[data-test-id="neighborhood"]')
                                location = loc_el.inner_text().strip() if loc_el else ''
                                
                                link_el = card.query_selector('a')
                                url = link_el.get_attribute('href') if link_el else ''
                                if url and url.startswith('/'):
                                    url = "https://www.expedia.com" + url
                                    
                                img_el = card.query_selector('img')
                                first_photo = img_el.get_attribute('src') if img_el else ''
                                if not is_valid_hotel_photo_url(first_photo):
                                    first_photo = ''

                                cleaned_cand = clean_hotel_name(name)
                                ratio, addr_score, city_match = verify_candidate_enhanced(cleaned_target, city, target_address, cleaned_cand, location)
                                
                                if not city_match and ratio < 0.8:
                                    continue
                                if city_match and ratio < 0.5:
                                    continue
                                
                                similarity = compute_unified_confidence(ratio, addr_score)
                                is_fab = 'fab' in name.lower()
                                verdict = 'FabHotel Chain' if is_fab else ('Potential Duplicate (Non-Fab)' if city_match else 'City Mismatch Warning')

                                res = list(row_data)
                                res.extend([name, 'Expedia', location, f"{similarity}%", verdict, url, first_photo, '', ''])
                                self.results.append(res)
                                found_match = True
                                found_match = True

                        elif platform == 'mmt':
                            search_url = f"https://www.makemytrip.com/hotels/hotel-listing/?searchText={query_encoded}"
                            page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
                            page.wait_for_timeout(2000)
                            cards = page.query_selector_all('.infinite-scroll-component > div, [class*="ListingCard"]')[:3]
                            
                            for card in cards:
                                name_el = card.query_selector('p[class*="hotelName"], h3, span[class*="hotelName"]')
                                name = name_el.inner_text().strip() if name_el else ''
                                if not name:
                                    continue

                                loc_el = card.query_selector('span[class*="location"]')
                                location = loc_el.inner_text().strip() if loc_el else ''
                                
                                link_el = card.query_selector('a[href*="/hotels/"]')
                                url = link_el.get_attribute('href') if link_el else ''
                                if url and url.startswith('/'):
                                    url = "https://www.makemytrip.com" + url
                                    
                                img_el = card.query_selector('img')
                                first_photo = img_el.get_attribute('src') if img_el else ''
                                if not is_valid_hotel_photo_url(first_photo):
                                    first_photo = ''

                                cleaned_cand = clean_hotel_name(name)
                                ratio, addr_score, city_match = verify_candidate_enhanced(cleaned_target, city, target_address, cleaned_cand, location)
                                
                                if not city_match and ratio < 0.8:
                                    continue
                                if city_match and ratio < 0.5:
                                    continue
                                
                                similarity = compute_unified_confidence(ratio, addr_score)
                                is_fab = 'fab' in name.lower()
                                verdict = 'FabHotel Chain' if is_fab else ('Potential Duplicate (Non-Fab)' if city_match else 'City Mismatch Warning')

                                res = list(row_data)
                                res.extend([name, 'MakeMyTrip', location, f"{similarity}%", verdict, url, first_photo, '', ''])
                                self.results.append(res)
                                found_match = True
                                found_match = True

                    except Exception as e:
                        self.progress.emit(idx + 1, total, f"⚠️ Error on {platform}: {e}")

                if not found_match:
                    res = list(row_data)
                    res.extend([
                        '', # Candidate Name
                        '', # Platform
                        '', # Candidate Address
                        '', # Name Similarity
                        'No Match Found', # Verdict
                        '', # Candidate URL
                        '', # Candidate Photo URL
                        '', # Booking Hotel ID
                        ''  # Candidate Lat,Long
                    ])
                    self.results.append(res)

                try:
                    added_suffixes = [r[len(row_data):] for r in self.results[initial_results_len:]]
                    db_cache.set_cached_parallel_finder(query, target_lat, target_lng, added_suffixes)
                    db_cache.update_batch_run('parallel_finder_batch', 'bulk_input', idx + 1, total, 'RUNNING', '')
                except Exception:
                    pass

            try:
                browser.close()
            except Exception:
                pass

        # Write multi-row CSV
        output_path = str(Path.home() / "Downloads" / f"parallel_listings_{int(time.time())}.csv")
        try:
            db_cache.update_batch_run('parallel_finder_batch', 'bulk_input', total, total, 'FINISHED', output_path)
        except Exception:
            pass
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if self.headers:
                    header_prefix = self.headers
                else:
                    header_prefix = [f"Col {i+1}" for i in range(max_parts)]
                    if max_parts >= 2:
                        header_prefix[0] = 'Target Name'
                        header_prefix[1] = 'Target City'
                fieldnames = header_prefix + ['Candidate Name', 'Platform', 'Candidate Address', 'Name Similarity', 'Verdict', 'Candidate URL', 'Candidate Photo URL', 'Booking Hotel ID', 'Candidate Lat,Long']
                writer.writerow(fieldnames)
                for res in self.results:
                    writer.writerow(res)
            
            # Generate Dashboard HTML
            try:
                from dashboard_generator import generate_dashboard_report
                html_path = output_path.replace('.csv', '_dashboard.html')
                generate_dashboard_report(self.results, fieldnames, html_path)
            except Exception as d_err:
                print(f"Error generating dashboard: {d_err}")
                
        except Exception as e:
            print(f"Error writing CSV: {e}")

        self.finished.emit(self.results, output_path)


# ── Bulk Link Builder Worker ──────────────────────────────

class BulkLinkBuilderWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list, str) # results list, output file path

    def __init__(self, items, original_rows=None, original_headers=None):
        super().__init__()
        self.items = items
        self.original_rows = original_rows or []
        self.original_headers = original_headers or []
        self._stop = False
        self._pause = False
        self.results = []

    def stop(self):
        self._stop = True

    def pause(self):
        self._pause = True

    def resume(self):
        self._pause = False

    def run(self):
        total = len(self.items)
        self.results = []
        
        for i, item in enumerate(self.items):
            while self._pause and not self._stop:
                self.msleep(100)
            if self._stop:
                break
                
            name = item.get('name', '')
            city = item.get('city', '')
            hotel_id = item.get('hotel_id', '')
            url = item.get('url', '')
            
            self.progress.emit(i + 1, total, f"Building links for: {name or hotel_id or 'Unknown'}")
            
            # Format URLs offline using build_all_platform_links
            input_data = {'name': name, 'city': city, 'hotel_id': hotel_id, 'url': url}
            links = build_all_platform_links(input_data)
            
            res = dict(item)
            for platform_name in ['Booking.com', 'MakeMyTrip', 'Agoda', 'Expedia']:
                res[platform_name] = links.get(platform_name, '')
            self.results.append(res)
            
            # Minor sleep delay to stream progress bar animations smoothly
            self.msleep(2)
            
        # Write CSV on finish
        output_path = str(Path.home() / "Downloads" / f"bulk_links_{int(time.time())}.csv")
        try:
            fieldnames = []
            if self.original_headers:
                fieldnames = list(self.original_headers)
                for plat in ['Booking.com Link', 'MakeMyTrip Link', 'Agoda Link', 'Expedia Link']:
                    if plat not in fieldnames:
                        fieldnames.append(plat)
            else:
                fieldnames = ['Name', 'City', 'FHID', 'Existing URL', 'Booking.com Link', 'MakeMyTrip Link', 'Agoda Link', 'Expedia Link']
                
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(fieldnames)
                
                for idx, res in enumerate(self.results):
                    if self.original_rows and idx < len(self.original_rows):
                        row = list(self.original_rows[idx])
                        while len(row) < len(self.original_headers):
                            row.append('')
                        for plat_name in ['Booking.com', 'MakeMyTrip', 'Agoda', 'Expedia']:
                            row.append(res.get(plat_name, ''))
                        writer.writerow(row)
                    else:
                        row = [
                            res.get('name', ''),
                            res.get('city', ''),
                            res.get('hotel_id', ''),
                            res.get('url', ''),
                            res.get('Booking.com', ''),
                            res.get('MakeMyTrip', ''),
                            res.get('Agoda', ''),
                            res.get('Expedia', '')
                        ]
                        writer.writerow(row)
        except Exception as e:
            print(f"Error writing CSV: {e}")
            
        self.finished.emit(self.results, output_path)


# ── Image Downloader for Comparison Dialog ───────────────

class ImageDownloader(QThread):
    loaded = pyqtSignal(bytes, str) # image_bytes, tag ('target' or 'candidate')

    def __init__(self, url, tag):
        super().__init__()
        self.url = url
        self.tag = tag

    def run(self):
        if not self.url or not self.url.startswith('http'):
            return
        try:
            import urllib.request
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            req = urllib.request.Request(self.url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                img_bytes = response.read()
                self.loaded.emit(img_bytes, self.tag)
        except Exception as e:
            print(f"Error downloading image for {self.tag}: {e}")


# ── Photo Comparison Dialog ───────────────────────────────

class PhotoCompareDialog(QDialog):
    def __init__(self, target_info, candidate_info, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Audit Parallel Listing Duplicate — Visual Comparison")
        self.setFixedSize(900, 600)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI'; }
            QLabel { color: #e0e0e0; }
            QPushButton { border-radius: 6px; padding: 8px 16px; font-weight: bold; border: none; }
            QPushButton:hover { opacity: 0.9; }
        """)

        self.result_action = None
        self.target_photos = target_info.get('photos', [target_info.get('photo_url')]) if target_info.get('photos') else [target_info.get('photo_url', '')]
        self.candidate_photos = candidate_info.get('photos', [candidate_info.get('photo_url')]) if candidate_info.get('photos') else [candidate_info.get('photo_url', '')]
        
        # Clean empty links
        self.target_photos = [p for p in self.target_photos if p]
        self.candidate_photos = [p for p in self.candidate_photos if p]

        self.downloaders = []

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # Header description
        desc_label = QLabel("Compare up to 10 photos side by side. Click thumbnails to switch the preview.")
        desc_label.setStyleSheet("color: #aaa; font-size: 11px;")
        main_layout.addWidget(desc_label)

        # Content split
        content_layout = QHBoxLayout()
        content_layout.setSpacing(15)

        # Left Column: Target Reference Hotel
        left_box = QGroupBox("Target Reference Hotel")
        left_box.setStyleSheet("QGroupBox { border: 1px solid #e94560; border-radius: 6px; font-weight: bold; color: #e94560; margin-top: 5px; padding-top: 10px; }")
        left_layout = QVBoxLayout(left_box)
        left_layout.setSpacing(6)

        t_name = QLabel(target_info.get('name', 'N/A'))
        t_name.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        t_name.setWordWrap(True)
        left_layout.addWidget(t_name)

        t_plat = QLabel(f"Platform: {target_info.get('platform', 'N/A')} | Address: {target_info.get('address', 'N/A')}")
        t_plat.setStyleSheet("color: #888; font-size: 10px;")
        t_plat.setWordWrap(True)
        left_layout.addWidget(t_plat)

        self.t_image = QLabel("No Image")
        self.t_image.setFixedSize(400, 240)
        self.t_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.t_image.setStyleSheet("background-color: #111; border: 1px solid #333; border-radius: 4px; color: #666;")
        left_layout.addWidget(self.t_image)

        # Target thumbnails
        self.t_thumb_layout = QHBoxLayout()
        self.t_thumb_layout.setSpacing(5)
        left_layout.addLayout(self.t_thumb_layout)

        content_layout.addWidget(left_box)

        # Right Column: Candidate Hotel
        right_box = QGroupBox("Parallel Listing Candidate")
        right_box.setStyleSheet("QGroupBox { border: 1px solid #0f3460; border-radius: 6px; font-weight: bold; color: #0f3460; margin-top: 5px; padding-top: 10px; }")
        right_layout = QVBoxLayout(right_box)
        right_layout.setSpacing(6)

        c_name = QLabel(candidate_info.get('name', 'N/A'))
        c_name.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        c_name.setWordWrap(True)
        right_layout.addWidget(c_name)

        c_plat = QLabel(f"Platform: {candidate_info.get('platform', 'N/A')} | Address: {candidate_info.get('address', 'N/A')}")
        c_plat.setStyleSheet("color: #888; font-size: 10px;")
        c_plat.setWordWrap(True)
        right_layout.addWidget(c_plat)

        self.c_image = QLabel("No Image")
        self.c_image.setFixedSize(400, 240)
        self.c_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.c_image.setStyleSheet("background-color: #111; border: 1px solid #333; border-radius: 4px; color: #666;")
        right_layout.addWidget(self.c_image)

        # Candidate thumbnails
        self.c_thumb_layout = QHBoxLayout()
        self.c_thumb_layout.setSpacing(5)
        right_layout.addLayout(self.c_thumb_layout)

        content_layout.addWidget(right_box)

        main_layout.addLayout(content_layout)

        # Similarity score label
        self.match_lbl = QLabel(f"Automatic Visual Match Score: {candidate_info.get('photo_match_score', 'N/A')}")
        self.match_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.match_lbl.setStyleSheet("color: #00bcd4; padding: 5px;")
        main_layout.addWidget(self.match_lbl)

        # Action Buttons Row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_duplicate = QPushButton("Confirm Duplicate Listing")
        self.btn_duplicate.setStyleSheet("background-color: #e94560; color: white;")
        self.btn_duplicate.clicked.connect(self._on_duplicate)
        btn_layout.addWidget(self.btn_duplicate)

        self.btn_safe = QPushButton("Mark Safe / Unique")
        self.btn_safe.setStyleSheet("background-color: #27ae60; color: white;")
        self.btn_safe.clicked.connect(self._on_safe)
        btn_layout.addWidget(self.btn_safe)

        btn_layout.addStretch()

        self.btn_close = QPushButton("Cancel")
        self.btn_close.setStyleSheet("background-color: #555; color: white;")
        self.btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_close)

        main_layout.addLayout(btn_layout)

        # Load thumbnails and setup callbacks
        self.t_pixmaps = {}
        self.c_pixmaps = {}
        self._setup_thumbnails()

    def _setup_thumbnails(self):
        # Target
        for idx, url in enumerate(self.target_photos[:10]):
            btn = QPushButton(f"P{idx+1}")
            btn.setFixedSize(35, 30)
            btn.setStyleSheet("background-color: #333; font-size: 10px; color: white; padding: 2px;")
            btn.clicked.connect(lambda checked, u=url, i=idx: self._view_target_photo(u, i))
            self.t_thumb_layout.addWidget(btn)
        
        # Candidate
        for idx, url in enumerate(self.candidate_photos[:10]):
            btn = QPushButton(f"P{idx+1}")
            btn.setFixedSize(35, 30)
            btn.setStyleSheet("background-color: #333; font-size: 10px; color: white; padding: 2px;")
            btn.clicked.connect(lambda checked, u=url, i=idx: self._view_candidate_photo(u, i))
            self.c_thumb_layout.addWidget(btn)

        # Auto-load first of each
        if self.target_photos:
            self._view_target_photo(self.target_photos[0], 0)
        if self.candidate_photos:
            self._view_candidate_photo(self.candidate_photos[0], 0)

    def _view_target_photo(self, url, idx):
        if url in self.t_pixmaps:
            self.t_image.setPixmap(self.t_pixmaps[url])
        else:
            self.t_image.setText("Loading Image...")
            downloader = ImageDownloader(url, f"target:{url}")
            downloader.loaded.connect(self._on_image_loaded)
            downloader.start()
            self.downloaders.append(downloader)

    def _view_candidate_photo(self, url, idx):
        if url in self.c_pixmaps:
            self.c_image.setPixmap(self.c_pixmaps[url])
        else:
            self.c_image.setText("Loading Image...")
            downloader = ImageDownloader(url, f"candidate:{url}")
            downloader.loaded.connect(self._on_image_loaded)
            downloader.start()
            self.downloaders.append(downloader)

    def _on_image_loaded(self, img_bytes, tag_info):
        try:
            image = QImage.fromData(img_bytes)
            if image.isNull():
                return
            pixmap = QPixmap.fromImage(image)
            scaled = pixmap.scaled(400, 240, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            
            parts = tag_info.split(':', 1)
            tag = parts[0]
            url = parts[1] if len(parts) > 1 else ""

            if tag == 'target':
                self.t_pixmaps[url] = scaled
                self.t_image.setPixmap(scaled)
            else:
                self.c_pixmaps[url] = scaled
                self.c_image.setPixmap(scaled)
        except Exception:
            pass

    def _on_duplicate(self):
        self.result_action = 'duplicate'
        self.accept()

    def _on_safe(self):
        self.result_action = 'safe'
        self.accept()


# ── Parallel Listing Finder Background Search Worker ──────

class ParallelListingWorker(QThread):
    progress = pyqtSignal(str)
    candidate_found = pyqtSignal(dict) # info about candidate
    finished = pyqtSignal(list) # all candidates

    def __init__(self, hotel_name, city, platforms):
        super().__init__()
        self.hotel_name = hotel_name
        self.city = city
        self.platforms = platforms
        self._stop = False
        self.candidates = []

    def stop(self):
        self._stop = True

    def calculate_dhash(self, img_bytes):
        try:
            from PIL import Image
            import io
            image = Image.open(io.BytesIO(img_bytes))
            # Convert to grayscale and resize to 9x8
            image = image.convert('L').resize((9, 8), Image.Resampling.LANCZOS)
            pixels = list(image.getdata())
            difference = []
            for row in range(8):
                for col in range(8):
                    pixel_left = pixels[row * 9 + col]
                    pixel_right = pixels[row * 9 + col + 1]
                    difference.append(pixel_left > pixel_right)
            return difference
        except Exception:
            return None

    def dhash_similarity(self, hash1, hash2):
        if not hash1 or not hash2:
            return 0.0
        hamming_dist = sum(p1 != p2 for p1, p2 in zip(hash1, hash2))
        return (64 - hamming_dist) / 64.0

    def download_image_bytes(self, url):
        try:
            import urllib.request
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as response:
                return response.read()
        except Exception:
            return None

    def run(self):
        from playwright.sync_api import sync_playwright
        import urllib.parse
        import difflib

        cleaned_target = clean_hotel_name(self.hotel_name)
        if self.city.lower() in cleaned_target.lower():
            query = cleaned_target
        else:
            query = f"{cleaned_target} {self.city}".strip()
        query_encoded = urllib.parse.quote_plus(query)

        self.progress.emit(f"Launching search for '{query}'...")

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                    locale="en-US",
                    timezone_id="Asia/Kolkata"
                )
                context.route("**/*", lambda route: route.abort() if route.request.resource_type in ("font", "media") else route.continue_())
            except Exception as e:
                self.progress.emit(f"Failed to launch browser: {e}")
                self.finished.emit([])
                return

            target_photos = []
            target_hashes = []
            target_url = ""

            # Iterate platforms to scan for candidates
            for platform in self.platforms:
                if self._stop:
                    break

                self.progress.emit(f"Searching platform: {platform.upper()}...")
                try:
                    cards = []
                    page = context.new_page()
                    
                    if platform == 'booking':
                        search_url = f"https://www.booking.com/searchresults.html?ss={query_encoded}"
                        page.goto(search_url, timeout=25000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)
                        cards = page.query_selector_all('[data-testid="property-card"], [data-testid="sr-property-card-common"]')[:5]
                    elif platform == 'agoda':
                        search_url = f"https://www.agoda.com/en-gb/search?text={query_encoded}"
                        page.goto(search_url, timeout=25000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2500)
                        cards = page.query_selector_all('li[data-selenium="property-item"], [data-selenium="hotel-item"], .PropertyCard, a[href*="/hotel/"]')[:5]
                    elif platform == 'expedia':
                        search_url = f"https://www.expedia.com/Hotel-Search?destination={query_encoded}"
                        page.goto(search_url, timeout=25000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2500)
                        cards = page.query_selector_all('[data-stid="property-card"], .uitk-card')[:5]
                    elif platform == 'mmt':
                        import pickle
                        from pathlib import Path
                        cookies_path = Path.home() / ".scrape-ratings" / "mmt_cookies.pkl"
                        if cookies_path.exists():
                            try:
                                with open(cookies_path, 'rb') as f:
                                    cookies = pickle.load(f)
                                page.context.add_cookies(cookies)
                            except Exception as e:
                                print(f"Failed to load MMT cookies: {e}")
                        search_url = f"https://www.makemytrip.com/hotels/hotel-listing/?searchText={query_encoded}"
                        page.goto(search_url, timeout=25000, wait_until="domcontentloaded")
                        page.wait_for_timeout(3500)
                        cards = page.query_selector_all('.infinite-scroll-component > div, [class*="ListingCard"]')[:5]

                    for card in cards:
                        if self._stop:
                            break
                        try:
                            # 1. Extract Details
                            name, location, url, first_photo = "", "", "", ""
                            if platform == 'booking':
                                name_el = card.query_selector('[data-testid="title"], h3, .sr-hotel__name')
                                name = name_el.inner_text().strip() if name_el else ''
                                loc_el = card.query_selector('[data-testid="address"], [data-testid="location"]')
                                location = loc_el.inner_text().strip() if loc_el else ''
                                link_el = card.query_selector('a[data-testid="title-link"], a[href*="/hotel/"]')
                                url = link_el.get_attribute('href') if link_el else ''
                                if url and url.startswith('/'):
                                    url = "https://www.booking.com" + url
                                img_el = card.query_selector('img[data-testid="image"], img')
                                first_photo = img_el.get_attribute('src') if img_el else ''
                            elif platform == 'agoda':
                                name_el = card.query_selector('[data-selenium="hotel-name"], h3, .property-card-title')
                                name = name_el.inner_text().strip() if name_el else ''
                                loc_el = card.query_selector('[data-selenium="area-city-name"], .property-card-location')
                                location = loc_el.inner_text().strip() if loc_el else ''
                                link_el = card.query_selector('a[href*="/hotel/"], a')
                                url = link_el.get_attribute('href') if link_el else ''
                                if url and url.startswith('/'):
                                    url = "https://www.agoda.com" + url
                                img_el = card.query_selector('img')
                                first_photo = img_el.get_attribute('src') if img_el else ''
                            elif platform == 'expedia':
                                name_el = card.query_selector('h3, h4')
                                name = name_el.inner_text().strip() if name_el else ''
                                loc_el = card.query_selector('[data-test-id="neighborhood"]')
                                location = loc_el.inner_text().strip() if loc_el else ''
                                link_el = card.query_selector('a')
                                url = link_el.get_attribute('href') if link_el else ''
                                if url and url.startswith('/'):
                                    url = "https://www.expedia.com" + url
                                img_el = card.query_selector('img')
                                first_photo = img_el.get_attribute('src') if img_el else ''
                            elif platform == 'mmt':
                                name_el = card.query_selector('p[class*="hotelName"], h3, span[class*="hotelName"]')
                                name = name_el.inner_text().strip() if name_el else ''
                                loc_el = card.query_selector('span[class*="location"]')
                                location = loc_el.inner_text().strip() if loc_el else ''
                                link_el = card.query_selector('a')
                                url = link_el.get_attribute('href') if link_el else ''
                                if url and url.startswith('/'):
                                    url = "https://www.makemytrip.com" + url
                                img_el = card.query_selector('img')
                                first_photo = img_el.get_attribute('src') if img_el else ''

                            if url:
                                url = url.split('?')[0]
                            if not name:
                                continue

                            # Clean candidate name of Devanagari/Hindi/New Window texts
                            name = clean_hotel_name(name)
                            cleaned_cand = name

                            # Exclude exact target/self matches
                            ratio = difflib.SequenceMatcher(None, cleaned_target.lower(), cleaned_cand.lower()).ratio()
                            similarity = int(ratio * 100)

                            # First card found becomes the Target Reference Property if we don't have one!
                            is_reference_hotel = False
                            if not target_url:
                                target_url = url
                                self.progress.emit(f"Designated target reference hotel: {name} ({platform.upper()})")
                                is_reference_hotel = True
                                # Fetch details photos for target
                                try:
                                    ref_page = context.new_page()
                                    ref_page.goto(url, timeout=15000, wait_until="domcontentloaded")
                                    ref_page.wait_for_timeout(1000)
                                    img_selectors = {
                                        'booking': '.gallery-image-container img, .gallery_grid img, img[src*="max1280x900"], a.gallery-entry img, .bh-photo-grid-item img, .bh-photo-grid-thumb img, .photo_grid_item img, [data-photo-id] img, img.kpv_photo',
                                        'agoda': '.PropertyGallery img, img[src*="images/hotel"], img[src*="agoda.com"]',
                                        'expedia': '[data-stid="gallery-image"] img, img[src*="expedia.com"], .media-gallery img',
                                        'mmt': 'img[id*="detpg_"], img[src*="hotel"], .gallery img'
                                    }
                                    sel = img_selectors.get(platform, 'img')
                                    img_els = ref_page.query_selector_all(sel)
                                    if not img_els:
                                        img_els = ref_page.query_selector_all('img[src*="hotel"], img[src*="max"], img[src*="images/hotel"]')
                                    if not img_els:
                                        img_els = [el for el in ref_page.query_selector_all('img') if el.get_attribute('src') and ('hotel' in el.get_attribute('src').lower() or 'max' in el.get_attribute('src').lower())]
                                    for img in img_els:
                                        src = img.get_attribute('src') or img.get_attribute('data-src') or img.get_attribute('data-lazy')
                                        if src and src not in target_photos:
                                            if src.startswith('//'): src = 'https:' + src
                                            target_photos.append(src)
                                            if len(target_photos) >= 10:
                                                break
                                    ref_page.close()
                                    self.progress.emit(f"Loaded {len(target_photos)} reference photos from details page.")
                                except Exception as e:
                                    self.progress.emit(f"Error loading reference photos: {e}")
                                
                                # Compute target hashes
                                for t_url in target_photos:
                                    ib = self.download_image_bytes(t_url)
                                    if ib:
                                        h = self.calculate_dhash(ib)
                                        if h:
                                            target_hashes.append(h)

                            # Skip self-match check
                            if not is_reference_hotel and (url == target_url or similarity >= 99):
                                # Avoid marking reference hotel as its own duplicate candidate
                                continue

                            # Navigate details page for the candidate to fetch up to 10 photos
                            cand_photos = []
                            cand_hashes = []
                            try:
                                cand_page = context.new_page()
                                cand_page.goto(url, timeout=15000, wait_until="domcontentloaded")
                                cand_page.wait_for_timeout(1000)
                                
                                img_selectors = {
                                    'booking': '.gallery-image-container img, .gallery_grid img, img[src*="max1280x900"], a.gallery-entry img, .bh-photo-grid-item img, .bh-photo-grid-thumb img, .photo_grid_item img, [data-photo-id] img, img.kpv_photo',
                                    'agoda': '.PropertyGallery img, img[src*="images/hotel"], img[src*="agoda.com"]',
                                    'expedia': '[data-stid="gallery-image"] img, img[src*="expedia.com"], .media-gallery img',
                                    'mmt': 'img[id*="detpg_"], img[src*="hotel"], .gallery img'
                                }
                                sel = img_selectors.get(platform, 'img')
                                img_els = cand_page.query_selector_all(sel)
                                if not img_els:
                                    # Fallback
                                    img_els = cand_page.query_selector_all('img[src*="hotel"], img[src*="max"], img[src*="images/hotel"]')
                                if not img_els:
                                    img_els = [el for el in cand_page.query_selector_all('img') if el.get_attribute('src') and ('hotel' in el.get_attribute('src').lower() or 'max' in el.get_attribute('src').lower())]
                                
                                for img in img_els:
                                    src = img.get_attribute('src') or img.get_attribute('data-src') or img.get_attribute('data-lazy')
                                    if src and src not in cand_photos:
                                        if src.startswith('//'): src = 'https:' + src
                                        cand_photos.append(src)
                                        if len(cand_photos) >= 10:
                                            break
                                cand_page.close()
                            except Exception:
                                pass

                            if not cand_photos and first_photo:
                                cand_photos.append(first_photo)

                            # Match hashes to find best visual similarity
                            match_count = 0
                            for curl in cand_photos:
                                cb = self.download_image_bytes(curl)
                                if cb:
                                    ch = self.calculate_dhash(cb)
                                    if ch:
                                        # Check if it matches any target hash at >= 95%
                                        best_sim = max([self.dhash_similarity(ch, th) for th in target_hashes]) if target_hashes else 0.0
                                        if best_sim >= 0.95:
                                            match_count += 1

                            photo_match_score = f"{match_count}/{max(1, len(cand_photos))} matched at 95%+"
                            
                            cand = {
                                'name': name,
                                'platform': platform.capitalize() if platform != 'mmt' else 'MakeMyTrip',
                                'address': location or self.city,
                                'url': url,
                                'photo_url': first_photo or (cand_photos[0] if cand_photos else ''),
                                'photos': cand_photos,
                                'similarity': f"{similarity}%",
                                'similarity_val': similarity,
                                'photo_match_score': photo_match_score
                            }
                            self.candidates.append(cand)
                            self.candidate_found.emit(cand)
                        except Exception as ce:
                            print(f"Error parsing card details: {ce}")
                    
                    page.close()
                except Exception as pe:
                    self.progress.emit(f"Error scraping {platform.upper()}: {pe}")

            try:
                if not getattr(browser, 'is_cdp', False): browser.close()
            except Exception:
                pass

        self.progress.emit("Search finished.")
        self.finished.emit(self.candidates)


# ── Image Validation Helper ───────────────────────────────

def is_valid_hotel_photo_url(url: str) -> bool:
    """Filter out non-hotel assets such as flags, logos, avatars, badges, etc."""
    if not url:
        return False
    url_lower = url.lower()
    rejects = ["flag", "logo", "icon", "design-assets", "sprite", "checkmark", "star", "badge", "avatar", "marker", "map", "heart", "share"]
    if any(x in url_lower for x in rejects):
        return False
    if not (url_lower.startswith("http://") or url_lower.startswith("https://") or url_lower.startswith("//") or url_lower.startswith("data:image")):
        return False
    return True

# ── Clean Hotel Name Helper (FabHotels Duplicate Checking) ──

def clean_hotel_name(name: str) -> str:
    """Strip brand prefixes, Devanagari/Hindi chars, and all non-Latin UI text."""
    if not name:
        return ""
    # Strip ALL Devanagari / Hindi Unicode block characters (\u0900-\u097F)
    name = re.sub(r'[\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F\u0A80-\u0AFF\u0B00-\u0B7F]+', '', name)
    # Strip common window/open texts in any language appended to the name
    name = re.sub(r'(?i)opens?\s*in\s*(?:a\s*)?new\s*(?:window|tab)s?', '', name)
    name = re.sub(r'(?i)opens?\s*new\s*(?:window|tab)s?', '', name)
    # Strip non-ASCII characters that sneak through (Hindi UI, icons, etc.)
    name = name.encode('ascii', 'ignore').decode('ascii')
    # Strip common brand prefixes/suffixes
    name = re.sub(r'\b(?:fabhotel|fabhotels|fabexpress|fab)\b', '', name, flags=re.IGNORECASE)
    # Clean whitespace
    return re.sub(r'\s+', ' ', name).strip()



def compute_address_score(target_address, cand_location):
    import re
    if not target_address or not cand_location:
        return 0.5
        
    fillers = {"the", "a", "near", "opposite", "behind", "hotel", "resort", "inn", "stay", "and", "of", "to", "for", "with", "at", "by", "on"}
    
    def tokenize(text):
        text = text.lower()
        text = text.replace("rd.", "road").replace("rd", "road")
        text = text.replace("st.", "street").replace("st", "street")
        text = text.replace("sec.", "sector").replace("sec", "sector")
        tokens = re.findall(r'\b\w+\b', text)
        return [t for t in tokens if t not in fillers and len(t) > 1]

    t_tokens = tokenize(target_address)
    c_tokens = tokenize(cand_location)
    
    if not t_tokens or not c_tokens:
        return 0.5
        
    def is_critical_token(t):
        return t.isdigit() or any(suffix in t for suffix in ("nagar", "sector", "road", "street", "lane", "colony", "enclave", "vihar", "chowk"))
        
    t_critical = set(t for t in t_tokens if is_critical_token(t))
    c_critical = set(c for c in c_tokens if is_critical_token(c))
    
    intersection = set(t_tokens) & set(c_tokens)
    
    t_sectors = set(t for t in t_tokens if t.startswith("sector") or (t.isdigit() and len(t) <= 3))
    c_sectors = set(c for c in c_tokens if c.startswith("sector") or (c.isdigit() and len(c) <= 3))
    if t_sectors and c_sectors and not (t_sectors & c_sectors):
        return 0.1
        
    score = len(intersection) / max(1, min(len(t_tokens), len(c_tokens)))
    if t_critical & c_critical:
        score = min(1.0, score + 0.2)
        
    return score

def compute_unified_confidence(name_similarity, address_score, dist_km=None):
    name_score = name_similarity
    addr_score = address_score
    
    if dist_km is not None:
        if dist_km <= 0.3:
            dist_score = 1.0
        elif dist_km >= 3.0:
            dist_score = 0.0
        else:
            dist_score = 1.0 - (dist_km - 0.3) / 2.7
        conf = (name_score * 0.40) + (dist_score * 0.40) + (addr_score * 0.20)
    else:
        conf = (name_score * 0.50) + (addr_score * 0.50)
        
    return int(conf * 100)

def verify_candidate_enhanced(target_name, target_city, target_address, cand_name, cand_location):
    import difflib
    import re
    target_name_c = target_name.lower().strip()
    cand_name_c   = cand_name.lower().strip()
    target_city_c = target_city.lower().strip()
    cand_loc_c    = cand_location.lower().strip()
    target_add_c  = (target_address or "").lower().strip()

    name_similarity = difflib.SequenceMatcher(None, target_name_c, cand_name_c).ratio()
    address_score = compute_address_score(target_add_c or target_city_c, cand_loc_c)

    city_match = False
    if cand_loc_c:
        if target_city_c in cand_loc_c:
            city_match = True
        else:
            tc_tokens = set(re.findall(r'\w{4,}', target_city_c))
            cl_tokens = set(re.findall(r'\w{4,}', cand_loc_c))
            if tc_tokens & cl_tokens:
                city_match = True
            if not city_match and target_add_c:
                ta_tokens = set(re.findall(r'\w{5,}', target_add_c))
                if ta_tokens & cl_tokens:
                    city_match = True

    return name_similarity, address_score, city_match

# ── Exact Match Helper ────────────────────────────────────

def verify_candidate(target_name, target_city, target_address, cand_name, cand_location):
    """
    Returns (similarity_ratio, city_match_bool).
    CRITICAL FIX: empty cand_location must NOT count as a city match.
    In Python, '' in 'mumbai' is True — that was the root cause of Jamshedpur false matches.
    """
    import difflib
    target_name_c = target_name.lower().strip()
    cand_name_c   = cand_name.lower().strip()
    target_city_c = target_city.lower().strip()
    cand_loc_c    = cand_location.lower().strip()   # may be empty
    target_add_c  = (target_address or "").lower().strip()

    # Name similarity
    ratio = difflib.SequenceMatcher(None, target_name_c, cand_name_c).ratio()

    # City / Location overlap
    # GUARD: never treat empty cand_location as a match
    city_match = False
    if cand_loc_c:  # only run if we actually have a location string
        if target_city_c in cand_loc_c or target_city_c in cand_loc_c:
            city_match = True
        else:
            tc_tokens = set(re.findall(r'\w{4,}', target_city_c))
            cl_tokens = set(re.findall(r'\w{4,}', cand_loc_c))
            if tc_tokens & cl_tokens:
                city_match = True
            if not city_match and target_add_c:
                ta_tokens = set(re.findall(r'\w{5,}', target_add_c))
                if ta_tokens & cl_tokens:
                    city_match = True

    return ratio, city_match


# ── Link Builder ──────────────────────────────────────────

def build_all_platform_links(input_data: dict) -> dict[str, str]:

    """
    Given hotel data (name, city, hotel_id, url), build working
    front-end links for all available platforms.
    Returns {platform_name: url}
    """
    links = {}
    for key, platform in AVAILABLE_PLATFORMS.items():
        try:
            url = platform.build_url(input_data)
            if url:
                links[platform.name] = url
        except Exception:
            pass
    return links


# ── Page Scan Worker for Thread-Safety ────────────────────

class PageScanWorker(QThread):
    finished = pyqtSignal(dict)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            scanner = PageScanner()
            result = scanner.scan(self.url)
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit({'url': self.url, 'error': str(e)})


# ── God Mode Tab Widget ───────────────────────────────────

class GodModeTab(QWidget):
    """The God Mode tab with Page Scanner, Element Picker, and Link Builder."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QWidget { background-color: #1a1a2e; color: #e0e0e0; font-size: 12px; }
            QPushButton { background-color: #0f3460; color: white; border: none;
                         padding: 8px 16px; border-radius: 6px; }
            QPushButton:hover { background-color: #16213e; }
            QPushButton:disabled { background-color: #333; color: #666; }
            QLineEdit, QTextEdit { background-color: #16213e; color: white;
                                  border: 1px solid #444; border-radius: 4px; padding: 6px; }
            QGroupBox { border: 1px solid #333; border-radius: 6px; margin-top: 12px;
                       padding-top: 16px; font-weight: bold; color: #e94560; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QTableWidget { background-color: #16213e; color: white; border: 1px solid #333; }
            QTableWidget::item { padding: 4px; }
            QHeaderView::section { background-color: #0f3460; color: white; padding: 4px; border: 1px solid #333; }
            QListWidget { background-color: #16213e; color: white; border: 1px solid #444; }
            QComboBox { background: #16213e; color: white; border: 1px solid #333; padding: 4px; }
            QSpinBox { background: #16213e; color: white; border: 1px solid #333; padding: 4px; }
            QProgressBar { border: 1px solid #333; border-radius: 4px; text-align: center; color: white; }
            QProgressBar::chunk { background-color: #e94560; border-radius: 3px; }
            QScrollArea { border: none; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # Title
        title = QLabel("God Mode Scraper — Scan Anything, Scrape Everything")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #e94560;")
        layout.addWidget(title)

        subtitle = QLabel("Visit any page, auto-detect scrapeable data, or build working links from partial info")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(subtitle)

        # ── Sub-tabs within God Mode ────────────────────────
        self.god_tabs = QTabWidget()
        self.god_tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background: #1a1a2e; }
            QTabBar::tab { background: #0f3460; color: #888; padding: 6px 14px;
                          margin-right: 2px; border-top-left-radius: 4px;
                          border-top-right-radius: 4px; }
            QTabBar::tab:selected { background: #16213e; color: white; }
        """)

        # Bulk Link Builder variables
        self.bulk_link_items = []
        self.bulk_link_original_rows = []
        self.bulk_link_original_headers = []
        self.bulk_link_csv_path = None
        self.bulk_link_output_path = None
        self.bulk_link_worker = None

        # Parallel Listing Finder variables
        self.parallel_worker = None
        self.parallel_candidates = []
        self.parallel_reference = None

        self.god_tabs.addTab(self._build_scanner_tab(), "Page Scanner")
        self.god_tabs.addTab(self._build_link_builder_tab(), "Link Builder")
        self.god_tabs.addTab(self._build_parallel_finder_tab(), "Parallel Listing Finder")
        layout.addWidget(self.god_tabs)

    def _build_scanner_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        # URL input
        url_row = QHBoxLayout()
        self.scanner_url = QLineEdit()
        self.scanner_url.setPlaceholderText("Enter any URL to scan (e.g. hotel page, listing page, any website)...")
        self.scanner_url.returnPressed.connect(self._run_scan)
        url_row.addWidget(self.scanner_url)

        self.scan_btn = QPushButton("Scan Page")
        self.scan_btn.setStyleSheet("background-color: #e94560; font-weight: bold;")
        self.scan_btn.clicked.connect(self._run_scan)
        url_row.addWidget(self.scan_btn)
        layout.addLayout(url_row)

        # Scan results area (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scan_content = QWidget()
        self.scan_layout = QVBoxLayout(scan_content)
        self.scan_layout.setSpacing(8)

        # Placeholder
        self.scan_placeholder = QLabel("Enter a URL and click 'Scan Page' to detect all scrapeable data.\n"
                                       "The scanner will find tables, lists, cards, ratings, JSON data, and more.")
        self.scan_placeholder.setStyleSheet("color: #666; font-size: 12px; padding: 20px;")
        self.scan_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scan_layout.addWidget(self.scan_placeholder)

        scroll.setWidget(scan_content)
        layout.addWidget(scroll, 1)

        # Field config area
        config_group = QGroupBox("Selected Fields to Scrape")
        config_layout = QVBoxLayout(config_group)

        self.field_list = QListWidget()
        self.field_list.setMaximumHeight(120)
        config_layout.addWidget(self.field_list)

        field_btn_row = QHBoxLayout()
        self.remove_field_btn = QPushButton("Remove Selected")
        self.remove_field_btn.clicked.connect(self._remove_field)
        field_btn_row.addWidget(self.remove_field_btn)

        self.field_input = QLineEdit()
        self.field_input.setPlaceholderText("Custom CSS selector...")
        field_btn_row.addWidget(self.field_input)

        self.add_custom_btn = QPushButton("Add Custom Field")
        self.add_custom_btn.clicked.connect(self._add_custom_field)
        field_btn_row.addWidget(self.add_custom_btn)

        config_layout.addLayout(field_btn_row)
        layout.addWidget(config_group)

        # Scrape URLs + results
        scrape_group = QGroupBox("Scrape Multiple URLs")
        scrape_layout = QVBoxLayout(scrape_group)

        url_input_row = QHBoxLayout()
        self.scrape_urls_input = QTextEdit()
        self.scrape_urls_input.setPlaceholderText("Paste URLs to scrape (one per line)...")
        self.scrape_urls_input.setMaximumHeight(60)
        url_input_row.addWidget(self.scrape_urls_input)

        url_input_row2 = QVBoxLayout()
        self.scrape_btn = QPushButton("Scrape All URLs")
        self.scrape_btn.setStyleSheet("background-color: #27ae60; font-weight: bold;")
        self.scrape_btn.clicked.connect(self._start_mass_scrape)
        url_input_row2.addWidget(self.scrape_btn)

        self.bulk_csv_btn = QPushButton("Upload CSV")
        self.bulk_csv_btn.setStyleSheet("background-color: #3498db; font-weight: bold;")
        self.bulk_csv_btn.clicked.connect(self._browse_bulk_csv)
        url_input_row2.addWidget(self.bulk_csv_btn)

        self.scrape_progress = QProgressBar()
        self.scrape_progress.setVisible(False)
        url_input_row2.addWidget(self.scrape_progress)
        url_input_row.addLayout(url_input_row2)

        scrape_layout.addLayout(url_input_row)
        layout.addWidget(scrape_group)

        # Log
        self.scanner_log = QTextEdit()
        self.scanner_log.setReadOnly(True)
        self.scanner_log.setMaximumHeight(100)
        self.scanner_log.setStyleSheet("background: #111; color: #a0e0a0; font-family: Consolas; font-size: 11px;")

        log_header = QHBoxLayout()
        log_title = QLabel("Scanner Logs:")
        log_title.setStyleSheet("font-weight: bold; color: #888;")
        log_header.addWidget(log_title)
        
        clear_scan_log_btn = QPushButton("Clear Logs")
        clear_scan_log_btn.clicked.connect(self.scanner_log.clear)
        clear_scan_log_btn.setMaximumWidth(100)
        clear_scan_log_btn.setStyleSheet("background-color: #555; font-weight: bold; padding: 4px 8px;")
        log_header.addWidget(clear_scan_log_btn)
        layout.addLayout(log_header)

        layout.addWidget(self.scanner_log)

        return tab

    def _build_link_builder_tab(self):
        tab = QWidget()
        main_layout = QHBoxLayout(tab)
        main_layout.setSpacing(15)

        # ── Left Column: Single Link Builder ──────────────────
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        input_group = QGroupBox("Single Link Builder")
        input_grid = QGridLayout(input_group)

        input_grid.addWidget(QLabel("Hotel Name:"), 0, 0)
        self.link_name = QLineEdit()
        self.link_name.setPlaceholderText("e.g. Grand Hyatt")
        input_grid.addWidget(self.link_name, 0, 1)

        input_grid.addWidget(QLabel("City:"), 1, 0)
        self.link_city = QLineEdit()
        self.link_city.setPlaceholderText("e.g. Mumbai")
        input_grid.addWidget(self.link_city, 1, 1)

        input_grid.addWidget(QLabel("Hotel / FH ID:"), 2, 0)
        self.link_id = QLineEdit()
        self.link_id.setPlaceholderText("e.g. 32775 (MMT FH ID)")
        input_grid.addWidget(self.link_id, 2, 1)

        input_grid.addWidget(QLabel("Existing URL:"), 3, 0)
        self.link_url = QLineEdit()
        self.link_url.setPlaceholderText("Any existing URL (optional)")
        input_grid.addWidget(self.link_url, 3, 1)

        build_btn = QPushButton("Build Working Links")
        build_btn.setStyleSheet("background-color: #e94560; font-weight: bold; padding: 10px;")
        build_btn.clicked.connect(self._build_links)
        input_grid.addWidget(build_btn, 4, 0, 1, 2)

        left_layout.addWidget(input_group)

        results_group = QGroupBox("Generated Links")
        results_layout = QVBoxLayout(results_group)

        self.links_table = QTableWidget()
        self.links_table.setColumnCount(2)
        self.links_table.setHorizontalHeaderLabels(["Platform", "Working URL / Search Link"])
        self.links_table.horizontalHeader().setStretchLastSection(True)
        results_layout.addWidget(self.links_table)

        copy_btn = QPushButton("Copy All Links")
        copy_btn.clicked.connect(self._copy_links)
        results_layout.addWidget(copy_btn)

        left_layout.addWidget(results_group, 1)

        # Log
        self.link_log = QTextEdit()
        self.link_log.setReadOnly(True)
        self.link_log.setMaximumHeight(80)
        self.link_log.setStyleSheet("background: #111; color: #a0e0a0; font-family: Consolas; font-size: 11px;")
        left_layout.addWidget(self.link_log)

        main_layout.addWidget(left_widget, 1)

        # ── Right Column: Bulk Link Builder ─────────────────
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        bulk_group = QGroupBox("Bulk Link Builder")
        bulk_layout = QVBoxLayout(bulk_group)
        bulk_layout.setSpacing(8)

        bulk_label = QLabel("Paste multiple hotels (one per line, format: name, city) OR load a CSV:")
        bulk_label.setStyleSheet("color: #aaa; font-size: 11px;")
        bulk_layout.addWidget(bulk_label)

        self.bulk_link_input = QTextEdit()
        self.bulk_link_input.setPlaceholderText(
            "e.g.\nGrand Hyatt, Mumbai\nHotel Taj Palace, Delhi\nhttp://booking.com/hotel/in/some-hotel\n32775"
        )
        self.bulk_link_input.setMaximumHeight(120)
        bulk_layout.addWidget(self.bulk_link_input)

        # Controls Row
        ctrl_row = QHBoxLayout()
        self.bulk_link_browse_btn = QPushButton("Browse CSV")
        self.bulk_link_browse_btn.clicked.connect(self.browse_link_csv)
        ctrl_row.addWidget(self.bulk_link_browse_btn)

        self.bulk_link_sample_btn = QPushButton("Download Sample")
        self.bulk_link_sample_btn.clicked.connect(self.download_link_sample)
        self.bulk_link_sample_btn.setStyleSheet("background-color: #3498db; font-weight: bold;")
        ctrl_row.addWidget(self.bulk_link_sample_btn)

        self.bulk_link_start_btn = QPushButton("Start")
        self.bulk_link_start_btn.clicked.connect(self.start_bulk_links)
        self.bulk_link_start_btn.setStyleSheet("background-color: #e94560; font-weight: bold;")
        ctrl_row.addWidget(self.bulk_link_start_btn)

        self.bulk_link_pause_btn = QPushButton("Pause")
        self.bulk_link_pause_btn.clicked.connect(self.pause_bulk_links)
        self.bulk_link_pause_btn.setStyleSheet("background-color: #f5a623; font-weight: bold;")
        self.bulk_link_pause_btn.setEnabled(False)
        ctrl_row.addWidget(self.bulk_link_pause_btn)

        self.bulk_link_stop_btn = QPushButton("Stop")
        self.bulk_link_stop_btn.clicked.connect(self.stop_bulk_links)
        self.bulk_link_stop_btn.setStyleSheet("background-color: #c0392b; font-weight: bold;")
        self.bulk_link_stop_btn.setEnabled(False)
        ctrl_row.addWidget(self.bulk_link_stop_btn)

        bulk_layout.addLayout(ctrl_row)

        # Actions Row
        act_row = QHBoxLayout()
        self.bulk_link_download_btn = QPushButton("Download CSV")
        self.bulk_link_download_btn.clicked.connect(self.download_link_csv)
        self.bulk_link_download_btn.setStyleSheet("background-color: #27ae60; font-weight: bold;")
        self.bulk_link_download_btn.setEnabled(False)
        act_row.addWidget(self.bulk_link_download_btn)

        self.bulk_link_clear_btn = QPushButton("Clear")
        self.bulk_link_clear_btn.clicked.connect(self.clear_bulk_links)
        self.bulk_link_clear_btn.setStyleSheet("background-color: #555; font-weight: bold;")
        act_row.addWidget(self.bulk_link_clear_btn)

        bulk_layout.addLayout(act_row)

        self.bulk_link_progress = QProgressBar()
        self.bulk_link_progress.setVisible(False)
        bulk_layout.addWidget(self.bulk_link_progress)

        right_layout.addWidget(bulk_group)

        # Log
        log_group = QGroupBox("Bulk Console Output")
        log_layout = QVBoxLayout(log_group)
        self.bulk_link_log = QTextEdit()
        self.bulk_link_log.setReadOnly(True)
        self.bulk_link_log.setStyleSheet("background: #111; color: #a0e0a0; font-family: Consolas; font-size: 11px;")
        log_layout.addWidget(self.bulk_link_log)
        right_layout.addWidget(log_group, 1)

        main_layout.addWidget(right_widget, 1)

        return tab

    def _build_parallel_finder_tab(self):
        tab = QWidget()
        main_layout = QHBoxLayout(tab)
        main_layout.setSpacing(10)

        # ── Left Column: Single Parallel Finder ─────────────────
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # Target Hotel input section
        target_group = QGroupBox("Target Hotel & Location Details")
        target_grid = QGridLayout(target_group)

        target_grid.addWidget(QLabel("Hotel Name:"), 0, 0)
        self.parallel_name_input = QLineEdit()
        self.parallel_name_input.setPlaceholderText("e.g. Taj Mahal Palace")
        target_grid.addWidget(self.parallel_name_input, 0, 1)

        target_grid.addWidget(QLabel("City:"), 1, 0)
        self.parallel_city_input = QLineEdit()
        self.parallel_city_input.setPlaceholderText("e.g. Mumbai")
        target_grid.addWidget(self.parallel_city_input, 1, 1)

        # Lat/Long input + button
        target_grid.addWidget(QLabel("Lat, Long:"), 2, 0)
        lat_long_layout = QHBoxLayout()
        self.parallel_lat_long_input = QLineEdit()
        self.parallel_lat_long_input.setPlaceholderText("e.g. 18.9217, 72.8332")
        lat_long_layout.addWidget(self.parallel_lat_long_input)
        self.geocode_btn = QPushButton("Lookup Hotel")
        self.geocode_btn.clicked.connect(self.reverse_geocode)
        lat_long_layout.addWidget(self.geocode_btn)
        target_grid.addLayout(lat_long_layout, 2, 1)

        # Platform checkboxes row
        cb_row = QHBoxLayout()
        cb_row.addWidget(QLabel("Platforms to Search:"))
        
        self.cb_booking = QCheckBox("Booking.com")
        self.cb_booking.setChecked(True)
        cb_row.addWidget(self.cb_booking)

        self.cb_mmt = QCheckBox("MakeMyTrip")
        self.cb_mmt.setChecked(True)
        cb_row.addWidget(self.cb_mmt)

        self.cb_agoda = QCheckBox("Agoda")
        self.cb_agoda.setChecked(True)
        cb_row.addWidget(self.cb_agoda)

        self.cb_expedia = QCheckBox("Expedia")
        self.cb_expedia.setChecked(True)
        cb_row.addWidget(self.cb_expedia)

        target_grid.addLayout(cb_row, 3, 0, 1, 2)

        # Search buttons
        btn_row = QHBoxLayout()
        self.parallel_search_btn = QPushButton("Find Parallel Listings")
        self.parallel_search_btn.setStyleSheet("background-color: #e94560; font-weight: bold; padding: 10px;")
        self.parallel_search_btn.clicked.connect(self.start_parallel_search)
        btn_row.addWidget(self.parallel_search_btn)

        self.parallel_stop_btn = QPushButton("Stop")
        self.parallel_stop_btn.setStyleSheet("background-color: #c0392b; font-weight: bold; padding: 10px;")
        self.parallel_stop_btn.clicked.connect(self.stop_parallel_search)
        self.parallel_stop_btn.setEnabled(False)
        btn_row.addWidget(self.parallel_stop_btn)

        target_grid.addLayout(btn_row, 4, 0, 1, 2)

        left_layout.addWidget(target_group)

        # Results table
        results_group = QGroupBox("Parallel Listing Candidates")
        results_layout = QVBoxLayout(results_group)

        self.parallel_table = QTableWidget()
        self.parallel_table.setColumnCount(6)
        self.parallel_table.setHorizontalHeaderLabels([
            "Candidate Hotel Name", "Platform", "Address / Location", 
            "Name Similarity", "Photo Match", "Action"
        ])
        self.parallel_table.horizontalHeader().setStretchLastSection(True)
        self.parallel_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        results_layout.addWidget(self.parallel_table)

        left_layout.addWidget(results_group, 1)

        # Console status
        self.parallel_log = QTextEdit()
        self.parallel_log.setReadOnly(True)
        self.parallel_log.setMaximumHeight(100)
        self.parallel_log.setStyleSheet("background: #111; color: #a0e0a0; font-family: Consolas; font-size: 11px;")
        left_layout.addWidget(self.parallel_log)

        main_layout.addWidget(left_widget, 1)

        # ── Right Column: Bulk Parallel Finder ─────────────────
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        bulk_group = QGroupBox("Bulk Parallel Finder")
        bulk_layout = QVBoxLayout(bulk_group)
        bulk_layout.setSpacing(8)

        bulk_label = QLabel("Paste multiple hotels (one per line, format: Target Name, City) OR load a CSV:")
        bulk_label.setStyleSheet("color: #aaa; font-size: 11px;")
        bulk_layout.addWidget(bulk_label)

        self.bulk_parallel_input = QTextEdit()
        self.bulk_parallel_input.setPlaceholderText(
            "e.g.\nFabHotel Raj Villa, Indore\nFabHotel The Corporate, Mumbai"
        )
        self.bulk_parallel_input.setMaximumHeight(120)
        bulk_layout.addWidget(self.bulk_parallel_input)

        # Controls Row
        ctrl_row2 = QHBoxLayout()
        self.bulk_parallel_browse_btn = QPushButton("Browse CSV")
        self.bulk_parallel_browse_btn.clicked.connect(self.browse_parallel_csv)
        ctrl_row2.addWidget(self.bulk_parallel_browse_btn)

        self.bulk_parallel_sample_btn = QPushButton("Download Sample")
        self.bulk_parallel_sample_btn.clicked.connect(self.download_parallel_sample)
        self.bulk_parallel_sample_btn.setStyleSheet("background-color: #3498db; font-weight: bold;")
        ctrl_row2.addWidget(self.bulk_parallel_sample_btn)

        self.bulk_parallel_start_btn = QPushButton("Start")
        self.bulk_parallel_start_btn.clicked.connect(self.start_bulk_parallel)
        self.bulk_parallel_start_btn.setStyleSheet("background-color: #e94560; font-weight: bold;")
        ctrl_row2.addWidget(self.bulk_parallel_start_btn)

        self.bulk_parallel_pause_btn = QPushButton("Pause")
        self.bulk_parallel_pause_btn.clicked.connect(self.pause_bulk_parallel)
        self.bulk_parallel_pause_btn.setStyleSheet("background-color: #f5a623; font-weight: bold;")
        self.bulk_parallel_pause_btn.setEnabled(False)
        ctrl_row2.addWidget(self.bulk_parallel_pause_btn)

        self.bulk_parallel_stop_btn = QPushButton("Stop")
        self.bulk_parallel_stop_btn.clicked.connect(self.stop_bulk_parallel)
        self.bulk_parallel_stop_btn.setStyleSheet("background-color: #c0392b; font-weight: bold;")
        self.bulk_parallel_stop_btn.setEnabled(False)
        ctrl_row2.addWidget(self.bulk_parallel_stop_btn)

        self.bulk_parallel_settings_btn = QPushButton("⚙ Settings")
        self.bulk_parallel_settings_btn.clicked.connect(self.show_parallel_settings)
        self.bulk_parallel_settings_btn.setStyleSheet("background-color: #4a5568; font-weight: bold;")
        ctrl_row2.addWidget(self.bulk_parallel_settings_btn)

        bulk_layout.addLayout(ctrl_row2)

        # Actions Row
        act_row2 = QHBoxLayout()
        self.bulk_parallel_download_btn = QPushButton("Download CSV")
        self.bulk_parallel_download_btn.clicked.connect(self.download_parallel_csv)
        self.bulk_parallel_download_btn.setStyleSheet("background-color: #27ae60; font-weight: bold;")
        self.bulk_parallel_download_btn.setEnabled(False)
        act_row2.addWidget(self.bulk_parallel_download_btn)

        self.bulk_parallel_clear_btn = QPushButton("Clear")
        self.bulk_parallel_clear_btn.clicked.connect(self.clear_bulk_parallel)
        self.bulk_parallel_clear_btn.setStyleSheet("background-color: #555; font-weight: bold;")
        act_row2.addWidget(self.bulk_parallel_clear_btn)

        bulk_layout.addLayout(act_row2)

        self.bulk_parallel_progress = QProgressBar()
        self.bulk_parallel_progress.setVisible(False)
        bulk_layout.addWidget(self.bulk_parallel_progress)

        right_layout.addWidget(bulk_group)

        # Log
        log_group = QGroupBox("Bulk Console Output")
        log_layout = QVBoxLayout(log_group)
        self.bulk_parallel_log = QTextEdit()
        self.bulk_parallel_log.setReadOnly(True)
        self.bulk_parallel_log.setStyleSheet("background: #111; color: #a0e0a0; font-family: Consolas; font-size: 11px;")
        log_layout.addWidget(self.bulk_parallel_log)
        right_layout.addWidget(log_group, 1)

        main_layout.addWidget(right_widget, 1)

        return tab


    # ── Page Scanner Logic ─────────────────────────────────

    def _run_scan(self):
        url = self.scanner_url.text().strip()
        if not url:
            return

        if not url.startswith('http'):
            url = 'https://' + url
            self.scanner_url.setText(url)

        self.scan_btn.setEnabled(False)
        self.scanner_log.append(f"Scanning: {url}...")
        self._clear_scan_results()

        self.scan_worker = PageScanWorker(url)
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.start()

    def _on_scan_finished(self, result):
        self.scanner_log.append(f"  Title: {result.get('title', 'N/A')[:100]}")
        self.scanner_log.append(f"  Tables: {len(result.get('tables', []))}  Lists: {len(result.get('lists', []))}  Cards: {len(result.get('cards', []))}")
        if result.get('jsonld'):
            self.scanner_log.append(f"  JSON-LD items: {len(result['jsonld'])}")
        if result.get('error'):
            self.scanner_log.append(f"  WARNING: {result['error']}")

        # Rebuild UI with scan results
        self.scan_btn.setEnabled(True)

        # Clear placeholder and add results
        self._clear_scan_results()

        # Add scan results widgets
        if result.get('tables'):
            tables_group = QGroupBox(f"Detected Tables ({len(result['tables'])})")
            tbl_layout = QVBoxLayout(tables_group)
            for t in result['tables'][:5]:
                hdr_text = ', '.join(t['headers'][:5]) if t['headers'] else '(no headers)'
                cb = QCheckBox(f"Table #{t['id']}: [{t['row_count']} rows] Headers: {hdr_text}")
                cb.setProperty('type', 'table')
                cb.setProperty('id', t['id'])
                cb.stateChanged.connect(lambda state, c=cb: self._on_field_toggled(c))
                tbl_layout.addWidget(cb)
            self.scan_layout.addWidget(tables_group)

        if result.get('lists'):
            lists_group = QGroupBox(f"Detected Lists ({len(result['lists'])})")
            lst_layout = QVBoxLayout(lists_group)
            for lst in result['lists'][:5]:
                sample_text = lst['sample'][0][:60] if lst['sample'] else '(empty)'
                cb = QCheckBox(f"List #{lst['id']}: [{lst.get('tag', '')}] {lst['item_count']} items — e.g. \"{sample_text}\"")
                cb.setProperty('type', 'list')
                cb.setProperty('id', lst['id'])
                cb.setProperty('selector', f"{lst.get('tag', 'ul').lower()} > li")
                cb.stateChanged.connect(lambda state, c=cb: self._on_field_toggled(c))
                lst_layout.addWidget(cb)
            self.scan_layout.addWidget(lists_group)

        if result.get('cards'):
            cards_group = QGroupBox(f"Detected Cards ({len(result['cards'])})")
            card_layout = QVBoxLayout(cards_group)
            for card in result['cards'][:5]:
                cls = card.get('class', '')
                sample_text = ''
                if card['sample']:
                    s = card['sample'][0]
                    sample_text = list(s.values())[0][:60] if isinstance(s, dict) else str(s)[:60]
                label = f"Card: <{card['tag']}> [{card['count']} items]"
                if cls:
                    label += f" class=\"{cls}\""
                label += f" — e.g. \"{sample_text}\""
                cb = QCheckBox(label)
                cb.setProperty('type', 'card')
                cb.setProperty('selector', f"div.{cls}" if cls else card['tag'])
                cb.stateChanged.connect(lambda state, c=cb: self._on_field_toggled(c))
                card_layout.addWidget(cb)
            self.scan_layout.addWidget(cards_group)

        if result.get('jsonld'):
            jsonld_group = QGroupBox("Detected JSON-LD / Structured Data")
            jsonld_layout = QVBoxLayout(jsonld_group)
            for j in result['jsonld'][:3]:
                type_name = j.get('type', 'Unknown')
                cb = QCheckBox(f"JSON-LD: {type_name}")
                cb.setProperty('type', 'jsonld')
                cb.setProperty('data', j['data'])
                cb.stateChanged.connect(lambda state, c=cb: self._on_field_toggled(c))
                jsonld_layout.addWidget(cb)
            self.scan_layout.addWidget(jsonld_group)

        if result.get('ratings'):
            ratings_group = QGroupBox("Detected Ratings / Reviews")
            r_layout = QVBoxLayout(ratings_group)
            for r in result['ratings']:
                rating = r.get('rating', '?')
                count = r.get('count', '?')
                cb = QCheckBox(f"Rating: {rating}/10  |  Reviews: {count}")
                cb.setProperty('type', 'rating')
                cb.setChecked(True)  # Default: include ratings
                cb.stateChanged.connect(lambda state, c=cb: self._on_field_toggled(c))
                r_layout.addWidget(cb)
            self.scan_layout.addWidget(ratings_group)

        if result.get('links'):
            links_group = QGroupBox("Detected Links (first 10 shown)")
            link_layout = QVBoxLayout(links_group)
            for l in result['links'][:10]:
                text = l.get('text', '')[:40]
                href = l.get('href', '')[:60]
                cb = QCheckBox(f"Link: \"{text}\" -> {href}")
                cb.setProperty('type', 'link')
                cb.setProperty('href', l.get('href', ''))
                cb.stateChanged.connect(lambda state, c=cb: self._on_field_toggled(c))
                link_layout.addWidget(cb)
            self.scan_layout.addWidget(links_group)

        if not result.get('tables') and not result.get('lists') and not result.get('cards') and not result.get('jsonld') and not result.get('ratings'):
            no_data = QLabel("No structured data detected on this page. Try a different URL or add custom fields manually.")
            no_data.setStyleSheet("color: #888; font-style: italic; padding: 10px;")
            self.scan_layout.addWidget(no_data)

    def _clear_scan_results(self):
        """Remove all scan result widgets (keep placeholder)."""
        while self.scan_layout.count() > 0:
            item = self.scan_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_field_toggled(self, checkbox):
        if checkbox.isChecked():
            label = checkbox.text()[:80]
            item = QListWidgetItem(label)
            item.setProperty('config', {
                'name': f"field_{self.field_list.count() + 1}",
                'selector': checkbox.property('selector') or '',
                'type': checkbox.property('type') or 'text',
            })
            self.field_list.addItem(item)
            self.scanner_log.append(f"  + Added: {label}")
        else:
            # Remove from field list by matching text
            for i in range(self.field_list.count()):
                item = self.field_list.item(i)
                if checkbox.text()[:80] in (item.text() or ''):
                    self.field_list.takeItem(i)
                    break

    def _remove_field(self):
        for item in self.field_list.selectedItems():
            row = self.field_list.row(item)
            self.field_list.takeItem(row)

    def _add_custom_field(self):
        selector = self.field_input.text().strip()
        if not selector:
            return
        name = f"custom_{self.field_list.count() + 1}"
        item = QListWidgetItem(f"[Custom] {selector}")
        item.setProperty('config', {'name': name, 'selector': selector, 'type': 'custom'})
        self.field_list.addItem(item)
        self.field_input.clear()
        self.scanner_log.append(f"  + Added custom field: {selector}")

    def _browse_bulk_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select CSV File", "", "CSV Files (*.csv);;All Files (*)")
        if not file_path:
            return
        
        try:
            urls = []
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f)
                for row in reader:
                    for val in row:
                        val = val.strip()
                        # Simple regex to find any HTTP/HTTPS URLs or maps links
                        found_urls = re.findall(r'https?://[^\s,\"\']+', val)
                        for u in found_urls:
                            if u not in urls:
                                urls.append(u)
            
            if urls:
                self.scrape_urls_input.setText("\n".join(urls))
                self.scanner_log.append(f"Loaded {len(urls)} unique URLs from CSV.")
                # Automatically trigger scraping!
                self._start_mass_scrape()
            else:
                QMessageBox.warning(self, "No URLs Found", "Could not find any HTTP/HTTPS URLs in the selected CSV file.")
        except Exception as e:
            QMessageBox.critical(self, "Error Reading CSV", f"Could not read the CSV file: {str(e)}")

    def _start_mass_scrape(self):
        urls_text = self.scrape_urls_input.toPlainText().strip()
        if not urls_text:
            return

        urls = [u.strip() for u in urls_text.split('\n') if u.strip()]
        urls = [u if u.startswith('http') else 'https://' + u for u in urls]

        # Collect field configs
        field_config = []
        for i in range(self.field_list.count()):
            item = self.field_list.item(i)
            config = item.property('config')
            if config:
                field_config.append(config)

        is_any_maps = any("google.com/maps" in u.lower() or "goo.gl" in u.lower() or "maps.google" in u.lower() or "g.page" in u.lower() for u in urls)

        if not field_config and not is_any_maps:
            self.scanner_log.append("ERROR: No fields selected. Scan a page and check boxes for data to scrape (unless scraping Google Maps URLs).")
            return

        output_path = str(Path.home() / "Downloads" / f"godmode_scrape_{int(time.time())}.csv")
        self.scanner_log.append(f"Starting scrape of {len(urls)} URLs with {len(field_config)} fields...")
        self.scanner_log.append(f"Output: {output_path}")
        self.scrape_progress.setVisible(True)
        self.scrape_progress.setMaximum(len(urls))

        self.worker = GodModeWorker(urls, field_config, output_path)
        self.worker.progress.connect(lambda c, t, s: (
            self.scrape_progress.setValue(c),
            self.scanner_log.append(f"  [{c}/{t}] {s}")
        ))
        self.worker.finished.connect(lambda path, ok, total: (
            self.scrape_progress.setVisible(False),
            self.scanner_log.append(f"\nDONE! {ok}/{total} processed -> {path}"),
            self.scan_btn.setEnabled(True)
        ))
        self.worker.start()

    # ── Link Builder Logic ─────────────────────────────────

    def _build_links(self):
        name = self.link_name.text().strip()
        city = self.link_city.text().strip()
        hotel_id = self.link_id.text().strip()
        url = self.link_url.text().strip()

        input_data = {'name': name, 'city': city, 'hotel_id': hotel_id, 'url': url}

        links = build_all_platform_links(input_data)

        self.links_table.setRowCount(len(links))
        for i, (platform, link_url) in enumerate(links.items()):
            self.links_table.setItem(i, 0, QTableWidgetItem(platform))
            self.links_table.setItem(i, 1, QTableWidgetItem(link_url))

        self.links_table.resizeColumnsToContents()
        self.link_log.append(f"Built {len(links)} links from input data")

    def _copy_links(self):
        lines = []
        for i in range(self.links_table.rowCount()):
            platform = self.links_table.item(i, 0).text() if self.links_table.item(i, 0) else ''
            link = self.links_table.item(i, 1).text() if self.links_table.item(i, 1) else ''
            lines.append(f"{platform}: {link}")

        if lines:
            import subprocess
            text = '\n'.join(lines)
            try:
                subprocess.run(['clip'], input=text.encode('utf-16-le'), check=True)
                self.link_log.append("Copied all links to clipboard!")
            except:
                self.link_log.append("Links generated:")
                for l in lines:
                    self.link_log.append(f"  {l}")

    # ── Bulk Link Builder Logic ────────────────────────────

    def browse_link_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select CSV", "", "CSV Files (*.csv)")
        if path:
            self.load_link_csv(path)

    def load_link_csv(self, path):
        self.bulk_link_csv_path = path
        self.bulk_link_items = []
        self.bulk_link_original_rows = []
        self.bulk_link_original_headers = []
        try:
            with open(path, newline='', encoding='utf-8') as f:
                rows = list(csv.reader(f))

            if not rows:
                self.bulk_link_log.append("ERROR: CSV is empty.")
                return

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

            def find_col(*names):
                for n in names:
                    for i, h in enumerate(lower_headers):
                        if n in h:
                            return i
                return None

            name_idx = find_col('name', 'hotel')
            city_idx = find_col('city', 'location')
            link_idx = find_col('link', 'url')
            id_idx = find_col('fhid', 'fh id', 'fh', 'hotel code', 'hotel id', 'hotel_id', 'code', 'id')

            self.bulk_link_original_headers = headers

            for row in rows[header_idx + 1:]:
                if len(row) <= (name_idx or 0):
                    continue
                name = row[name_idx].strip() if name_idx is not None and name_idx < len(row) else ''
                city = row[city_idx].strip() if city_idx is not None and city_idx < len(row) else ''
                url = row[link_idx].strip() if link_idx is not None and link_idx < len(row) else ''
                hotel_id = row[id_idx].strip() if id_idx is not None and id_idx < len(row) else ''

                if not name and not url and not hotel_id:
                    continue

                self.bulk_link_original_rows.append(row)
                self.bulk_link_items.append({'name': name, 'city': city, 'url': url, 'hotel_id': hotel_id})

            self.bulk_link_input.setPlainText(
                f"Loaded: {Path(path).name} — {len(self.bulk_link_items)} hotels."
            )
            self.bulk_link_log.append(f"Loaded {len(self.bulk_link_items)} hotels from {Path(path).name}")
        except Exception as e:
            self.bulk_link_log.append(f"ERROR loading CSV: {e}")

    def start_bulk_links(self):
        bulk_text = self.bulk_link_input.toPlainText().strip()
        if bulk_text and not self.bulk_link_items:
            lines = [l.strip() for l in bulk_text.split('\n') if l.strip()]
            self.bulk_link_items = []
            for line in lines:
                parts = [p.strip() for p in line.split(',', 1)]
                name = parts[0]
                city = parts[1] if len(parts) > 1 else ''
                self.bulk_link_items.append({'name': name, 'city': city, 'url': '', 'hotel_id': ''})

        if not self.bulk_link_items:
            self.bulk_link_log.append("ERROR: No hotels loaded or pasted. Please paste names or load a CSV.")
            return

        self.bulk_link_start_btn.setEnabled(False)
        self.bulk_link_browse_btn.setEnabled(False)
        self.bulk_link_progress.setVisible(True)
        self.bulk_link_progress.setMaximum(len(self.bulk_link_items))
        self.bulk_link_progress.setValue(0)
        self.bulk_link_pause_btn.setEnabled(True)
        self.bulk_link_stop_btn.setEnabled(True)

        self.bulk_link_worker = BulkLinkBuilderWorker(
            self.bulk_link_items, self.bulk_link_original_rows, self.bulk_link_original_headers
        )
        self.bulk_link_worker.progress.connect(self.on_bulk_link_progress)
        self.bulk_link_worker.finished.connect(self.on_bulk_link_finished)
        self.bulk_link_worker.start()

    def pause_bulk_links(self):
        if self.bulk_link_worker and self.bulk_link_worker.isRunning():
            if self.bulk_link_worker._pause:
                self.bulk_link_worker.resume()
                self.bulk_link_pause_btn.setText("Pause")
                self.bulk_link_log.append("Resumed...")
            else:
                self.bulk_link_worker.pause()
                self.bulk_link_pause_btn.setText("Resume")
                self.bulk_link_log.append("Paused...")

    def stop_bulk_links(self):
        if self.bulk_link_worker and self.bulk_link_worker.isRunning():
            self.bulk_link_worker.stop()
            self.bulk_link_log.append("Stopping...")

    def download_link_csv(self):
        if self.bulk_link_output_path and os.path.exists(self.bulk_link_output_path):
            os.startfile(self.bulk_link_output_path)

    def clear_bulk_links(self):
        self.bulk_link_items = []
        self.bulk_link_original_rows = []
        self.bulk_link_original_headers = []
        self.bulk_link_csv_path = None
        self.bulk_link_output_path = None
        self.bulk_link_input.clear()
        self.bulk_link_log.clear()
        self.bulk_link_progress.setVisible(False)
        self.bulk_link_download_btn.setEnabled(False)

    def on_bulk_link_progress(self, current, total, status):
        self.bulk_link_progress.setValue(current)
        self.bulk_link_log.append(f"[{current}/{total}] {status}")

    def on_bulk_link_finished(self, results, output_path):
        self.bulk_link_start_btn.setEnabled(True)
        self.bulk_link_browse_btn.setEnabled(True)
        self.bulk_link_pause_btn.setEnabled(False)
        self.bulk_link_stop_btn.setEnabled(False)
        self.bulk_link_pause_btn.setText("Pause")
        self.bulk_link_output_path = output_path
        self.bulk_link_download_btn.setEnabled(True)
        self.bulk_link_log.append(f"\nDONE! Working links saved to: {output_path}")


    # ── Lat/Long Geocode Action ───────────────────────────
    def reverse_geocode(self):
        lat_long_text = self.parallel_lat_long_input.text().strip()
        if not lat_long_text:
            QMessageBox.warning(self, "Error", "Please enter Latitude and Longitude.")
            return

        parts = [p.strip() for p in lat_long_text.split(',')]
        if len(parts) != 2:
            QMessageBox.warning(self, "Error", "Format should be: Lat, Long (e.g. 18.9217, 72.8332)")
            return
            
        lat, lon = parts[0], parts[1]
        self.parallel_log.append(f"Looking up location for {lat}, {lon}...")
        
        import urllib.request
        
        try:
            url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
            req = urllib.request.Request(url, headers={'User-Agent': 'HotelDataTools/2.1'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                
            if 'address' in data:
                addr = data['address']
                hotel_name = addr.get('hotel') or addr.get('building') or addr.get('amenity') or addr.get('tourism') or addr.get('commercial')
                city = addr.get('city') or addr.get('town') or addr.get('village') or addr.get('county') or addr.get('state_district')
                
                if hotel_name:
                    self.parallel_name_input.setText(hotel_name)
                    if city:
                        self.parallel_city_input.setText(city)
                    self.parallel_log.append(f"✓ Found: {hotel_name} in {city}")
                else:
                    self.parallel_log.append("No specific hotel/building name found at this exact coordinate.")
                    self.parallel_log.append(f"Address: {data.get('display_name', '')}")
            else:
                self.parallel_log.append("No address data returned.")
                
        except Exception as e:
            self.parallel_log.append(f"Error looking up coordinates: {e}")
            QMessageBox.warning(self, "Error", f"Failed to lookup coordinates: {e}")

    # ── Parallel Listing Actions ────────────────────────────

    def start_parallel_search(self):
        name = self.parallel_name_input.text().strip()
        city = self.parallel_city_input.text().strip()

        if not name or not city:
            QMessageBox.warning(self, "Missing Fields", "Please enter both Hotel Name and City to search.")
            return

        platforms = []
        if self.cb_booking.isChecked():
            platforms.append('booking')
        if self.cb_mmt.isChecked():
            platforms.append('mmt')
        if self.cb_agoda.isChecked():
            platforms.append('agoda')
        if self.cb_expedia.isChecked():
            platforms.append('expedia')

        if not platforms:
            QMessageBox.warning(self, "No Platforms", "Please select at least one platform to search.")
            return

        self.parallel_candidates = []
        self.parallel_reference = None
        self.parallel_table.setRowCount(0)
        self.parallel_log.clear()

        self.parallel_search_btn.setEnabled(False)
        self.parallel_stop_btn.setEnabled(True)

        self.parallel_worker = ParallelListingWorker(name, city, platforms)
        self.parallel_worker.progress.connect(self.on_parallel_progress)
        self.parallel_worker.candidate_found.connect(self.on_candidate_found)
        self.parallel_worker.finished.connect(self.on_parallel_finished)
        self.parallel_worker.start()

    def stop_parallel_search(self):
        if self.parallel_worker and self.parallel_worker.isRunning():
            self.parallel_worker.stop()
            self.parallel_log.append("Stopping search worker...")

    def on_parallel_progress(self, status):
        self.parallel_log.append(status)

    def on_candidate_found(self, candidate):
        self.parallel_candidates.append(candidate)
        
        # The very first candidate is designated as the Target Reference Property
        if self.parallel_reference is None:
            self.parallel_reference = candidate
            self.parallel_log.append(f"Reference Hotel set to: {candidate['name']} ({candidate['platform']})")

        row = self.parallel_table.rowCount()
        self.parallel_table.insertRow(row)

        self.parallel_table.setItem(row, 0, QTableWidgetItem(candidate['name']))
        self.parallel_table.setItem(row, 1, QTableWidgetItem(candidate['platform']))
        self.parallel_table.setItem(row, 2, QTableWidgetItem(candidate['address']))
        self.parallel_table.setItem(row, 3, QTableWidgetItem(candidate['similarity']))
        
        # Photo match score
        pm_score = candidate.get('photo_match_score', 'Not Audited')
        self.parallel_table.setItem(row, 4, QTableWidgetItem(pm_score))
        
        # Action button
        btn = QPushButton("Compare Photos")
        btn.setStyleSheet("background-color: #0f3460; font-size: 11px; padding: 4px 8px;")
        btn.clicked.connect(lambda checked, r=row: self.compare_candidate_photos(r))
        self.parallel_table.setCellWidget(row, 5, btn)

    def on_parallel_finished(self, candidates):
        self.parallel_search_btn.setEnabled(True)
        self.parallel_stop_btn.setEnabled(False)
        self.parallel_log.append(f"\nCompleted! Found {len(candidates)} total listings across searched platforms.")

    def compare_candidate_photos(self, row):
        if not self.parallel_reference:
            QMessageBox.warning(self, "No Reference", "No target reference property available for comparison.")
            return

        if row >= len(self.parallel_candidates):
            return

        candidate = self.parallel_candidates[row]
        dialog = PhotoCompareDialog(self.parallel_reference, candidate, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            action = dialog.result_action
            item = self.parallel_table.item(row, 4)
            if item:
                if action == 'duplicate':
                    item.setText(f"❌ DUPLICATE ({candidate.get('photo_match_score', '')})")
                    item.setForeground(Qt.GlobalColor.red)
                    self.parallel_log.append(f"Row #{row+1} Marked as DUPLICATE listing.")
                elif action == 'safe':
                    item.setText(f"✅ SAFE ({candidate.get('photo_match_score', '')})")
                    item.setForeground(Qt.GlobalColor.green)
                    self.parallel_log.append(f"Row #{row+1} Marked as SAFE / Unique listing.")

    def copy_parallel_results_to_clipboard(self):
        import subprocess
        lines = []
        # Header
        lines.append("Candidate Hotel Name\tPlatform\tAddress / Location\tName Similarity\tPhoto Match\tDetail Link\tFirst Photo Link")
        
        for cand in self.parallel_candidates:
            name = cand.get('name', '')
            platform = cand.get('platform', '')
            address = cand.get('address', '')
            similarity = cand.get('similarity', '')
            photo_match = cand.get('photo_match_score', 'Not Audited')
            url = cand.get('url', '')
            photo_url = cand.get('photo_url', '')
            
            # Excel formula for hyperlinks
            url_formula = f'=HYPERLINK("{url}", "View Listing")' if url else ''
            photo_formula = f'=HYPERLINK("{photo_url}", "View Photo")' if photo_url else ''
            
            lines.append(f"{name}\t{platform}\t{address}\t{similarity}\t{photo_match}\t{url_formula}\t{photo_formula}")
            
        if lines:
            text = '\n'.join(lines)
            try:
                subprocess.run(['clip'], input=text.encode('utf-16-le'), check=True)
                self.parallel_log.append("Copied results table with embedded links to clipboard!")
            except Exception as e:
                self.parallel_log.append(f"Failed to copy to clipboard: {e}")


    # ── Samples & Utilities ──────────────────────────────────────

    def _save_sample_csv(self, headers: list, default_name: str, mock_rows: list):
        path, _ = QFileDialog.getSaveFileName(self, "Save Sample CSV", default_name, "CSV Files (*.csv)")
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(mock_rows)
            QMessageBox.information(self, "Success", f"Sample CSV saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save CSV:\n{e}")

    def download_link_sample(self):
        headers = ["Hotel Name", "City", "FHID", "URL"]
        rows = [
            ["FabHotel Raj Villa", "Indore", "1234", "http://booking.com/..."],
            ["FabHotel The Corporate", "Mumbai", "", ""]
        ]
        self._save_sample_csv(headers, "sample_link_builder.csv", rows)

    def download_parallel_sample(self):
        headers = ["Hotel Name", "City"]
        rows = [
            ["FabHotel Raj Villa", "Indore"],
            ["FabHotel The Corporate", "Mumbai"]
        ]
        self._save_sample_csv(headers, "sample_parallel_finder.csv", rows)

    # ── Bulk Parallel Finder Logic ───────────────────────────────

    def browse_parallel_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select CSV", "", "CSV Files (*.csv)")
        if path:
            try:
                with open(path, newline='', encoding='utf-8') as f:
                    csv_content = f.read()
                self.bulk_parallel_input.setPlainText(csv_content)
                self.bulk_parallel_log.append(f"Loaded CSV: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load CSV:\n{e}")

    def start_bulk_parallel(self):
        text = self.bulk_parallel_input.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "No Input", "Please paste some items or load a CSV.")
            return

        items = []
        import csv
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if not lines:
            return

        # Check if first line is a header
        first_line = lines[0]
        try:
            headers = next(csv.reader([first_line]))
            is_header = any(x in first_line.lower() for x in ('name', 'city', 'col', 'lat', 'lng', 'long', 'address', 'pincode'))
        except:
            headers = [p.strip() for p in first_line.split(',')]
            is_header = False

        data_rows_start = 1 if is_header else 0
        self.bulk_parallel_headers = headers if is_header else None

        # Sample data row to auto-detect columns
        sample_row = None
        for line in lines[data_rows_start:]:
            if '\t' in line:
                parts = [p.strip() for p in line.split('\t')]
            else:
                try:
                    parts = next(csv.reader([line]))
                except:
                    parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 2:
                sample_row = parts
                break

        # Defaults
        name_idx = 0
        city_idx = 1
        addr_idx = None
        lat_idx = None
        lng_idx = None
        id_idx = None

        if sample_row:
            col_scores = []
            for col_i, val in enumerate(sample_row):
                val_clean = val.strip()
                val_lower = val_clean.lower()
                header_name = headers[col_i].lower().strip() if is_header and col_i < len(headers) else ""
                
                scores = {'id': 0, 'name': 0, 'city': 0, 'address': 0, 'lat': 0, 'lng': 0, 'pincode': 0}
                
                # Check numeric values
                try:
                    num_val = float(val_clean)
                    if 8.0 <= num_val <= 38.0:
                        scores['lat'] += 10
                    elif 68.0 <= num_val <= 98.0:
                        scores['lng'] += 10
                    elif len(val_clean) == 6 and val_clean.isdigit():
                        scores['pincode'] += 10
                    else:
                        scores['id'] += 5
                except ValueError:
                    if len(val_clean) > 0:
                        if ',' in val_clean or len(val_clean) > 30 or any(x in val_lower for x in ('road', 'street', 'behind', 'near', 'opposite', 'nagar', 'colony', 'marg')):
                            scores['address'] += 10
                        elif any(x in val_lower for x in ('hotel', 'inn', 'residency', 'palace', 'villa', 'suites', 'comfort')):
                            scores['name'] += 10
                        elif len(val_clean) < 20:
                            scores['city'] += 5

                # Header check
                if header_name:
                    if 'id' in header_name or 'code' in header_name:
                        scores['id'] += 15
                    if 'name' in header_name:
                        scores['name'] += 15
                    if 'city' in header_name or 'location' in header_name:
                        scores['city'] += 15
                    if 'address' in header_name or 'addr' in header_name:
                        scores['address'] += 15
                    if 'latitude' in header_name or 'lat' in header_name:
                        scores['lat'] += 15
                    if 'longitude' in header_name or 'lng' in header_name or 'long' in header_name or 'lon' in header_name:
                        scores['lng'] += 15
                    if 'pincode' in header_name or 'pin' in header_name:
                        scores['pincode'] += 15
                
                col_scores.append(scores)

            if col_scores:
                # Find indices using highest scores
                name_idx = max(range(len(col_scores)), key=lambda idx: col_scores[idx]['name'])
                city_idx = max(range(len(col_scores)), key=lambda idx: col_scores[idx]['city'] if idx != name_idx else -1)
                
                addr_score_idx = max(range(len(col_scores)), key=lambda idx: col_scores[idx]['address'] if idx not in (name_idx, city_idx) else -1)
                if col_scores[addr_score_idx]['address'] >= 5:
                    addr_idx = addr_score_idx
                    
                lat_score_idx = max(range(len(col_scores)), key=lambda idx: col_scores[idx]['lat'])
                if col_scores[lat_score_idx]['lat'] >= 5:
                    lat_idx = lat_score_idx
                    
                lng_score_idx = max(range(len(col_scores)), key=lambda idx: col_scores[idx]['lng'])
                if col_scores[lng_score_idx]['lng'] >= 5:
                    lng_idx = lng_score_idx
                    
                id_score_idx = max(range(len(col_scores)), key=lambda idx: col_scores[idx]['id'] if idx not in (name_idx, city_idx, addr_idx) else -1)
                if col_scores[id_score_idx]['id'] >= 5:
                    id_idx = id_score_idx

        for line in lines[data_rows_start:]:
            if '\t' in line:
                parts = [p.strip() for p in line.split('\t')]
            else:
                try:
                    parts = next(csv.reader([line]))
                except:
                    parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 2:
                item_name = parts[name_idx] if name_idx < len(parts) else ""
                item_city = parts[city_idx] if city_idx < len(parts) else ""
                item_addr = parts[addr_idx] if (addr_idx is not None and addr_idx < len(parts)) else ""
                item_lat = parts[lat_idx] if (lat_idx is not None and lat_idx < len(parts)) else ""
                item_lng = parts[lng_idx] if (lng_idx is not None and lng_idx < len(parts)) else ""
                item_id = parts[id_idx] if (id_idx is not None and id_idx < len(parts)) else ""

                items.append({
                    'name': item_name,
                    'city': item_city,
                    'address': item_addr,
                    'latitude': item_lat,
                    'longitude': item_lng,
                    'hotel_id': item_id,
                    'row_data': parts
                })

        if not items:
            QMessageBox.warning(self, "Invalid Input", "Could not parse any valid items. Format: Name, City")
            return

        platforms = []
        if self.cb_booking.isChecked(): platforms.append('booking')
        if self.cb_mmt.isChecked(): platforms.append('mmt')
        if self.cb_agoda.isChecked(): platforms.append('agoda')
        if self.cb_expedia.isChecked(): platforms.append('expedia')

        if not platforms:
            QMessageBox.warning(self, "No Platforms", "Please select at least one platform to search.")
            return

        if hasattr(self, 'bulk_parallel_worker') and self.bulk_parallel_worker.isRunning():
            if self.bulk_parallel_worker._pause:
                self.bulk_parallel_worker.resume()
                self.bulk_parallel_pause_btn.setText("Pause")
                self.bulk_parallel_log.append("Resumed worker...")
                return

        self.bulk_parallel_start_btn.setEnabled(False)
        self.bulk_parallel_pause_btn.setEnabled(True)
        self.bulk_parallel_stop_btn.setEnabled(True)
        self.bulk_parallel_download_btn.setEnabled(False)

        self.bulk_parallel_log.clear()
        self.bulk_parallel_log.append(f"Starting bulk parallel finder for {len(items)} targets...")

        self.bulk_parallel_progress.setVisible(True)
        self.bulk_parallel_progress.setMaximum(len(items))
        self.bulk_parallel_progress.setValue(0)

        self.bulk_parallel_worker = BulkParallelFinderWorker(items, platforms, headers=getattr(self, 'bulk_parallel_headers', None))
        self.bulk_parallel_worker.progress.connect(self.on_bulk_parallel_progress)
        self.bulk_parallel_worker.finished.connect(self.on_bulk_parallel_finished)
        self.bulk_parallel_worker.start()
    def pause_bulk_parallel(self):
        if hasattr(self, 'bulk_parallel_worker') and self.bulk_parallel_worker.isRunning():
            if not self.bulk_parallel_worker._pause:
                self.bulk_parallel_worker.pause()
                self.bulk_parallel_pause_btn.setText("Resume")
                self.bulk_parallel_log.append("Pausing worker (will pause after current item)...")

    def stop_bulk_parallel(self):
        if hasattr(self, 'bulk_parallel_worker') and self.bulk_parallel_worker.isRunning():
            self.bulk_parallel_worker.stop()
            self.bulk_parallel_log.append("Stopping worker (will stop after current item)...")

    def clear_bulk_parallel(self):
        self.bulk_parallel_input.clear()
        self.bulk_parallel_log.clear()
        self.bulk_parallel_progress.setVisible(False)
        self.bulk_parallel_download_btn.setEnabled(False)

    def on_bulk_parallel_progress(self, current, total, status):
        self.bulk_parallel_progress.setValue(current)
        self.bulk_parallel_log.append(status)

    def on_bulk_parallel_finished(self, results, output_path):
        self.bulk_parallel_start_btn.setEnabled(True)
        self.bulk_parallel_pause_btn.setEnabled(False)
        self.bulk_parallel_stop_btn.setEnabled(False)
        self.bulk_parallel_pause_btn.setText("Pause")
        self.bulk_parallel_output_path = output_path
        self.bulk_parallel_download_btn.setEnabled(True)
        self.bulk_parallel_log.append(f"\nDONE! Results saved to: {output_path}")

    def download_parallel_csv(self):
        if hasattr(self, 'bulk_parallel_output_path') and self.bulk_parallel_output_path:
            import os, shutil, time
            default_name = f"parallel_results_{int(time.time())}.csv"
            save_path, _ = QFileDialog.getSaveFileName(self, "Save Results", default_name, "CSV Files (*.csv)")
            if save_path:
                try:
                    shutil.copy(self.bulk_parallel_output_path, save_path)
                    QMessageBox.information(self, "Success", f"File saved to:\n{save_path}")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")

    def show_parallel_settings(self):
        from settings_dialog import SettingsDialog
        dialog = SettingsDialog(self, on_resume_callback=self.resume_parallel_finder)
        dialog.exec()

    def resume_parallel_finder(self, run_data):
        input_file = run_data.get("input_file")
        if input_file and os.path.exists(input_file):
            try:
                with open(input_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.bulk_parallel_input.setPlainText(content)
                self.bulk_parallel_log.append(f"Resuming run using input file: {input_file}")
                self.start_bulk_parallel()
            except Exception as e:
                self.bulk_parallel_log.append(f"Failed to resume parallel finder: {e}")

    # ── Samples & Utilities ──────────────────────────────────────

    def _save_sample_csv(self, headers: list, default_name: str, mock_rows: list):
        path, _ = QFileDialog.getSaveFileName(self, "Save Sample CSV", default_name, "CSV Files (*.csv)")
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(mock_rows)
            QMessageBox.information(self, "Success", f"Sample CSV saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save CSV:\n{e}")

    def download_link_sample(self):
        headers = ["Hotel Name", "City", "FHID", "URL"]
        rows = [
            ["FabHotel Raj Villa", "Indore", "1234", "http://booking.com/..."],
            ["FabHotel The Corporate", "Mumbai", "", ""]
        ]
        self._save_sample_csv(headers, "sample_link_builder.csv", rows)

    def download_parallel_sample(self):
        headers = ["Hotel Name", "City"]
        rows = [
            ["FabHotel Raj Villa", "Indore"],
            ["FabHotel The Corporate", "Mumbai"]
        ]
        self._save_sample_csv(headers, "sample_parallel_finder.csv", rows)

    