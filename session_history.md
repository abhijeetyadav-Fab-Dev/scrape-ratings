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
