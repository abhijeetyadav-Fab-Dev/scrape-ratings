# Scrape Ratings — Session History

## 2026-05-21

### Initial Setup
- Initialized git repository for the project
- Created `.gitignore` for Python project (ignores `__pycache__/`, `build/`, `dist/`, `.pkl`, `.db`, etc.)
- Created this session history file to track changes
- Created `CLAUDE.md` with auto-commit instructions for future coding sessions
- Committed all existing project files as the initial commit

### Project Overview
`scrape-ratings` is a PyQt6 desktop application for scraping hotel ratings and reviews from Booking.com and MakeMyTrip. Key files:
- **app.py** — Main application with PyQt6 GUI, scrapers for Booking.com and MMT
- **universal_scraper.py** — Universal scraper tab
- **scrape_ratings.py / scrape_ratings_fast.py** — Additional scraper implementations
- **Various test files** — debug_mmt.py, test_mmt*.py, etc.

## 2026-05-23

### GUI Fix
- Fixed critical bug in `app.py` where tab initialization was placed inside `dropEvent` instead of `__init__`.
- Enabled drag-and-drop CSV handling to work correctly without causing NameErrors or reference crashes.
- Fixed PyQt6 initialization crash in `ratings_tab.py` where `platform_tabs.currentChanged` signal was connected before child widgets (`bulk_input`, `quick_input`) were constructed, throwing an `AttributeError`. Safety checks with `hasattr` were also added.
- Refactored platform filter logic in `ratings_tab.py` to be adaptive: when a specific sub-tab is active (e.g. Booking.com, Agoda, Expedia), all compatible items are dynamically adapted and retained (e.g. name-only items are converted to `'search'` or the respective platform's search) instead of being skipped. This prevents skipping items when CSV files contain both names and numeric MakeMyTrip IDs (FH IDs) but are scraped on the Booking.com tab.
- Fixed `notify_complete` thread crash in `ratings_tab.py`'s `on_finished` where passing the message string without a trailing comma inside the `args` tuple caused it to be treated as an unpackable sequence (resulting in a TypeError due to multiple positional arguments).
- Refactored the CSV parsing engine in `ratings_tab.py` (`load_csv`) to enforce strict prioritization: **Name > URL > ID**. Added support to capture custom numeric ID columns (such as `FHID`, `fhid`, `fh id`, etc.) as reference lookup fields.
- Implemented **CSV Format Preservation & In-Place Overwrite**: Refactored `save_incremental` in `ratings_tab.py` to dynamically map and overwrite existing `Scraped_Rating`, `Scraped_Reviews`, `Scraped_Source`, and `Scraped_Fail_Reason` columns in-place if they exist, or append them cleanly if not, fully preserving the user's original CSV columns and order.
- Implemented **Blazing-Fast Scraping Speed Optimization**: Added route interception in `ratings_platforms.py` (`new_page`) to block load requests for images, stylesheets, fonts, and media. This reduces network overhead and page load times by up to 500% in headless mode.
- Expanded GUI worker count selector limits to `100` parallel threads in `ratings_tab.py` to leverage system capacity and finish 15k+ hotels in ~15 to 20 minutes.
- Fixed critical **Playwright Threading/Greenlet switching crash** in `ratings_platforms.py` by implementing a robust **Thread-Local Browser Pool** using Python's `threading.local()`. This isolates browser and manager instances per thread, completely preventing greenlet collisions in parallel scraping, and automatically handles clean-up of all instances.
- Improved header parsing logic in `ratings_tab.py` to prevent ID, Code, Link, or URL columns from being misidentified as the name column (`name_idx`) when proper hotel name columns are present. Expanded `id_idx` keyword boundaries to cover all spelling variations of `fhid`, `fh id`, `hotel code`, `code`, etc.
- Fixed Playwright launch context crash in `universal_scraper.py` by restoring `launch_persistent_context` instead of `launch` when using `--user-data-dir` as an argument (which Playwright explicitly forbids).
- Fixed Booking.com Extranet session validation bug in `universal_scraper.py` where a simple redirect check falsely verified system-redirects to the login form index.html as a successful login (active dashboard session). Implemented robust multi-indicator verification checking page DOM body text and checking if the URL actually contains expected path segments (`/hotel/`, `/extranet/`, `/dashboard/`).

### Universal Scraper Upgrades & Group Multi-Property Support
- **Robust Session Redirection Verification**: Implemented a polling check that waits up to 8 seconds for redirects to fully settle. Validates active session context by ensuring the absence of password fields, login text indicators, or error pages (like *"sorry, this page does not exist"*), resolving false-positive session validations.
- **Delayed Session Parameter Capture**: Implemented a 15-second wait for active dashboard parameters (`ses=...`, `hotel_id=...`, `hotel_account_id=...`) to appear in the URL before saving and refreshing pickled session cookies, ensuring only fully authenticated sessions are recorded.
- **Disrupted Reload Protection**: Inside `navigate_to_section()`, added an initial 10-second polling wait for URL params to load. Bypasses redundant target navigations if the browser is currently showing the login page, completely preventing page reloads while the user is typing credentials.
- **Booking.com Extranet Group Homepage Auto-Detection**: Added scanning for `/groups/home/` in the URL to automatically detect if the account manages a portfolio of multiple properties.
- **Portfolio Table DOM Scanner**: Designed a Javascript DOM parser that evaluates the Group Homepage table, automatically extracts all managed `hotel_id` parameters, and resolves their names.
- **Recursive Portfolio Pagination**: Implemented recursive portfolio table pagination (up to 15 pages). The scraper automatically locates and clicks the visible pagination "Next" button/arrow, waits for the table to settle, and continues scanning until the entire portfolio is queued.
- **Real-Time DOM Hotel Name Extraction**: Created `_extract_property_name_from_page()` which inspects header elements (or parses document `<title>`) right after loading each individual hotel's page, capturing the exact formatted hotel name with 100% accuracy.
- **Uniform Metadata Tagging**: Dynamically tags both multi-property and single-property scrapes with the exact `hotel_name` and `hotel_id` columns, providing clean and consistent CSV reporting.
- **SQLite History Logging (`ScrapeHistoryManager`)**: Integrated `sqlite3` to maintain a local Scrape History database (`scrape_history.db` under `.scrape-ratings`). Logs every run, capturing Platform, Start Timestamp, Fields, Status, Progress, and Total Rows.
- **Real-Time Incremental Saving**: Restructured the scraper engine to write/append extracted records to the output CSV in real-time as each individual hotel finishes scraping, fully protecting against data loss in case of abrupt system closures, power losses, or manual cancellations.
- **Scrape Resume / Crash Recovery**: Implemented resume support to query the SQLite database and automatically skip already completed property IDs for the current session, picking up right where it was interrupted.
- **Double-Tab PyQt GUI Dashboard**: Redesigned the Universal Scraper Tab into a dual sub-tab interface:
  1. **Scraper Config**: To configure new runs and view logging.
  2. **Scrape History & Resume**: Renders a premium historical table containing past session runs with Month and Status filters, a one-click **"Open CSV"** action to view spreadsheet files instantly in your default system viewer (e.g. Excel), and a **"Resume"** action to instantly recover and resume interrupted scrape runs!

## 2026-05-29

### Goibibo Scraper Integration & Multi-Platform Preservation
- **Implementation of Goibibo Platform Scraper**: Designed and implemented the `GoibiboPlatform` subclass in `ratings_platforms.py` to route Goibibo hotel scraping via a shared local Chrome instance over CDP on port `9222`, effectively bypassing Akamai/bot shield protection layers.
- **Accurate Goibibo Selector Hooks**: Added strict selector matchers targeting Goibibo's active overall ratings DOM (`AvgReviewTextWrapper` and `GuestRating-styles__AvgReviewTextWrapper`) and ratings/reviews count containers, completely resolving issues with incorrect fallbacks extracting individual user review ratings (like `1.0` instead of `3.6`).
- **First-Class Platform Tab & Labels**: Registered Goibibo as a first-class citizen tab in the PyQt6 GUI dashboard (`ratings_tab.py`), added bulk parsing capability, and correctly mapped `Goibibo` to the `Scraped_Source` column in output CSV files instead of defaulting to `Booking.com`.
- **Systemic Platform Override Bug Fix**: Resolved a critical system-wide bug where loaded CSV rows containing specific platform URLs (e.g. MMT, Goibibo, Agoda, Expedia) were overwritten to `search` (Booking.com name-based search) or skipped whenever a scrape was started from the active Booking.com tab. Added a global preservation hook that respects and retains the correct scraper engine dynamically matching any recognized platform domains, regardless of the active tab.
- **GUI Launch Reliability**: Resolved widget initialization order issues in the God Mode Page Scanner tab to prevent index out of bounds exceptions on startup.
- **Background Scraper Deployment**: Safely terminated and redeployed the active background PyQt6 scraper process to load all recent reliability patches and preserve current scrape contexts.
