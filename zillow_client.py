"""
Zillow API client — supports two RapidAPI hosts:

  zillow56        https://rapidapi.com/apimaker/api/zillow56           (recommended)
  zillow-com1     https://rapidapi.com/s.mahmoud97/api/zillow-com1     (fallback)

Set in .env:
  RAPIDAPI_KEY=your_key
  ZILLOW_HOST=zillow56.p.rapidapi.com        (or zillow-com1.p.rapidapi.com)
"""
import json
import os
import time
import logging
from datetime import datetime
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import RAPIDAPI_KEY, MAX_PRICE

log = logging.getLogger(__name__)

# Read host from env — defaults to zillow56
ZILLOW_HOST = os.getenv("ZILLOW_HOST", "zillow56.p.rapidapi.com")

# Per-host endpoint + param configuration
HOST_CONFIGS = {
    "zillow56.p.rapidapi.com": {
        "search_endpoint": "search",
        "detail_endpoint": "property",
        "search_params": lambda loc, home_type, max_price, page: {
            "location": loc,
            "home_type": home_type,
            "price_max": str(max_price),
            "status": "forSale",
            "page": str(page),
            "sortOrder": "Newest",
        },
        "detail_params": lambda zpid: {"zpid": zpid},
        "results_key": "results",
        "total_pages_key": "totalPages",
    },
    "zillow-com1.p.rapidapi.com": {
        "search_endpoint": "propertyExtendedSearch",
        "detail_endpoint": "property",
        "search_params": lambda loc, home_type, max_price, page: {
            "location": loc,
            "home_type": home_type,
            "maxPrice": str(max_price),
            "status_type": "ForSale",
            "page": str(page),
        },
        "detail_params": lambda zpid: {"zpid": zpid},
        "results_key": "props",
        "total_pages_key": "totalPages",
    },
}

# Fall back to zillow56 config for unknown hosts
def _get_host_config(host: str) -> dict:
    return HOST_CONFIGS.get(host, HOST_CONFIGS["zillow56.p.rapidapi.com"])


class ZillowAPIError(Exception):
    pass


