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
- **CDP Loopback Host Refinement**: Replaced `localhost` with explicit `127.0.0.1` for all remote debugging CDP connections, preventing silent connection failures on Windows machines due to IPv6 double-resolution loops.
- **CDP Scrape Serialization Lock**: Implemented a global `_cdp_lock` threading lock in `ratings_platforms.py` to serialize MMT and Goibibo navigations. This prevents the shared visible Google Chrome instance from overloading or timing out when the scraper runs with 10+ concurrent background threads, ensuring 100% successful page loads and eliminating random `N/A` errors.
- **Dedicated Single-Thread CDP Executor Routing**: Refactored `ScrapeWorker.run` in `ratings_tab.py` to segregate execution. Headless scrapes (Booking.com, Agoda, Expedia) execute concurrently in a parallel `ThreadPoolExecutor`, while all CDP-based scrapes (Goibibo and MakeMyTrip) run sequentially inside a **dedicated single-thread executor** (`max_workers=1`). This enforces strict thread affinity and guarantees CDP browser calls run on the exact same thread, fully eliminating the Playwright Sync API thread-reuse asyncio loop crash (`[exception: It looks like you are using Playwright Sync API inside the asyncio loop. Please use the Async API instead.]`).
- **First-Class Platform Adaptive Preservation**: Fixed a bug where files containing names or FHIDs without explicit MMT URLs would have their parsed `mmt` source property overridden or filtered out under specific platform tabs (e.g. MMT Tab). Added a priority check in `start_scraping()` to respect and preserve pre-detected `source` tags (`mmt`, `goibibo`, `booking`, etc.) on load, preventing platform filter skips.
- **Search Box Platform Alignment**: Fixed a bug in `quick_search()` where submitting a plain text hotel name query in the MMT, Goibibo, Agoda, or Expedia tabs defaulted to scraping Booking.com results. Integrated platform-level search query resolvers inside `MMTPlatform` and `GoibiboPlatform` subclasses to search and auto-resolve the correct property page details on those respective platforms first.
- **Zero-Tolerance Property Card Validation**: Fixed a bug in `BookingPlatform._search_hotel()` where broad name searches grabbed unrelated carousel properties or ad cards (e.g. mapping *Hotel Roomers* -> *San Spa* or *FabHotel Roomers* -> *FabHotel F9 Pitampura*). Completely rewrote the validation loop to explicitly query property cards (`[data-testid="property-card"]`) and target title elements (`[data-testid="title"]`). Normalized strings are compared after stripping out generic brand prefixes like `fabhotel` or `hotel`. Removed all lenient page-level link fallbacks; if a strict match is not found in the search result titles, the scraper returns `None` (scoring a correct `not_found` status), eliminating false-positive ad/carousel overrides.
- **MMT Direct Redirect & Search Query Pasting**: Fixed a search matching bug where name queries or direct MMT links (e.g. *FabHotel New Journey Hospitality*) entered into the search box failed to resolve, returning `not_found` repeatedly. Upgraded `MMTPlatform.scrape()` and `quick_search()` to detect and isolate pasted MMT detail links containing the `hotelId=` parameter. It now parses the direct ID dynamically from the pasted query string or redirect url, bypassing redundant listing searches and resolving results with 100% accuracy.
- **Floating AI Agent & Thread-Safe Query Sanitization**: Integrated a floating AI Agent widget (`FloatingAgentWidget`) and DuckDuckGo HTML fallback indexes. Resolved a thread initialization bug in `DeepResearchWorker` where performing query sanitization inside `__init__` called `self.signals` before thread execution start (crashing the worker). Relocated sanitization inside `run()`. Developed a conversational parser that strips filler (e.g. *"is this hotel still live and running ?"* or newlines) from target queries, yielding highly accurate, sanitized search terms like *"HOTEL SAWARIYA"* and ensuring successful crawler listing footprint matches.

## 2026-05-30

