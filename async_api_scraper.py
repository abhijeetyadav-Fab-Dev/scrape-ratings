import asyncio
import re
import json
import logging
from typing import List, Dict, Any, Tuple
from curl_cffi import requests

logger = logging.getLogger(__name__)

class AsyncScraperEngine:
    """
    Sub-30 second scraper engine using TLS impersonation and asyncio.
    Executes concurrent API endpoints completely bypassing UI/Playwright bottlenecks.
    """
    def __init__(self, concurrency_limit: int = 50):
        self.concurrency_limit = concurrency_limit
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        
    async def fetch_mmt(self, session: requests.AsyncSession, mmt_id: str) -> Tuple[float, int, str]:
        """Fetch MMT rating via desktop HTML embedded state or mobile API."""
        if not mmt_id: return None, None, "no_id"
        url = f"https://www.makemytrip.com/hotels/hotel-details/?hotelId={mmt_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            async with self.semaphore:
                resp = await session.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    if len(resp.text) < 100 or "200-OK" in resp.text:
                        return None, None, "waf_blocked"
                    import ujson
                    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});\s*</script>', resp.text, re.DOTALL)
                    if match:
                        state = ujson.loads(match.group(1))
                        try:
                            rating_data = state.get("hotelDetails", {}).get("staticDetails", {}).get("hotelRating", {})
                            rating = rating_data.get("rating")
                            count = rating_data.get("ratingCount")
                            return rating, count, "ok"
                        except Exception as e:
                            return None, None, f"parse_error: {e}"
                    return None, None, "state_not_found"
                return None, None, f"status_{resp.status_code}"
        except Exception as e:
            return None, None, f"req_error: {e}"

    async def fetch_booking(self, session: requests.AsyncSession, bcom_id: str) -> Tuple[float, int, str]:
        """Fetch Booking.com rating via review list API or HTML."""
        if not bcom_id: return None, None, "no_id"
        url = f"https://www.booking.com/hotel/in/{bcom_id}.html"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        try:
            async with self.semaphore:
                resp = await session.get(url, headers=headers, timeout=10)
                if "awsWaf" in resp.text or "challenge" in resp.text.lower():
                    return None, None, "waf_blocked"
                
                rating, count = None, None
                lat_match = re.search(r'<meta[^>]*itemprop="ratingValue"[^>]*content="([^"]+)"', resp.text)
                if lat_match: rating = float(lat_match.group(1))
                
                cnt_match = re.search(r'<meta[^>]*itemprop="reviewCount"[^>]*content="([^"]+)"', resp.text)
                if cnt_match: count = int(cnt_match.group(1))
                
                if rating and count:
                    return rating, count, "ok"
                return None, None, "rating_not_found"
        except Exception as e:
            return None, None, f"req_error: {e}"

    async def fetch_goibibo(self, session: requests.AsyncSession, goibibo_id: str) -> Tuple[float, int, str]:
        """Fetch Goibibo rating via JSON endpoint."""
        if not goibibo_id: return None, None, "no_id"
        url = f"https://www.goibibo.com/hotels/api/get_review_data/?vid={goibibo_id}"
        try:
            async with self.semaphore:
                resp = await session.get(url, timeout=10)
                if resp.status_code == 200:
                    if len(resp.text) < 50 or "200 - OK" in resp.text:
                        return None, None, "waf_blocked"
                    try:
                        import ujson
                        data = ujson.loads(resp.text)
                        rating = data.get("data", {}).get("rating", {}).get("aggr", {}).get("rating")
                        count = data.get("data", {}).get("rating", {}).get("aggr", {}).get("count")
                        return rating, count, "ok"
                    except ValueError:
                        return None, None, "waf_blocked"
                return None, None, f"status_{resp.status_code}"
        except Exception as e:
            return None, None, f"req_error: {e}"

    async def _process_item(self, session: requests.AsyncSession, item: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single item routing to the correct platform endpoint."""
        plat = item.get("platform", "").lower()
        hid = item.get("hotel_id", "")
        mmt_id = item.get("mmt_id", "")
        bcom_id = item.get("bcom_id", "")
        
        rating, count, reason = None, None, "not_implemented"
        
        if 'mmt' in plat or 'makemytrip' in plat:
            target_id = mmt_id if mmt_id else hid
            rating, count, reason = await self.fetch_mmt(session, target_id)
        elif 'booking' in plat:
            target_id = bcom_id if bcom_id else hid
            rating, count, reason = await self.fetch_booking(session, target_id)
        elif 'goibibo' in plat:
            rating, count, reason = await self.fetch_goibibo(session, hid)
            
        return {
            "item_idx": item.get("idx"),
            "rating": rating,
            "review_count": count,
            "reason": reason
        }

    async def scrape_batch(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Scrape a batch of items concurrently using TLS impersonation session."""
        async with requests.AsyncSession(impersonate="chrome120") as session:
            tasks = [self._process_item(session, item) for item in items]
            results = await asyncio.gather(*tasks)
            return results
