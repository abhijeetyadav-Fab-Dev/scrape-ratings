"""
Universal Hotel Data Scraper
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A flexible, extensible scraping framework for pulling data from
multiple hotel extranet sources (Booking.com, MMT, etc.).

Architecture:
  Source Plugin (defines available fields & login/extract logic)
  → ScrapeJob (config: which source + which fields)
  → ScrapeJobRunner (executes the job via Playwright)
  → CSV output

How to add a new source:
  1. Subclass ExtranetSource
  2. Define available_fields, source_name, login_url
  3. Implement login(), navigate_to_section(), extract_data()
  4. Register it in EXTRANET_SOURCES
"""

import os, csv, json, time, re, threading, subprocess, pickle, sqlite3
from pathlib import Path
from abc import ABC, abstractmethod
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QTextEdit, QProgressBar, QFileDialog,
    QComboBox, QScrollArea, QFrame, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from playwright.sync_api import sync_playwright

# ────────────────────────────────────────────────────────────
#  Config & constants
# ────────────────────────────────────────────────────────────

COOKIES_DIR = Path.home() / ".scrape-ratings"
COOKIES_DIR.mkdir(exist_ok=True)

BOOKING_EXTRANET_COOKIES = COOKIES_DIR / "booking_extranet_cookies.pkl"
MMT_EXTRANET_COOKIES = COOKIES_DIR / "mmt_extranet_cookies.pkl"
GOIBIBO_EXTRANET_COOKIES = COOKIES_DIR / "goibibo_extranet_cookies.pkl"
AGODA_EXTRANET_COOKIES = COOKIES_DIR / "agoda_extranet_cookies.pkl"
EXPEDIA_EXTRANET_COOKIES = COOKIES_DIR / "expedia_extranet_cookies.pkl"

# Shared Chrome debug port (different from ratings scraper's 9222)
EXTRANET_DEBUG_PORT = 9223

# ────────────────────────────────────────────────────────────
#  ExtranetSource — abstract base for all data-source plugins
# ────────────────────────────────────────────────────────────

class ExtranetSource(ABC):
    """Override these to define a new extranet data source."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable name, e.g. 'Booking.com Extranet'"""
        ...

    @property
    @abstractmethod
    def login_url(self) -> str:
        """URL where the user logs in."""
        ...

    @property
    @abstractmethod
    def available_fields(self) -> list[dict]:
        """List of field groups & fields the user can select.
        Each entry: { "group": "Reservations", "fields": [
            {"key": "guest_name",    "label": "Guest Name"},
            {"key": "check_in",      "label": "Check-in Date"},
            {"key": "check_out",     "label": "Check-out Date"},
        ]}
        """
        ...

    @property
    def cookies_path(self) -> Path:
        """Path where session cookies are saved/loaded."""
        raise NotImplementedError

    @property
    def multi_tab(self) -> bool:
        """If True, the worker opens a new tab for each section.
        Useful for SPAs (like MMT) where navigating between sections
        on a single page causes session or rendering issues.
        """
        return False

    @abstractmethod
    def login(self, page) -> None:
        """Navigate to login_url and guide the user through login.
        This runs in headed mode — user enters credentials manually.
        After login, the cookies are saved automatically.
        """
        ...

    @abstractmethod
    def navigate_to_section(self, page, section_key: str) -> None:
        """Navigate to the page section that contains the requested data.
        section_key comes from the field's 'key' (first part before underscore).
        """
        ...

    @abstractmethod
    def extract_data(self, page, selected_fields: list[dict]) -> list[dict]:
        """Extract rows of data from the current page.
        selected_fields is the list of field dicts the user chose.
        Returns a list of dicts (one per row) with keys matching field['key'].
        """
        ...

    def _append_scraped_property_data(self, hotel_id: str, hotel_name: str, rows: list[dict], status: str = "Completed"):
        """Shared helper to write a property's scraped rows to CSV and log to SQLite in real-time."""
        session_id = getattr(self, "session_id", None)
        out_path = getattr(self, "output_path", None)
        
        # 1. Update SQLite
        if session_id:
            try:
                ScrapeHistoryManager.add_scraped_property(session_id, hotel_id, hotel_name, status, len(rows))
            except Exception:
                pass
                
        # 2. Append to CSV in real-time
        if out_path and rows:
            try:
                file_exists = os.path.exists(out_path) and os.path.getsize(out_path) > 0
                
                # Construct ordered keys from job or dynamic discovery
                field_keys = []
                if getattr(self, "job", None):
                    field_keys = [f["key"] for f in self.job.selected_fields]
                else:
                    all_keys = set()
                    for r in rows:
                        all_keys.update(r.keys())
                    for k in ["hotel_id", "hotel_name", "_source", "_error"]:
                        all_keys.discard(k)
                    field_keys = sorted(list(all_keys))
                o_keys = field_keys + ["hotel_id", "hotel_name", "_source", "_error"]
                
                with open(out_path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=o_keys, extrasaction="ignore")
                    if not file_exists:
                        writer.writeheader()
                    writer.writerows(rows)
            except Exception:
                pass

    # ── Shared helper methods for section-aware extraction ──

    def _try_selectors(self, page, selectors: list[str]) -> str:
        """Try each CSS selector and return first non-empty inner_text."""
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    text = el.inner_text().strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

    def _extract_value_by_label(self, page, label_text: str) -> str:
        """Find a form field by its associated label text.
        Uses a single page.evaluate call to handle all patterns:
        for= attribute, next sibling, parent's next sibling.
        """
        try:
            return page.evaluate(
                """(text) => {
                    const labels = document.querySelectorAll('label');
                    for (const label of labels) {
                        if (!label.textContent.includes(text)) continue;
                        const forAttr = label.getAttribute('for');
                        if (forAttr) {
                            const el = document.getElementById(forAttr);
                            if (el) {
                                const val = el.value || el.textContent || '';
                                if (val.trim()) return val.trim();
                            }
                        }
                        const sibling = label.nextElementSibling;
                        if (sibling) {
                            const txt = sibling.textContent || '';
                            if (txt.trim()) return txt.trim();
                        }
                        const parent = label.parentElement;
                        if (parent && parent.nextElementSibling) {
                            const txt = parent.nextElementSibling.textContent || '';
                            if (txt.trim()) return txt.trim();
                        }
                    }
                    return '';
                }""",
                label_text
            )
        except Exception:
            pass
        return ""

    def _extract_table_fields(self, page, field_keys: list[str],
                               known_columns: dict[str, str] = None) -> list[dict]:
        """Extract fields from data tables with column header matching.
        known_columns maps lowercase column header patterns → field keys.
        """
        # First, check if the page is an error page
        is_error, error_context = self._is_error_page(page)
        if is_error:
            return [{"_error": error_context, "_source": "error_detected"}]

        rows = []
        try:
            tables = page.query_selector_all("table")
            for table in tables:
                header_els = table.query_selector_all("th")
                headers = [h.inner_text().strip().lower() for h in header_els]
                if not headers:
                    continue
                col_map = {}
                if known_columns:
                    for i, hdr in enumerate(headers):
                        for pattern, fk in known_columns.items():
                            if pattern in hdr and fk in field_keys:
                                col_map[i] = fk
                body_rows = table.query_selector_all("tbody tr, tr:not(:has(th))")
                for tr in body_rows:
                    cells = tr.query_selector_all("td")
                    row = {}
                    if col_map:
                        for i, cell in enumerate(cells):
                            if i in col_map:
                                row[col_map[i]] = cell.inner_text().strip()
                    else:
                        for i, cell in enumerate(cells):
                            if i < len(headers):
                                key = f"raw_{headers[i].replace(' ', '_')}"
                                row[key] = cell.inner_text().strip()
                    if row:
                        rows.append(row)
        except Exception:
            pass
        return rows

    def _extract_card_fields(self, page, field_keys: list[str],
                              card_selector: str, field_mappings: dict[str, str]) -> list[dict]:
        """Parse repeated card elements with child selectors per field.
        field_mappings: field_key → CSS selector relative to each card.
        """
        rows = []
        try:
            cards = page.query_selector_all(card_selector)
            for card in cards:
                row = {}
                for fk, sel in field_mappings.items():
                    if fk in field_keys:
                        try:
                            el = card.query_selector(sel)
                            if el:
                                row[fk] = el.inner_text().strip()
                        except Exception:
                            pass
                if row:
                    rows.append(row)
        except Exception:
            pass
        return rows

    def _extract_metric_cards(self, page, field_keys: list[str],
                               label_map: dict[str, str],
                               card_selector: str = "") -> list[dict]:
        """Parse metric/KPI cards to extract value-label pairs.
        label_map: keyword in card text → field key.
        """
        rows = []
        row = {}
        try:
            sel = card_selector or "[class*='metric'], [class*='kpi'], [class*='stat'], [class*='card'], [class*='widget']"
            cards = page.query_selector_all(sel)
            for card in cards:
                card_text = card.inner_text()
                lines = [l.strip() for l in card_text.split("\n") if l.strip()]
                text_lower = card_text.lower()
                for keyword, fk in label_map.items():
                    if keyword in text_lower and fk in field_keys and not row.get(fk):
                        for line in lines:
                            if keyword not in line.lower():
                                row[fk] = line
                                break
                        if not row.get(fk):
                            row[fk] = card_text.strip()[:300]
        except Exception:
            pass
        if row:
            rows.append(row)
        return rows


    def _is_error_page(self, page) -> tuple[bool, str]:
        """Detect if the page is showing an error, login page, or is not a valid data page.
        Returns (is_error, error_context).
        """
        error_indicators = [
            "sorry, this page does not exist",
            "sorry, this page isn't working",
            "page not found",
            "404 not found",
            "access denied",
            "you are not authorized",
            "please sign in",
            "sign in to continue",
            "session expired",
        ]
        try:
            url = page.url
            title = (page.evaluate("document.title") or "").lower()
            body_text = ""
            body = page.query_selector("body")
            if body:
                body_text = body.inner_text()[:2000].lower()

            for indicator in error_indicators:
                if indicator in body_text or indicator in title:
                    return True, f"Error page: '{indicator}' at {url}"

            if body_text and len(body_text.strip()) < 150:
                return True, f"Page too short ({len(body_text.strip())} chars) at {url}"
        except Exception:
            pass
        return False, ""

    def _generic_fallback(self, page) -> list[dict]:
        """Final fallback: try tables → list items → body text.
        Checks for error pages first and returns meaningful context instead of raw error text."""
        # First, check if the page is an error page
        is_error, error_context = self._is_error_page(page)
        if is_error:
            return [{"_error": error_context, "_source": "error_detected"}]

        rows = []
        try:
            tables = page.query_selector_all("table")
            if tables:
                for table in tables:
                    headers = [h.inner_text().strip().lower() for h in
                               table.query_selector_all("th")]
                    if not headers:
                        continue
                    body_rows = table.query_selector_all("tbody tr")
                    for tr in body_rows:
                        cells = tr.query_selector_all("td")
                        row = {}
                        for i, cell in enumerate(cells):
                            if i < len(headers):
                                key = f"raw_{headers[i].replace(' ', '_')}"
                                row[key] = cell.inner_text().strip()
                        if row:
                            rows.append(row)
        except Exception:
            pass
        if not rows:
            try:
                items = page.query_selector_all(
                    "[data-booking-id], .booking-item, .reservation-card, "
                    ".booking-row, [class*=booking], [class*=order], "
                    ".MuiTableRow-root, [data-testid*=booking]"
                )
                for item in items:
                    rows.append({"raw_data": item.inner_text().strip()})
            except Exception:
                pass
        if not rows:
            try:
                body = page.query_selector("body")
                if body:
                    body_text = body.inner_text()[:5000]
                    if len(body_text.strip()) >= 150:
                        rows.append({"raw_page_text": body_text})
                    else:
                        rows.append({"_error": f"No meaningful data (page has {len(body_text.strip())} chars)",
                                     "_source": "empty_page"})
            except Exception:
                pass
        return rows


# ────────────────────────────────────────────────────────────
#  Booking.com Extranet Source
# ────────────────────────────────────────────────────────────

