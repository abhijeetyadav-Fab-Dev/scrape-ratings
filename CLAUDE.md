# CLAUDE.md — Scrape Ratings Project

## Auto-Commit Policy
- After every significant change (new feature, bug fix, refactor, or file modification), **commit the changes** with a descriptive message.
- Commit messages should be concise but descriptive (e.g., "Fix MMT login flow to handle timeout", "Add checkpoint resume for CSV scraping").
- Push changes together when a logical group of work is complete.

## Session History
- After each session or major milestone, add an entry to `session_history.md` summarizing what was done.
- Include the date, what files were changed, and why.

## Project Structure
- **app.py** — Main PyQt6 GUI application (5 tabs)
  - Ratings Scraper (ratings_tab.py) — hotel ratings by platform
  - God Mode (god_mode.py) — page scanner & link builder
  - Universal Scraper (universal_scraper.py) — extranet data extraction
  - **Async Scraper (async_scraper_tab.py)** — high-performance HTTP scraping (NEW)
  - Bulk OCM Generator (ocm_tab.py) — mass content generation
- **async_scraper_core.py** — Core async scraper engine (RatingScraper class)
- **async_scraper_tab.py** — PyQt6 GUI tab for async scraping
- **scrape_ratings.py / scrape_ratings_fast.py** — Alternative scraper implementations
- **test_*.py / debug_*.py** — Test and debug scripts
- **test_csvs/** — Test CSV data files

## Key Patterns

### Existing Patterns
- Uses Playwright (sync API) for browser automation
- Uses PyQt6 for the GUI
- MMT scraping uses a shared Chrome instance via CDP (remote debugging port 9222)
- Checkpoint system in app.py auto-saves progress to ~/.scrape-ratings/checkpoint_*.json
- Cookies saved to ~/.scrape-ratings/

### New: Async Scraper Patterns
- **async_scraper_core.py**: Thread-safe async HTTP scraper with:
  - Concurrency control via `asyncio.Semaphore` (configurable, default 10)
  - Browser-like headers with random user agent rotation
  - Random delays between requests (0.5-2s) to prevent IP blocking
  - Optional API endpoint discovery (tests /api, /v1, /graphql, etc. patterns)
  - CSV export support with structured data extraction
  - Progress callbacks for UI integration
  - Stats tracking (success/failure counts, duration)
  
- **async_scraper_tab.py**: PyQt6 tab with:
  - Worker thread (ScrapeWorkerThread) running async operations
  - Signal-slot communication for thread-safe UI updates
  - Checkpoint system saving progress to `~/.scrape-ratings/checkpoints/`
  - Colored logging display with timestamps
  - Real-time progress bar and URL status
  - Concurrency spinner (1-50 range)
  - API discovery toggle
  - Export folder shortcut
  
### Integration Points
- AsyncScraperTab added as Tab 4 in app.py (after Universal Scraper)
- Agent overlay updates context when switching to Async Scraper tab
- Dark theme styling matches existing app (#1a1a2e background, #0f3460 buttons)
- Logging integrated with project logger

## Dependencies
Core requirements:
- PyQt6 (GUI)
- playwright (browser automation)
- httpx (async HTTP client)
- beautifulsoup4 (HTML parsing)
- lxml (fast XML/HTML parsing)
- pandas (data handling)
- aiofiles (async file I/O)
- openpyxl (Excel export)

Note: requirements.txt is .gitignored; install manually:
```bash
pip install httpx beautifulsoup4 lxml aiofiles pandas playwright PyQt6 openpyxl
```

## Style
- Follow existing patterns in the codebase
- Python 3.x, keep imports organized
- Use asyncio.run() for async operations in threads
- Always use progress callbacks to keep GUI responsive
- Store checkpoints as JSON in ~/.scrape-ratings/checkpoints/