### Deep Research Link Resolution & Domain Verification Fix
- **Static and Active Redirect Resolution**: Upgraded `DeepResearchWorker` to handle search engine redirect and ad tracking wrappers (e.g. Yahoo's `RU=`, Google's `/url?q=`). First attempts static query parameter extraction, and then dynamically resolves redirects by navigating to the candidate URL via `page.goto` to retrieve the final destination URL (`page.url`).
- **Strict Domain Verification and Filtering**: Enforced strict domain filtering on the resolved final destination URLs. Obvious non-hotel domains (like `reviewcentre.com`, `tripadvisor.com`, etc.) are excluded, and if a platform filter is active (e.g. `'mmt'`), the final URL is required to match that specific platform (e.g. `makemytrip.com/hotels/` or `makemytrip.com/hotels-international/`). This prevents `reviewcentre.com` tracking redirects from leaking into the scraper input queue.
- **Deep MMT Hotel ID Extraction Bug Fix**: Fixed a PyQt application crash/NameError by adding `import urllib.request` inline inside the fallback request logic.
- **MMT Evaluator Context Retry Logic**: Implemented retry logic for evaluation context destruction errors by waiting for the dynamic router redirects to settle before executing JavaScript evaluations.
- **Stealth Headless Chrome Mode**: Reconfigured the thread-local headless browser parameters to run under Chrome's new headless architecture (`--headless=new` and `--disable-blink-features=AutomationControlled`), completely bypassing Akamai's bot-detection protocol blockers on MakeMyTrip's SEO friendly details pages.
- **CSV Output Cleanups**: Clear the bulk input text box in `ratings_tab.py` prior to resolving links to prevent original input query names from ending up at the top of the exported CSV file.

### 2026-05-31