class ZillowClient:
    def __init__(self, rate_limit_delay: float = 2.0):
        self.delay = rate_limit_delay
        self.host = ZILLOW_HOST
        self.cfg = _get_host_config(self.host)
        self.headers = {
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": self.host,
        }
        self.base_url = f"https://{self.host}"

        if not RAPIDAPI_KEY:
            log.warning("RAPIDAPI_KEY not set – Zillow API calls will fail.")
        log.info(f"ZillowClient using host: {self.host}")

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=3, max=60),
    )
    def _get(self, endpoint: str, params: dict) -> dict:
        url = f"{self.base_url}/{endpoint}"
        resp = requests.get(url, headers=self.headers, params=params, timeout=20)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 15))
            log.warning(f"Rate limited – sleeping {retry_after}s")
            time.sleep(retry_after)
            resp = requests.get(url, headers=self.headers, params=params, timeout=20)

        if resp.status_code == 403:
            try:
                msg = resp.json().get("message", resp.text)
            except Exception:
                msg = resp.text
            raise ZillowAPIError(
                f"403 Forbidden from {self.host}: {msg}\n"
                f"  --> Make sure you are subscribed to the API at:\n"
                f"      https://rapidapi.com/apimaker/api/zillow56"
            )

        resp.raise_for_status()
        return resp.json()

    # ── Search ────────────────────────────────────────────────────────────────

    def search_properties(
        self,
        location: str,
        home_type: str = "MultiFamily2To4",
        max_price: int = MAX_PRICE,
    ) -> list[dict]:
        """Search and paginate. Returns raw result dicts from the API."""
        results = []
        page = 1

        while True:
            log.info(f"Searching: location={location!r}  page={page}")
            params = self.cfg["search_params"](location, home_type, max_price, page)
            try:
                data = self._get(self.cfg["search_endpoint"], params)
            except ZillowAPIError:
                raise
            except Exception as e:
                log.error(f"Search failed ({location} p{page}): {e}")
                break

            props = data.get(self.cfg["results_key"], [])
            if not props:
                log.info(f"  No more results at page {page}")
                break

            results.extend(props)
            log.info(f"  -> {len(props)} results (total: {len(results)})")

            total_pages = data.get(self.cfg["total_pages_key"], 1)
            if page >= total_pages:
                break
            page += 1
            time.sleep(self.delay)

        return results

    def get_property_details(self, zpid: str) -> Optional[dict]:
        """Fetch full property detail — HOA, price history, description, photos."""
        try:
            params = self.cfg["detail_params"](zpid)
            data = self._get(self.cfg["detail_endpoint"], params)
            time.sleep(self.delay)
            return data
        except Exception as e:
            log.error(f"Detail fetch failed zpid={zpid}: {e}")
            return None

    # ── Parsing ───────────────────────────────────────────────────────────────

    def parse_search_result(self, raw: dict) -> dict:
        """Normalise a raw search result into our DB schema dict."""
        addr = raw.get("address", {})
        if isinstance(addr, str):
            street = addr
            addr = {}
        else:
            street = addr.get("streetAddress", "")

        return {
            "zpid": str(raw.get("zpid", "")),
            "address": raw.get("streetAddress") or street,
            "city": raw.get("city") or addr.get("city", ""),
            "state": raw.get("state") or addr.get("state", "PA"),
            "zip_code": raw.get("zipcode") or addr.get("zipcode", ""),
            "latitude": raw.get("latitude"),
            "longitude": raw.get("longitude"),
            "price": raw.get("price") or raw.get("unformattedPrice"),
            "zestimate": raw.get("zestimate"),
            "rent_zestimate": raw.get("rentZestimate"),
            "beds": raw.get("bedrooms") or raw.get("beds"),
            "baths": raw.get("bathrooms") or raw.get("baths"),
            "sqft": raw.get("livingArea") or raw.get("area"),
            "lot_size_sqft": raw.get("lotAreaValue"),
            "year_built": raw.get("yearBuilt"),
            "property_type": raw.get("homeType", "MultiFamily2To4"),
            "status": raw.get("homeStatus", "FOR_SALE"),
            "days_on_market": raw.get("daysOnZillow"),
            "zillow_url": f"https://www.zillow.com/homedetails/{raw.get('zpid')}_zpid/",
        }

    def parse_property_details(self, raw: dict) -> dict:
        """Extract HOA, sale history, photos from a full property response."""
        resoFacts = raw.get("resoFacts", {})
        price_history = raw.get("priceHistory", [])

        sale_events = []
        for event in price_history:
            try:
                t = event.get("time")
                date_iso = (
                    datetime.utcfromtimestamp(t / 1000).isoformat()
                    if isinstance(t, (int, float))
                    else event.get("date", "")
                )
                sale_events.append({
                    "date": date_iso,
                    "price": event.get("price"),
                    "event": event.get("event"),
                    "buyer": (event.get("buyerAgent") or {}).get("name"),
                    "seller": (event.get("sellerAgent") or {}).get("name"),
                    "source": "zillow",
                })
            except Exception:
                continue

        attribution = raw.get("attributionInfo", {})
        return {
            "hoa_fee": resoFacts.get("hoaFee") or 0,
            "has_hoa": bool(resoFacts.get("hasAssociation")) or (resoFacts.get("hoaFee") or 0) > 0,
            "unit_count": resoFacts.get("unitCount") or resoFacts.get("numberOfUnitsTotal"),
            "description": raw.get("description"),
            "photos": json.dumps([
                p.get("url") for p in (raw.get("photos") or []) if p.get("url")
            ]),
            "sale_history": sale_events,
            "listing_agent_name": attribution.get("agentName") or attribution.get("listingAgentName"),
            "listing_agent_phone": attribution.get("agentPhoneNumber") or attribution.get("listingAgentPhoneNumber"),
        }

    # ── High-level ────────────────────────────────────────────────────────────

    def fetch_and_filter(self, location: str) -> list[dict]:
        """
        Search + fetch details + filter HOA.
        Returns fully-parsed dicts ready for DB upsert.
        """
        raw_results = self.search_properties(location)
        filtered = []

        for raw in raw_results:
            parsed = self.parse_search_result(raw)

            price = parsed.get("price") or 0
            if price > MAX_PRICE or price <= 0:
                continue

            zpid = parsed.get("zpid")
            if zpid:
                details = self.get_property_details(zpid)
                if details:
                    extra = self.parse_property_details(details)
                    if extra.get("has_hoa"):
                        log.debug(f"Skipping HOA property zpid={zpid}")
                        continue
                    parsed.update(extra)

            filtered.append(parsed)
            log.info(f"  Kept: {parsed['address']}, {parsed['city']} – ${price:,.0f}")

        return filtered