class BookingExtranetSource(ExtranetSource):
    source_name = "Booking.com Extranet"
    login_url = "https://admin.booking.com/"

    @property
    def cookies_path(self):
        return BOOKING_EXTRANET_COOKIES

    @property
    def available_fields(self):
        return [
            {
                "group": "Dashboard / Home",
                "section": "dashboard",
                "fields": [
                    {"key": "dash_occupancy",        "label": "Occupancy Rate"},
                    {"key": "dash_revenue_ytd",      "label": "Revenue YTD"},
                    {"key": "dash_avg_daily_rate",   "label": "Average Daily Rate (ADR)"},
                    {"key": "dash_revpar",           "label": "RevPAR"},
                    {"key": "dash_bookings_today",   "label": "Bookings Today"},
                    {"key": "dash_check_ins_today",  "label": "Check-ins Today"},
                    {"key": "dash_check_outs_today", "label": "Check-outs Today"},
                    {"key": "dash_net_revenue",      "label": "Net Revenue"},
                    {"key": "dash_commission_total", "label": "Total Commission"},
                ]
            },
            {
                "group": "Reservations",
                "section": "reservations",
                "fields": [
                    {"key": "res_guest_name",     "label": "Guest Name"},
                    {"key": "res_check_in",       "label": "Check-in Date"},
                    {"key": "res_check_out",      "label": "Check-out Date"},
                    {"key": "res_room_type",      "label": "Room Type"},
                    {"key": "res_status",         "label": "Booking Status"},
                    {"key": "res_total_price",    "label": "Total Price"},
                    {"key": "res_balance",        "label": "Balance Due"},
                    {"key": "res_booking_id",     "label": "Booking ID / Confirmation"},
                ]
            },
            {
                "group": "Rates & Availability",
                "section": "rates",
                "fields": [
                    {"key": "rate_plan_name",       "label": "Rate Plan Name"},
                    {"key": "rate_plan_price",      "label": "Rate Plan Price"},
                    {"key": "rate_room_type",       "label": "Room Type"},
                    {"key": "rate_availability",    "label": "Available Rooms"},
                    {"key": "rate_los_min",         "label": "Min Length of Stay"},
                    {"key": "rate_los_max",         "label": "Max Length of Stay"},
                    {"key": "rate_restrictions",    "label": "Restrictions (CTA, closed-to-arrival)"},
                    {"key": "rate_meal_plan",       "label": "Meal Plan Included"},
                    {"key": "rate_cancel_policy",   "label": "Cancellation Policy"},
                ]
            },
            {
                "group": "Property Details",
                "section": "property",
                "fields": [
                    {"key": "prop_name",          "label": "Property Name"},
                    {"key": "prop_description",   "label": "Description"},
                    {"key": "prop_amenities",     "label": "Amenities"},
                    {"key": "prop_room_types",    "label": "Room Types"},
                    {"key": "prop_policies",      "label": "Policies"},
                    {"key": "prop_photos",        "label": "Photo URLs"},
                    {"key": "prop_facilities",    "label": "Facilities & Services"},
                    {"key": "prop_house_rules",   "label": "House Rules"},
                ]
            },
            {
                "group": "Boost Performance",
                "section": "boost",
                "fields": [
                    {"key": "boost_visibility_score",  "label": "Visibility Score"},
                    {"key": "boost_preferred_status",  "label": "Preferred Partner Status"},
                    {"key": "boost_genius_tier",       "label": "Genius Tier"},
                    {"key": "boost_conversion_rate",   "label": "Conversion Rate"},
                    {"key": "boost_competitor_rank",   "label": "Competitor Rank"},
                ]
            },
            {
                "group": "Inbox / Messages",
                "section": "inbox",
                "fields": [
                    {"key": "inb_guest_name",   "label": "Guest Name"},
                    {"key": "inb_subject",      "label": "Message Subject"},
                    {"key": "inb_message",      "label": "Message Body"},
                    {"key": "inb_date",         "label": "Message Date"},
                    {"key": "inb_status",       "label": "Read / Unread"},
                ]
            },
            {
                "group": "Reviews",
                "section": "reviews",
                "fields": [
                    {"key": "rev_guest_name",    "label": "Guest Name"},
                    {"key": "rev_score",         "label": "Review Score"},
                    {"key": "rev_comment",       "label": "Review Comment"},
                    {"key": "rev_response",      "label": "Your Response"},
                    {"key": "rev_date",          "label": "Review Date"},
                    {"key": "rev_language",      "label": "Language"},
                ]
            },
            {
                "group": "Financial / Payouts",
                "section": "financial",
                "fields": [
                    {"key": "fin_payout_amount", "label": "Payout Amount"},
                    {"key": "fin_payout_date",   "label": "Payout Date"},
                    {"key": "fin_commission",    "label": "Commission"},
                    {"key": "fin_invoice_id",    "label": "Invoice ID"},
                    {"key": "fin_status",        "label": "Payment Status"},
                ]
            },
            {
                "group": "Analytics",
                "section": "analytics",
                "fields": [
                    {"key": "anl_page_views",     "label": "Page Views"},
                    {"key": "anl_click_through",  "label": "Click-Through Rate"},
                    {"key": "anl_booking_demand", "label": "Booking Demand"},
                    {"key": "anl_market_share",   "label": "Market Share"},
                    {"key": "anl_competitor_pricing", "label": "Competitor Pricing"},
                    {"key": "anl_booking_window", "label": "Booking Window (days ahead)"},
                ]
            },
            {
                "group": "Promotions / Offers",
                "section": "promotions",
                "fields": [
                    {"key": "promo_name",          "label": "Promotion Name"},
                    {"key": "promo_type",          "label": "Promotion Type"},
                    {"key": "promo_discount",      "label": "Discount % / Amount"},
                    {"key": "promo_valid_from",    "label": "Valid From"},
                    {"key": "promo_valid_to",      "label": "Valid To"},
                    {"key": "promo_conditions",    "label": "Terms & Conditions"},
                    {"key": "promo_status",        "label": "Status"},
                ]
            },
        ]

    def login(self, page):
        page.goto(self.login_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

    def navigate_to_section(self, page, section_key: str) -> None:
        # Check if we are on the Group Homepage
        current_url = page.url.lower()
        if "/groups/home/" in current_url:
            # Let the DOM settle
            page.wait_for_timeout(2000)
            properties = []
            
            # Helper function to scan properties on the current Group page
            def scan_current_page():
                return page.evaluate("""() => {
                    const props = [];
                    const elements = document.querySelectorAll('a, button, [data-hotel-id], [data-id]');
                    for (const el of elements) {
                        let hotelId = '';
                        let hotelName = '';
                        
                        if (el.getAttribute('data-hotel-id')) {
                            hotelId = el.getAttribute('data-hotel-id');
                        } else if (el.getAttribute('data-id') && /^\d+$/.test(el.getAttribute('data-id'))) {
                            hotelId = el.getAttribute('data-id');
                        } else {
                            const href = el.getAttribute('href') || '';
                            const match = href.match(/hotel_id=(\d+)/) || href.match(/\/hotel\/(\d+)/);
                            if (match) {
                                hotelId = match[1];
                            }
                        }
                        
                        if (!hotelId || !/^\d+$/.test(hotelId)) continue;
                        
                        hotelName = el.textContent.trim();
                        if (hotelName.length < 4 || /manage|select|go|enter|edit|open/i.test(hotelName) || /^\d+$/.test(hotelName)) {
                            const row = el.closest('tr') || el.closest('[class*="row"]') || el.closest('[class*="item"]') || el.closest('li');
                            if (row) {
                                const cells = row.querySelectorAll('td, div, span, a');
                                for (const cell of cells) {
                                    if (cell === el) continue;
                                    const txt = cell.textContent.trim();
                                    if (txt.length >= 4 && !txt.includes('hotel_id') && !/^\d+$/.test(txt) && !/manage|select|go|enter|edit|open/i.test(txt)) {
                                        hotelName = txt;
                                        break;
                                    }
                                }
                            }
                        }
                        
                        hotelName = hotelName.replace(/\s+/g, ' ').trim();
                        
                        if (!props.some(p => p.id === hotelId)) {
                            props.push({ id: hotelId, name: hotelName });
                        }
                    }
                    return props;
                }""")

            # Loop through paginated Group Homepage to collect all properties (up to 1000 pages)
            for page_num in range(1, 1000):
                current_props = scan_current_page()
                for p in current_props:
                    if not any(x["id"] == p["id"] for x in properties):
                        properties.append(p)
                
                # Scroll to the bottom of the page to ensure lazy-loaded pagination elements are rendered and visible
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1000)
                except Exception:
                    pass

                # Look for a visible pagination 'Next' link or button
                next_btn = None
                try:
                    next_btn = page.query_selector(
                        'a[class*="next"], button[class*="next"], [data-testid="pagination-next-button"], '
                        '.bui-pagination__link[title*="Next"], .pagination__link--next, '
                        'button[aria-label*="Next"], a[aria-label*="Next"], [class*="pagination"] [class*="next"]'
                    )
                    if not next_btn:
                        buttons = page.query_selector_all('a, button, span')
                        for btn in buttons:
                            if btn.is_visible() and re.search(r'^(next|>|»)$', btn.inner_text().strip().lower()):
                                next_btn = btn
                                break
                except Exception:
                    pass
                
                if next_btn:
                    # Check if next button is disabled (has disabled attribute or class)
                    is_disabled = False
                    try:
                        is_disabled = page.evaluate("""(btn) => {
                            return btn.hasAttribute('disabled') || 
                                   btn.classList.contains('disabled') || 
                                   btn.getAttribute('aria-disabled') === 'true' ||
                                   btn.classList.contains('bui-pagination__item--disabled') ||
                                   (btn.parentElement && (
                                       btn.parentElement.classList.contains('bui-pagination__item--disabled') ||
                                       btn.parentElement.classList.contains('disabled')
                                   ));
                        }""", next_btn)
                    except Exception:
                        pass
                    if is_disabled:
                        break
                        
                    try:
                        next_btn.click()
                        page.wait_for_timeout(1500) # Wait for page load to settle
                    except Exception:
                        break
                else:
                    break

            self._properties = properties
        else:
            self._properties = []

        # Extract session parameters from current page URL (ses, hotel_account_id, hotel_id)
        # First, wait up to 10 seconds for session parameters to appear in the URL (if the page is loading/redirecting)
        ses_match = None
        account_match = None
        hotel_match = None
        
        for _ in range(10):
            current_url = page.url
            ses_match = re.search(r'ses=([a-f0-9]+)', current_url)
            account_match = re.search(r'hotel_account_id=(\d+)', current_url)
            hotel_match = re.search(r'hotel_id=(\d+)', current_url)
            if ses_match or account_match or hotel_match:
                break
            page.wait_for_timeout(1000)

        # If no ses params, navigate to login to establish session
        if not ses_match and not account_match and not hotel_match:
            # Check if we are already on a login or error page. If so, don't trigger redundant page loads
            if "login" not in page.url.lower():
                page.goto(self.login_url, timeout=30000, wait_until="domcontentloaded")
                time.sleep(4)
            current_url = page.url
            ses_match = re.search(r'ses=([a-f0-9]+)', current_url)
            account_match = re.search(r'hotel_account_id=(\d+)', current_url)
            hotel_match = re.search(r'hotel_id=(\d+)', current_url)

        base = "https://admin.booking.com/hotel/hoteladmin/extranet_ng/manage"

        params = []
        if ses_match:
            params.append(f"ses={ses_match.group(1)}")
        if account_match:
            params.append(f"hotel_account_id={account_match.group(1)}")
            
        # Override hotel_id if we scanned properties from group homepage
        properties = getattr(self, "_properties", [])
        if properties:
            params.append(f"hotel_id={properties[0]['id']}")
        elif hotel_match:
            params.append(f"hotel_id={hotel_match.group(1)}")
            
        params.append("lang=en")
        param_str = "?" + "&".join(params) if (ses_match or account_match or hotel_match or properties) else ""

        section_map = {
            "dashboard":     f"{base}/home.html{param_str}",
            "reservations":  f"{base}/reservations.html{param_str}",
            "rates":         f"{base}/rates_availability.html{param_str}",
            "property":      f"{base}/property.html{param_str}",
            "boost":         f"{base}/boost_performance.html{param_str}",
            "inbox":         f"{base}/inbox.html{param_str}",
            "reviews":       f"{base}/reviews.html{param_str}",
            "financial":     f"{base}/finance.html{param_str}",
            "analytics":     f"{base}/analytics.html{param_str}",
            "promotions":    f"{base}/promotions/list.html{param_str}",
        }
        url = section_map.get(section_key, base)
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

    # ── Section-aware field extraction ──────────────────────

    def _detect_section(self, field_keys: list[str]) -> str:
        """Determine which section we're on by field key prefix."""
        prefix_map = {
            "dash": "dashboard", "res": "reservations", "rate": "rates",
            "prop": "property", "boost": "boost", "inb": "inbox",
            "rev": "reviews", "fin": "financial", "anl": "analytics",
            "promo": "promotions",
        }
        for key in field_keys:
            prefix = key.split("_")[0]
            if prefix in prefix_map:
                return prefix_map[prefix]
        return "general"

    def _extract_property_fields(self, page, field_keys: list[str]) -> dict:
        """Extract Property Details fields from the Booking.com extranet property page."""
        row = {}

        # ── Property Name ────────────────────────────────────
        if "prop_name" in field_keys:
            val = self._try_selectors(page, [
                "h1",
                "h1[class*='name']", "h1[class*='title']",
                "input[name='name']", "input[name*='hotel_name']", "input[id*='name']",
                "[class*='property-name']", "[class*='hotel-name']",
                "[data-name='hotel-name']", "[data-name='property-name']",
                "span[class*='bui-header__title']",
                ".bui-header__title",
                "div[class*='page-title']",
                "[class*='main-title']",
                "[class*='headline']",
            ])
            if not val:
                # Fallback: page <title> tag
                try:
                    val = page.evaluate("document.title").strip()
                    # Clean common suffixes
                    for suffix in [" - Booking.com", " - Booking.com Extranet", " | Booking.com", " - Manage your property"]:
                        if val.endswith(suffix):
                            val = val[:-len(suffix)].strip()
                            break
                except Exception:
                    pass
            row["prop_name"] = val or ""

        # ── Description ──────────────────────────────────────
        if "prop_description" in field_keys:
            val = self._try_selectors(page, [
                "textarea[name*='description']", "textarea[id*='description']",
                "[class*='description']", "[data-name='description']",
                "div[class*='desc']", "textarea[class*='desc']",
                ".editor-content", "[contenteditable='true']",
            ])
            if not val:
                val = self._extract_value_by_label(page, "Description")
                if not val:
                    val = self._extract_value_by_label(page, "desc")
            row["prop_description"] = val or ""

        # ── Amenities ────────────────────────────────────────
        if "prop_amenities" in field_keys:
            val = self._try_selectors(page, [
                "[class*='amenity']", "[data-name='amenities']",
                ".amenities-list", ".facilities-list",
            ])
            if not val:
                # Collect text from checked checkboxes
                checked_items = page.evaluate("""() => {
                    const checked = document.querySelectorAll('input[type="checkbox"]:checked');
                    const texts = [];
                    for (const cb of checked) {
                        const label = cb.closest('label');
                        if (label) texts.push(label.textContent.trim());
                        else {
                            const parent = cb.parentElement;
                            if (parent) texts.push(parent.textContent.trim());
                        }
                    }
                    return texts.join('; ');
                }""")
                if checked_items and checked_items.strip():
                    val = checked_items.strip()
            row["prop_amenities"] = val or ""

        # ── Room Types ───────────────────────────────────────
        if "prop_room_types" in field_keys:
            val = self._try_selectors(page, [
                "[class*='room-type']", "[class*='roomtype']", "[data-name='room-types']",
                "[class*='room'] h3", "[class*='room'] h4",
                ".room-list", "[class*='unit-type']",
            ])
            if not val:
                val = self._extract_value_by_label(page, "Room Types")
            row["prop_room_types"] = val or ""

        # ── Facilities & Services ────────────────────────────
        if "prop_facilities" in field_keys:
            val = self._try_selectors(page, [
                "[class*='facilities']", "[class*='facility']",
                "[data-name='facilities']", "[class*='services']",
                ".facilities-list", ".services-list",
            ])
            if not val:
                val = self._extract_value_by_label(page, "Facilities")
            row["prop_facilities"] = val or ""

        # ── Policies ─────────────────────────────────────────
        if "prop_policies" in field_keys:
            val = self._try_selectors(page, [
                "[class*='policy']", "[data-name='policies']",
                "[class*='policy-section']",
            ])
            if not val:
                val = self._extract_value_by_label(page, "Policies")
            row["prop_policies"] = val or ""

        # ── House Rules ──────────────────────────────────────
        if "prop_house_rules" in field_keys:
            val = self._try_selectors(page, [
                "[class*='house-rule']", "[class*='house_rule']",
                "[data-name='house-rules']", "[class*='rules']",
            ])
            if not val:
                val = self._extract_value_by_label(page, "House Rules")
            row["prop_house_rules"] = val or ""

        # ── Photos ───────────────────────────────────────────
        if "prop_photos" in field_keys:
            photo_urls = page.evaluate("""() => {
                const imgs = document.querySelectorAll('img[class*="photo"], img[class*="gallery"], [class*="photo"] img, [class*="gallery"] img');
                const urls = [];
                for (const img of imgs) {
                    const src = img.getAttribute('src') || img.getAttribute('data-src') || '';
                    if (src && !urls.includes(src)) urls.push(src);
                }
                return urls.join('; ');
            }""")
            row["prop_photos"] = photo_urls.strip() if photo_urls else ""

        return row

    def _extract_dashboard_fields(self, page, field_keys: list[str]) -> list[dict]:
        """Extract Dashboard / Home metrics from the Booking.com extranet dashboard.
        Looks for metric cards / KPI boxes that contain a value and label.
        """
        rows = []
        row = {}

        # Try to find metric cards — common patterns in Booking.com extranet dashboard
        # Often these are structured as: <value> <label> pairs in cards
        try:
            # Pattern 1: cards with a number/big text and a label below
            metric_cards = page.query_selector_all(
                "[class*='metric'], [class*='kpi'], [class*='stat'], "
                "[class*='dashboard-card'], [class*='summary-card'], "
                "[class*='overview'] > div, [class*='widget']"
            )
            if metric_cards:
                for card in metric_cards:
                    card_text = card.inner_text().strip()
                    if not card_text:
                        continue
                    lines = [l.strip() for l in card_text.split("\n") if l.strip()]
                    # Look for known labels
                    label_map = {
                        "occupancy": "dash_occupancy", "revenue ytd": "dash_revenue_ytd",
                        "average daily rate": "dash_avg_daily_rate", "adr": "dash_avg_daily_rate",
                        "revpar": "dash_revpar", "bookings today": "dash_bookings_today",
                        "check-ins": "dash_check_ins_today", "check-ins today": "dash_check_ins_today",
                        "check-outs": "dash_check_outs_today", "check-outs today": "dash_check_outs_today",
                        "net revenue": "dash_net_revenue", "total commission": "dash_commission_total",
                        "commission": "dash_commission_total",
                    }
                    for line in lines:
                        line_lower = line.lower()
                        for keyword, field_key in label_map.items():
                            if keyword in line_lower and field_key in field_keys and not row.get(field_key):
                                # The value is likely the numeric part (first line or adjacent)
                                if lines.index(line) > 0:
                                    val = lines[lines.index(line) - 1]
                                else:
                                    val = line
                                row[field_key] = val
                                break
        except Exception:
            pass

        if row:
            rows.append(row)
        return rows

    def _extract_review_fields(self, page, field_keys: list[str]) -> list[dict]:
        """Extract review data from review cards/lists.
        Booking.com extranet reviews show guest name, score, comment, etc.
        """
        rows = []

        # Try table-based extraction first (column mapping)
        table_rows = self._extract_table_fields(page, field_keys, {
            "guest": "rev_guest_name", "name": "rev_guest_name",
            "score": "rev_score", "rating": "rev_score",
            "comment": "rev_comment", "review": "rev_comment",
            "response": "rev_response", "reply": "rev_response",
            "date": "rev_date", "language": "rev_language", "lang": "rev_language",
        })
        if table_rows:
            return table_rows

        # Fallback: parse review cards
        try:
            cards = page.query_selector_all(
                "[class*='review'], [class*='feedback'], "
                ".review-card, .guest-review, [data-review-id]"
            )
            for card in cards:
                row = {}
                full_text = card.inner_text()
                if "rev_guest_name" in field_keys:
                    name_el = card.query_selector("[class*='name'], [class*='guest'], h3, h4")
                    row["rev_guest_name"] = name_el.inner_text().strip() if name_el else ""
                if "rev_score" in field_keys:
                    score_el = card.query_selector("[class*='score'], [class*='rating'], [class*='grade']")
                    row["rev_score"] = score_el.inner_text().strip() if score_el else ""
                if "rev_comment" in field_keys:
                    comment_el = card.query_selector("[class*='comment'], [class*='review-text'], [class*='text']")
                    row["rev_comment"] = comment_el.inner_text().strip() if comment_el else ""
                if "rev_date" in field_keys:
                    date_el = card.query_selector("[class*='date'], [class*='time'], time")
                    row["rev_date"] = date_el.inner_text().strip() if date_el else ""
                if "rev_response" in field_keys:
                    resp_el = card.query_selector("[class*='response'], [class*='reply']")
                    row["rev_response"] = resp_el.inner_text().strip() if resp_el else ""
                if row:
                    rows.append(row)
        except Exception:
            pass

        return rows

    def _extract_inbox_fields(self, page, field_keys: list[str]) -> list[dict]:
        """Extract messages from the Inbox section."""
        rows = []

        # Try table first with column mapping
        table_rows = self._extract_table_fields(page, field_keys, {
            "guest": "inb_guest_name", "name": "inb_guest_name",
            "from": "inb_guest_name", "sender": "inb_guest_name",
            "subject": "inb_subject", "message": "inb_message",
            "date": "inb_date", "time": "inb_date",
            "status": "inb_status", "read": "inb_status", "unread": "inb_status",
        })
        if table_rows:
            return table_rows

        # Fallback: parse message list items
        try:
            items = page.query_selector_all(
                "[class*='message'], .inbox-item, [class*='conversation'], "
                "tr[class*='message'], [data-message-id]"
            )
            for item in items:
                row = {}
                if "inb_guest_name" in field_keys:
                    el = item.query_selector("[class*='sender'], [class*='from'], [class*='guest']")
                    row["inb_guest_name"] = el.inner_text().strip() if el else ""
                if "inb_subject" in field_keys:
                    el = item.query_selector("[class*='subject'], [class*='title']")
                    row["inb_subject"] = el.inner_text().strip() if el else ""
                if "inb_message" in field_keys:
                    el = item.query_selector("[class*='preview'], [class*='snippet'], [class*='body']")
                    row["inb_message"] = el.inner_text().strip() if el else ""
                if "inb_date" in field_keys:
                    el = item.query_selector("[class*='date'], [class*='time'], time")
                    row["inb_date"] = el.inner_text().strip() if el else ""
                if "inb_status" in field_keys:
                    # Check for read/unread indicators
                    unread = item.query_selector("[class*='unread'], [class*='new']")
                    row["inb_status"] = "Unread" if unread else "Read"
                if row:
                    rows.append(row)
        except Exception:
            pass

        return rows

    def _extract_boost_fields(self, page, field_keys: list[str]) -> list[dict]:
        """Extract Boost / Performance section data."""
        rows = []
        row = {}

        try:
            # Try to find metric cards on the boost performance page
            cards = page.query_selector_all(
                "[class*='metric'], [class*='kpi'], [class*='stat'], "
                "[class*='boost'], [class*='performance'], "
                ".bui-card, [class*='card']"
            )
            label_map = {
                "visibility": "boost_visibility_score",
                "preferred": "boost_preferred_status", "partner": "boost_preferred_status",
                "genius": "boost_genius_tier",
                "conversion": "boost_conversion_rate",
                "competitor": "boost_competitor_rank", "rank": "boost_competitor_rank",
            }
            for card in cards:
                text = card.inner_text().strip().lower()
                for keyword, fk in label_map.items():
                    if keyword in text and fk in field_keys and not row.get(fk):
                        # Value is often the numeric/status part preceding the label
                        lines = [l.strip() for l in card.inner_text().split("\n") if l.strip()]
                        for line in lines:
                            if keyword not in line.lower():
                                row[fk] = line
                                break
                        if not row.get(fk):
                            row[fk] = card.inner_text().strip()[:200]
        except Exception:
            pass

        if row:
            rows.append(row)
        return rows

    def _extract_analytics_fields(self, page, field_keys: list[str]) -> list[dict]:
        """Extract Analytics section data."""
        rows = []
        row = {}

        try:
            cards = page.query_selector_all(
                "[class*='metric'], [class*='kpi'], [class*='stat'], "
                "[class*='analytics'], [class*='chart'], "
                ".bui-card, [class*='card'], [class*='widget']"
            )
            label_map = {
                "page views": "anl_page_views", "views": "anl_page_views",
                "click-through": "anl_click_through", "ctr": "anl_click_through",
                "booking demand": "anl_booking_demand", "demand": "anl_booking_demand",
                "market share": "anl_market_share",
                "competitor pricing": "anl_competitor_pricing", "pricing": "anl_competitor_pricing",
                "booking window": "anl_booking_window", "window": "anl_booking_window",
            }
            for card in cards:
                text = card.inner_text().strip().lower()
                for keyword, fk in label_map.items():
                    if keyword in text and fk in field_keys and not row.get(fk):
                        lines = [l.strip() for l in card.inner_text().split("\n") if l.strip()]
                        for line in lines:
                            if keyword not in line.lower():
                                row[fk] = line
                                break
                        if not row.get(fk):
                            row[fk] = card.inner_text().strip()[:200]
        except Exception:
            pass

        if row:
            rows.append(row)
        return rows

    def _extract_promotions_fields(self, page, field_keys: list[str]) -> list[dict]:
        """Extract Promotions / Offers data."""
        rows = []

        # Check if the page has an indicator of "no active promotions"
        try:
            body_text = page.inner_text("body").lower()
            no_promo_indicators = [
                "don't have any active promotions",
                "no active promotions",
                "no promotions running",
                "you don't have any promotions",
            ]
            if any(ind in body_text for ind in no_promo_indicators):
                return []
        except Exception:
            pass

        # Try table-based extraction first
        table_rows = self._extract_table_fields(page, field_keys, {
            "name": "promo_name", "promotion": "promo_name", "offer": "promo_name",
            "type": "promo_type",
            "discount": "promo_discount", "%": "promo_discount",
            "from": "promo_valid_from", "valid from": "promo_valid_from",
            "to": "promo_valid_to", "valid to": "promo_valid_to",
            "terms": "promo_conditions", "conditions": "promo_conditions",
            "status": "promo_status",
        })
        if table_rows:
            return table_rows

        # Fallback: parse promotion cards with a line classifier
        try:
            items = page.query_selector_all(
                ".promo-card, .offer-card, [data-promo-id], "
                "[class*='promo-card'], [class*='offer-card'], [class*='promotion-card'], "
                "div[class*='promo-row'], div[class*='offer-row']"
            )
            for item in items:
                row = {}
                full_text = item.inner_text().strip()
                if not full_text or len(full_text) < 10:
                    continue
                lines = [l.strip() for l in full_text.split("\n") if l.strip()]
                
                # Basic classification of lines
                discount = ""
                name = ""
                dates = []
                status = "Active"
                conditions = ""
                promo_type = "Standard"
                
                for idx, line in enumerate(lines):
                    l_lower = line.lower()
                    if "%" in line or any(curr in line for curr in ["$", "€", "£", "rs", "inr"]) or "off" in l_lower or "discount" in l_lower:
                        discount = line
                    elif "valid" in l_lower or "from" in l_lower or "to" in l_lower or any(m in l_lower for m in ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]):
                        dates.append(line)
                    elif "status" in l_lower or "ended" in l_lower or "inactive" in l_lower or "expired" in l_lower:
                        status = line
                    elif "terms" in l_lower or "condition" in l_lower or "min stay" in l_lower:
                        conditions = line
                    elif idx == 0:
                        name = line
                    elif idx == 1 and not name:
                        name = line
                        
                # Map extracted variables to the requested field keys
                row["promo_name"] = name or (lines[0] if lines else "Promotion")
                row["promo_type"] = promo_type
                row["promo_discount"] = discount or "No Discount"
                if len(dates) >= 2:
                    row["promo_valid_from"] = dates[0]
                    row["promo_valid_to"] = dates[1]
                elif len(dates) == 1:
                    row["promo_valid_from"] = dates[0]
                    row["promo_valid_to"] = dates[0]
                else:
                    row["promo_valid_from"] = "N/A"
                    row["promo_valid_to"] = "N/A"
                row["promo_conditions"] = conditions or "Standard terms"
                row["promo_status"] = status
                
                if row:
                    rows.append(row)
        except Exception:
            pass

        return rows

    def _extract_single_property_data(self, page, field_keys: list[str], section: str) -> list[dict]:
        # ── Section-specific extraction ──────────────────────
        if section == "property":
            row = self._extract_property_fields(page, field_keys)
            if any(row.values()):
                return [row]

        elif section == "dashboard":
            rows = self._extract_dashboard_fields(page, field_keys)
            if rows:
                return rows

        elif section == "reservations":
            rows = self._extract_table_fields(page, field_keys, {
                "booking": "res_booking_id", "id": "res_booking_id", "confirmation": "res_booking_id",
                "guest": "res_guest_name", "name": "res_guest_name",
                "check-in": "res_check_in", "check in": "res_check_in", "arrival": "res_check_in",
                "check-out": "res_check_out", "check out": "res_check_out", "departure": "res_check_out",
                "room": "res_room_type", "room type": "res_room_type",
                "status": "res_status",
                "price": "res_total_price", "total": "res_total_price", "amount": "res_total_price",
                "balance": "res_balance", "due": "res_balance",
            })
            if rows:
                return rows

        elif section == "rates":
            rows = self._extract_table_fields(page, field_keys, {
                "plan": "rate_plan_name", "rate plan": "rate_plan_name",
                "price": "rate_plan_price", "rate": "rate_plan_price",
                "room": "rate_room_type", "room type": "rate_room_type",
                "available": "rate_availability", "availability": "rate_availability",
                "min": "rate_los_min", "min stay": "rate_los_min",
                "max": "rate_los_max", "max stay": "rate_los_max",
                "restriction": "rate_restrictions",
                "meal": "rate_meal_plan", "board": "rate_meal_plan",
                "cancel": "rate_cancel_policy", "cancellation": "rate_cancel_policy",
            })
            if rows:
                return rows

        elif section == "reviews":
            rows = self._extract_review_fields(page, field_keys)
            if rows:
                return rows

        elif section == "inbox":
            rows = self._extract_inbox_fields(page, field_keys)
            if rows:
                return rows

        elif section == "boost":
            rows = self._extract_boost_fields(page, field_keys)
            if rows:
                return rows

        elif section == "analytics":
            rows = self._extract_analytics_fields(page, field_keys)
            if rows:
                return rows

        elif section == "promotions":
            rows = self._extract_promotions_fields(page, field_keys)
            if rows:
                return rows

        elif section == "financial":
            rows = self._extract_table_fields(page, field_keys, {
                "amount": "fin_payout_amount", "payout": "fin_payout_amount",
                "date": "fin_payout_date", "payout date": "fin_payout_date",
                "commission": "fin_commission",
                "invoice": "fin_invoice_id", "id": "fin_invoice_id",
                "status": "fin_status", "payment": "fin_status",
            })
            if rows:
                return rows

        # ── Generic fallback (inherited from ExtranetSource) ─
        return self._generic_fallback(page)

    def _extract_property_name_from_page(self, page) -> str:
        """Extract the exact hotel/property name from the current extranet page."""
        try:
            # Settle DOM briefly
            page.wait_for_timeout(1000)
            
            # Words to exclude (since they represent section/page names rather than hotel names)
            exclude_words = {
                "promotions", "rates & availability", "rates", "availability", 
                "reservations", "property", "inbox", "reviews", "finance", 
                "analytics", "dashboard", "home", "group home", "extranet", 
                "calendar", "bulk edit", "deals", "offers", "opportunities"
            }
            
            # Selector list representing elements containing hotel/property name on Booking.com
            selectors = [
                "[class*='hotel-name']",
                "[class*='property-name']",
                "[data-name='hotel-name']",
                "[data-name='property-name']",
                "div[class*='property-name']",
                "[class*='property-selector']",
                "span[class*='property_name']",
                ".property_name",
                ".hotel_name",
                "span[class*='bui-header__title']",
                ".bui-header__title",
                "h1[class*='name']",
                "h1[class*='title']",
                "[class*='header-title']",
            ]
            for sel in selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        text = el.inner_text().strip()
                        if text and len(text) > 2:
                            if text.lower() not in exclude_words and not any(w in text.lower() for w in exclude_words):
                                return text
                except Exception:
                    continue
            
            # Fallback: Extract from document.title by splitting on structural separators
            title = page.evaluate("document.title") or ""
            parts = re.split(r'[\-\|·•:—–\(\)]+', title)
            cleaned_parts = []
            for part in parts:
                p = part.strip()
                if not p:
                    continue
                # Clean up Booking keywords
                p_clean = p.replace("Booking.com Extranet", "").replace("Booking.com", "").replace("Extranet", "").strip()
                p_clean_lower = p_clean.lower()
                
                if not p_clean or len(p_clean) < 3:
                    continue
                if p_clean_lower in exclude_words:
                    continue
                if p_clean_lower in ["booking", "extranet", "com", "admin", "hotel", "property"]:
                    continue
                if re.match(r'^\d+$', p_clean):
                    continue
                cleaned_parts.append(p_clean)
                
            if cleaned_parts:
                return cleaned_parts[0]
        except Exception:
            pass
        return ""

    def extract_data(self, page, selected_fields: list[dict]) -> list[dict]:
        """Extract rows from the currently loaded Booking.com extranet page.
        Routes to section-specific extraction methods based on the field key prefixes.
        Falls back to generic table/body extraction if no fields are matched.
        """
        field_keys = [f["key"] for f in selected_fields]
        section = self._detect_section(field_keys)

        # Check if we have multiple properties scanned from the Group Homepage
        properties = getattr(self, "_properties", [])
        if properties and len(properties) > 1:
            all_rows = []
            ses_match = re.search(r'ses=([a-f0-9]+)', page.url)
            ses = ses_match.group(1) if ses_match else ""
            
            # Keep a copy of properties and clear self._properties to prevent infinite recursion
            props_list = list(properties)
            self._properties = []
            
            # Update SQLite session total properties count
            session_id = getattr(self, "session_id", None)
            if session_id:
                ScrapeHistoryManager.update_session_counts(session_id, len(props_list))
                
            # Get already completed properties to skip them (resume functionality)
            completed_props = set()
            if session_id:
                completed_props = ScrapeHistoryManager.get_completed_properties(session_id)
            
            base = "https://admin.booking.com/hotel/hoteladmin/extranet_ng/manage"
            section_paths = {
                "dashboard": "home.html",
                "reservations": "reservations.html",
                "rates": "rates_availability.html",
                "property": "property.html",
                "boost": "boost_performance.html",
                "inbox": "inbox.html",
                "reviews": "reviews.html",
                "financial": "finance.html",
                "analytics": "analytics.html",
                "promotions": "promotions/list.html",
            }
            path = section_paths.get(section, "promotions/list.html")
            
            worker = getattr(self, "worker", None)
            
            for idx, prop in enumerate(props_list):
                # Graceful cancellation check
                if worker and worker._stop:
                    if worker:
                        worker.log_msg.emit("Scrape job stop requested. Stopping multi-property loop...")
                    break
                    
                hotel_id = prop["id"]
                hotel_name = prop["name"]
                
                # Check for resume skip
                if hotel_id in completed_props:
                    if worker:
                        worker.log_msg.emit(f"Skipping already completed property {idx+1}/{len(props_list)}: {hotel_name} ({hotel_id})")
                        worker.progress.emit(idx, len(props_list), f"Skipping {hotel_name}...")
                    continue
                
                if worker:
                    worker.log_msg.emit(f"Scraping property {idx+1}/{len(props_list)}: {hotel_name} ({hotel_id})")
                    worker.progress.emit(idx, len(props_list), f"Scraping {hotel_name}...")
                
                url = f"{base}/{path}?hotel_id={hotel_id}&ses={ses}&lang=en"
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    
                    # Dynamic wait for page contents to render (promotions table, cards, or empty state text)
                    try:
                        page.wait_for_selector(
                            ".promo-card, .offer-card, table, [data-promo-id], "
                            "[class*='promo'], [class*='offer'], "
                            "text='active promotions', text='no active promotions', "
                            "text='Choose new promotion'",
                            timeout=1500
                        )
                    except Exception:
                        page.wait_for_timeout(500) # fallback sleep
                    
                    # Extract the exact property name from the actual property page!
                    exact_name = self._extract_property_name_from_page(page)
                    if exact_name and exact_name.lower() not in ["promotions", "rates", "availability", "reservations", "property", "inbox", "reviews", "finance", "analytics", "dashboard", "home", "extranet"]:
                        hotel_name = exact_name
                    
                    # Call single-property extraction
                    rows = self._extract_single_property_data(page, field_keys, section)
                    
                    # Tag with hotel info
                    for r in rows:
                        r["hotel_id"] = hotel_id
                        r["hotel_name"] = hotel_name
                        all_rows.append(r)
                        
                    # Save incremental data & update SQLite
                    self._append_scraped_property_data(hotel_id, hotel_name, rows, "Completed")
                except Exception as e:
                    err_row = {
                        "_error": f"Failed to scrape hotel {hotel_name} ({hotel_id}): {str(e)}",
                        "hotel_id": hotel_id,
                        "hotel_name": hotel_name
                    }
                    all_rows.append(err_row)
                    self._append_scraped_property_data(hotel_id, hotel_name, [err_row], "Failed")
            
            return all_rows

        # Single-property extraction logic
        # For single property, also try to tag with the exact hotel name and ID if we are on a valid extranet page
        exact_hotel_name = self._extract_property_name_from_page(page)
        hotel_id_match = re.search(r'hotel_id=(\d+)', page.url)
        hotel_id = hotel_id_match.group(1) if hotel_id_match else "single"
        if not exact_hotel_name:
            exact_hotel_name = "Single Property"
            
        session_id = getattr(self, "session_id", None)
        if session_id:
            ScrapeHistoryManager.update_session_counts(session_id, 1)
        
        rows = self._extract_single_property_data(page, field_keys, section)
        if exact_hotel_name or hotel_id:
            for r in rows:
                if exact_hotel_name and not r.get("hotel_name"):
                    r["hotel_name"] = exact_hotel_name
                if hotel_id and not r.get("hotel_id"):
                    r["hotel_id"] = hotel_id
                    
        # Save incremental data & update SQLite
        self._append_scraped_property_data(hotel_id, exact_hotel_name, rows, "Completed")
        
        return rows


