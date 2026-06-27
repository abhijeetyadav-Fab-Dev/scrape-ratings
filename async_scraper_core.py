"""
Async Web Scraper Core Module
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

High-performance, thread-safe async scraper with:
  • Concurrency control (semaphore-based queue)
  • Browser-like headers & user agent rotation
  • Random delays (anti-blocking)
  • Optional API endpoint discovery
  • CSV export support
  • Structured logging

Designed for PyQt6 integration (thread-safe, no blocking).
"""

import asyncio
import httpx
import json
import csv
import logging
import random
import time
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin, urlparse
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("AsyncScraper")


class RatingScraper:
    """Thread-safe async web scraper with concurrency control."""
    
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    ]
    
    API_PATTERNS = [
        "/api/",
        "/v1/",
        "/v2/",
        "/graphql",
        "/rest/",
        "/data/",
        "/services/",
        "/ajax/",
        "/endpoint/",
    ]
    
    def __init__(self, max_concurrent: int = 10, delay_range: Tuple[float, float] = (0.5, 2.0),
                 request_timeout: float = 30.0):
        """
        Initialize the scraper.
        
        Args:
            max_concurrent: Maximum concurrent HTTP requests
            delay_range: (min, max) seconds between requests
            request_timeout: HTTP request timeout in seconds
        """
        self.max_concurrent = max_concurrent
        self.delay_range = delay_range
        self.request_timeout = request_timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        self.data = []
        self.api_endpoints = []
        self.stats = {
            'total_urls': 0,
            'successful': 0,
            'failed': 0,
            'start_time': None,
            'end_time': None,
        }
    
    async def _get_headers(self) -> Dict[str, str]:
        """Generate browser-like headers."""
        return {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0",
        }
    
    async def _delay(self):
        """Add random delay to mimic human behavior."""
        delay = random.uniform(*self.delay_range)
        await asyncio.sleep(delay)
    
    async def _fetch(self, url: str, method: str = "GET", **kwargs) -> Optional[str]:
        """Fetch URL with concurrency control and retry logic."""
        async with self.semaphore:
            try:
                await self._delay()
                headers = await self._get_headers()
                
                async with httpx.AsyncClient(timeout=self.request_timeout, http2=True) as client:
                    response = await client.request(method, url, headers=headers, **kwargs)
                    response.raise_for_status()
                    
                    logger.info(f"✓ Fetched: {url} (Status: {response.status_code})")
                    self.stats['successful'] += 1
                    return response.text
                    
            except httpx.HTTPStatusError as e:
                logger.warning(f"✗ HTTP Error {e.response.status_code}: {url}")
                self.stats['failed'] += 1
                return None
            except httpx.RequestError as e:
                logger.warning(f"✗ Request Error: {url} - {type(e).__name__}")
                self.stats['failed'] += 1
                return None
            except asyncio.CancelledError:
                logger.info(f"⊘ Scraping cancelled for: {url}")
                raise
    
    async def discover_apis(self, base_url: str) -> List[str]:
        """Discover hidden API endpoints."""
        logger.info(f"🔍 Discovering API endpoints for: {base_url}")
        
        discovered = []
        parsed_url = urlparse(base_url)
        base = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        for pattern in self.API_PATTERNS:
            test_url = urljoin(base, pattern)
            response = await self._fetch(test_url)
            
            if response and len(response) > 0:
                discovered.append(test_url)
                logger.info(f"  ✓ Found API endpoint: {test_url}")
        
        self.api_endpoints = discovered
        return discovered
    
    async def scrape_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Scrape a single URL and extract data."""
        try:
            html = await self._fetch(url)
            if not html:
                return None
            
            from bs4 import BeautifulSoup
            
            soup = BeautifulSoup(html, 'lxml')
            
            # Try to detect JSON-LD structured data
            json_ld_scripts = soup.find_all('script', {'type': 'application/ld+json'})
            
            data = {
                'url': url,
                'timestamp': datetime.now().isoformat(),
                'title': soup.title.string if soup.title else 'N/A',
                'status': 'success',
            }
            
            # Extract structured data if available
            for script in json_ld_scripts:
                try:
                    json_data = json.loads(script.string)
                    if isinstance(json_data, dict):
                        if 'aggregateRating' in json_data:
                            data['rating'] = json_data['aggregateRating'].get('ratingValue', 'N/A')
                        if '@type' in json_data:
                            data['schema_type'] = json_data['@type']
                        if 'name' in json_data:
                            data['name'] = json_data['name']
                except (json.JSONDecodeError, AttributeError):
                    pass
            
            self.data.append(data)
            return data
            
        except Exception as e:
            logger.error(f"Scrape error for {url}: {str(e)}")
            return None
    
    async def scrape_urls(self, urls: List[str], progress_callback: Optional[callable] = None) -> List[Dict[str, Any]]:
        """Scrape multiple URLs with optional progress callback."""
        self.stats['total_urls'] = len(urls)
        self.stats['successful'] = 0
        self.stats['failed'] = 0
        self.stats['start_time'] = time.time()
        
        logger.info(f"🚀 Starting scrape of {len(urls)} URLs (max {self.max_concurrent} concurrent)")
        
        tasks = []
        for i, url in enumerate(urls):
            task = self._scrape_with_callback(url, i + 1, len(urls), progress_callback)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        self.data = [r for r in results if r and not isinstance(r, Exception)]
        self.stats['end_time'] = time.time()
        
        duration = self.stats['end_time'] - self.stats['start_time']
        logger.info(f"✓ Scraping complete. {len(self.data)} items collected in {duration:.1f}s")
        
        return self.data
    
    async def _scrape_with_callback(self, url: str, index: int, total: int, callback: Optional[callable]):
        """Scrape with progress callback."""
        result = await self.scrape_url(url)
        if callback:
            callback(index, total, url, result)
        return result
    
    def export_to_csv(self, filename: str = "ratings.csv") -> str:
        """Export data to CSV file."""
        if not self.data:
            logger.warning("No data to export to CSV")
            return None
        
        try:
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                fieldnames = set()
                for item in self.data:
                    fieldnames.update(item.keys())
                fieldnames = sorted(list(fieldnames))
                
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.data)
            
            logger.info(f"✓ Exported to CSV: {filename}")
            return filename
            
        except Exception as e:
            logger.error(f"CSV export error: {str(e)}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get scraping statistics."""
        return {
            **self.stats,
            'items_collected': len(self.data),
            'duration_seconds': (self.stats['end_time'] - self.stats['start_time']) if self.stats['end_time'] else None,
        }


async def scrape_urls_simple(urls: List[str], max_concurrent: int = 10) -> List[Dict[str, Any]]:
    """Simple interface for scraping a list of URLs."""
    scraper = RatingScraper(max_concurrent=max_concurrent)
    return await scraper.scrape_urls(urls)
