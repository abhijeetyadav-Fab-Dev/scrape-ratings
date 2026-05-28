"""
God Mode Scraper
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Three tools in one:
  1. Page Scanner   – Visit any URL, auto-detect all scrapeable data
  2. Element Picker – Let user select which fields to extract
  3. Link Builder   – Build front-end URLs from partial hotel data
"""

import re, csv, json, time, io
from pathlib import Path
from collections import Counter
from urllib.parse import urljoin, urlparse

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


from playwright.sync_api import sync_playwright

from ratings_platforms import (
    AVAILABLE_PLATFORMS, detect_input_type, _get_headless_browser,
    extract_rating_review_count,
)


# ── Page Scanner Engine ───────────────────────────────────

class PageScanner:
    """Core scanning engine — visits a page and detects all scrapeable data."""

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
        return result


# ── Scrape Worker for God Mode ────────────────────────────

class GodModeWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str, int, int)

    def __init__(self, urls, field_config, output_path):
        super().__init__()
        self.urls = urls
        self.field_config = field_config  # list of {'name': ..., 'selector': ..., 'attribute': ...}
        self.output_path = output_path
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        total = len(self.urls)
        results = []

        browser = _get_headless_browser()
        page = browser.new_page()
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })

        for i, url in enumerate(self.urls):
            if self._stop:
                break

            self.progress.emit(i + 1, total, f"Processing {url[:60]}...")
            row = {'url': url}

            try:
                page.goto(url, timeout=20000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                for field in self.field_config:
                    name = field['name']
                    selector = field['selector']
                    attr = field.get('attribute', 'text')
                    multiple = field.get('multiple', False)

                    try:
                        if multiple:
                            elements = page.query_selector_all(selector)
                            values = []
                            for el in elements[:50]:
                                if attr == 'text':
                                    v = el.inner_text().strip()
                                elif attr == 'href':
                                    v = el.get_attribute('href') or ''
                                else:
                                    v = el.get_attribute(attr) or ''
                                if v:
                                    values.append(v)
                            row[name] = ' | '.join(values[:10])
                        else:
                            el = page.query_selector(selector)
                            if el:
                                if attr == 'text':
                                    row[name] = el.inner_text().strip()
                                elif attr == 'href':
                                    row[name] = el.get_attribute('href') or ''
                                else:
                                    row[name] = el.get_attribute(attr) or ''
                            else:
                                row[name] = ''
                    except Exception:
                        row[name] = ''

            except Exception as e:
                for field in self.field_config:
                    row[field['name']] = f'[ERROR: {str(e)[:50]}]'

            results.append(row)

        page.close()

        # Write CSV
        if results:
            fieldnames = ['url'] + [f['name'] for f in self.field_config]
            with open(self.output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(results)

        success = sum(1 for r in results if any(v for k, v in r.items() if k != 'url'))
        self.finished.emit(self.output_path, success, total)


# ── Bulk Parallel Listing Finder Worker ───────────────────

class BulkParallelFinderWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list, str) # results list, output file path

    def __init__(self, items, platforms):
        super().__init__()
        self.items = items # list of {'name': name, 'city': city}
        self.platforms = platforms
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

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
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
                cleaned_target = clean_hotel_name(target_name)
                
                self.progress.emit(idx + 1, total, f"Searching for: {target_name} ({city})")

                query = f"{cleaned_target} {city}".strip()
                query_encoded = urllib.parse.quote_plus(query)

                for platform in self.platforms:
                    if self._stop:
                        break

                    try:
                        if platform == 'booking':
                            search_url = f"https://www.booking.com/searchresults.html?ss={query_encoded}"
                            page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
                            page.wait_for_timeout(1500)
                            cards = page.query_selector_all('[data-testid="property-card"], [data-testid="sr-property-card-common"]')[:3]
                            
                            for card in cards:
                                name_el = card.query_selector('[data-testid="title"], h3, .sr-hotel__name')
                                name = name_el.inner_text().strip() if name_el else ''
                                if not name:
                                    continue
                                
                                loc_el = card.query_selector('[data-testid="address"], [data-testid="location"]')
                                location = loc_el.inner_text().strip() if loc_el else ''

                                cleaned_cand = clean_hotel_name(name)
                                ratio = difflib.SequenceMatcher(None, cleaned_target.lower(), cleaned_cand.lower()).ratio()
                                similarity = int(ratio * 100)
                                is_fab = 'fab' in name.lower()

                                self.results.append({
                                    'target_name': target_name,
                                    'target_city': city,
                                    'candidate_name': name,
                                    'platform': 'Booking.com',
                                    'address': location or city,
                                    'similarity': f"{similarity}%",
                                    'verdict': 'FabHotel Chain' if is_fab else 'Potential Duplicate (Non-Fab)'
                                })

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

                                cleaned_cand = clean_hotel_name(name)
                                ratio = difflib.SequenceMatcher(None, cleaned_target.lower(), cleaned_cand.lower()).ratio()
                                similarity = int(ratio * 100)
                                is_fab = 'fab' in name.lower()

                                self.results.append({
                                    'target_name': target_name,
                                    'target_city': city,
                                    'candidate_name': name,
                                    'platform': 'Agoda',
                                    'address': location or city,
                                    'similarity': f"{similarity}%",
                                    'verdict': 'FabHotel Chain' if is_fab else 'Potential Duplicate (Non-Fab)'
                                })

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

                                cleaned_cand = clean_hotel_name(name)
                                ratio = difflib.SequenceMatcher(None, cleaned_target.lower(), cleaned_cand.lower()).ratio()
                                similarity = int(ratio * 100)
                                is_fab = 'fab' in name.lower()

                                self.results.append({
                                    'target_name': target_name,
                                    'target_city': city,
                                    'candidate_name': name,
                                    'platform': 'Expedia',
                                    'address': location or city,
                                    'similarity': f"{similarity}%",
                                    'verdict': 'FabHotel Chain' if is_fab else 'Potential Duplicate (Non-Fab)'
                                })

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

                                cleaned_cand = clean_hotel_name(name)
                                ratio = difflib.SequenceMatcher(None, cleaned_target.lower(), cleaned_cand.lower()).ratio()
                                similarity = int(ratio * 100)
                                is_fab = 'fab' in name.lower()

                                self.results.append({
                                    'target_name': target_name,
                                    'target_city': city,
                                    'candidate_name': name,
                                    'platform': 'MakeMyTrip',
                                    'address': location or city,
                                    'similarity': f"{similarity}%",
                                    'verdict': 'FabHotel Chain' if is_fab else 'Potential Duplicate (Non-Fab)'
                                })

                    except Exception as e:
                        pass

            try:
                browser.close()
            except Exception:
                pass

        # Write multi-row CSV
        output_path = str(Path.home() / "Downloads" / f"parallel_listings_{int(time.time())}.csv")
        try:
            fieldnames = ['Target Hotel Name', 'Target City', 'Candidate Name', 'Platform', 'Candidate Address', 'Name Similarity', 'Verdict']
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for res in self.results:
                    writer.writerow(res)
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
        query = f"{cleaned_target} {self.city}".strip()
        query_encoded = urllib.parse.quote_plus(query)

        self.progress.emit(f"Launching search for '{query}'...")

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                context.route("**/*", lambda route: route.abort() if route.request.resource_type in ("font", "media") else route.continue_())
                page = context.new_page()
            except Exception as e:
                self.progress.emit(f"Failed to launch browser: {e}")
                self.finished.emit([])
                return

            # 1. Fetch Target / Reference Listing Photos first
            target_photos = []
            target_hashes = []
            target_url = ""
            
            self.progress.emit("Obtaining reference details for target hotel...")
            try:
                # Search booking.com to find the target details
                ss_url = f"https://www.booking.com/searchresults.html?ss={query_encoded}"
                page.goto(ss_url, timeout=20000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                first_card = page.query_selector('[data-testid="property-card"], [data-testid="sr-property-card-common"]')
                if first_card:
                    link_el = first_card.query_selector('a[data-testid="title-link"], a[href*="/hotel/"]')
                    target_url = link_el.get_attribute('href') if link_el else ''
                    if target_url and target_url.startswith('/'):
                        target_url = "https://www.booking.com" + target_url
                    target_url = target_url.split('?')[0] if target_url else ""
            except Exception as e:
                self.progress.emit(f"Could not automatically fetch target detail page: {e}")

            if target_url:
                try:
                    page.goto(target_url, timeout=20000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                    img_elements = page.query_selector_all('.gallery-image-container img, .gallery_grid img, img[src*="max1280x900"], a.gallery-entry img')
                    for img in img_elements:
                        src = img.get_attribute('src') or img.get_attribute('data-lazy') or img.get_attribute('data-src')
                        if src and src not in target_photos:
                            target_photos.append(src)
                            if len(target_photos) >= 10:
                                break
                    self.progress.emit(f"Loaded {len(target_photos)} reference photos from details page.")
                except Exception as e:
                    self.progress.emit(f"Error reading target details page gallery: {e}")

            # Calculate hashes for reference photos
            for url in target_photos:
                ib = self.download_image_bytes(url)
                if ib:
                    h = self.calculate_dhash(ib)
                    if h:
                        target_hashes.append(h)

            # 2. Iterate platforms to scan for candidates
            for platform in self.platforms:
                if self._stop:
                    break

                self.progress.emit(f"Searching platform: {platform.upper()}...")
                try:
                    cards = []
                    if platform == 'booking':
                        search_url = f"https://www.booking.com/searchresults.html?ss={query_encoded}"
                        page.goto(search_url, timeout=25000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)
                        cards = page.query_selector_all('[data-testid="property-card"], [data-testid="sr-property-card-common"]')[:5]
                    elif platform == 'agoda':
                        search_url = f"https://www.agoda.com/search?text={query_encoded}"
                        page.goto(search_url, timeout=25000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2500)
                        cards = page.query_selector_all('li[data-selenium="property-item"], [data-selenium="hotel-item"], .PropertyCard')[:5]
                    elif platform == 'expedia':
                        search_url = f"https://www.expedia.com/Hotel-Search?destination={query_encoded}"
                        page.goto(search_url, timeout=25000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2500)
                        cards = page.query_selector_all('[data-stid="property-card"], .uitk-card')[:5]
                    elif platform == 'mmt':
                        search_url = f"https://www.makemytrip.com/hotels/hotel-listing/?searchText={query_encoded}"
                        page.goto(search_url, timeout=25000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2500)
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

                            # Skip self-match check
                            if similarity >= 99 and (url == target_url or (platform == 'booking' and target_url)):
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
                                    'booking': '.gallery-image-container img, .gallery_grid img, img[src*="max1280x900"], a.gallery-entry img',
                                    'agoda': '.PropertyGallery img, img[src*="images/hotel"], img[src*="agoda.com"]',
                                    'expedia': '[data-stid="gallery-image"] img, img[src*="expedia.com"], .media-gallery img',
                                    'mmt': 'img[id*="detpg_"], img[src*="hotel"], .gallery img'
                                }
                                sel = img_selectors.get(platform, 'img')
                                for img in cand_page.query_selector_all(sel):
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
                except Exception as pe:
                    self.progress.emit(f"Error scraping {platform.upper()}: {pe}")

            try:
                browser.close()
            except Exception:
                pass

        self.progress.emit("Search finished.")
        self.finished.emit(self.candidates)


# ── Clean Hotel Name Helper (FabHotels Duplicate Checking) ──

def clean_hotel_name(name: str) -> str:
    """Strip common brand prefixes and Devanagari/Hindi characters and window texts."""
    if not name:
        return ""
    # Strip Hindi phrases and Devanagari characters
    name = re.sub(r'नई\s+विंडो\s+में\s+खुलता\s+है', '', name)
    name = re.sub(r'[\u0900-\u097F]+', '', name)
    # Strip common window/open texts
    name = re.sub(r'(?i)\b(?:opens\s+in\s+(?:a\s+)?new\s+window|opens\s+new\s+window)\b', '', name)
    # Strip common brand prefixes/suffixes
    name = re.sub(r'\b(?:fabhotel|fabhotels|fabexpress|fab)\b', '', name, flags=re.IGNORECASE)
    # Clean whitespace
    return re.sub(r'\s+', ' ', name).strip()



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

        target_grid.addLayout(cb_row, 2, 0, 1, 2)

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

        target_grid.addLayout(btn_row, 3, 0, 1, 2)

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

        # Copy Results for Excel button
        self.parallel_copy_btn = QPushButton("Copy Results for Excel / Google Sheets")
        self.parallel_copy_btn.setStyleSheet("background-color: #27ae60; font-weight: bold; padding: 10px; margin-top: 5px;")
        self.parallel_copy_btn.clicked.connect(self.copy_parallel_results_to_clipboard)
        results_layout.addWidget(self.parallel_copy_btn)

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

        def do_scan():
            scanner = PageScanner()
            result = scanner.scan(url)

            self.scanner_log.append(f"  Title: {result.get('title', 'N/A')[:100]}")
            self.scanner_log.append(f"  Tables: {len(result['tables'])}  Lists: {len(result['lists'])}  Cards: {len(result['cards'])}")
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

        import threading
        threading.Thread(target=do_scan, daemon=True).start()

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

        if not field_config:
            self.scanner_log.append("ERROR: No fields selected. Scan a page and check boxes for data to scrape.")
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


    # ── Parallel Listing Finder Logic ──────────────────────

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
        for line in text.split('\n'):
            line = line.strip()
            if not line or line.lower().startswith('hotel name'):
                continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 2:
                items.append({'name': parts[0], 'city': parts[1]})

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

        self.bulk_parallel_worker = BulkParallelFinderWorker(items, platforms)
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
