"""
Enhanced Async Scraper Core — Multi-Source URL Generation & Scraping
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Features:
  • CSV input (hotel names, IDs, search terms)
  • Auto-generate search URLs from input data
  • Multi-source scraping (Google, Booking, Maps, APIs)
  • Concurrency control with anti-blocking
  • Batch results to CSV
  • Real-time progress tracking
"""

import asyncio
import httpx
import json
import csv
import logging
import random
import time
import re
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin, urlparse, quote
from datetime import datetime
from pathlib import Path
from io import StringIO

logger = logging.getLogger("AsyncScraperEnhanced")


class EnhancedRatingScraper:
    """Advanced async scraper that generates URLs from search terms."""
    
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    ]
    
    SEARCH_SOURCES = {
        'booking': 'https://www.booking.com/searchresults.html?ss=',
        'google': 'https://www.google.com/search?q=',
        'tripadvisor': 'https://www.tripadvisor.com/Search?q=',
        'agoda': 'https://www.agoda.com/search?ss=',
        'expedia': 'https://www.expedia.com/Hotel-Search?q=',
    }
    
    def __init__(self, max_concurrent: int = 10, delay_range: Tuple[float, float] = (0.5, 2.0),
                 request_timeout: float = 30.0):
        """Initialize the enhanced scraper."""
        self.max_concurrent = max_concurrent
        self.delay_range = delay_range
        self.request_timeout = request_timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        self.data = []
        self.stats = {
            'total_items': 0,
            'urls_generated': 0,
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
        }
    
    async def _delay(self):
        """Add random delay to mimic human behavior."""
        delay = random.uniform(*self.delay_range)
        await asyncio.sleep(delay)
    
    def generate_search_urls(self, hotel_name: str, sources: List[str] = None) -> Dict[str, str]:
        """Generate search URLs for a hotel name across multiple sources."""
        if sources is None:
            sources = list(self.SEARCH_SOURCES.keys())
        
        urls = {}
        encoded_name = quote(hotel_name)
        
        for source in sources:
            if source in self.SEARCH_SOURCES:
                urls[source] = self.SEARCH_SOURCES[source] + encoded_name
        
        return urls
    
    async def _fetch(self, url: str, method: str = "GET", **kwargs) -> Optional[str]:
        """Fetch URL with concurrency control."""
        async with self.semaphore:
            try:
                await self._delay()
                headers = await self._get_headers()
                
                async with httpx.AsyncClient(timeout=self.request_timeout, http2=True) as client:
                    response = await client.request(method, url, headers=headers, **kwargs, follow_redirects=True)
                    response.raise_for_status()
                    
                    logger.info(f"✓ Fetched: {url[:80]} (Status: {response.status_code})")
                    self.stats['successful'] += 1
                    return response.text
                    
            except httpx.HTTPStatusError as e:
                logger.warning(f"✗ HTTP Error {e.response.status_code}: {url[:60]}")
                self.stats['failed'] += 1
                return None
            except httpx.RequestError as e:
                logger.warning(f"✗ Request Error: {url[:60]} - {type(e).__name__}")
                self.stats['failed'] += 1
                return None
            except asyncio.CancelledError:
                logger.info(f"⊘ Cancelled: {url[:60]}")
                raise
    
    async def scrape_hotel(self, hotel_name: str, sources: List[str] = None, 
                          progress_callback: Optional[callable] = None) -> Dict[str, Any]:
        """Scrape a hotel across multiple sources."""
        try:
            urls = self.generate_search_urls(hotel_name, sources)
            
            result = {
                'hotel_name': hotel_name,
                'timestamp': datetime.now().isoformat(),
                'sources_scraped': 0,
                'status': 'success',
            }
            
            # Scrape from each source
            for source_name, url in urls.items():
                html = await self._fetch(url)
                
                if html:
                    result[f'{source_name}_url'] = url
                    result[f'{source_name}_status'] = 'scraped'
                    result['sources_scraped'] += 1
                    
                    # Extract basic info from HTML
                    if source_name == 'booking':
                        rating_match = re.search(r'[\d.]+(?=\s*/\s*10)', html)
                        if rating_match:
                            result[f'{source_name}_rating'] = rating_match.group()
                    
                    if source_name == 'google':
                        result[f'{source_name}_indexed'] = 'yes' if len(html) > 1000 else 'no'
                else:
                    result[f'{source_name}_status'] = 'failed'
            
            self.data.append(result)
            
            if progress_callback:
                progress_callback(hotel_name, len(urls), result['sources_scraped'])
            
            return result
            
        except Exception as e:
            logger.error(f"Error scraping hotel {hotel_name}: {str(e)}")
            return None
    
    async def scrape_hotels_from_csv(self, csv_content: str, sources: List[str] = None,
                                     progress_callback: Optional[callable] = None) -> List[Dict[str, Any]]:
        """Scrape multiple hotels from CSV content."""
        try:
            # Parse CSV
            reader = csv.DictReader(StringIO(csv_content))
            hotels = []
            
            for row in reader:
                # Try to find hotel name in common columns
                hotel_name = (
                    row.get('hotel_name') or 
                    row.get('name') or 
                    row.get('Hotel Name') or 
                    row.get('Name') or
                    row.get('hotel') or
                    row.get('Hotel')
                )
                
                if hotel_name and hotel_name.strip():
                    hotels.append(hotel_name.strip())
            
            self.stats['total_items'] = len(hotels)
            self.stats['urls_generated'] = len(hotels) * len(sources or list(self.SEARCH_SOURCES.keys()))
            self.stats['start_time'] = time.time()
            
            logger.info(f"🚀 Starting to scrape {len(hotels)} hotels from {len(sources or list(self.SEARCH_SOURCES.keys()))} sources")
            
            # Scrape all hotels concurrently
            tasks = [
                self._scrape_with_index(i + 1, len(hotels), hotel, sources, progress_callback)
                for i, hotel in enumerate(hotels)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self.data = [r for r in results if r and not isinstance(r, Exception)]
            
            self.stats['end_time'] = time.time()
            duration = self.stats['end_time'] - self.stats['start_time']
            
            logger.info(f"✓ Scraping complete. {len(self.data)} hotels processed in {duration:.1f}s")
            
            return self.data
        
        except Exception as e:
            logger.error(f"Error processing CSV: {str(e)}")
            return []
    
    async def _scrape_with_index(self, index: int, total: int, hotel_name: str, 
                                 sources: Optional[List[str]], callback: Optional[callable]):
        """Scrape with index tracking."""
        result = await self.scrape_hotel(hotel_name, sources, callback)
        if callback:
            callback(f"({index}/{total}) {hotel_name}", 0, 0)
        return result
    
    def export_to_csv(self, filename: str = "hotels.csv") -> str:
        """Export scraped data to CSV."""
        if not self.data:
            logger.warning("No data to export to CSV")
            return None
        
        try:
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            
            # Collect all unique field names
            all_fields = set()
            for item in self.data:
                all_fields.update(item.keys())
            
            # Order: hotel_name first, then others
            fieldnames = ['hotel_name', 'timestamp', 'sources_scraped', 'status']
            for field in sorted(all_fields):
                if field not in fieldnames:
                    fieldnames.append(field)
            
            with open(filename, 'w', newline='', encoding='utf-8') as f:
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
