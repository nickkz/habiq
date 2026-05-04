"""
RentCast API client — https://rentcast.io

Endpoints used:
  GET /v1/listings/sale          On-market active listings
  GET /v1/properties             All properties (on + off market)
  GET /v1/properties/{id}        Full property record + owner info
  GET /v1/avm/value              Automated valuation
  GET /v1/avm/rent/long-term     Rental estimate

Sign up: https://app.rentcast.io/app/api-access
Set RENTCAST_API_KEY in .env.  Free tier: 50 req/month.
"""
import json
import os
import time
import logging
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import MAX_PRICE, POCONO_ZIPS

log = logging.getLogger(__name__)

RENTCAST_KEY = os.getenv("RENTCAST_API_KEY", "")
BASE_URL = "https://api.rentcast.io/v1"
MULTI_FAMILY_TYPE = "Multi Family"
PAGE_LIMIT = 500


class RentCastError(Exception):
    pass


class RentCastClient:
    def __init__(self, rate_limit_delay: float = 1.0):
        self.delay = rate_limit_delay
        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": RENTCAST_KEY,
            "Accept": "application/json",
        })
        if not RENTCAST_KEY:
            log.warning("RENTCAST_API_KEY not set.")

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
    )
    def _get(self, path: str, params: dict) -> dict | list:
        url = f"{BASE_URL}{path}"
        resp = self.session.get(url, params=params, timeout=20)
        if resp.status_code == 401:
            raise RentCastError("401 Unauthorized – check RENTCAST_API_KEY in .env")
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 10))
            log.warning(f"Rate limited – sleeping {wait}s")
            time.sleep(wait)
            resp = self.session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    # ── Listings (on-market) ──────────────────────────────────────────────────

    def search_listings_by_zip(self, zip_code: str, max_price: int = MAX_PRICE,
                               status: str = "Active") -> list[dict]:
        log.info(f"Listings search: zip={zip_code} status={status}")
        try:
            data = self._get("/listings/sale", {
                "zipCode": zip_code,
                "propertyType": MULTI_FAMILY_TYPE,
                "maxPrice": max_price,
                "status": status,
                "limit": PAGE_LIMIT,
                "offset": 0,
            })
        except RentCastError:
            raise
        except Exception as e:
            log.error(f"Listing search failed zip={zip_code}: {e}")
            return []
        results = data if isinstance(data, list) else data.get("data", [])
        log.info(f"  -> {len(results)} listings")
        time.sleep(self.delay)
        return results

    # ── All properties (off-market sweep) ────────────────────────────────────

    def search_properties_by_zip(self, zip_code: str) -> list[dict]:
        """
        Returns ALL multi-family properties in a ZIP regardless of listing status.
        Used to surface off-market leads. Filters by estimated value <= MAX_PRICE.
        """
        log.info(f"Property sweep: zip={zip_code}")
        results = []
        offset = 0
        while True:
            try:
                data = self._get("/properties", {
                    "zipCode": zip_code,
                    "propertyType": MULTI_FAMILY_TYPE,
                    "limit": PAGE_LIMIT,
                    "offset": offset,
                })
            except RentCastError:
                raise
            except Exception as e:
                log.error(f"Property sweep failed zip={zip_code}: {e}")
                break

            batch = data if isinstance(data, list) else data.get("data", [])
            if not batch:
                break

            # Filter by estimated value
            affordable = [
                p for p in batch
                if (p.get("estimatedValue") or p.get("lastSalePrice") or MAX_PRICE + 1) <= MAX_PRICE
            ]
            results.extend(affordable)

            if len(batch) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
            time.sleep(self.delay)

        log.info(f"  -> {len(results)} off-market candidates")
        time.sleep(self.delay)
        return results

    def get_property_detail(self, property_id: str) -> Optional[dict]:
        """Full property record: owner name, mailing address, sale history."""
        try:
            data = self._get(f"/properties/{property_id}", {})
            time.sleep(self.delay)
            return data
        except Exception as e:
            log.error(f"Property detail failed id={property_id}: {e}")
            return None

    def get_valuation(self, address: str, city: str, state: str,
                      zip_code: str) -> Optional[dict]:
        try:
            data = self._get("/avm/value", {
                "address": address, "city": city,
                "state": state, "zipCode": zip_code,
            })
            time.sleep(self.delay)
            return data
        except Exception as e:
            log.debug(f"Valuation failed {address}: {e}")
            return None

    def get_rent_estimate(self, address: str, city: str, state: str,
                          zip_code: str) -> Optional[dict]:
        try:
            data = self._get("/avm/rent/long-term", {
                "address": address, "city": city,
                "state": state, "zipCode": zip_code,
                "propertyType": MULTI_FAMILY_TYPE,
            })
            time.sleep(self.delay)
            return data
        except Exception as e:
            log.debug(f"Rent estimate failed {address}: {e}")
            return None

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _extract_photos(self, raw: dict) -> list[str]:
        """Pull photo URLs from any field RentCast might use."""
        photos = []
        # Try various field names
        for key in ("photos", "photoUrls", "imageUrls", "images"):
            val = raw.get(key)
            if isinstance(val, list):
                photos.extend([p for p in val if isinstance(p, str) and p.startswith("http")])
        # Single photo field
        for key in ("photoUrl", "imageUrl", "thumbnailUrl"):
            val = raw.get(key)
            if isinstance(val, str) and val.startswith("http"):
                photos.append(val)
        return list(dict.fromkeys(photos))  # deduplicate, preserve order

    def _extract_sale_history(self, raw: dict) -> list[dict]:
        """Extract sale / price history events from a listing or property record."""
        events = []
        # priceHistory array (listings)
        for evt in raw.get("priceHistory", []) or []:
            events.append({
                "date":   evt.get("date") or evt.get("listingDate"),
                "price":  evt.get("price") or evt.get("listingPrice"),
                "event":  evt.get("event") or evt.get("priceChangeType") or "Price Change",
                "buyer":  None,
                "seller": None,
                "source": "rentcast",
            })
        # saleHistory array (property records)
        for evt in raw.get("saleHistory", []) or []:
            events.append({
                "date":   evt.get("date") or evt.get("saleDate"),
                "price":  evt.get("price") or evt.get("salePrice"),
                "event":  "Sold",
                "buyer":  evt.get("buyerName"),
                "seller": evt.get("sellerName"),
                "source": "rentcast",
            })
        # Last sale fields (fallback)
        if not events and raw.get("lastSaleDate"):
            events.append({
                "date":  raw["lastSaleDate"],
                "price": raw.get("lastSalePrice"),
                "event": "Sold",
                "source": "rentcast",
            })
        return [e for e in events if e.get("date") and e.get("price")]

    def parse_listing(self, raw: dict, market_status: str = "on_market") -> dict:
        hoa_fee = raw.get("hoaFeeMonthly") or raw.get("hoaFee") or 0
        has_hoa = hoa_fee > 0 or bool(raw.get("hasHoa"))
        rc_id   = raw.get("id", "")

        owner = raw.get("owner") or {}
        if not isinstance(owner, dict):
            owner = {}

        return {
            "zpid":           f"rc_{rc_id}",
            "address":        raw.get("addressLine1") or raw.get("address", ""),
            "city":           raw.get("city", ""),
            "state":          raw.get("state", "PA"),
            "zip_code":       raw.get("zipCode", ""),
            "latitude":       raw.get("latitude"),
            "longitude":      raw.get("longitude"),
            "price":          raw.get("price") or raw.get("listPrice") or raw.get("lastSalePrice"),
            "zestimate":      raw.get("estimatedValue"),
            "rent_zestimate": raw.get("estimatedRent"),
            "beds":           raw.get("bedrooms"),
            "baths":          raw.get("bathrooms"),
            "sqft":           raw.get("squareFootage"),
            "lot_size_sqft":  raw.get("lotSize"),
            "year_built":     raw.get("yearBuilt"),
            "property_type":  raw.get("propertyType", MULTI_FAMILY_TYPE),
            "unit_count":     raw.get("units") or raw.get("unitCount"),
            "status":         "FOR_SALE" if market_status == "on_market" else "OFF_MARKET",
            "market_status":  market_status,
            "days_on_market": raw.get("daysOnMarket"),
            "hoa_fee":        hoa_fee,
            "has_hoa":        has_hoa,
            "zillow_url":     raw.get("zillowUrl"),
            "description":    raw.get("description"),
            "photo_urls":     json.dumps(self._extract_photos(raw)),
            "sale_history":   self._extract_sale_history(raw),
            # Owner fields (saved separately)
            "_owner_name":    owner.get("name") or raw.get("ownerName"),
            "_owner_phone":   owner.get("phone"),
            "_owner_email":   owner.get("email"),
            "_owner_mailing": owner.get("mailingAddress"),
            "_owner_city":    owner.get("mailingCity"),
            "_owner_state":   owner.get("mailingState"),
            "_owner_zip":     owner.get("mailingZip"),
            "source":         "rentcast",
        }

    # ── High-level orchestration ──────────────────────────────────────────────

    def fetch_onmarket(self) -> list[dict]:
        """Active for-sale multi-family listings across all Pocono ZIPs."""
        seen, results = set(), []
        for z in POCONO_ZIPS:
            for raw in self.search_listings_by_zip(z, MAX_PRICE, "Active"):
                rc_id = raw.get("id", "")
                if rc_id in seen:
                    continue
                seen.add(rc_id)
                parsed = self.parse_listing(raw, market_status="on_market")
                if self._qualifies(parsed):
                    results.append(parsed)
        log.info(f"On-market total: {len(results)}")
        return results

    def fetch_offmarket(self, on_market_ids: set) -> list[dict]:
        """
        All multi-family properties under MAX_PRICE that are NOT in active listings.
        Caller passes the set of zpids already captured from on-market search.
        """
        seen, results = set(), []
        for z in POCONO_ZIPS:
            for raw in self.search_properties_by_zip(z):
                rc_id = raw.get("id", "")
                zpid = f"rc_{rc_id}"
                if rc_id in seen or zpid in on_market_ids:
                    continue
                seen.add(rc_id)
                parsed = self.parse_listing(raw, market_status="off_market")
                if self._qualifies(parsed):
                    results.append(parsed)
        log.info(f"Off-market total: {len(results)}")
        return results

    def _qualifies(self, p: dict) -> bool:
        """Apply HOA + type + price filters."""
        if p.get("has_hoa"):
            return False
        ptype = (p.get("property_type") or "").lower()
        if not any(k in ptype for k in ["multi", "duplex", "triplex", "fourplex", "apartment"]):
            return False
        price = p.get("price") or p.get("zestimate") or 0
        if price > MAX_PRICE or price <= 0:
            return False
        return True
