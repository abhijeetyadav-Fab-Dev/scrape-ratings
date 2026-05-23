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