# ────────────────────────────────────────────────────────────
#  MMT Extranet Source
# ────────────────────────────────────────────────────────────

class MMTExtranetSource(ExtranetSource):
    source_name = "MMT (MakeMyTrip) Extranet"
    login_url = "https://in.goibibo.com/newextranet/dashboard"

    @property
    def cookies_path(self):
        return MMT_EXTRANET_COOKIES

    @property
    def available_fields(self):
        return [
            {
                "group": "Reservations / Bookings",
                "section": "reservations",
                "fields": [
                    {"key": "mmt_booking_id",     "label": "Booking ID"},
                    {"key": "mmt_guest_name",     "label": "Guest Name"},
                    {"key": "mmt_check_in",       "label": "Check-in Date"},
                    {"key": "mmt_check_out",      "label": "Check-out Date"},
                    {"key": "mmt_room_type",      "label": "Room Type"},
                    {"key": "mmt_status",         "label": "Booking Status"},
                    {"key": "mmt_total_amount",   "label": "Total Amount"},
                ]
            },
            {
                "group": "Property Details",
                "section": "property",
                "fields": [
                    {"key": "mmt_prop_name",      "label": "Property Name"},
                    {"key": "mmt_prop_desc",      "label": "Description"},
                    {"key": "mmt_amenities",      "label": "Amenities"},
                    {"key": "mmt_room_inventory", "label": "Room Inventory / Rates"},
                ]
            },
            {
                "group": "Reviews",
                "section": "reviews",
                "fields": [
                    {"key": "mmt_rev_guest",     "label": "Guest Name"},
                    {"key": "mmt_rev_score",     "label": "Rating / Score"},
                    {"key": "mmt_rev_comment",   "label": "Review Comment"},
                    {"key": "mmt_rev_date",      "label": "Review Date"},
                ]
            },
            {
                "group": "Financial / Settlement",
                "section": "financial",
                "fields": [
                    {"key": "mmt_settlement_amt","label": "Settlement Amount"},
                    {"key": "mmt_settlement_date","label": "Settlement Date"},
                    {"key": "mmt_commission",    "label": "Commission"},
                    {"key": "mmt_tds",           "label": "TDS"},
                    {"key": "mmt_invoice_no",    "label": "Invoice Number"},
                ]
            },
            {
                "group": "Promotions / Offers",
                "section": "promotions",
                "fields": [
                    {"key": "promo_mmt_name",       "label": "Offer Name"},
                    {"key": "promo_mmt_type",       "label": "Offer Type"},
                    {"key": "promo_mmt_discount",   "label": "Discount % / Amount"},
                    {"key": "promo_mmt_valid_from", "label": "Valid From"},
                    {"key": "promo_mmt_valid_to",   "label": "Valid To"},
                    {"key": "promo_mmt_conditions", "label": "Terms & Conditions"},
                    {"key": "promo_mmt_status",     "label": "Status"},
                ]
            },
        ]

    @property
    def multi_tab(self) -> bool:
        return True

    def login(self, page):
        page.goto(self.login_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

    def navigate_to_section(self, page, section_key: str) -> None:
        base = "https://hotel.makemytrip.com"
        section_map = {
            "reservations": f"{base}/bookings",
            "property":     f"{base}/property",
            "reviews":      f"{base}/reviews",
            "financial":    f"{base}/settlement",
            "promotions":   f"{base}/promotions",
        }
        url = section_map.get(section_key, base)
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

    def _detect_section(self, field_keys: list[str]) -> str:
        """Determine which MMT section we're on by field key prefix."""
        for key in field_keys:
            if key.startswith("promo_mmt"):
                return "promotions"
            if key.startswith("mmt_rev"):
                return "reviews"
            if key.startswith("mmt_settlement") or key.startswith("mmt_commission") or key.startswith("mmt_tds") or key.startswith("mmt_invoice"):
                return "financial"
            if key.startswith("mmt_prop") or key.startswith("mmt_amenities") or key.startswith("mmt_room"):
                return "property"
            if key.startswith("mmt"):
                return "reservations"
        return "general"

    def _extract_mmt_property_fields(self, page, field_keys: list[str]) -> dict:
        """Extract MMT Property Details fields."""
        row = {}
        if "mmt_prop_name" in field_keys:
            val = self._try_selectors(page, [
                "h1", "h2", "input[name*='name']", "input[id*='name']",
                "[class*='property-name']", "[class*='hotel-name']",
                "[class*='page-title']", "[class*='headline']",
            ])
            if not val:
                try:
                    val = page.evaluate("document.title").strip()
                    for suf in [" - MakeMyTrip", " | MakeMyTrip", " - MMT"]:
                        if val.endswith(suf):
                            val = val[:-len(suf)].strip()
                            break
                except Exception:
                    pass
            row["mmt_prop_name"] = val or ""
        if "mmt_prop_desc" in field_keys:
            val = self._try_selectors(page, [
                "textarea[name*='description']", "textarea[id*='description']",
                "[class*='description']", "[class*='desc']",
                ".editor-content", "[contenteditable='true']",
            ])
            if not val:
                val = self._extract_value_by_label(page, "Description")
            row["mmt_prop_desc"] = val or ""
        if "mmt_amenities" in field_keys:
            val = self._try_selectors(page, [
                "[class*='amenity']", "[class*='facilities']", ".amenities-list",
            ])
            if not val:
                checked = page.evaluate("""() => {
                    const cbs = document.querySelectorAll('input[type="checkbox"]:checked');
                    return Array.from(cbs).map(cb => {
                        const lbl = cb.closest('label');
                        return lbl ? lbl.textContent.trim() : (cb.parentElement ? cb.parentElement.textContent.trim() : '');
                    }).filter(t => t).join('; ');
                }""")
                val = checked
            row["mmt_amenities"] = val or ""
        if "mmt_room_inventory" in field_keys:
            val = self._try_selectors(page, [
                "[class*='room']", "[class*='inventory']", "[class*='rate-plan']",
                "table",
            ])
            row["mmt_room_inventory"] = val or ""
        return row

    def extract_data(self, page, selected_fields: list[dict]) -> list[dict]:
        """Extract rows from the currently loaded MMT extranet page.
        Routes to section-specific extraction based on field key prefixes.
        """
        field_keys = [f["key"] for f in selected_fields]
        section = self._detect_section(field_keys)

        if section == "property":
            row = self._extract_mmt_property_fields(page, field_keys)
            if any(row.values()):
                return [row]

        elif section == "reservations":
            rows = self._extract_table_fields(page, field_keys, {
                "booking": "mmt_booking_id", "id": "mmt_booking_id", "confirmation": "mmt_booking_id",
                "guest": "mmt_guest_name", "name": "mmt_guest_name",
                "check-in": "mmt_check_in", "check in": "mmt_check_in", "arrival": "mmt_check_in",
                "check-out": "mmt_check_out", "check out": "mmt_check_out", "departure": "mmt_check_out",
                "room": "mmt_room_type", "room type": "mmt_room_type",
                "status": "mmt_status",
                "total": "mmt_total_amount", "amount": "mmt_total_amount", "price": "mmt_total_amount",
            })
            if rows:
                return rows

        elif section == "reviews":
            rows = self._extract_table_fields(page, field_keys, {
                "guest": "mmt_rev_guest", "name": "mmt_rev_guest",
                "score": "mmt_rev_score", "rating": "mmt_rev_score",
                "comment": "mmt_rev_comment", "review": "mmt_rev_comment",
                "date": "mmt_rev_date", "time": "mmt_rev_date",
            })
            if rows:
                return rows
            rows = self._extract_card_fields(page, field_keys,
                "[class*='review'], [class*='feedback'], .review-card, [data-review-id]",
                {
                    "mmt_rev_guest": "[class*='name'], [class*='guest'], h3, h4",
                    "mmt_rev_score": "[class*='score'], [class*='rating'], [class*='grade']",
                    "mmt_rev_comment": "[class*='comment'], [class*='review-text'], [class*='text']",
                    "mmt_rev_date": "[class*='date'], [class*='time'], time",
                }
            )
            if rows:
                return rows

        elif section == "financial":
            rows = self._extract_table_fields(page, field_keys, {
                "amount": "mmt_settlement_amt", "settlement": "mmt_settlement_amt",
                "date": "mmt_settlement_date", "settlement date": "mmt_settlement_date",
                "commission": "mmt_commission",
                "tds": "mmt_tds",
                "invoice": "mmt_invoice_no", "number": "mmt_invoice_no",
            })
            if rows:
                return rows

        elif section == "promotions":
            rows = self._extract_table_fields(page, field_keys, {
                "name": "promo_mmt_name", "offer": "promo_mmt_name", "promotion": "promo_mmt_name",
                "type": "promo_mmt_type",
                "discount": "promo_mmt_discount", "%": "promo_mmt_discount",
                "from": "promo_mmt_valid_from", "valid from": "promo_mmt_valid_from",
                "to": "promo_mmt_valid_to", "valid to": "promo_mmt_valid_to",
                "terms": "promo_mmt_conditions", "conditions": "promo_mmt_conditions",
                "status": "promo_mmt_status",
            })
            if rows:
                return rows
            rows = self._extract_card_fields(page, field_keys,
                "[class*='promotion'], [class*='offer'], .promo-card, .offer-card",
                {fk: "." for fk in field_keys}  # Full card text as fallback
            )
            if rows:
                for r in rows:
                    for fk in field_keys:
                        if fk not in r:
                            r[fk] = ""
                return rows

        # Generic fallback
        return self._generic_fallback(page)


# ────────────────────────────────────────────────────────────
#  Goibibo Extranet Source  (shares InGo-MMT platform with MMT)
# ────────────────────────────────────────────────────────────

class GoibiboExtranetSource(ExtranetSource):
    """Goibibo partner extranet via the shared Go-MMT / InGo-MMT platform."""
    source_name = "Goibibo Extranet"
    login_url = "https://partners.go-mmt.com/"

    @property
    def cookies_path(self):
        return GOIBIBO_EXTRANET_COOKIES

    @property
    def available_fields(self):
        return [
            {
                "group": "Reservations / Bookings",
                "section": "reservations",
                "fields": [
                    {"key": "goi_booking_id",     "label": "Booking ID"},
                    {"key": "goi_guest_name",     "label": "Guest Name"},
                    {"key": "goi_check_in",       "label": "Check-in Date"},
                    {"key": "goi_check_out",      "label": "Check-out Date"},
                    {"key": "goi_room_type",      "label": "Room Type"},
                    {"key": "goi_status",         "label": "Booking Status"},
                    {"key": "goi_total_amount",   "label": "Total Amount"},
                    {"key": "goi_payment_mode",   "label": "Payment Mode"},
                    {"key": "goi_contact",        "label": "Guest Contact"},
                ]
            },
            {
                "group": "Property Details",
                "section": "property",
                "fields": [
                    {"key": "goi_prop_name",      "label": "Property Name"},
                    {"key": "goi_prop_desc",      "label": "Description"},
                    {"key": "goi_amenities",      "label": "Amenities"},
                    {"key": "goi_room_inventory", "label": "Room Inventory / Rates"},
                    {"key": "goi_prop_images",    "label": "Property Images"},
                ]
            },
            {
                "group": "Reviews",
                "section": "reviews",
                "fields": [
                    {"key": "goi_rev_guest",      "label": "Guest Name"},
                    {"key": "goi_rev_score",      "label": "Rating / Score"},
                    {"key": "goi_rev_comment",    "label": "Review Comment"},
                    {"key": "goi_rev_date",       "label": "Review Date"},
                    {"key": "goi_rev_response",   "label": "Your Response"},
                ]
            },
            {
                "group": "Financial / Settlement",
                "section": "financial",
                "fields": [
                    {"key": "goi_settlement_amt", "label": "Settlement Amount"},
                    {"key": "goi_settlement_date","label": "Settlement Date"},
                    {"key": "goi_commission",     "label": "Commission"},
                    {"key": "goi_tds",            "label": "TDS"},
                    {"key": "goi_invoice_no",     "label": "Invoice Number"},
                    {"key": "goi_payout_status",   "label": "Payout Status"},
                ]
            },
            {
                "group": "Reports / Analytics",
                "section": "reports",
                "fields": [
                    {"key": "goi_rpt_occupancy",  "label": "Occupancy Rate"},
                    {"key": "goi_rpt_revenue",    "label": "Revenue Summary"},
                    {"key": "goi_rpt_avg_rate",   "label": "Average Daily Rate (ADR)"},
                    {"key": "goi_rpt_revpar",     "label": "RevPAR"},
                ]
            },
            {
                "group": "Promotions / Offers",
                "section": "promotions",
                "fields": [
                    {"key": "promo_goi_name",       "label": "Offer Name"},
                    {"key": "promo_goi_type",       "label": "Offer Type"},
                    {"key": "promo_goi_discount",   "label": "Discount % / Amount"},
                    {"key": "promo_goi_valid_from", "label": "Valid From"},
                    {"key": "promo_goi_valid_to",   "label": "Valid To"},
                    {"key": "promo_goi_conditions", "label": "Terms & Conditions"},
                    {"key": "promo_goi_status",     "label": "Status"},
                ]
            },
        ]

    @property
    def multi_tab(self) -> bool:
        return True

    def login(self, page):
        page.goto(self.login_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

    def navigate_to_section(self, page, section_key: str) -> None:
        base = "https://partners.go-mmt.com"
        section_map = {
            "reservations": f"{base}/bookings",
            "property":     f"{base}/property",
            "reviews":      f"{base}/reviews",
            "financial":    f"{base}/settlement",
            "reports":      f"{base}/reports/analytics",
            "promotions":   f"{base}/promotions",
        }
        url = section_map.get(section_key, base)
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

    def _detect_section(self, field_keys: list[str]) -> str:
        """Determine which Goibibo section we're on by field key prefix."""
        for key in field_keys:
            if key.startswith("promo_goi"):
                return "promotions"
            if key.startswith("goi_rpt"):
                return "reports"
            if key.startswith("goi_rev"):
                return "reviews"
            if key.startswith("goi_settlement") or key.startswith("goi_commission") or key.startswith("goi_tds") or key.startswith("goi_invoice") or key.startswith("goi_payout"):
                return "financial"
            if key.startswith("goi_prop") or key.startswith("goi_amenities") or key.startswith("goi_room"):
                return "property"
            if key.startswith("goi"):
                return "reservations"
        return "general"

    def _extract_goi_property_fields(self, page, field_keys: list[str]) -> dict:
        """Extract Goibibo Property Details fields."""
        row = {}
        if "goi_prop_name" in field_keys:
            val = self._try_selectors(page, [
                "h1", "h2", "input[name*='name']", "input[id*='name']",
                "[class*='property-name']", "[class*='hotel-name']",
                "[class*='page-title']", "[class*='headline']",
            ])
            if not val:
                try:
                    val = page.evaluate("document.title").strip()
                    for suf in [" - Goibibo", " | Goibibo", " - Go-MMT"]:
                        if val.endswith(suf):
                            val = val[:-len(suf)].strip()
                            break
                except Exception:
                    pass
            row["goi_prop_name"] = val or ""
        if "goi_prop_desc" in field_keys:
            val = self._try_selectors(page, [
                "textarea[name*='description']", "textarea[id*='description']",
                "[class*='description']", ".editor-content",
            ])
            if not val:
                val = self._extract_value_by_label(page, "Description")
            row["goi_prop_desc"] = val or ""
        if "goi_amenities" in field_keys:
            val = self._try_selectors(page, [
                "[class*='amenity']", "[class*='facilities']", ".amenities-list",
            ])
            row["goi_amenities"] = val or ""
        if "goi_room_inventory" in field_keys:
            val = self._try_selectors(page, ["[class*='room']", "[class*='inventory']", "table"])
            row["goi_room_inventory"] = val or ""
        if "goi_prop_images" in field_keys:
            urls = page.evaluate("""() => {
                const imgs = document.querySelectorAll('img[src*="property"], img[class*="photo"], img[class*="gallery"]');
                return Array.from(new Set(Array.from(imgs).map(i => i.getAttribute('src') || i.getAttribute('data-src') || '').filter(s => s))).join('; ');
            }""")
            row["goi_prop_images"] = urls or ""
        return row

    def extract_data(self, page, selected_fields: list[dict]) -> list[dict]:
        """Extract rows from the currently loaded Go-MMT partner portal page.
        Routes to section-specific extraction based on field key prefixes.
        """
        field_keys = [f["key"] for f in selected_fields]
        section = self._detect_section(field_keys)

        if section == "property":
            row = self._extract_goi_property_fields(page, field_keys)
            if any(row.values()):
                return [row]

        elif section == "reservations":
            rows = self._extract_table_fields(page, field_keys, {
                "booking": "goi_booking_id", "id": "goi_booking_id", "confirmation": "goi_booking_id",
                "guest": "goi_guest_name", "name": "goi_guest_name",
                "check-in": "goi_check_in", "check in": "goi_check_in", "arrival": "goi_check_in",
                "check-out": "goi_check_out", "check out": "goi_check_out", "departure": "goi_check_out",
                "room": "goi_room_type", "room type": "goi_room_type",
                "status": "goi_status",
                "total": "goi_total_amount", "amount": "goi_total_amount", "price": "goi_total_amount",
                "payment": "goi_payment_mode", "mode": "goi_payment_mode",
                "contact": "goi_contact", "phone": "goi_contact", "mobile": "goi_contact",
            })
            if rows:
                return rows

        elif section == "reviews":
            rows = self._extract_table_fields(page, field_keys, {
                "guest": "goi_rev_guest", "name": "goi_rev_guest",
                "score": "goi_rev_score", "rating": "goi_rev_score",
                "comment": "goi_rev_comment", "review": "goi_rev_comment",
                "date": "goi_rev_date", "time": "goi_rev_date",
                "response": "goi_rev_response", "reply": "goi_rev_response",
            })
            if rows:
                return rows
            rows = self._extract_card_fields(page, field_keys,
                "[class*='review'], [class*='feedback'], .review-card",
                {
                    "goi_rev_guest": "[class*='name'], [class*='guest'], h3, h4",
                    "goi_rev_score": "[class*='score'], [class*='rating']",
                    "goi_rev_comment": "[class*='comment'], [class*='review-text']",
                    "goi_rev_date": "[class*='date'], [class*='time'], time",
                    "goi_rev_response": "[class*='response'], [class*='reply']",
                }
            )
            if rows:
                return rows

        elif section == "financial":
            rows = self._extract_table_fields(page, field_keys, {
                "amount": "goi_settlement_amt", "settlement": "goi_settlement_amt",
                "date": "goi_settlement_date", "settlement date": "goi_settlement_date",
                "commission": "goi_commission",
                "tds": "goi_tds",
                "invoice": "goi_invoice_no", "number": "goi_invoice_no",
                "status": "goi_payout_status", "payout status": "goi_payout_status",
            })
            if rows:
                return rows

        elif section == "reports":
            rows = self._extract_table_fields(page, field_keys, {
                "occupancy": "goi_rpt_occupancy",
                "revenue": "goi_rpt_revenue",
                "average daily rate": "goi_rpt_avg_rate", "adr": "goi_rpt_avg_rate", "avg rate": "goi_rpt_avg_rate",
                "revpar": "goi_rpt_revpar",
            })
            if rows:
                return rows
            rows = self._extract_metric_cards(page, field_keys, {
                "occupancy": "goi_rpt_occupancy",
                "revenue": "goi_rpt_revenue",
                "average daily rate": "goi_rpt_avg_rate", "adr": "goi_rpt_avg_rate",
                "revpar": "goi_rpt_revpar",
            })
            if rows:
                return rows

        elif section == "promotions":
            rows = self._extract_table_fields(page, field_keys, {
                "name": "promo_goi_name", "offer": "promo_goi_name", "promotion": "promo_goi_name",
                "type": "promo_goi_type",
                "discount": "promo_goi_discount", "%": "promo_goi_discount",
                "from": "promo_goi_valid_from", "valid from": "promo_goi_valid_from",
                "to": "promo_goi_valid_to", "valid to": "promo_goi_valid_to",
                "terms": "promo_goi_conditions", "conditions": "promo_goi_conditions",
                "status": "promo_goi_status",
            })
            if rows:
                return rows

        return self._generic_fallback(page)


# ────────────────────────────────────────────────────────────
#  Agoda (YCS) Extranet Source
# ────────────────────────────────────────────────────────────

class AgodaExtranetSource(ExtranetSource):
    """Agoda YCS (Yield Control System) — the extranet for Agoda hotel partners."""
    source_name = "Agoda (YCS) Extranet"
    login_url = "https://ycs.agoda.com/"

    @property
    def cookies_path(self):
        return AGODA_EXTRANET_COOKIES

    @property
    def multi_tab(self) -> bool:
        return True

    @property
    def available_fields(self):
        return [
            {
                "group": "Reservations / Bookings",
                "section": "reservations",
                "fields": [
                    {"key": "agd_booking_id",      "label": "Booking ID"},
                    {"key": "agd_guest_name",      "label": "Guest Name"},
                    {"key": "agd_check_in",        "label": "Check-in Date"},
                    {"key": "agd_check_out",       "label": "Check-out Date"},
                    {"key": "agd_room_type",       "label": "Room Type"},
                    {"key": "agd_status",          "label": "Booking Status"},
                    {"key": "agd_total_amount",    "label": "Total Amount"},
                    {"key": "agd_currency",        "label": "Currency"},
                    {"key": "agd_cancel_policy",   "label": "Cancellation Policy"},
                ]
            },
            {
                "group": "Property Details / Rates",
                "section": "property",
                "fields": [
                    {"key": "agd_prop_name",       "label": "Property Name"},
                    {"key": "agd_room_types",      "label": "Room Types"},
                    {"key": "agd_rate_plans",      "label": "Rate Plans"},
                    {"key": "agd_amenities",       "label": "Amenities"},
                    {"key": "agd_policies",        "label": "Property Policies"},
                    {"key": "agd_photos",          "label": "Photo URLs"},
                ]
            },
            {
                "group": "Reviews",
                "section": "reviews",
                "fields": [
                    {"key": "agd_rev_guest",       "label": "Guest Name"},
                    {"key": "agd_rev_score",       "label": "Review Score"},
                    {"key": "agd_rev_comment",     "label": "Review Comment"},
                    {"key": "agd_rev_response",    "label": "Your Response"},
                    {"key": "agd_rev_date",        "label": "Review Date"},
                    {"key": "agd_rev_language",    "label": "Language"},
                ]
            },
            {
                "group": "Financial / Payouts",
                "section": "financial",
                "fields": [
                    {"key": "agd_payout_amount",   "label": "Payout Amount"},
                    {"key": "agd_payout_date",     "label": "Payout Date"},
                    {"key": "agd_commission",      "label": "Commission"},
                    {"key": "agd_invoice_id",      "label": "Invoice ID"},
                    {"key": "agd_txn_id",          "label": "Transaction ID"},
                    {"key": "agd_payment_status",  "label": "Payment Status"},
                ]
            },
            {
                "group": "Promotions / Offers",
                "section": "promotions",
                "fields": [
                    {"key": "promo_agd_name",       "label": "Promotion Name"},
                    {"key": "promo_agd_type",       "label": "Promotion Type"},
                    {"key": "promo_agd_discount",   "label": "Discount % / Amount"},
                    {"key": "promo_agd_valid_from", "label": "Valid From"},
                    {"key": "promo_agd_valid_to",   "label": "Valid To"},
                    {"key": "promo_agd_conditions", "label": "Terms & Conditions"},
                    {"key": "promo_agd_status",     "label": "Status"},
                ]
            },
        ]

    def login(self, page):
        page.goto(self.login_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

    def navigate_to_section(self, page, section_key: str) -> None:
        base = "https://ycs.agoda.com"
        section_map = {
            "reservations": f"{base}/en-us/manage-reservations",
            "property":     f"{base}/en-us/property",
            "reviews":      f"{base}/en-us/reviews",
            "financial":    f"{base}/en-us/financial",
            "promotions":   f"{base}/en-us/promotions",
        }
        url = section_map.get(section_key, base)
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

    def _detect_section(self, field_keys: list[str]) -> str:
        """Determine which Agoda YCS section we're on by field key prefix."""
        for key in field_keys:
            if key.startswith("promo_agd"):
                return "promotions"
            if key.startswith("agd_rev"):
                return "reviews"
            if key.startswith("agd_prop") or key.startswith("agd_room") or key.startswith("agd_rate") or key.startswith("agd_amenities") or key.startswith("agd_policies") or key.startswith("agd_photos"):
                return "property"
            if key.startswith("agd_payout") or key.startswith("agd_commission") or key.startswith("agd_invoice") or key.startswith("agd_txn") or key.startswith("agd_payment"):
                return "financial"
            if key.startswith("agd"):
                return "reservations"
        return "general"

    def _extract_agd_property_fields(self, page, field_keys: list[str]) -> dict:
        """Extract Agoda YCS Property Details fields."""
        row = {}
        if "agd_prop_name" in field_keys:
            val = self._try_selectors(page, [
                "h1", "h2", "input[name*='name']", "input[id*='name']",
                "[class*='property-name']", "[class*='hotel-name']",
                "[class*='page-title']", "[class*='headline']",
                ".ycs-header-title", "[class*='ycs-'] h1",
            ])
            if not val:
                try:
                    val = page.evaluate("document.title").strip()
                    for suf in [" - Agoda", " | Agoda", " - YCS", " - Agoda YCS"]:
                        if val.endswith(suf):
                            val = val[:-len(suf)].strip()
                            break
                except Exception:
                    pass
            row["agd_prop_name"] = val or ""
        if "agd_room_types" in field_keys:
            val = self._try_selectors(page, [
                "[class*='room-type']", "[class*='roomtype']", "[class*='room'] h3", "[class*='room'] h4",
            ])
            if not val:
                val = self._extract_value_by_label(page, "Room Types")
            row["agd_room_types"] = val or ""
        if "agd_rate_plans" in field_keys:
            val = self._try_selectors(page, [
                "[class*='rate-plan']", "[class*='rateplan']", "table",
            ])
            row["agd_rate_plans"] = val or ""
        if "agd_amenities" in field_keys:
            val = self._try_selectors(page, ["[class*='amenity']", "[class*='facilities']", ".amenities-list"])
            row["agd_amenities"] = val or ""
        if "agd_policies" in field_keys:
            val = self._try_selectors(page, ["[class*='policy']", "[class*='policy-section']"])
            if not val:
                val = self._extract_value_by_label(page, "Policies")
            row["agd_policies"] = val or ""
        if "agd_photos" in field_keys:
            urls = page.evaluate("""() => {
                const imgs = document.querySelectorAll('img[class*="photo"], img[class*="gallery"], [class*="photo"] img');
                return Array.from(new Set(Array.from(imgs).map(i => i.getAttribute('src') || i.getAttribute('data-src') || '').filter(s => s))).join('; ');
            }""")
            row["agd_photos"] = urls or ""
        return row

    def extract_data(self, page, selected_fields: list[dict]) -> list[dict]:
        """Extract rows from the currently loaded Agoda YCS page.
        Routes to section-specific extraction based on field key prefixes.
        """
        field_keys = [f["key"] for f in selected_fields]
        section = self._detect_section(field_keys)

        if section == "property":
            row = self._extract_agd_property_fields(page, field_keys)
            if any(row.values()):
                return [row]

        elif section == "reservations":
            rows = self._extract_table_fields(page, field_keys, {
                "booking": "agd_booking_id", "id": "agd_booking_id", "confirmation": "agd_booking_id",
                "guest": "agd_guest_name", "name": "agd_guest_name",
                "check-in": "agd_check_in", "check in": "agd_check_in", "arrival": "agd_check_in",
                "check-out": "agd_check_out", "check out": "agd_check_out", "departure": "agd_check_out",
                "room": "agd_room_type", "room type": "agd_room_type",
                "status": "agd_status",
                "total": "agd_total_amount", "amount": "agd_total_amount", "price": "agd_total_amount",
                "currency": "agd_currency",
                "cancel": "agd_cancel_policy", "cancellation": "agd_cancel_policy",
            })
            if rows:
                return rows

        elif section == "reviews":
            rows = self._extract_table_fields(page, field_keys, {
                "guest": "agd_rev_guest", "name": "agd_rev_guest",
                "score": "agd_rev_score", "rating": "agd_rev_score",
                "comment": "agd_rev_comment", "review": "agd_rev_comment",
                "response": "agd_rev_response", "reply": "agd_rev_response",
                "date": "agd_rev_date", "time": "agd_rev_date",
                "language": "agd_rev_language", "lang": "agd_rev_language",
            })
            if rows:
                return rows
            rows = self._extract_card_fields(page, field_keys,
                "[class*='review'], .review-card, .guest-review, [data-review-id]",
                {
                    "agd_rev_guest": "[class*='name'], [class*='guest'], h3, h4",
                    "agd_rev_score": "[class*='score'], [class*='rating']",
                    "agd_rev_comment": "[class*='comment'], [class*='review-text']",
                    "agd_rev_date": "[class*='date'], [class*='time'], time",
                    "agd_rev_response": "[class*='response'], [class*='reply']",
                    "agd_rev_language": "[class*='language'], [class*='lang']",
                }
            )
            if rows:
                return rows

        elif section == "financial":
            rows = self._extract_table_fields(page, field_keys, {
                "amount": "agd_payout_amount", "payout": "agd_payout_amount",
                "date": "agd_payout_date", "payout date": "agd_payout_date",
                "commission": "agd_commission",
                "invoice": "agd_invoice_id", "id": "agd_invoice_id",
                "transaction": "agd_txn_id", "txn": "agd_txn_id",
                "status": "agd_payment_status", "payment": "agd_payment_status",
            })
            if rows:
                return rows

        elif section == "promotions":
            rows = self._extract_table_fields(page, field_keys, {
                "name": "promo_agd_name", "promotion": "promo_agd_name", "offer": "promo_agd_name",
                "type": "promo_agd_type",
                "discount": "promo_agd_discount", "%": "promo_agd_discount",
                "from": "promo_agd_valid_from", "valid from": "promo_agd_valid_from",
                "to": "promo_agd_valid_to", "valid to": "promo_agd_valid_to",
                "terms": "promo_agd_conditions", "conditions": "promo_agd_conditions",
                "status": "promo_agd_status",
            })
            if rows:
                return rows

        return self._generic_fallback(page)


# ────────────────────────────────────────────────────────────
#  Expedia Partner Central Source
# ────────────────────────────────────────────────────────────

class ExpediaExtranetSource(ExtranetSource):
    """Expedia Partner Central (EPC) — the extranet for Expedia Group hotel partners.
    Manages listings across Expedia, Hotels.com, Vrbo, Orbitz, Travelocity, and more.
    """
    source_name = "Expedia Partner Central"
    login_url = "https://expediapartnercentral.com/"

    @property
    def cookies_path(self):
        return EXPEDIA_EXTRANET_COOKIES

    @property
    def multi_tab(self) -> bool:
        return True

    @property
    def available_fields(self):
        return [
            {
                "group": "Reservations / Bookings",
                "section": "reservations",
                "fields": [
                    {"key": "exp_booking_id",      "label": "Booking / Itinerary ID"},
                    {"key": "exp_guest_name",      "label": "Guest Name"},
                    {"key": "exp_check_in",        "label": "Check-in Date"},
                    {"key": "exp_check_out",       "label": "Check-out Date"},
                    {"key": "exp_room_type",       "label": "Room Type"},
                    {"key": "exp_status",          "label": "Booking Status"},
                    {"key": "exp_total_charged",   "label": "Total Charged"},
                    {"key": "exp_source",          "label": "Booking Source (Expedia / Hotels.com / etc.)"},
                    {"key": "exp_cancel_policy",    "label": "Cancellation Policy"},
                ]
            },
            {
                "group": "Property Details / Rates",
                "section": "property",
                "fields": [
                    {"key": "exp_prop_name",       "label": "Property Name"},
                    {"key": "exp_prop_desc",       "label": "Description"},
                    {"key": "exp_room_types",      "label": "Room Types"},
                    {"key": "exp_rate_plans",      "label": "Rate Plans"},
                    {"key": "exp_amenities",       "label": "Amenities"},
                    {"key": "exp_policies",        "label": "Property Policies"},
                    {"key": "exp_photos",          "label": "Photo URLs"},
                ]
            },
            {
                "group": "Reviews & Guest Feedback",
                "section": "reviews",
                "fields": [
                    {"key": "exp_rev_guest",       "label": "Guest Name"},
                    {"key": "exp_rev_score",       "label": "Overall Rating"},
                    {"key": "exp_rev_comment",     "label": "Review Comment"},
                    {"key": "exp_rev_response",    "label": "Your Response"},
                    {"key": "exp_rev_date",        "label": "Review Date"},
                    {"key": "exp_rev_cleanliness", "label": "Cleanliness Score"},
                    {"key": "exp_rev_service",     "label": "Service Score"},
                ]
            },
            {
                "group": "Financial / Payouts",
                "section": "financial",
                "fields": [
                    {"key": "exp_payout_amount",   "label": "Payout Amount"},
                    {"key": "exp_payout_date",     "label": "Payout Date"},
                    {"key": "exp_commission",      "label": "Commission"},
                    {"key": "exp_invoice_id",      "label": "Invoice / Statement ID"},
                    {"key": "exp_transaction_fee", "label": "Transaction Fee"},
                    {"key": "exp_payout_status",    "label": "Payout Status"},
                ]
            },
            {
                "group": "Promotions / Offers",
                "section": "promotions",
                "fields": [
                    {"key": "promo_exp_name",        "label": "Promotion Name"},
                    {"key": "promo_exp_type",        "label": "Promotion Type"},
                    {"key": "promo_exp_discount",    "label": "Discount % / Amount"},
                    {"key": "promo_exp_valid_from",  "label": "Valid From"},
                    {"key": "promo_exp_valid_to",    "label": "Valid To"},
                    {"key": "promo_exp_conditions",  "label": "Terms & Conditions"},
                    {"key": "promo_exp_status",      "label": "Status"},
                ]
            },
            {
                "group": "Competitive Insights",
                "section": "insights",
                "fields": [
                    {"key": "exp_ci_occupancy",      "label": "Occupancy Rate"},
                    {"key": "exp_ci_avg_rate",       "label": "Average Daily Rate (ADR)"},
                    {"key": "exp_ci_revpar",         "label": "RevPAR"},
                    {"key": "exp_ci_market_position", "label": "Market Position"},
                ]
            },
        ]

    def login(self, page):
        page.goto(self.login_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

    def navigate_to_section(self, page, section_key: str) -> None:
        base = "https://expediapartnercentral.com"
        section_map = {
            "reservations": f"{base}/reservations",
            "property":     f"{base}/property",
            "reviews":      f"{base}/reviews",
            "financial":    f"{base}/financial",
            "promotions":   f"{base}/promotions",
            "insights":     f"{base}/insights",
        }
        url = section_map.get(section_key, base)
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

    def _detect_section(self, field_keys: list[str]) -> str:
        """Determine which Expedia Partner Central section we're on."""
        for key in field_keys:
            if key.startswith("exp_ci"):
                return "insights"
            if key.startswith("promo_exp"):
                return "promotions"
            if key.startswith("exp_rev"):
                return "reviews"
            if key.startswith("exp_prop"):
                return "property"
            if key.startswith("exp"):
                return "reservations"
        return "general"

    def _extract_exp_property_fields(self, page, field_keys: list[str]) -> dict:
        """Extract Expedia Property Details fields."""
        row = {}
        if "exp_prop_name" in field_keys:
            val = self._try_selectors(page, [
                "h1", "h2", "input[name*='name']", "input[id*='name']",
                "[class*='property-name']", "[class*='hotel-name']",
                "[class*='page-title']", "[class*='headline']",
                ".epc-header-title", "[class*='epc-'] h1",
            ])
            if not val:
                try:
                    val = page.evaluate("document.title").strip()
                    for suf in [" - Expedia Partner Central", " | Expedia", " - Expedia", " - EPC"]:
                        if val.endswith(suf):
                            val = val[:-len(suf)].strip()
                            break
                except Exception:
                    pass
            row["exp_prop_name"] = val or ""
        if "exp_prop_desc" in field_keys:
            val = self._try_selectors(page, [
                "textarea[name*='description']", "textarea[id*='description']",
                "[class*='description']", ".editor-content",
            ])
            if not val:
                val = self._extract_value_by_label(page, "Description")
            row["exp_prop_desc"] = val or ""
        if "exp_room_types" in field_keys:
            val = self._try_selectors(page, [
                "[class*='room-type']", "[class*='roomtype']", "[class*='room'] h3",
            ])
            row["exp_room_types"] = val or ""
        if "exp_rate_plans" in field_keys:
            val = self._try_selectors(page, ["[class*='rate-plan']", "[class*='rateplan']", "table"])
            row["exp_rate_plans"] = val or ""
        if "exp_amenities" in field_keys:
            val = self._try_selectors(page, ["[class*='amenity']", "[class*='facilities']", ".amenities-list"])
            row["exp_amenities"] = val or ""
        if "exp_policies" in field_keys:
            val = self._try_selectors(page, ["[class*='policy']", "[class*='policy-section']"])
            if not val:
                val = self._extract_value_by_label(page, "Policies")
            row["exp_policies"] = val or ""
        if "exp_photos" in field_keys:
            urls = page.evaluate("""() => {
                const imgs = document.querySelectorAll('img[class*="photo"], img[class*="gallery"], [class*="photo"] img');
                return Array.from(new Set(Array.from(imgs).map(i => i.getAttribute('src') || i.getAttribute('data-src') || '').filter(s => s))).join('; ');
            }""")
            row["exp_photos"] = urls or ""
        return row

    def extract_data(self, page, selected_fields: list[dict]) -> list[dict]:
        """Extract rows from the currently loaded Expedia Partner Central page.
        Routes to section-specific extraction based on field key prefixes.
        """
        field_keys = [f["key"] for f in selected_fields]
        section = self._detect_section(field_keys)

        if section == "property":
            row = self._extract_exp_property_fields(page, field_keys)
            if any(row.values()):
                return [row]

        elif section == "reservations":
            rows = self._extract_table_fields(page, field_keys, {
                "booking": "exp_booking_id", "id": "exp_booking_id", "itinerary": "exp_booking_id",
                "guest": "exp_guest_name", "name": "exp_guest_name",
                "check-in": "exp_check_in", "check in": "exp_check_in", "arrival": "exp_check_in",
                "check-out": "exp_check_out", "check out": "exp_check_out", "departure": "exp_check_out",
                "room": "exp_room_type", "room type": "exp_room_type",
                "status": "exp_status",
                "charged": "exp_total_charged", "total": "exp_total_charged",
                "source": "exp_source", "brand": "exp_source",
                "cancel": "exp_cancel_policy", "cancellation": "exp_cancel_policy",
            })
            if rows:
                return rows

        elif section == "reviews":
            rows = self._extract_table_fields(page, field_keys, {
                "guest": "exp_rev_guest", "name": "exp_rev_guest",
                "score": "exp_rev_score", "rating": "exp_rev_score", "overall": "exp_rev_score",
                "comment": "exp_rev_comment", "review": "exp_rev_comment",
                "response": "exp_rev_response", "reply": "exp_rev_response",
                "date": "exp_rev_date", "time": "exp_rev_date",
                "cleanliness": "exp_rev_cleanliness", "clean": "exp_rev_cleanliness",
                "service": "exp_rev_service", "staff": "exp_rev_service",
            })
            if rows:
                return rows
            rows = self._extract_card_fields(page, field_keys,
                "[class*='review'], .review-card, .guest-review, [data-review-id]",
                {
                    "exp_rev_guest": "[class*='name'], [class*='guest'], h3, h4",
                    "exp_rev_score": "[class*='score'], [class*='rating']",
                    "exp_rev_comment": "[class*='comment'], [class*='review-text']",
                    "exp_rev_date": "[class*='date'], [class*='time'], time",
                    "exp_rev_response": "[class*='response'], [class*='reply']",
                    "exp_rev_cleanliness": "[class*='cleanliness'], [class*='clean']",
                    "exp_rev_service": "[class*='service']",
                }
            )
            if rows:
                return rows

        elif section == "financial":
            rows = self._extract_table_fields(page, field_keys, {
                "amount": "exp_payout_amount", "payout": "exp_payout_amount",
                "date": "exp_payout_date", "payout date": "exp_payout_date",
                "commission": "exp_commission",
                "invoice": "exp_invoice_id", "statement": "exp_invoice_id", "id": "exp_invoice_id",
                "fee": "exp_transaction_fee", "transaction fee": "exp_transaction_fee",
                "status": "exp_payout_status", "payout status": "exp_payout_status",
            })
            if rows:
                return rows

        elif section == "promotions":
            rows = self._extract_table_fields(page, field_keys, {
                "name": "promo_exp_name", "promotion": "promo_exp_name", "offer": "promo_exp_name",
                "type": "promo_exp_type",
                "discount": "promo_exp_discount", "%": "promo_exp_discount",
                "from": "promo_exp_valid_from", "valid from": "promo_exp_valid_from",
                "to": "promo_exp_valid_to", "valid to": "promo_exp_valid_to",
                "terms": "promo_exp_conditions", "conditions": "promo_exp_conditions",
                "status": "promo_exp_status",
            })
            if rows:
                return rows

        elif section == "insights":
            rows = self._extract_table_fields(page, field_keys, {
                "occupancy": "exp_ci_occupancy",
                "average daily rate": "exp_ci_avg_rate", "adr": "exp_ci_avg_rate", "avg rate": "exp_ci_avg_rate",
                "revpar": "exp_ci_revpar",
                "market": "exp_ci_market_position", "position": "exp_ci_market_position",
            })
            if rows:
                return rows
            rows = self._extract_metric_cards(page, field_keys, {
                "occupancy": "exp_ci_occupancy",
                "average daily rate": "exp_ci_avg_rate", "adr": "exp_ci_avg_rate",
                "revpar": "exp_ci_revpar",
                "market position": "exp_ci_market_position", "market share": "exp_ci_market_position",
            })
            if rows:
                return rows

        return self._generic_fallback(page)


# ────────────────────────────────────────────────────────────
#  Hotels.com Partner Central Source  (same EPC platform as Expedia)
# ────────────────────────────────────────────────────────────

class HotelsExtranetSource(ExtranetSource):
    """Hotels.com Partner Central — shares the Expedia Group Partner Central platform (EPC).
    Hotels.com is part of Expedia Group, so hotel partners manage all Expedia Group
    brands (Expedia, Hotels.com, Vrbo, Orbitz, Travelocity) through the same portal.
    """
    source_name = "Hotels.com Partner Central"
    login_url = "https://expediapartnercentral.com/"

    @property
    def cookies_path(self):
        return EXPEDIA_EXTRANET_COOKIES  # Same platform as Expedia — shared cookies

    @property
    def multi_tab(self) -> bool:
        return True

    @property
    def available_fields(self):
        return [
            {
                "group": "Reservations / Bookings",
                "section": "reservations",
                "fields": [
                    {"key": "htl_booking_id",     "label": "Booking ID"},
                    {"key": "htl_guest_name",     "label": "Guest Name"},
                    {"key": "htl_check_in",       "label": "Check-in Date"},
                    {"key": "htl_check_out",      "label": "Check-out Date"},
                    {"key": "htl_room_type",      "label": "Room Type"},
                    {"key": "htl_status",         "label": "Booking Status"},
                    {"key": "htl_total_charged",  "label": "Total Charged"},
                    {"key": "htl_cancel_policy",  "label": "Cancellation Policy"},
                ]
            },
            {
                "group": "Property Details / Rates",
                "section": "property",
                "fields": [
                    {"key": "htl_prop_name",      "label": "Property Name"},
                    {"key": "htl_prop_desc",      "label": "Description"},
                    {"key": "htl_room_types",     "label": "Room Types"},
                    {"key": "htl_rate_plans",     "label": "Rate Plans"},
                    {"key": "htl_amenities",      "label": "Amenities"},
                    {"key": "htl_policies",       "label": "Policies"},
                    {"key": "htl_photos",         "label": "Photo URLs"},
                ]
            },
            {
                "group": "Reviews & Guest Feedback",
                "section": "reviews",
                "fields": [
                    {"key": "htl_rev_guest",      "label": "Guest Name"},
                    {"key": "htl_rev_score",      "label": "Overall Rating"},
                    {"key": "htl_rev_comment",    "label": "Review Comment"},
                    {"key": "htl_rev_response",   "label": "Your Response"},
                    {"key": "htl_rev_date",       "label": "Review Date"},
                    {"key": "htl_rev_cleanliness","label": "Cleanliness Score"},
                    {"key": "htl_rev_service",    "label": "Service Score"},
                ]
            },
            {
                "group": "Financial / Payouts",
                "section": "financial",
                "fields": [
                    {"key": "htl_payout_amount",  "label": "Payout Amount"},
                    {"key": "htl_payout_date",    "label": "Payout Date"},
                    {"key": "htl_commission",     "label": "Commission"},
                    {"key": "htl_invoice_id",     "label": "Invoice ID"},
                    {"key": "htl_transaction_fee","label": "Transaction Fee"},
                    {"key": "htl_payout_status",  "label": "Payout Status"},
                ]
            },
            {
                "group": "Promotions / Offers",
                "section": "promotions",
                "fields": [
                    {"key": "promo_htl_name",       "label": "Promotion Name"},
                    {"key": "promo_htl_type",       "label": "Promotion Type"},
                    {"key": "promo_htl_discount",   "label": "Discount % / Amount"},
                    {"key": "promo_htl_valid_from", "label": "Valid From"},
                    {"key": "promo_htl_valid_to",   "label": "Valid To"},
                    {"key": "promo_htl_conditions", "label": "Terms & Conditions"},
                    {"key": "promo_htl_status",     "label": "Status"},
                ]
            },
            {
                "group": "Competitive Insights",
                "section": "insights",
                "fields": [
                    {"key": "htl_ci_occupancy",     "label": "Occupancy Rate"},
                    {"key": "htl_ci_avg_rate",      "label": "Average Daily Rate (ADR)"},
                    {"key": "htl_ci_revpar",        "label": "RevPAR"},
                    {"key": "htl_ci_market_position","label": "Market Position"},
                ]
            },
        ]

    def login(self, page):
        page.goto(self.login_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

    def navigate_to_section(self, page, section_key: str) -> None:
        base = "https://expediapartnercentral.com"
        section_map = {
            "reservations": f"{base}/reservations",
            "property":     f"{base}/property",
            "reviews":      f"{base}/reviews",
            "financial":    f"{base}/financial",
            "promotions":   f"{base}/promotions",
            "insights":     f"{base}/insights",
        }
        url = section_map.get(section_key, base)
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

    def _detect_section(self, field_keys: list[str]) -> str:
        """Determine which Hotels.com Partner Central section we're on."""
        for key in field_keys:
            if key.startswith("htl_ci"):
                return "insights"
            if key.startswith("promo_htl"):
                return "promotions"
            if key.startswith("htl_rev"):
                return "reviews"
            if key.startswith("htl_prop"):
                return "property"
            if key.startswith("htl"):
                return "reservations"
        return "general"

    def _extract_htl_property_fields(self, page, field_keys: list[str]) -> dict:
        """Extract Hotels.com Property Details fields."""
        row = {}
        if "htl_prop_name" in field_keys:
            val = self._try_selectors(page, [
                "h1", "h2", "input[name*='name']", "input[id*='name']",
                "[class*='property-name']", "[class*='hotel-name']",
                "[class*='page-title']", "[class*='headline']",
                ".epc-header-title", "[class*='epc-'] h1",
            ])
            if not val:
                try:
                    val = page.evaluate("document.title").strip()
                    for suf in [" - Hotels.com", " | Hotels.com", " - Expedia", " - EPC"]:
                        if val.endswith(suf):
                            val = val[:-len(suf)].strip()
                            break
                except Exception:
                    pass
            row["htl_prop_name"] = val or ""
        if "htl_prop_desc" in field_keys:
            val = self._try_selectors(page, [
                "textarea[name*='description']", "textarea[id*='description']",
                "[class*='description']", ".editor-content",
            ])
            if not val:
                val = self._extract_value_by_label(page, "Description")
            row["htl_prop_desc"] = val or ""
        if "htl_room_types" in field_keys:
            val = self._try_selectors(page, [
                "[class*='room-type']", "[class*='roomtype']", "[class*='room'] h3",
            ])
            row["htl_room_types"] = val or ""
        if "htl_rate_plans" in field_keys:
            val = self._try_selectors(page, ["[class*='rate-plan']", "[class*='rateplan']", "table"])
            row["htl_rate_plans"] = val or ""
        if "htl_amenities" in field_keys:
            val = self._try_selectors(page, ["[class*='amenity']", "[class*='facilities']", ".amenities-list"])
            row["htl_amenities"] = val or ""
        if "htl_policies" in field_keys:
            val = self._try_selectors(page, ["[class*='policy']", "[class*='policy-section']"])
            if not val:
                val = self._extract_value_by_label(page, "Policies")
            row["htl_policies"] = val or ""
        if "htl_photos" in field_keys:
            urls = page.evaluate("""() => {
                const imgs = document.querySelectorAll('img[class*="photo"], img[class*="gallery"], [class*="photo"] img');
                return Array.from(new Set(Array.from(imgs).map(i => i.getAttribute('src') || i.getAttribute('data-src') || '').filter(s => s))).join('; ');
            }""")
            row["htl_photos"] = urls or ""
        return row

    def extract_data(self, page, selected_fields: list[dict]) -> list[dict]:
        """Extract rows from Hotels.com Partner Central (same EPC platform as Expedia).
        Routes to section-specific extraction based on field key prefixes.
        """
        field_keys = [f["key"] for f in selected_fields]
        section = self._detect_section(field_keys)

        if section == "property":
            row = self._extract_htl_property_fields(page, field_keys)
            if any(row.values()):
                return [row]

        elif section == "reservations":
            rows = self._extract_table_fields(page, field_keys, {
                "booking": "htl_booking_id", "id": "htl_booking_id", "itinerary": "htl_booking_id",
                "guest": "htl_guest_name", "name": "htl_guest_name",
                "check-in": "htl_check_in", "check in": "htl_check_in", "arrival": "htl_check_in",
                "check-out": "htl_check_out", "check out": "htl_check_out", "departure": "htl_check_out",
                "room": "htl_room_type", "room type": "htl_room_type",
                "status": "htl_status",
                "charged": "htl_total_charged", "total": "htl_total_charged",
                "cancel": "htl_cancel_policy", "cancellation": "htl_cancel_policy",
            })
            if rows:
                return rows

        elif section == "reviews":
            rows = self._extract_table_fields(page, field_keys, {
                "guest": "htl_rev_guest", "name": "htl_rev_guest",
                "score": "htl_rev_score", "rating": "htl_rev_score", "overall": "htl_rev_score",
                "comment": "htl_rev_comment", "review": "htl_rev_comment",
                "response": "htl_rev_response", "reply": "htl_rev_response",
                "date": "htl_rev_date", "time": "htl_rev_date",
                "cleanliness": "htl_rev_cleanliness", "clean": "htl_rev_cleanliness",
                "service": "htl_rev_service", "staff": "htl_rev_service",
            })
            if rows:
                return rows
            rows = self._extract_card_fields(page, field_keys,
                "[class*='review'], .review-card, .guest-review, [data-review-id]",
                {
                    "htl_rev_guest": "[class*='name'], [class*='guest'], h3, h4",
                    "htl_rev_score": "[class*='score'], [class*='rating']",
                    "htl_rev_comment": "[class*='comment'], [class*='review-text']",
                    "htl_rev_date": "[class*='date'], [class*='time'], time",
                    "htl_rev_response": "[class*='response'], [class*='reply']",
                    "htl_rev_cleanliness": "[class*='cleanliness'], [class*='clean']",
                    "htl_rev_service": "[class*='service']",
                }
            )
            if rows:
                return rows

        elif section == "financial":
            rows = self._extract_table_fields(page, field_keys, {
                "amount": "htl_payout_amount", "payout": "htl_payout_amount",
                "date": "htl_payout_date", "payout date": "htl_payout_date",
                "commission": "htl_commission",
                "invoice": "htl_invoice_id", "id": "htl_invoice_id",
                "fee": "htl_transaction_fee", "transaction fee": "htl_transaction_fee",
                "status": "htl_payout_status", "payout status": "htl_payout_status",
            })
            if rows:
                return rows

        elif section == "promotions":
            rows = self._extract_table_fields(page, field_keys, {
                "name": "promo_htl_name", "promotion": "promo_htl_name", "offer": "promo_htl_name",
                "type": "promo_htl_type",
                "discount": "promo_htl_discount", "%": "promo_htl_discount",
                "from": "promo_htl_valid_from", "valid from": "promo_htl_valid_from",
                "to": "promo_htl_valid_to", "valid to": "promo_htl_valid_to",
                "terms": "promo_htl_conditions", "conditions": "promo_htl_conditions",
                "status": "promo_htl_status",
            })
            if rows:
                return rows

        elif section == "insights":
            rows = self._extract_table_fields(page, field_keys, {
                "occupancy": "htl_ci_occupancy",
                "average daily rate": "htl_ci_avg_rate", "adr": "htl_ci_avg_rate", "avg rate": "htl_ci_avg_rate",
                "revpar": "htl_ci_revpar",
                "market": "htl_ci_market_position", "position": "htl_ci_market_position",
            })
            if rows:
                return rows
            rows = self._extract_metric_cards(page, field_keys, {
                "occupancy": "htl_ci_occupancy",
                "average daily rate": "htl_ci_avg_rate", "adr": "htl_ci_avg_rate",
                "revpar": "htl_ci_revpar",
                "market position": "htl_ci_market_position", "market share": "htl_ci_market_position",
            })
            if rows:
                return rows

        return self._generic_fallback(page)


# ───────────────────────────────────────────────────────────
#  Source registry — add new sources here
# ───────────────────────────────────────────────────────────

EXTRANET_SOURCES: dict[str, ExtranetSource] = {
    "booking_extranet": BookingExtranetSource(),
    "mmt_extranet":     MMTExtranetSource(),
    "goibibo_extranet": GoibiboExtranetSource(),
    "agoda_extranet":   AgodaExtranetSource(),
    "expedia_extranet": ExpediaExtranetSource(),
    "hotels_extranet":  HotelsExtranetSource(),
}


# ────────────────────────────────────────────────────────────
#  Config system
# ────────────────────────────────────────────────────────────

class ScrapeJob:
    """A single scrape job configuration — serializable to/from JSON."""

    def __init__(self, source_key: str = "", selected_fields: list[dict] = None,
                 label: str = "", output_path: str = ""):
        self.source_key = source_key
        self.selected_fields = selected_fields or []
        self.label = label or f"Scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.output_path = output_path or ""

    def to_dict(self) -> dict:
        return {
            "source": self.source_key,
            "label": self.label,
            "output_path": self.output_path,
            "fields": [
                {"key": f["key"], "label": f.get("label", f["key"])}
                for f in self.selected_fields
            ],
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            source_key=data.get("source", ""),
            selected_fields=data.get("fields", []),
            label=data.get("label", ""),
            output_path=data.get("output_path", ""),
        )

    @classmethod
    def from_file(cls, path: str):
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def to_file(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def display_summary(self) -> str:
        source = EXTRANET_SOURCES.get(self.source_key)
        name = source.source_name if source else self.source_key
        field_labels = [f.get("label", f["key"]) for f in self.selected_fields]
        return f"[{name}]  {len(field_labels)} fields: {', '.join(field_labels[:5])}{'...' if len(field_labels) > 5 else ''}"


# ────────────────────────────────────────────────────────────
#  SQLite-based Scrape History and Progress Auto-Save Manager
# ────────────────────────────────────────────────────────────

class ScrapeHistoryManager:
    DB_PATH = COOKIES_DIR / "scrape_history.db"

    @classmethod
    def init_db(cls):
        """Initialize the SQLite database schema."""
        conn = sqlite3.connect(str(cls.DB_PATH))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scrape_sessions (
                id TEXT PRIMARY KEY,
                timestamp TEXT,
                platform TEXT,
                source_key TEXT,
                fields TEXT,
                output_path TEXT,
                status TEXT,
                total_properties INTEGER,
                processed_properties INTEGER,
                total_rows INTEGER
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scraped_properties (
                session_id TEXT,
                hotel_id TEXT,
                hotel_name TEXT,
                status TEXT,
                rows_count INTEGER,
                timestamp TEXT,
                PRIMARY KEY (session_id, hotel_id)
            )
        """)
        conn.commit()
        conn.close()

    @classmethod
    def create_session(cls, session_id: str, platform: str, source_key: str, fields: list[dict], output_path: str):
        cls.init_db()
        conn = sqlite3.connect(str(cls.DB_PATH))
        cursor = conn.cursor()
        fields_json = json.dumps(fields)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT OR REPLACE INTO scrape_sessions 
            (id, timestamp, platform, source_key, fields, output_path, status, total_properties, processed_properties, total_rows)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (session_id, timestamp, platform, source_key, fields_json, output_path, "Running", 0, 0, 0))
        conn.commit()
        conn.close()

    @classmethod
    def update_session_counts(cls, session_id: str, total_properties: int):
        conn = sqlite3.connect(str(cls.DB_PATH))
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE scrape_sessions 
            SET total_properties = ?
            WHERE id = ?
        """, (total_properties, session_id))
        conn.commit()
        conn.close()

    @classmethod
    def add_scraped_property(cls, session_id: str, hotel_id: str, hotel_name: str, status: str, rows_count: int):
        cls.init_db()
        conn = sqlite3.connect(str(cls.DB_PATH))
        cursor = conn.cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT OR REPLACE INTO scraped_properties 
            (session_id, hotel_id, hotel_name, status, rows_count, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, hotel_id, hotel_name, status, rows_count, timestamp))
        
        # Update processed count and total rows in session
        cursor.execute("""
            SELECT COUNT(*), SUM(rows_count) FROM scraped_properties
            WHERE session_id = ? AND (status = 'Completed' OR rows_count > 0)
        """, (session_id,))
        processed, total_rows = cursor.fetchone()
        
        cursor.execute("""
            UPDATE scrape_sessions 
            SET processed_properties = ?, total_rows = ?
            WHERE id = ?
        """, (processed or 0, total_rows or 0, session_id))
        
        conn.commit()
        conn.close()

    @classmethod
    def complete_session(cls, session_id: str, status: str = "Completed"):
        cls.init_db()
        conn = sqlite3.connect(str(cls.DB_PATH))
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE scrape_sessions 
            SET status = ?
            WHERE id = ?
        """, (status, session_id))
        conn.commit()
        conn.close()

    @classmethod
    def get_completed_properties(cls, session_id: str) -> set[str]:
        """Get set of hotel_ids already successfully scraped in this session."""
        cls.init_db()
        conn = sqlite3.connect(str(cls.DB_PATH))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT hotel_id FROM scraped_properties
            WHERE session_id = ? AND status = 'Completed'
        """, (session_id,))
        rows = cursor.fetchall()
        conn.close()
        return {r[0] for r in rows}

    @classmethod
    def get_session(cls, session_id: str) -> dict:
        cls.init_db()
        conn = sqlite3.connect(str(cls.DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM scrape_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        result = dict(row) if row else {}
        conn.close()
        return result

    @classmethod
    def get_history(cls) -> list[dict]:
        """Fetch all sessions ordered by timestamp descending."""
        cls.init_db()
        conn = sqlite3.connect(str(cls.DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM scrape_sessions ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        result = [dict(r) for r in rows]
        conn.close()
        return result


# ────────────────────────────────────────────────────────────
#  Scrape engine (runs a job in a background thread)
# ────────────────────────────────────────────────────────────

class ExtranetScrapeWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str, int)
    log_msg = pyqtSignal(str)
    login_required = pyqtSignal(str)

    def __init__(self, job: ScrapeJob, session_id: str = None):
        super().__init__()
        self.job = job
        self._stop = False
        self.login_event = threading.Event()
        self.session_id = session_id or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.is_resume = session_id is not None

    def stop(self):
        self._stop = True

    def run(self):
        source = EXTRANET_SOURCES.get(self.job.source_key)
        if not source:
            self.log_msg.emit(f"Unknown source: {self.job.source_key}")
            self.finished.emit("", 0)
            return

        source_name = source.source_name
        output_path = self.job.output_path or str(
            Path.home() / "Downloads" / f"{self.job.label}.csv"
        )
        
        # Set attributes on source singleton immediately (early initialization)
        source.output_path = output_path
        source.session_id = self.session_id
        source.job = self.job
        source.worker = self

        # Initialize or update session in SQLite history
        selected_field_keys = self.job.selected_fields
        if not self.is_resume:
            ScrapeHistoryManager.create_session(
                self.session_id, source_name, self.job.source_key, selected_field_keys, output_path
            )
        else:
            ScrapeHistoryManager.complete_session(self.session_id, "Running")

        # Prepare CSV file and headers in real-time mode
        field_keys = [f["key"] for f in self.job.selected_fields]
        ordered_keys = field_keys + ["hotel_id", "hotel_name", "_source", "_error"]
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        file_exists = os.path.exists(output_path) and os.path.getsize(output_path) > 0
        if not file_exists:
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(ordered_keys)

        self.log_msg.emit(f"Starting scrape from {source_name}")
        self.progress.emit(0, 1, "Launching browser...")

        try:
            pw = sync_playwright().start()
            # Use launch_persistent_context to safely maintain logins/profile persistent state
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(COOKIES_DIR / 'chrome_extranet'),
                headless=False,
                channel="chrome",
                args=[
                    f"--remote-debugging-port={EXTRANET_DEBUG_PORT}",
                    "--no-first-run",
                    "--window-size=1280,900",
                ]
            )
            page = context.pages[0] if context.pages else context.new_page()
            
            # Singleton attributes already early-initialized at start of run()
            pass

            # ── Login (if needed) ──────────────────────────
            cookies_path = source.cookies_path
            if cookies_path and cookies_path.exists():
                with open(cookies_path, "rb") as f:
                    cookies = pickle.load(f)
                context.add_cookies(cookies)
                self.log_msg.emit("Session cookies loaded.")
                # Navigate to the source domain to establish session context.
                # This does two things:
                #   1. Verifies the cookies are still valid (will redirect to dashboard if so)
                #   2. Populates page.url with session params (ses, hotel_id, etc.)
                #   3. Essential for Booking.com — navigate_to_section needs ses params from URL
                page.goto(source.login_url, timeout=30000, wait_until="domcontentloaded")
                
                # Let's wait up to 8 seconds for redirects to settle and evaluate if session is active
                is_session_active = False
                for i in range(8):
                    page.wait_for_timeout(1000)
                    current_url = page.url.lower()
                    
                    body_text = ""
                    try:
                        body_text = page.inner_text("body")[:2000].lower()
                    except Exception:
                        pass
                    
                    has_password_input = False
                    try:
                        has_password_input = page.query_selector("input[type='password']") is not None
                    except Exception:
                        pass
                        
                    login_indicators = [
                        "sign in to manage",      # Booking.com
                        "sign in with",           # Generic
                        "log in to your",         # Generic
                        "enter your password",    # Login form
                        "forgot password",        # Login form
                        "create your account",    # Booking.com signup
                        "login-form",             # Form class
                        "username",               # Input name
                        "password",               # Input name
                    ]
                    has_login_text = any(ind in body_text for ind in login_indicators)
                    
                    # Detect if we landed on an error page (e.g. "sorry, this page does not exist")
                    is_err, _ = source._is_error_page(page)
                    
                    if "admin.booking.com" in current_url:
                        has_session_params = "ses=" in current_url or "hotel_id=" in current_url or "hotel_account_id=" in current_url
                        has_dashboard_path = any(x in current_url for x in ("/hotel/", "/extranet/", "/dashboard/"))
                        
                        if has_session_params and has_dashboard_path and not has_password_input and not has_login_text and not is_err:
                            is_session_active = True
                            break
                        elif has_password_input or has_login_text or "login" in current_url or is_err:
                            is_session_active = False
                            break
                    else:
                        # Non-booking sources logic
                        if not has_password_input and not has_login_text and not is_err and any(x in current_url for x in ("dashboard", "home", "extranet")):
                            is_session_active = True
                            break
                        elif has_password_input or has_login_text or "login" in current_url or is_err:
                            is_session_active = False
                            break
                
                if is_session_active:
                    self.log_msg.emit("Session active.")
                else:
                    self.log_msg.emit("Session expired — re-login required.")
                    self.login_required.emit(f"{source.source_name} session expired, please log in again.")
                    self.log_msg.emit("Chrome opened — log in and confirm in the app.")
                    self.login_event.wait()
                    
                    # Wait for dashboard/home URL with session parameters to appear to ensure login succeeded
                    self.log_msg.emit("Waiting for dashboard to load...")
                    has_params = False
                    for _ in range(15):
                        current_url = page.url.lower()
                        if "ses=" in current_url or "hotel_id=" in current_url or "hotel_account_id=" in current_url:
                            has_params = True
                            break
                        page.wait_for_timeout(1000)
                    
                    if not has_params:
                        self.log_msg.emit("Warning: Dashboard URL with session parameters not detected yet.")
                        
                    cookies = context.cookies()
                    with open(cookies_path, "wb") as f:
                        pickle.dump(cookies, f)
                    self.log_msg.emit("Session refreshed.")
            else:
                self.log_msg.emit(f"Navigating to {source.source_name} login page...")
                page.goto(source.login_url, timeout=30000, wait_until="domcontentloaded")
                time.sleep(3)
                self.login_required.emit(f"{source.source_name} login required.")
                self.log_msg.emit("Chrome opened — log in and confirm in the app.")
                self.login_event.wait()
                
                # Wait for dashboard/home URL with session parameters to appear to ensure login succeeded
                self.log_msg.emit("Waiting for dashboard to load...")
                has_params = False
                for _ in range(15):
                    current_url = page.url.lower()
                    if "ses=" in current_url or "hotel_id=" in current_url or "hotel_account_id=" in current_url:
                        has_params = True
                        break
                    page.wait_for_timeout(1000)
                
                cookies = context.cookies()
                if cookies_path:
                    with open(cookies_path, "wb") as f:
                        pickle.dump(cookies, f)
                    self.log_msg.emit("Session saved.")

            # ── Group fields by section ────────────────────
            sections = {}
            for field in self.job.selected_fields:
                key = field["key"]
                parts = key.split("_")
                # Try compound prefix first (e.g. "exp_ci" → insights),
                # then fall back to single prefix (e.g. "exp" → reservations)
                compound_key = "_".join(parts[:2]) if len(parts) >= 3 else None
                simple_key = parts[0] if len(parts) >= 2 else "general"
                # Map short prefixes to actual section keys
                section_map = {
                    "res": "reservations", "prop": "property",
                    "rev": "reviews", "fin": "financial",
                    "promo": "promotions",
                    # Source-specific section prefixes (compound 2-part keys)
                    "exp_ci": "insights",
                    "htl_ci": "insights",
                    "goi_rpt": "reports",
                    "mmt_rev": "reviews",          # MMT Reviews
                    "mmt_settlement": "financial",  # MMT Financial
                    "goi_rev": "reviews",           # Goibibo Reviews
                    "goi_settlement": "financial",  # Goibibo Financial
                    "agd_rev": "reviews",           # Agoda Reviews
                    "agd_prop": "property",         # Agoda Property
                    "exp_rev": "reviews",           # Expedia Reviews
                    "exp_prop": "property",         # Expedia Property
                    "htl_rev": "reviews",           # Hotels.com Reviews
                    "htl_prop": "property",         # Hotels.com Property
                    # Booking.com section prefixes (single-word keys)
                    "dash": "dashboard",
                    "rate": "rates",
                    "boost": "boost",
                    "inb": "inbox",
                    "anl": "analytics",
                    # Fallback simple prefixes -> "reservations"
                    "mmt": "reservations",
                    "goi": "reservations",
                    "agd": "reservations",
                    "exp": "reservations",
                    "htl": "reservations",
                }
                # Check compound prefix first
                if compound_key and compound_key in section_map:
                    section_key = section_map[compound_key]
                else:
                    section_key = section_map.get(simple_key, simple_key)
                if section_key not in sections:
                    sections[section_key] = []
                sections[section_key].append(field)

            if not sections:
                sections["general"] = self.job.selected_fields

            # ── Scrape each section ────────────────────────
            all_rows = []
            section_count = len(sections)
            for idx, (section_key, fields) in enumerate(sections.items()):
                if self._stop:
                    break
                self.log_msg.emit(f"Navigating to section: {section_key} ({idx+1}/{section_count})")
                self.progress.emit(idx, section_count, f"Scraping {section_key}...")

                if source.multi_tab:
                    # Open a new tab for each section (MMT/Goibibo SPAs don't
                    # handle cross-section navigation well on a single page)
                    tab = context.new_page()
                    try:
                        source.navigate_to_section(tab, section_key)
                        time.sleep(2)
                        rows = source.extract_data(tab, fields)
                    finally:
                        tab.close()
                else:
                    source.navigate_to_section(page, section_key)
                    time.sleep(2)  # let the page render
                    rows = source.extract_data(page, fields)

                self.log_msg.emit(f"  → Got {len(rows)} rows from '{section_key}'")
                all_rows.extend(rows)

            context.close()
            pw.stop()

            # ── Double-Safety CSV Write & Consolidation ───────────────────────────
            if self._stop:
                ScrapeHistoryManager.complete_session(self.session_id, "Interrupted")
                self.log_msg.emit("\nScrape job stopped/interrupted by user.")
                self.finished.emit(output_path, 0)
            elif all_rows:
                # Read any existing rows from CSV first (for resume safety)
                existing_rows = []
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    try:
                        with open(output_path, "r", newline="", encoding="utf-8") as f:
                            reader = csv.DictReader(f)
                            for r in reader:
                                existing_rows.append(dict(r))
                    except Exception as e:
                        self.log_msg.emit(f"Warning: could not read existing CSV for consolidation: {e}")
                
                # Combine: remove old rows for hotels we just scraped to prevent duplicates
                scraped_hotel_ids = {r.get("hotel_id") for r in all_rows if r.get("hotel_id")}
                consolidated = [r for r in existing_rows if r.get("hotel_id") not in scraped_hotel_ids]
                consolidated.extend(all_rows)
                
                # Rewrite consolidated data
                try:
                    with open(output_path, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=ordered_keys, extrasaction="ignore")
                        writer.writeheader()
                        writer.writerows(consolidated)
                except Exception as e:
                    self.log_msg.emit(f"Error writing final CSV file: {e}")

                ScrapeHistoryManager.complete_session(self.session_id, "Completed")
                
                # Get the actual total row count for the session from SQLite for accuracy
                session_stats = ScrapeHistoryManager.get_session(self.session_id)
                final_row_count = session_stats.get("total_rows", len(consolidated)) if session_stats else len(consolidated)
                
                self.log_msg.emit(f"\nDone! Scrape finished successfully.")
                self.log_msg.emit(f"  Output saved to: {output_path}")
                self.progress.emit(section_count, section_count, "Complete!")
                self.finished.emit(output_path, final_row_count)
            else:
                # If no rows extracted in this run, check if there's data in the database
                session_stats = ScrapeHistoryManager.get_session(self.session_id)
                total_rows = session_stats.get("total_rows", 0) if session_stats else 0
                if total_rows > 0:
                    ScrapeHistoryManager.complete_session(self.session_id, "Completed")
                    self.log_msg.emit(f"\nDone! Scrape finished successfully with {total_rows} total records.")
                    self.log_msg.emit(f"  Output saved to: {output_path}")
                    self.progress.emit(section_count, section_count, "Complete!")
                    self.finished.emit(output_path, total_rows)
                else:
                    ScrapeHistoryManager.complete_session(self.session_id, "Completed")
                    self.log_msg.emit("Scrape finished. No new active promotions or data extracted.")
                    self.finished.emit(output_path, 0)

        except Exception as e:
            self.log_msg.emit(f"ERROR: {e}")
            import traceback
            self.log_msg.emit(traceback.format_exc())
            ScrapeHistoryManager.complete_session(self.session_id, "Failed")
            self.finished.emit("", 0)


# ────────────────────────────────────────────────────────────
#  UI Widget — embeddable in the main window's tab
# ────────────────────────────────────────────────────────────

class UniversalScraperTab(QWidget):
    """A full widget that can be added as a tab in the main window."""

    log_signal = pyqtSignal(str)
    ui_signal = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.current_job = None
        self.worker = None
        self.log_signal.connect(self._append_log)
        self.ui_signal.connect(lambda fn: fn())
        self._build_ui()
        self._refresh_source_fields()
        self._load_history_into_table()

    def _append_log(self, msg: str):
        self.log.append(msg)
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        self.sub_tabs = QTabWidget()
        self.sub_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #333; background: #1a1a2e; }
            QTabBar::tab { background: #0f3460; color: #aaa; padding: 10px 24px;
                          margin-right: 2px; border-top-left-radius: 4px;
                          border-top-right-radius: 4px; font-weight: bold; }
            QTabBar::tab:selected { background: #16213e; color: #e94560; border-bottom: 2px solid #e94560; }
            QTabBar::tab:hover { background: #1a3a6a; color: white; }
        """)
        main_layout.addWidget(self.sub_tabs)
        
        # ── Tab 1: Config ────────────────────────────────────
        config_widget = QWidget()
        self._build_config_ui(config_widget)
        self.sub_tabs.addTab(config_widget, "Scraper Config")
        
        # ── Tab 2: History ───────────────────────────────────
        history_widget = QWidget()
        self._build_history_ui(history_widget)
        self.sub_tabs.addTab(history_widget, "Scrape History & Resume")

    def _build_config_ui(self, widget):
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # ── Header ────────────────────────────────────────
        title = QLabel("Universal Data Scraper")
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Configure and run targeted extranet scrapes")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(subtitle)

        # ── Source selector ────────────────────────────────
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("Data Source:"))
        self.source_combo = QComboBox()
        for key, src in EXTRANET_SOURCES.items():
            self.source_combo.addItem(src.source_name, userData=key)
        self.source_combo.currentIndexChanged.connect(self._refresh_source_fields)
        self.source_combo.setStyleSheet(
            "background: #16213e; color: white; border: 1px solid #444; "
            "border-radius: 4px; padding: 6px; font-size: 13px;"
        )
        src_row.addWidget(self.source_combo, 1)

        self.login_btn = QPushButton("Login")
        self.login_btn.setStyleSheet("background-color: #0a7; padding: 8px 16px;")
        self._login_mode = "login"  # "login" | "confirm"
        self.login_btn.clicked.connect(self._on_login_btn_clicked)
        src_row.addWidget(self.login_btn)

        self.session_label = QLabel("Not logged in")
        self.session_label.setStyleSheet("color: #888; font-size: 11px;")
        src_row.addWidget(self.session_label)
        layout.addLayout(src_row)

        # ── Field selection (scrollable) ──────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none;")
        scroll_container = QWidget()
        self.fields_layout = QVBoxLayout(scroll_container)
        scroll.setWidget(scroll_container)
        scroll.setMaximumHeight(260)
        layout.addWidget(QLabel("Select fields to scrape:"))
        layout.addWidget(scroll)

        # ── Job controls ──────────────────────────────────
        ctrl_row = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._select_all_fields)
        self.select_all_btn.setStyleSheet("background-color: #34495e;")
        ctrl_row.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self._deselect_all_fields)
        self.deselect_all_btn.setStyleSheet("background-color: #34495e;")
        ctrl_row.addWidget(self.deselect_all_btn)

        self.scrape_all_btn = QPushButton("Scrape All Data")
        self.scrape_all_btn.clicked.connect(self._scrape_all_data)
        self.scrape_all_btn.setStyleSheet("background-color: #8e44ad; font-weight: bold;")
        ctrl_row.addWidget(self.scrape_all_btn)

        ctrl_row.addStretch()

        self.export_config_btn = QPushButton("Export Config")
        self.export_config_btn.clicked.connect(self._export_config)
        self.export_config_btn.setStyleSheet("background-color: #555;")
        ctrl_row.addWidget(self.export_config_btn)

        self.import_config_btn = QPushButton("Import Config")
        self.import_config_btn.clicked.connect(self._import_config)
        self.import_config_btn.setStyleSheet("background-color: #555;")
        ctrl_row.addWidget(self.import_config_btn)
        layout.addLayout(ctrl_row)

        # ── Run controls ──────────────────────────────────
        run_row = QHBoxLayout()
        self.output_label = QLabel("Output label:")
        self.output_label.setStyleSheet("color: #ccc;")
        run_row.addWidget(self.output_label)

        self.label_input = QTextEdit()
        self.label_input.setMaximumHeight(32)
        self.label_input.setPlaceholderText("e.g. Oct2024_Bookings")
        self.label_input.setStyleSheet(
            "background: #16213e; color: white; border: 1px solid #444; "
            "border-radius: 4px; font-size: 12px;"
        )
        run_row.addWidget(self.label_input, 1)

        self.run_btn = QPushButton("▶  Start Scrape")
        self.run_btn.setStyleSheet("background-color: #27ae60; font-weight: bold; padding: 10px 24px;")
        self.run_btn.clicked.connect(lambda: self._run_job())
        run_row.addWidget(self.run_btn)

        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.setStyleSheet("background-color: #c0392b; font-weight: bold;")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_job)
        run_row.addWidget(self.stop_btn)
        layout.addLayout(run_row)

        # ── Progress ──────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # ── Log ───────────────────────────────────────────
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        self.log.setStyleSheet(
            "background-color: #16213e; color: #a0e0a0; border: 1px solid #333; "
            "border-radius: 4px; font-family: Consolas; font-size: 11px;"
        )
        layout.addWidget(QLabel("Log:"))
        layout.addWidget(self.log)

    def _build_history_ui(self, widget):
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # Title
        hist_title = QLabel("Scrape Session History & Resume")
        hist_title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        hist_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hist_title)

        # Filters Row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter by Month:"))
        self.month_filter = QComboBox()
        self.month_filter.addItem("All Months")
        self.month_filter.currentIndexChanged.connect(self._load_history_into_table)
        filter_row.addWidget(self.month_filter)

        filter_row.addWidget(QLabel("Filter by Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All Statuses", "Completed", "Running", "Interrupted", "Failed"])
        self.status_filter.currentIndexChanged.connect(self._load_history_into_table)
        filter_row.addWidget(self.status_filter)

        filter_row.addStretch()

        self.refresh_hist_btn = QPushButton("Refresh")
        self.refresh_hist_btn.setStyleSheet("background-color: #2980b9; padding: 6px 14px;")
        self.refresh_hist_btn.clicked.connect(self._load_history_into_table)
        filter_row.addWidget(self.refresh_hist_btn)
        layout.addLayout(filter_row)

        # History Table
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(6)
        self.history_table.setHorizontalHeaderLabels([
            "Date & Time", "Platform", "Progress", "Records", "Status", "Actions"
        ])
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setStyleSheet("""
            QTableWidget { background-color: #16213e; color: #e0e0e0; gridline-color: #333; border: 1px solid #333; }
            QHeaderView::section { background-color: #0f3460; color: white; padding: 6px; border: 1px solid #333; font-weight: bold; }
            QTableWidget::item { padding: 6px; }
        """)
        
        # Set column widths/strech
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.history_table.setColumnWidth(1, 150)
        self.history_table.setColumnWidth(2, 80)
        self.history_table.setColumnWidth(3, 80)
        self.history_table.setColumnWidth(4, 90)
        
        layout.addWidget(self.history_table)

    def _load_history_into_table(self):
        """Load, filter, and render history items from the SQLite database."""
        history = ScrapeHistoryManager.get_history()
        
        # Populate month filter combo dynamically if not already filled
        current_month_sel = self.month_filter.currentText()
        self.month_filter.blockSignals(True)
        self.month_filter.clear()
        self.month_filter.addItem("All Months")
        
        months = set()
        for h in history:
            ts = h.get("timestamp", "")
            if len(ts) >= 7:
                year_month = ts[:7]
                try:
                    dt = datetime.strptime(year_month, "%Y-%m")
                    months.add(dt.strftime("%B %Y"))
                except Exception:
                    months.add(year_month)
                    
        for m in sorted(list(months), reverse=True):
            self.month_filter.addItem(m)
            
        idx = self.month_filter.findText(current_month_sel)
        if idx >= 0:
            self.month_filter.setCurrentIndex(idx)
        self.month_filter.blockSignals(False)

        # Apply filters
        month_sel = self.month_filter.currentText()
        status_sel = self.status_filter.currentText()
        
        filtered_history = []
        for h in history:
            if month_sel != "All Months":
                ts = h.get("timestamp", "")
                if len(ts) >= 7:
                    try:
                        dt = datetime.strptime(ts[:7], "%Y-%m")
                        m_str = dt.strftime("%B %Y")
                        if m_str != month_sel:
                            continue
                    except Exception:
                        if ts[:7] != month_sel:
                            continue
                            
            if status_sel != "All Statuses":
                if h.get("status", "") != status_sel:
                    continue
                    
            filtered_history.append(h)

        self.history_table.setRowCount(0)
        self.history_table.setRowCount(len(filtered_history))
        
        for row_idx, h in enumerate(filtered_history):
            self.history_table.setItem(row_idx, 0, QTableWidgetItem(h.get("timestamp", "")))
            self.history_table.setItem(row_idx, 1, QTableWidgetItem(h.get("platform", "")))
            
            total_p = h.get("total_properties", 0) or 0
            proc_p = h.get("processed_properties", 0) or 0
            progress_str = f"{proc_p} / {total_p}" if total_p > 0 else "1 / 1"
            self.history_table.setItem(row_idx, 2, QTableWidgetItem(progress_str))
            self.history_table.setItem(row_idx, 3, QTableWidgetItem(str(h.get("total_rows", 0))))
            
            status = h.get("status", "")
            status_item = QTableWidgetItem(status)
            if status == "Completed":
                status_item.setForeground(Qt.GlobalColor.green)
            elif status == "Running":
                status_item.setForeground(Qt.GlobalColor.cyan)
            elif status == "Interrupted":
                status_item.setForeground(Qt.GlobalColor.yellow)
            elif status == "Failed":
                status_item.setForeground(Qt.GlobalColor.red)
            self.history_table.setItem(row_idx, 4, status_item)
            
            # Actions cell
            actions_layout = QHBoxLayout()
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(6)
            
            open_btn = QPushButton("Open CSV")
            open_btn.setStyleSheet("background-color: #27ae60; font-size: 11px; padding: 4px 8px;")
            out_path = h.get("output_path", "")
            open_btn.clicked.connect(lambda checked, p=out_path: self._open_csv_file(p))
            actions_layout.addWidget(open_btn)
            
            resume_btn = QPushButton("Resume")
            resume_btn.setStyleSheet("background-color: #d35400; font-size: 11px; padding: 4px 8px;")
            session_id = h.get("id", "")
            
            # Can resume if running/interrupted/failed and there are properties remaining to scrape
            can_resume = status in ("Interrupted", "Failed", "Running") and total_p > proc_p
            resume_btn.setEnabled(can_resume)
            if not can_resume:
                resume_btn.setStyleSheet("background-color: #333; color: #666; font-size: 11px; padding: 4px 8px;")
                
            resume_btn.clicked.connect(lambda checked, s_id=session_id: self._resume_session(s_id))
            actions_layout.addWidget(resume_btn)
            
            cell_widget = QWidget()
            cell_widget.setLayout(actions_layout)
            self.history_table.setCellWidget(row_idx, 5, cell_widget)

    def _open_csv_file(self, output_path: str):
        if not output_path or not os.path.exists(output_path):
            self.log_msg(f"Error: CSV file not found at {output_path}")
            return
        try:
            os.startfile(output_path)
            self.log_msg(f"Opened file: {output_path}")
        except Exception as e:
            self.log_msg(f"Failed to open CSV file: {e}")

    def _resume_session(self, session_id: str):
        session = ScrapeHistoryManager.get_session(session_id)
        if not session:
            self.log_msg("Error: Session not found in database.")
            return
            
        output_path = session.get("output_path", "")
        source_key = session.get("source_key", "")
        fields_str = session.get("fields", "[]")
        
        try:
            fields = json.loads(fields_str)
        except Exception:
            self.log_msg("Error: Failed to parse fields configuration for this session.")
            return
            
        label = session_id.replace("session_", "")
        job = ScrapeJob(
            source_key=source_key,
            selected_fields=fields,
            label=label,
            output_path=output_path
        )
        
        self.sub_tabs.setCurrentIndex(0)
        self._run_job(job, session_id=session_id)

    def _refresh_source_fields(self):
        """Rebuild the field checklist for the currently selected source."""
        while self.fields_layout.count():
            item = self.fields_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        source_key = self.source_combo.currentData()
        source = EXTRANET_SOURCES.get(source_key)
        if not source:
            return

        self._update_session_status()

        for group_def in source.available_fields:
            group_box = QGroupBox(group_def["group"])
            group_box.setStyleSheet("""
                QGroupBox { color: #e0e0e0; font-weight: bold; border: 1px solid #444;
                            border-radius: 6px; margin-top: 10px; padding-top: 16px; }
                QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
            """)
            group_layout = QVBoxLayout()
            for field in group_def["fields"]:
                cb = QCheckBox(field["label"])
                cb.setProperty("field_key", field["key"])
                cb.setStyleSheet("color: #ccc; spacing: 6px;")
                group_layout.addWidget(cb)
            group_box.setLayout(group_layout)
            self.fields_layout.addWidget(group_box)

        self.fields_layout.addStretch()

    def _update_session_status(self):
        source_key = self.source_combo.currentData()
        source = EXTRANET_SOURCES.get(source_key)
        if source and hasattr(source, 'cookies_path') and source.cookies_path.exists():
            self.session_label.setText("✓ Session active")
            self.session_label.setStyleSheet("color: #0a7; font-size: 11px;")
        else:
            self.session_label.setText("Not logged in")
            self.session_label.setStyleSheet("color: #888; font-size: 11px;")

    def _on_login_btn_clicked(self):
        if self._login_mode == "login":
            self._do_login()
        elif self._login_mode == "confirm":
            self._confirm_login()
        elif self._login_mode == "worker_confirm":
            self._confirm_worker_login()

    def _do_login(self):
        source_key = self.source_combo.currentData()
        source = EXTRANET_SOURCES.get(source_key)
        if not source:
            return

        self.log_signal.emit(f"\nOpening {source.source_name} login...")
        self.login_btn.setEnabled(False)
        self._login_event = threading.Event()

        def login_thread():
            try:
                pw = sync_playwright().start()
                context = pw.chromium.launch_persistent_context(
                    user_data_dir=str(COOKIES_DIR / 'chrome_extranet'),
                    headless=False,
                    channel="chrome",
                    args=[
                        f"--remote-debugging-port={EXTRANET_DEBUG_PORT}",
                        "--no-first-run",
                        "--window-size=1280,900",
                    ]
                )
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(source.login_url, timeout=30000, wait_until="domcontentloaded")
                time.sleep(3)
                self.log_signal.emit(f"Chrome opened at {source.login_url}")
                self.log_signal.emit("Log in to the browser window, then click 'Confirm Login'")
                self.ui_signal.emit(self._show_confirm_login_button)
                self._login_event.wait()
                cookies = context.cookies()
                if hasattr(source, 'cookies_path'):
                    with open(source.cookies_path, "wb") as f:
                        pickle.dump(cookies, f)
                context.close()
                pw.stop()
                self.log_signal.emit(f"{source.source_name} session saved!")
                self.ui_signal.emit(self._update_session_status)
            except Exception as e:
                self.log_signal.emit(f"Login error: {e}")
            self.ui_signal.emit(self._reset_login_button)

        threading.Thread(target=login_thread, daemon=True).start()

    def _show_confirm_login_button(self):
        self._login_mode = "confirm"
        self.login_btn.setText("Click here after logging in → Confirm")
        self.login_btn.setStyleSheet(
            "background-color: #f39c12; font-weight: bold; padding: 8px 16px;"
        )
        self.login_btn.setEnabled(True)

    def _confirm_login(self):
        self._login_mode = "login"
        if hasattr(self, '_login_event') and self._login_event:
            self._login_event.set()
        self.login_btn.setEnabled(False)
        self.login_btn.setText("Saving session...")

    def _reset_login_button(self):
        self._login_mode = "login"
        self.login_btn.setText("Login")
        self.login_btn.setStyleSheet("background-color: #0a7; padding: 8px 16px;")
        self.login_btn.setEnabled(True)

    def log_msg(self, msg: str):
        self.log.append(msg)
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _select_all_fields(self):
        self._set_all_checkboxes(True)

    def _deselect_all_fields(self):
        self._set_all_checkboxes(False)

    def _scrape_all_data(self):
        self._set_all_checkboxes(True)
        self.log_msg("All fields selected — starting scrape with all available data...")
        self._run_job()

    def _set_all_checkboxes(self, checked: bool):
        for i in range(self.fields_layout.count()):
            item = self.fields_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QGroupBox):
                for cb in item.widget().findChildren(QCheckBox):
                    cb.setChecked(checked)

    def _get_selected_fields(self) -> list[dict]:
        fields = []
        for i in range(self.fields_layout.count()):
            item = self.fields_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QGroupBox):
                for cb in item.widget().findChildren(QCheckBox):
                    if cb.isChecked():
                        key = cb.property("field_key")
                        fields.append({"key": key, "label": cb.text()})
        return fields

    def _export_config(self):
        source_key = self.source_combo.currentData()
        fields = self._get_selected_fields()
        if not fields:
            self.log_msg("No fields selected to export.")
            return
        label = self.label_input.toPlainText().strip() or f"scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        job = ScrapeJob(source_key=source_key, selected_fields=fields, label=label)

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Config", str(Path.home() / "Downloads" / f"{label}.json"),
            "JSON Files (*.json)"
        )
        if path:
            job.to_file(path)
            self.log_msg(f"Config saved: {path}")

    def _import_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Config", str(Path.home() / "Downloads"), "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            job = ScrapeJob.from_file(path)
            idx = self.source_combo.findData(job.source_key)
            if idx >= 0:
                self.source_combo.setCurrentIndex(idx)
            for field in job.selected_fields:
                for i in range(self.fields_layout.count()):
                    item = self.fields_layout.itemAt(i)
                    if item and item.widget() and isinstance(item.widget(), QGroupBox):
                        for cb in item.widget().findChildren(QCheckBox):
                            if cb.property("field_key") == field["key"]:
                                cb.setChecked(True)
            self.log_msg(f"Config loaded: {Path(path).name} — {len(job.selected_fields)} fields selected")
        except Exception as e:
            self.log_msg(f"Failed to load config: {e}")

    def _run_job(self, job=None, session_id=None):
        if job is None:
            source_key = self.source_combo.currentData()
            fields = self._get_selected_fields()
            if not fields:
                self.log_msg("Select at least one field to scrape.")
                return

            label = self.label_input.toPlainText().strip() or f"scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            output_path = str(Path.home() / "Downloads" / f"{label}.csv")

            job = ScrapeJob(
                source_key=source_key,
                selected_fields=fields,
                label=label,
                output_path=output_path,
            )
        self.current_job = job

        self.log_msg(f"\n{'='*50}")
        if session_id:
            self.log_msg(f"Resuming Job: {job.display_summary()}")
        else:
            self.log_msg(f"Job: {job.display_summary()}")
        self.log_msg(f"Output: {job.output_path}")
        self.log_msg(f"{'='*50}")

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setMaximum(1)
        self.progress.setValue(0)

        self.worker = ExtranetScrapeWorker(job, session_id=session_id)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.log_msg.connect(self.log_msg)
        self.worker.login_required.connect(self._on_worker_login_required)
        self.worker.start()

    def _stop_job(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.log_msg("Stopping...")

    def _on_worker_progress(self, current, total, status):
        self.progress.setMaximum(total)
        self.progress.setValue(current)
        self.progress.setFormat(f"{status}  ({current}/{total})")

    def _on_worker_finished(self, output_path: str, rows: int):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._reset_login_button()
        if output_path and rows >= 0:
            self._load_history_into_table()
            self.log_msg(f"\n✓ Complete! {rows} rows → {output_path}")
            self.progress.setFormat(f"Done! {rows} rows")
        else:
            self.progress.setFormat("No data extracted")
        import winsound
        try:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    def _on_worker_login_required(self, message: str):
        self.log_msg(message)
        self.log_msg("Chrome opened — log in to the browser window, then click Confirm Login below.")
        self.login_btn.setText("Click here after logging in → Confirm (Worker)")
        self.login_btn.setStyleSheet(
            "background-color: #e67e22; font-weight: bold; padding: 8px 16px;"
        )
        self.login_btn.setEnabled(True)
        self._login_mode = "worker_confirm"

    def _confirm_worker_login(self):
        if self.worker and hasattr(self.worker, 'login_event'):
            self.worker.login_event.set()
        self._login_mode = "login"
        self.login_btn.setText("Scraping in progress...")
        self.login_btn.setStyleSheet(
            "background-color: #555; padding: 8px 16px;"
        )
        self.login_btn.setEnabled(False)
        self.log_msg("Session confirmed — continuing scrape...")
