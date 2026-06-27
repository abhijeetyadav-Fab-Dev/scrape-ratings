# Scrape Ratings — Hotel Data Tools

A comprehensive PyQt6-based toolkit for scraping hotel data from multiple platforms and extranets.

## Features

**5 Independent Scraping Tools:**

1. **Ratings Scraper** — Extract hotel ratings from Booking.com, Agoda, Expedia, MakeMyTrip, Goibibo, and Hotels.com
   - Multi-threaded scraping (configurable worker count, up to 100)
   - CSV upload with flexible ID/Name/URL detection
   - Incremental CSV export with real-time progress
   - Checkpoint-based resume capability

2. **God Mode** — Advanced page analysis and link discovery
   - Scan any webpage for all scrapeable data
   - Auto-detect tables, lists, JSON-LD data, ratings, API endpoints
   - Element picker for custom field extraction
   - Link builder for dynamic URL generation

3. **Universal Scraper** — Extract data from hotel extranets
   - Multi-platform support: Booking.com, MakeMyTrip, Goibibo, Agoda, Expedia, Hotels.com
   - Extranet-specific field extraction (reservations, property info, reviews, finance, analytics)
   - Group property portfolio support with recursive pagination
   - Real-time incremental CSV/Excel export
   - Session-based resume and crash recovery
   - SQLite history logging

4. **Async Scraper** — High-performance async HTTP scraping
   - Concurrency control (1-50 threads, default 10)
   - Browser-like headers with random user agent rotation
   - Anti-blocking delays (0.5-2s configurable)
   - Optional API endpoint auto-discovery
   - CSV export with structured data extraction
   - Checkpoint system for progress tracking

5. **Bulk OCM Generator** — Mass content generation
   - Batch create and manage OCM (Online Channel Manager) entries
   - CSV-based bulk operations

## Installation

```bash
# Clone the repository
git clone https://github.com/abhijeetyadav-Fab-Dev/scrape-ratings.git
cd scrape-ratings

# Install dependencies
pip install PyQt6 playwright httpx beautifulsoup4 lxml pandas aiofiles openpyxl

# Download Playwright browsers
playwright install

# Run the application
python app.py
```

## Quick Start

### Launch GUI Application
```bash
python app.py
```

### Use Async Scraper Programmatically
```python
import asyncio
from async_scraper_core import RatingScraper

async def main():
    scraper = RatingScraper(max_concurrent=10, delay_range=(0.5, 2.0))
    urls = ["https://example.com/page1", "https://example.com/page2"]
    data = await scraper.scrape_urls(urls)
    scraper.export_to_csv("output.csv")

asyncio.run(main())
```

## Architecture

- **app.py** — Main PyQt6 application with tabbed interface
- **async_scraper_core.py** — Core async scraper engine
- **async_scraper_tab.py** — PyQt6 GUI tab for async scraping
- **ratings_tab.py** — Ratings scraper tab
- **god_mode.py** — Page analysis tool
- **universal_scraper.py** — Extranet scraper with multi-platform support
- **ocm_tab.py** — Bulk OCM generator

## Configuration

### Async Scraper Settings (in GUI)
- **Max Concurrent Requests**: 1-50 (default: 10)
- **API Discovery**: Toggle to auto-detect API endpoints
- **Delay Range**: 0.5-2.0 seconds (built-in)

### Data Storage
- Exported files: `~/.scrape-ratings/exports/`
- Checkpoints: `~/.scrape-ratings/checkpoints/`
- Cookies: `~/.scrape-ratings/`
- History: `~/.scrape-ratings/scrape_history.db`

## Key Features

✅ Multi-threaded/async operations  
✅ Browser-like anti-blocking (headers, delays, user agents)  
✅ Checkpoint-based progress tracking & resume  
✅ Multiple export formats (CSV, Excel, JSON)  
✅ Real-time progress monitoring  
✅ Dark theme GUI with responsive design  
✅ Comprehensive error logging  
✅ Cross-platform support (Windows, macOS, Linux)  

## Project Structure

```
scrape-ratings/
├── app.py                    # Main application
├── async_scraper_core.py     # Async HTTP scraper
├── async_scraper_tab.py      # Async scraper GUI tab
├── ratings_tab.py            # Ratings scraper tab
├── god_mode.py               # Page analyzer tool
├── universal_scraper.py      # Extranet scraper
├── ocm_tab.py                # Bulk OCM generator
├── ratings_platforms.py      # Platform-specific scrapers
├── CLAUDE.md                 # Development guidelines
├── session_history.md        # Session changelog
└── test_csvs/                # Test data
```

## License

© 2026 Scrape Ratings. All rights reserved.