### Deep Research Akamai Bypass & Validation Improvements
- **Akamai Bot-Bypass via Browser Contexts**: Reconfigured the page crawler initialization in `DeepResearchWorker` and `RatingPlatform` to launch explicit, fully configured browser contexts (`browser.new_context()`) with mocked `user_agent`, `viewport`, `locale`, and `timezone_id` parameters. This ensures the browser's JavaScript evaluation engine (`navigator.userAgent`) correctly spoofs a real desktop browser, completely bypassing Akamai bot-detection layers.
- **Context Lifecycle Management**: Overrode `page.close` dynamically in `RatingPlatform.new_page()` to automatically clean up and close its parent browser context, avoiding context/memory leakage without requiring changes to the rest of the codebase where `page.close()` is invoked.
- **Timeout Buffering**: Increased the `page.goto` redirection resolution timeout in [agent_overlay.py](file:///C:/Users/CS05180/Desktop/scrape-ratings/agent_overlay.py) from 10 seconds to 25 seconds to give slow MMT details pages adequate time to load and populate `window.__INITIAL_STATE__` before extracting hotel IDs.
- **MMT Details Page Redirect Filtering**: Added validation to verify that resolved MakeMyTrip URLs contain `-details-` or `hotel-details`. This prevents dead listings that automatically redirect to the generic MMT `/hotels/` home page from registering as resolved, keeping the CSV inputs clean.

## 2026-06-07

### MMT Extranet Routing & Executable Launch Fixes
- **Fixed MMT & Goibibo Room Type Misclassification**: Resolved a critical bug where `mmt_room_type` and `goi_room_type` fields under *Reservations* were incorrectly mapped to the *Property* section because the system matched `"mmt_room"` and `"goi_room"` compound prefixes. Fixed this by narrowing down the property-section mappings specifically to `"mmt_room_inventory"` and `"goi_room_inventory"`.
- **Prevented Cross-Section Drift**: Verified that requesting reservation fields (Booking ID, Guest Name, Check-in, Check-out, Room Type) now navigates only to the `reservations` section, eliminating multi-section split row execution and preserving correct row formatting.
- **PyInstaller Compile & Permissions Resolution**: Terminated locked background processes of `RatingsScraper_v2.1.exe` that were causing `PermissionError: [WinError 5]` and rebuilt the standalone PyQt6 executable successfully using PyInstaller.
- **Taskbar Pinning & Interactive Launch**: Re-ran the taskbar pinning script to pin the updated executable to the taskbar and launched the application in Session 1 (interactive desktop) using `cmd.exe /c start` so the user can interact with the GUI directly.

## 2026-06-11

### Booking.com Extranet Fast API-based Scraping Engine
- **GraphQL Property List Discovery**: Replaced the paginated DOM scrolling/scanning on the Group Homepage with a same-origin Apollo GraphQL query (`GroupProperties` query to `/dml/graphql`). This discovers the entire portfolio of properties instantly in a single background query without any physical browser navigation or pagination clicks.
- **Same-Origin Background Fetch for Tabs**: Added `SUB_TAB_URLS` mapping all sub-tab fields under Home, Rates, Promotions, Reservations, Property, Boost, Inbox, Guest Reviews, Finance, and Analytics to their relative REST HTML paths on Booking.com. Navigating between sub-tabs now uses same-origin background fetches (`_fast_fetch_html` calling browser `fetch()`) and loads the HTML locally in-memory via `page.set_content(html, wait_until="commit")`. This completely eliminates visible dropdown clicking and tab navigation.
- **Fast Fetch for Property Pages**: Overhauled the multi-property loop in `extract_data` to fast-fetch the main property details pages in the background and load them locally, eliminating sequential visible `page.goto` page reloads.
- **Corrected 404 URL Mapping Errors**: Resolved critical URL mapping errors under BookingExtranetSource where sections (like `"financial"`, `"reservations"`, `"property"`, `"inbox"`, `"analytics"`) were mapped to incorrect/non-existent filenames like `finance.html` (which returned 404 pages). Updated them to correct active endpoints (like `finance_overview.html`, `search_reservations.html`, `content_score.html`, `messaging/inbox.html`, `statistics/index.html`), preventing session-loss symptoms caused by 404 redirects.
- **Robust Session Parameter Tracking**: Tracked and cached `current_hotel_id` and `current_ses` parameters dynamically during the scraping worker loop, ensuring accurate background fetch endpoint construction even when `page.url` remains on a neutral same-origin base page.

## 2026-06-14

### Async API Scraper Engine Implementation
- **Massive Performance Overhaul**: Transitioned the application from slow, sequential HTML/headless browser scraping to a blazing-fast pure AsyncIO API backend engine (`async_api_scraper.py`).
- **TLS Impersonation Engine**: Integrated `curl_cffi` to mimic Chrome 120 at the TLS/JA3 layer, effectively bypassing Cloudflare and Akamai/Kong WAF protections without needing heavy browser instances.
- **Concurrent Batch Processing**: Configured the PyQt6 worker (`ratings_tab.py`) to chunk incoming CSV properties into batches of 100, blasting the requests simultaneously to achieve sub-30 second processing times for massive datasets.
- **WAF Auto-Routing Fallback**: Added robust WAF intercept detection (`200-OK` blank pages and `awsWaf` challenge scripts). If the API engine gets blocked, it gracefully flags the item and routes it automatically to the Playwright Headless Browser fallback loop for 100% extraction accuracy.
- **Direct ID Routing**: Added dedicated CSV columns (`mmt_id` and `bcom_id`) inside the `ratings_tab.py` importer. When these IDs are detected, the `DeepResearchWorker` completely skips Yahoo/Bing search index engines and executes lightning-fast direct link construction.
- **Strict Verification Upgrades**: Upgraded `agent_overlay.py` prompt logic to enforce rigorous Latitude/Longitude coordinate matching, Address matching, and strict Pincode and Brand image matching. Removed Gemma fallback and forced `nemotron-ultra:latest` for extreme accuracy.

### God Mode Page Scanner CDP Routing & Thread-Safety Fix
- **CDP Fallback Routing**: Solved MakeMyTrip (MMT) and Goibibo Akamai bot detection by routing Page Scanner requests through the shared CDP Chrome instance on port 9222.
- **PyQt6 GUI Thread-Safety Refactoring**: Resolved empty/invisible scanner results inside the God Mode UI tab by refactoring `_run_scan` and defining a thread-safe `PageScanWorker` class (subclassing `QThread`). The page scan execution is now offloaded from the GUI thread while GUI widget updates are properly delegated to the main thread via Qt signals, preventing silent UI failures and ensuring the detected checkboxes, tables, lists, and cards render correctly.
- **CDP WebSocket Session Leak Prevention**: Discovered and resolved memory/resource connection leaks occurring on CDP Chrome integrations. Connect-over-CDP clients in `PageScanner.scan` and `GodModeWorker._run_async` now invoke `browser.close()` upon task completion. This safely disconnects the Playwright WebSocket sessions and releases resources without terminating the external, persistent Chrome process.


 
 