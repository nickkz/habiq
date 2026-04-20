"""
RentCast API client — https://rentcast.io

Endpoints used:
  GET /v1/listings/sale          Search active for-sale listings
  GET /v1/properties/{id}        Full property detail
  GET /v1/avm/value              Automated valuation (Zestimate equivalent)
  GET /v1/avm/rent/long-term     Rental estimate

Sign up at https://app.rentcast.io/app/api-access
Set RENTCAST_API_KEY in your .env file.

Free tier: 50 requests/month.
Paid tiers start at $35/month for 1,000 requests.
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

# RentCast property type value for multi-family
MULTI_FAMILY_TYPE = "Multi Family"

# Max results per request (RentCast cap)
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
            log.warning("RENTCAST_API_KEY not set – RentCast calls will fail.")

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
    )
    def _get(self, path: str, params: dict) -> dict | list:
        url = f"{BASE_URL}{path}"
        resp = self.session.get(url, params=params, timeout=20)

        if resp.status_code == 401:
            raise RentCastError(
                "401 Unauthorized – check RENTCAST_API_KEY in your .env file.\n"
                "  Get your key at: https://app.rentcast.io/app/api-access"
            )
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 10))
            log.warning(f"Rate limited – sleeping {wait}s")
            time.sleep(wait)
            resp = self.session.get(url, params=params, timeout=20)

        resp.raise_for_status()
        return resp.json()

    # ── Search ────────────────────────────────────────────────────────────────

    def search_by_zip(self, zip_code: str, max_price: int = MAX_PRICE) -> list[dict]:
        """Search for multi-family for-sale listings in a ZIP code."""
        log.info(f"RentCast search: zip={zip_code}  max_price=${max_price:,}")
        try:
            data = self._get("/listings/sale", {
                "zipCode": zip_code,
                "propertyType": MULTI_FAMILY_TYPE,
                "maxPrice": max_price,
                "status": "Active",
                "limit": PAGE_LIMIT,
                "offset": 0,
            })
        except RentCastError:
            raise
        except Exception as e:
            log.error(f"Search failed for zip {zip_code}: {e}")
            return []

        results = data if isinstance(data, list) else data.get("data", [])
        log.info(f"  -> {len(results)} listings in {zip_code}")
        time.sleep(self.delay)
        return results

    def search_by_city(self, city: str, state: str = "PA", max_price: int = MAX_PRICE) -> list[dict]:
        """Search for multi-family for-sale listings in a city."""
        log.info(f"RentCast search: city={city}, {state}  max_price=${max_price:,}")
        try:
            data = self._get("/listings/sale", {
                "city": city,
                "state": state,
                "propertyType": MULTI_FAMILY_TYPE,
                "maxPrice": max_price,
                "status": "Active",
                "limit": PAGE_LIMIT,
                "offset": 0,
            })
        except RentCastError:
            raise
        except Exception as e:
            log.error(f"Search failed for {city}, {state}: {e}")
            return []

        results = data if isinstance(data, list) else data.get("data", [])
        log.info(f"  -> {len(results)} listings in {city}, {state}")
        time.sleep(self.delay)
        return results

    def get_property_detail(self, property_id: str) -> Optional[dict]:
        """Full property record including owner and sale history."""
        try:
            data = self._get(f"/properties/{property_id}", {})
            time.sleep(self.delay)
            return data
        except Exception as e:
            log.error(f"Detail fetch failed id={property_id}: {e}")
            return None

    def get_valuation(self, address: str, city: str, state: str, zip_code: str) -> Optional[dict]:
        """AVM (automated valuation) for a property."""
        try:
            data = self._get("/avm/value", {
                "address": address,
                "city": city,
                "state": state,
                "zipCode": zip_code,
            })
            time.sleep(self.delay)
            return data
        except Exception as e:
            log.debug(f"Valuation failed for {address}: {e}")
            return None

    def get_rent_estimate(self, address: str, city: str, state: str, zip_code: str,
                          property_type: str = "Multi Family") -> Optional[dict]:
        """Long-term rent estimate."""
        try:
            data = self._get("/avm/rent/long-term", {
                "address": address,
                "city": city,
                "state": state,
                "zipCode": zip_code,
                "propertyType": property_type,
            })
            time.sleep(self.delay)
            return data
        except Exception as e:
            log.debug(f"Rent estimate failed for {address}: {e}")
            return None

    # ── Parsing ───────────────────────────────────────────────────────────────

    def parse_listing(self, raw: dict) -> dict:
        """Normalise a RentCast listing into our DB schema dict."""
        hoa_fee = raw.get("hoaFeeMonthly") or raw.get("hoaFee") or 0
        has_hoa = hoa_fee > 0 or bool(raw.get("hasHoa"))

        # Build full address string
        address = raw.get("addressLine1") or raw.get("address", "")
        city    = raw.get("city", "")
        state   = raw.get("state", "PA")
        zip_c   = raw.get("zipCode", "")
        rc_id   = raw.get("id", "")

        # Sale history from RentCast (if present)
        sale_history = []
        for evt in raw.get("saleHistory", []) or []:
            sale_history.append({
                "date":   evt.get("date") or evt.get("saleDate"),
                "price":  evt.get("price") or evt.get("salePrice"),
                "event":  "Sold",
                "buyer":  evt.get("buyerName"),
                "seller": evt.get("sellerName"),
                "source": "rentcast",
            })

        # Owner info embedded in listing
        owner_name = raw.get("ownerName") or raw.get("owner", {}).get("name") if isinstance(raw.get("owner"), dict) else raw.get("ownerName")
        owner_phone = None
        owner_email = None
        if isinstance(raw.get("owner"), dict):
            owner_phone = raw["owner"].get("phone")
            owner_email = raw["owner"].get("email")

        return {
            # Identity
            "zpid":          f"rc_{rc_id}",    # prefix to avoid collision with Zillow IDs
            "address":       address,
            "city":          city,
            "state":         state,
            "zip_code":      zip_c,
            "latitude":      raw.get("latitude"),
            "longitude":     raw.get("longitude"),
            # Financials
            "price":         raw.get("price") or raw.get("listPrice"),
            "zestimate":     raw.get("estimatedValue"),
            "rent_zestimate": raw.get("estimatedRent"),
            # Property details
            "beds":          raw.get("bedrooms"),
            "baths":         raw.get("bathrooms"),
            "sqft":          raw.get("squareFootage"),
            "lot_size_sqft": raw.get("lotSize"),
            "year_built":    raw.get("yearBuilt"),
            "property_type": raw.get("propertyType", "Multi Family"),
            "unit_count":    raw.get("units") or raw.get("unitCount"),
            "status":        "FOR_SALE",
            "days_on_market": raw.get("daysOnMarket"),
            # HOA
            "hoa_fee":       hoa_fee,
            "has_hoa":       has_hoa,
            # Links
            "zillow_url":    raw.get("zillowUrl"),
            # Extras
            "description":   raw.get("description"),
            "photos":        json.dumps(raw.get("photos") or []),
            "sale_history":  sale_history,
            # Owner (will be saved to Owner table by data_collector)
            "_owner_name":   owner_name,
            "_owner_phone":  owner_phone,
            "_owner_email":  owner_email,
            "source":        "rentcast",
        }

    # ── High-level ────────────────────────────────────────────────────────────

    def fetch_pocono_properties(self) -> list[dict]:
        """
        Fetch all qualifying Pocono multi-family listings.
        Searches by ZIP code to stay within API call budget.
        Returns fully-parsed dicts ready for DB upsert.
        """
        seen_ids = set()
        results = []

        for zip_code in POCONO_ZIPS:
            listings = self.search_by_zip(zip_code, max_price=MAX_PRICE)
            for raw in listings:
                rc_id = raw.get("id", "")
                if rc_id in seen_ids:
                    continue
                seen_ids.add(rc_id)

                parsed = self.parse_listing(raw)

                # Filter: no HOA
                if parsed.get("has_hoa"):
                    log.debug(f"Skipping HOA property: {parsed['address']}")
                    continue

                # Filter: multi-family only
                ptype = (parsed.get("property_type") or "").lower()
                if not any(k in ptype for k in ["multi", "duplex", "triplex", "fourplex", "apartment"]):
                    log.debug(f"Skipping non-multi-family: {parsed['address']} ({ptype})")
                    continue

                results.append(parsed)
                price = parsed.get("price") or 0
                log.info(f"  Kept: {parsed['address']}, {parsed['city']} – ${price:,.0f}")

        log.info(f"\nTotal qualifying properties: {len(results)}")
        return results
