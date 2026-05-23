try:
    from playwright.sync_api import sync_playwright
    print("Playwright OK")
except ImportError as e:
    print(f"NOT INSTALLED: {e}")
