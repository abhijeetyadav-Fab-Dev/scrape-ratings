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
- Refactored the CSV parsing engine in `ratings_tab.py` (`load_csv`) to enforce strict prioritization: **Name > URL > ID**. This ensures that if a row has a hotel name, it is treated as a name-only search item (regardless of any numeric lookup IDs), storing the numeric IDs as reference/lookup fields for mapping instead of forcing an MMT routing.






