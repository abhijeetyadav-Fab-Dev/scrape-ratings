import asyncio
import re
import json
import logging
import os
import pickle
from typing import List, Dict, Any, Tuple
from curl_cffi import requests
from curl_cffi.const import CurlHttpVersion

logger = logging.getLogger(__name__)

class AsyncScraperEngine:
    """
    Sub-30 second scraper engine using TLS impersonation and asyncio.
    Executes concurrent API/HTML fetches completely bypassing UI/Playwright bottlenecks.
    """
    def __init__(self, concurrency_limit: int = 50):
        self.concurrency_limit = concurrency_limit
        self.semaphore = None

    def _ensure_semaphore(self):
        if self.semaphore is None:
            self.semaphore = asyncio.Semaphore(self.concurrency_limit)

    async def fetch_mmt(self, session: requests.AsyncSession, mmt_id: str) -> Tuple[float, int, str]:
        """Fetch MMT rating via desktop HTML embedded state or mobile API."""
        self._ensure_semaphore()
        if not mmt_id: return None, None, "no_id"
        url = f"https://www.makemytrip.com/hotels/hotel-details/?hotelId={mmt_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.makemytrip.com/",
        }
        
        # Load cookies from pickle
        cookies_path = os.path.expanduser('~/.scrape-ratings/mmt_cookies.pkl')
        cookies = {}
        if os.path.exists(cookies_path):
            try:
                with open(cookies_path, 'rb') as f:
                    c_list = pickle.load(f)
                    for c in c_list:
                        cookies[c['name']] = c['value']
            except Exception as ce:
                logger.error(f"Error loading MMT cookies: {ce}")

        try:
            async with self.semaphore:
                resp = await session.get(
                    url, 
                    headers=headers, 
                    cookies=cookies,
                    http_version=CurlHttpVersion.V1_1, 
                    timeout=12
                )
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
                            if rating is not None:
                                return float(rating), int(count) if count is not None else 0, "ok"
                        except Exception as e:
                            return None, None, f"parse_error: {e}"
                    return None, None, "state_not_found"
                return None, None, f"status_{resp.status_code}"
        except Exception as e:
            return None, None, f"req_error: {e}"

    async def fetch_booking(self, session: requests.AsyncSession, bcom_id_or_url: str) -> Tuple[float, int, str]:
        """Fetch Booking.com rating via HTML scraping."""
        self._ensure_semaphore()
        if not bcom_id_or_url: return None, None, "no_id"
        if bcom_id_or_url.startswith("http"):
            url = bcom_id_or_url
        else:
            url = f"https://www.booking.com/hotel/in/{bcom_id_or_url}.html"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        try:
            async with self.semaphore:
                resp = await session.get(url, headers=headers, timeout=12)
                if "awsWaf" in resp.text or "challenge" in resp.text.lower() or resp.status_code == 202:
                    return None, None, "waf_blocked"
                
                from ratings_platforms import extract_rating_review_count
                rating, count = extract_rating_review_count(resp.text, scale_10=True)
                if rating:
                    try:
                        count = int(count) if count else 0
                    except:
                        count = 0
                    return float(rating), count, "ok"
                return None, None, "rating_not_found"
        except Exception as e:
            return None, None, f"req_error: {e}"

    async def fetch_goibibo(self, session: requests.AsyncSession, goibibo_id: str) -> Tuple[float, int, str]:
        """Fetch Goibibo rating via JSON endpoint."""
        self._ensure_semaphore()
        if not goibibo_id: return None, None, "no_id"
        url = f"https://www.goibibo.com/hotels/api/get_review_data/?vid={goibibo_id}"
        try:
            async with self.semaphore:
                resp = await session.get(url, timeout=12)
                if resp.status_code == 200:
                    if len(resp.text) < 50 or "200 - OK" in resp.text:
                        return None, None, "waf_blocked"
                    try:
                        import ujson
                        data = ujson.loads(resp.text)
                        rating = data.get("data", {}).get("rating", {}).get("aggr", {}).get("rating")
                        count = data.get("data", {}).get("rating", {}).get("aggr", {}).get("count")
                        if rating is not None:
                            return float(rating), int(count) if count is not None else 0, "ok"
                    except ValueError:
                        return None, None, "waf_blocked"
                return None, None, f"status_{resp.status_code}"
        except Exception as e:
            return None, None, f"req_error: {e}"

    async def fetch_agoda(self, session: requests.AsyncSession, url: str) -> Tuple[float, int, str]:
        """Fetch Agoda rating via HTML parse."""
        self._ensure_semaphore()
        if not url: return None, None, "no_url"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.google.com/",
        }
        try:
            async with self.semaphore:
                resp = await session.get(url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    if "denied" in resp.text.lower() or "blocked" in resp.text.lower() or "captcha" in resp.text.lower():
                        return None, None, "waf_blocked"
                    
                    from ratings_platforms import extract_rating_review_count
                    rating, review_count = extract_rating_review_count(resp.text, scale_10=True)
                    if rating:
                        try:
                            review_count = int(review_count) if review_count else 0
                        except:
                            review_count = 0
                        return float(rating), review_count, "ok"
                    return None, None, "rating_not_found"
                return None, None, f"status_{resp.status_code}"
        except Exception as e:
            return None, None, f"req_error: {e}"

    async def fetch_expedia(self, session: requests.AsyncSession, url: str) -> Tuple[float, int, str]:
        """Fetch Expedia rating via HTML parse."""
        self._ensure_semaphore()
        if not url: return None, None, "no_url"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.google.com/",
        }
        try:
            async with self.semaphore:
                resp = await session.get(url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    if "denied" in resp.text.lower() or "blocked" in resp.text.lower() or "captcha" in resp.text.lower():
                        return None, None, "waf_blocked"
                    
                    from ratings_platforms import extract_rating_review_count
                    rating, review_count = extract_rating_review_count(resp.text, scale_10=True)
                    if rating:
                        try:
                            review_count = int(review_count) if review_count else 0
                        except:
                            review_count = 0
                        return float(rating), review_count, "ok"
                    return None, None, "rating_not_found"
                return None, None, f"status_{resp.status_code}"
        except Exception as e:
            return None, None, f"req_error: {e}"

    async def _process_item(self, session: requests.AsyncSession, item: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single item routing to the correct platform endpoint."""
        plat = item.get("source", "").lower() or item.get("platform", "").lower()
        hid = item.get("hotel_id", "")
        mmt_id = item.get("mmt_id", "")
        bcom_id = item.get("bcom_id", "")
        url = item.get("url", "")
        
        rating, count, reason = None, None, "not_implemented"
        
        if 'mmt' in plat or 'makemytrip' in plat:
            target_id = mmt_id if mmt_id else hid
            rating, count, reason = await self.fetch_mmt(session, target_id)
        elif 'booking' in plat:
            target_id = bcom_id if bcom_id else hid
            if url:
                rating, count, reason = await self.fetch_booking(session, url)
            else:
                rating, count, reason = await self.fetch_booking(session, target_id)
        elif 'goibibo' in plat:
            target_id = hid
            if not target_id and url:
                m = re.search(r'-vid-(\d+)', url)
                if m: target_id = m.group(1)
            rating, count, reason = await self.fetch_goibibo(session, target_id)
        elif 'agoda' in plat:
            rating, count, reason = await self.fetch_agoda(session, url)
        elif 'expedia' in plat:
            rating, count, reason = await self.fetch_expedia(session, url)
            
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

if __name__ == "__main__":
    async def test_samples():
        print("Running Fast API Async Scraper Samples...")
        # Sample items to scrape using real MMT/Booking/Goibibo sample IDs
        sample_items = [
            {"idx": 1, "platform": "booking", "bcom_id": "8062182", "url": "https://www.booking.com/hotel/in/capital-o-84509-ritz-plaza.html"},
            {"idx": 2, "platform": "booking", "bcom_id": "4735846", "url": "https://www.booking.com/hotel/in/oyo-23616-ss.html"},
            {"idx": 3, "platform": "booking", "bcom_id": "5181098", "url": "https://www.booking.com/hotel/in/spot-on-40727-star-residency-spot.html"},
            {"idx": 4, "platform": "makemytrip", "mmt_id": "32775"},
            {"idx": 5, "platform": "goibibo", "hotel_id": "385457116400804839"}
        ]
        scraper = AsyncScraperEngine(concurrency_limit=10)
        results = await scraper.scrape_batch(sample_items)
        print("\n--- Results ---")
        for res in results:
            print(res)
            
    asyncio.run(test_samples())
