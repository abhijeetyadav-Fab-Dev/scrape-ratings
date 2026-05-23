# CLAUDE.md — Scrape Ratings Project

## Auto-Commit Policy
- After every significant change (new feature, bug fix, refactor, or file modification), **commit the changes** with a descriptive message.
- Commit messages should be concise but descriptive (e.g., "Fix MMT login flow to handle timeout", "Add checkpoint resume for CSV scraping").
- Push changes together when a logical group of work is complete.

## Session History
- After each session or major milestone, add an entry to `session_history.md` summarizing what was done.
- Include the date, what files were changed, and why.

## Project Structure
- **app.py** — Main PyQt6 GUI application with Booking.com and MMT scrapers
- **universal_scraper.py** — Universal scraper tab
- **scrape_ratings.py / scrape_ratings_fast.py** — Alternative scraper implementations
- **test_*.py / debug_*.py** — Test and debug scripts
- **test_csvs/** — Test CSV data files

## Key Patterns
- Uses Playwright (sync API) for browser automation
- Uses PyQt6 for the GUI
- MMT scraping uses a shared Chrome instance via CDP (remote debugging port 9222)
- Checkpoint system in app.py auto-saves progress to ~/.scrape-ratings/checkpoint_*.json
- Cookies saved to ~/.scrape-ratings/

## Style
- Follow existing patterns in the codebase
- Python 3.x, keep imports organized
