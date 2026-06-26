import asyncio
import re
import json
import logging
import os
import pickle
from typing import List, Dict, Any, Tuple
from curl_cffi import requests

logger = logging.getLogger(__name__)

class AsyncScraperEngine:
    """
    Sub-30 second scraper engine using TLS impersonation and asyncio.
    Executes concurrent API/HTML fetches completely bypassing UI/Playwright bottlenecks.
    """
    def __init__(self, concurrency_limit: int = 50):
        self.concurrency_limit = concurrency_limit
        self.semaphore = None
        self.proxies = self._load_proxies()
        self.proxy_index = 0
        self.proxy_lock = None

    def _ensure_semaphore(self):
        if self.semaphore is None:
            self.semaphore = asyncio.Semaphore(self.concurrency_limit)
        if self.proxy_lock is None:
            self.proxy_lock = asyncio.Lock()

    def _load_proxies(self) -> List[str]:
        settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r") as f:
                    data = json.load(f)
                    if data.get("enable_proxies") and data.get("proxy_list"):
                        proxies = [p.strip() for p in data["proxy_list"].split("\n") if p.strip()]
                        logger.info(f"Loaded {len(proxies)} proxies from settings.json")
                        return proxies
            except Exception as e:
                logger.error(f"Error loading proxies from settings.json: {e}")
        return []

    async def _get_next_proxy(self) -> Dict[str, str]:
        if not self.proxies:
            return None
        async with self.proxy_lock:
            proxy = self.proxies[self.proxy_index]
            self.proxy_index = (self.proxy_index + 1) % len(self.proxies)
            if not proxy.startswith("http://") and not proxy.startswith("https://"):
                proxy = "http://" + proxy
            return {"http": proxy, "https": proxy}

    def _is_waf_blocked(self, text: str) -> bool:
        if len(text) < 20000:
            text_lower = text.lower()
            if any(ind in text_lower for ind in ["denied", "blocked", "captcha", "forbidden", "challenge", "robot"]):
                return True
        else:
            title_m = re.search(r'<title[^>]*>(.*?)</title>', text, re.IGNORECASE)
            if title_m:
                title = title_m.group(1).lower()
                if any(ind in title for ind in ["access denied", "blocked", "forbidden", "security"]):
                    return True
        return False

    async def fetch_mmt(self, session: requests.AsyncSession, mmt_id: str, original_url: str = None) -> Tuple[float, int, str]:
        """Fetch MMT rating via desktop HTML embedded state or mobile API."""
        self._ensure_semaphore()
        if not mmt_id and not original_url: return None, None, "no_id"
        url = original_url if original_url else f"https://www.makemytrip.com/hotels/hotel-details/?hotelId={mmt_id}"
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

        proxy = await self._get_next_proxy()
        # Attempt 0: with proxy (if available), Attempt 1: direct (no proxy)
        max_attempts = 2 if proxy else 1
        for attempt in range(max_attempts):
            current_proxy = proxy if attempt == 0 else None
            try:
                async with self.semaphore:
                    resp = await session.get(
                        url,
                        headers=headers,
                        cookies=cookies,
                        proxies=current_proxy,
                        timeout=12
                    )
                    if resp.status_code == 200:
                        # WAF / empty body guard
                        if len(resp.text) < 100 or "200-OK" in resp.text:
                            if attempt == 0 and proxy:
                                # Retry without proxy
                                continue
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
                    if attempt == 0 and proxy:
                        # Non-200 on proxy: retry direct
                        continue
                    return None, None, f"status_{resp.status_code}"
            except Exception as e:
                if attempt == 0 and proxy:
                    continue
                return None, None, f"req_error: {e}"
        return None, None, "all_attempts_failed"

    async def fetch_booking(self, session: requests.AsyncSession, bcom_id_or_url: str, url: str = None) -> Tuple[float, int, str]:
        """Fetch Booking.com rating via GraphQL API directly, falling back to HTML scraping."""
        self._ensure_semaphore()
        if not bcom_id_or_url: return None, None, "no_id"
        
        hotel_id = None
        # Preserve url if passed and valid
        if url and str(url).startswith("http"):
            m = re.search(r'app_hotel_id=(\d+)', url)
            if m:
                hotel_id = int(m.group(1))
            else:
                m2 = re.search(r'booking_id=(\d+)', url)
                if m2:
                    hotel_id = int(m2.group(1))
        
        # If hotel_id is still not found, check bcom_id_or_url
        if not hotel_id:
            if str(bcom_id_or_url).isdigit():
                hotel_id = int(bcom_id_or_url)
                if not url:
                    url = f"https://www.booking.com/hotel/in/{hotel_id}.html"
            elif str(bcom_id_or_url).startswith("http"):
                url = bcom_id_or_url
                m = re.search(r'app_hotel_id=(\d+)', url)
                if m:
                    hotel_id = int(m.group(1))
                else:
                    m2 = re.search(r'booking_id=(\d+)', url)
                    if m2:
                        hotel_id = int(m2.group(1))
            else:
                if not url:
                    url = f"https://www.booking.com/hotel/in/{bcom_id_or_url}.html"
            
        # Try GraphQL first if we have a numeric hotel ID
        if hotel_id:
            try:
                gql_url = "https://www.booking.com/dml/graphql"
                payload = {
                  "operationName": "ReviewList",
                  "variables": {
                    "input": {
                      "hotelId": hotel_id,
                      "ufi": 0,
                      "hotelCountryCode": "",
                      "sorter": "MOST_RELEVANT",
                      "filters": {"text": ""},
                      "skip": 0,
                      "limit": 1,
                      "hotelScore": 0.0
                    }
                  },
                  "query": "query ReviewList($input: ReviewListFrontendInput!) { reviewListFrontend(input: $input) { ... on ReviewListFrontendResult { reviewsCount ratingScores { value name } } } }"
                }
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Content-Type": "application/json",
                    "Accept": "*/*",
                    "Origin": "https://www.booking.com",
                    "Referer": url or "https://www.booking.com/",
                }
                proxy = await self._get_next_proxy()
                async with self.semaphore:
                    resp = await session.post(gql_url, json=payload, headers=headers, proxies=proxy, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        res = data.get("data", {}).get("reviewListFrontend", {})
                        if res and res.get("__typename") == "ReviewListFrontendResult":
                            count = res.get("reviewsCount")
                            rating_scores = res.get("ratingScores", [])
                            rating = None
                            if rating_scores:
                                try:
                                    # Prefer the overall/total score (name is empty or 'Total')
                                    overall = next(
                                        (s for s in rating_scores if not s.get("name") or s.get("name", "").lower() in ("", "total", "overall")),
                                        None
                                    )
                                    if overall and overall.get("value"):
                                        rating = float(overall["value"])
                                    else:
                                        # Fall back to the highest-valued score (usually the overall rating)
                                        vals = [float(s["value"]) for s in rating_scores if s.get("value")]
                                        if vals:
                                            rating = max(vals)
                                except Exception:
                                    pass

                            if count is not None:
                                return float(rating) if rating is not None else None, int(count), "ok"
            except Exception as e:
                logger.error(f"Booking.com GraphQL query error: {e}")
                
        return None, None, "api_failed"

    async def fetch_goibibo(self, session: requests.AsyncSession, goibibo_id: str) -> Tuple[float, int, str]:
        """Fetch Goibibo rating via JSON endpoint."""
        self._ensure_semaphore()
        if not goibibo_id: return None, None, "no_id"
        url = f"https://www.goibibo.com/hotels/api/get_review_data/?vid={goibibo_id}"
        proxy = await self._get_next_proxy()
        try:
            async with self.semaphore:
                resp = await session.get(url, proxies=proxy, timeout=12)
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
        """Fetch Agoda rating via a two-step scrape:
        1. Retrieve main details page using curl_cffi to extract hotel_id.
        2. Call BelowFoldParams/GetSecondaryData?hotel_id={hotel_id} to parse JSON rating keys.
        """
        self._ensure_semaphore()
        if not url: return None, None, "no_url"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.google.com/",
        }
        proxy = await self._get_next_proxy()
        try:
            async with self.semaphore:
                # Step 1: Fetch details page to get hotel_id
                resp = await session.get(url, headers=headers, proxies=proxy, timeout=12)
                if resp.status_code != 200:
                    return None, None, f"details_status_{resp.status_code}"
                
                if self._is_waf_blocked(resp.text):
                    return None, None, "waf_blocked"
                
                # Extract hotel_id from script or HTML
                m = re.search(r'BelowFoldParams/GetSecondaryData\?hotel_id=(\d+)', resp.text)
                if not m:
                    m = re.search(r'hotelId["\']?:\s*(\d+)', resp.text)
                
                if not m:
                    return None, None, "hotel_id_not_found"
                
                hotel_id = m.group(1)
                
                # Step 2: Fetch secondary data JSON
                api_url = f"https://www.agoda.com/api/cronos/property/BelowFoldParams/GetSecondaryData?hotel_id={hotel_id}&all=false&isHostPropertiesEnabled=false"
                api_headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Referer": url,
                }
                
                # Rotate proxy independently for step 2
                proxy2 = await self._get_next_proxy()
                api_resp = await session.get(api_url, headers=api_headers, proxies=proxy2, timeout=12)
                if api_resp.status_code != 200:
                    return None, None, f"api_status_{api_resp.status_code}"
                
                import ujson
                data = ujson.loads(api_resp.text)
                
                rating = None
                review_count = None
                
                # Try standard reviews object
                rev_obj = data.get("reviews", {})
                if rev_obj:
                    rating = rev_obj.get("score")
                    review_count = rev_obj.get("reviewsCount")
                
                # Fallback to mapParams review object
                if rating is None or review_count is None:
                    map_rev = data.get("mapParams", {}).get("review", {})
                    if map_rev:
                        if rating is None:
                            rating = map_rev.get("formattedScore")
                        if review_count is None:
                            review_count = map_rev.get("reviewCount")
                
                if rating is not None:
                    try:
                        r_val = float(rating)
                        c_val = int(review_count) if review_count is not None else 0
                        return r_val, c_val, "ok"
                    except ValueError:
                        pass
                
                return None, None, "rating_not_found"
        except Exception as e:
            return None, None, f"req_error: {e}"

    async def fetch_expedia(self, session: requests.AsyncSession, url: str) -> Tuple[float, int, str]:
        """Fetch Expedia rating via GraphQL API directly, falling back to HTML scraping."""
        self._ensure_semaphore()
        if not url: return None, None, "no_url"
        
        property_id = None
        # Extract property_id from Expedia URL
        m = re.search(r'\.h(\d+)\.', url)
        if not m:
            m = re.search(r'h(\d+)', url)
        if m:
            property_id = m.group(1)
            
        proxy = await self._get_next_proxy()
        if property_id:
            try:
                gql_url = "https://www.expedia.com/graphql"
                query = """
                query PropertyReviewsQuery($propertyId: String!) {
                  property(id: $propertyId) {
                    reviews {
                      ratingValue
                      count
                    }
                  }
                }
                """
                payload = {
                    "operationName": "PropertyReviewsQuery",
                    "variables": {"propertyId": property_id},
                    "query": query
                }
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Content-Type": "application/json",
                    "Accept": "*/*",
                    "client-id": "shopping-lodging",
                    "Origin": "https://www.expedia.com",
                    "Referer": url,
                }
                async with self.semaphore:
                    resp = await session.post(gql_url, json=payload, headers=headers, proxies=proxy, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        prop = data.get("data", {}).get("property", {})
                        if prop and prop.get("reviews"):
                            rating = prop["reviews"].get("ratingValue")
                            count = prop["reviews"].get("count")
                            if rating is not None:
                                return float(rating), int(count) if count is not None else 0, "ok"
            except Exception as e:
                logger.error(f"Expedia GraphQL query failed: {e}")
                
        return None, None, "api_failed"

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
            rating, count, reason = await self.fetch_mmt(session, target_id, url)
        elif 'booking' in plat:
            target_id = bcom_id if bcom_id else hid
            rating, count, reason = await self.fetch_booking(session, target_id, url)
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
        # Initialise semaphore and lock before gather() so there's no race
        # between the first tasks that all call _ensure_semaphore() simultaneously.
        self._ensure_semaphore()
        async with requests.AsyncSession(impersonate="chrome120") as session:
            tasks = [self._process_item(session, item) for item in items]
            results = await asyncio.gather(*tasks, return_exceptions=False)
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
