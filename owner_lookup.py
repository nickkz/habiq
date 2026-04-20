"""
Owner research and skip-trace module.

Data sources (in priority order):
  1. Zillow attribution info (already in property data)
  2. PA county public assessment portals (scrape)
  3. BatchSkipTracing API (paid – set BATCH_SKIP_TRACE_KEY in .env)
  4. TruePeopleSearch (free, rate-limited fallback)

For LLC / corporate owners, the tool will note the entity name and flag
it for manual lookup in the PA Secretary of State entity search:
  https://www.corporations.pa.gov/search/corpsearch
"""
import logging
import time
import re
import json
from typing import Optional

import requests
from config import BATCH_SKIP_TRACE_KEY

log = logging.getLogger(__name__)


# ─── County Assessment Scrapers ───────────────────────────────────────────────

COUNTY_PORTALS = {
    "Monroe County": "https://propertyinfo.monroecountypa.gov/",
    "Pike County":   "https://pike.assessorpro.com/",
    "Wayne County":  "https://property.co.wayne.pa.us/",
    "Carbon County": "https://carbon.assessorpro.com/",
}

# Monroe County uses iAssets / PropertyInfo portal
# Pike & Carbon use AssessorPro
# Wayne County uses a custom portal


def _clean_owner_name(name: str) -> str:
    """Normalize owner name – remove trailing LLC / INC / etc suffixes noise."""
    return name.strip().title() if name else ""


def lookup_from_zillow_data(property_dict: dict) -> Optional[dict]:
    """Extract owner info from already-fetched Zillow property data."""
    name = property_dict.get("listing_agent_name")
    phone = property_dict.get("listing_agent_phone")
    if name:
        return {
            "name": name,
            "phone": phone,
            "source": "zillow_listing_agent",
            "owner_type": "Individual",
        }
    return None


def lookup_monroe_county(address: str, zpid: str = None) -> Optional[dict]:
    """
    Query Monroe County Property Info portal.
    Returns owner name + mailing address if found.
    """
    try:
        # Monroe County uses iAssets search API
        search_url = "https://propertyinfo.monroecountypa.gov/api/v1/parcels/search"
        resp = requests.get(
            search_url,
            params={"query": address},
            headers={"User-Agent": "Mozilla/5.0 HaBIQ Real Estate Tool"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        results = data.get("results") or data.get("parcels") or []
        if not results:
            return None

        parcel = results[0]
        owner_name = parcel.get("ownerName") or parcel.get("owner_name", "")
        mailing = parcel.get("mailingAddress") or {}

        return {
            "name": _clean_owner_name(owner_name),
            "mailing_address": mailing.get("street", ""),
            "mailing_city": mailing.get("city", ""),
            "mailing_state": mailing.get("state", ""),
            "mailing_zip": mailing.get("zip", ""),
            "source": "monroe_county_records",
            "owner_type": _classify_owner(owner_name),
        }
    except Exception as e:
        log.debug(f"Monroe County lookup failed for {address!r}: {e}")
        return None


def _classify_owner(name: str) -> str:
    """Guess owner entity type from name."""
    name_upper = (name or "").upper()
    if any(k in name_upper for k in ["LLC", "L.L.C", "LP", "LTD"]):
        return "LLC"
    if any(k in name_upper for k in ["INC", "CORP", "CO.", "COMPANY", "ENTERPRISES"]):
        return "Corporation"
    if any(k in name_upper for k in ["TRUST", "TRUSTEE", "ESTATE"]):
        return "Trust"
    return "Individual"


# ─── BatchSkipTracing ─────────────────────────────────────────────────────────

def batch_skip_trace(records: list[dict]) -> list[dict]:
    """
    Send a batch of address records to BatchSkipTracing.com for phone/email lookup.

    Each record should have: first_name OR full_name, address, city, state, zip.
    Returns enriched records with phone, email fields populated.

    Docs: https://batchskiptracing.com/api
    """
    if not BATCH_SKIP_TRACE_KEY:
        log.warning("BATCH_SKIP_TRACE_KEY not set – skipping skip trace.")
        return records

    # BatchSkipTracing expects CSV upload or JSON array
    url = "https://api.batchskiptracing.com/api/v2/lookup"
    headers = {
        "Authorization": f"Bearer {BATCH_SKIP_TRACE_KEY}",
        "Content-Type": "application/json",
    }

    enriched = []
    BATCH_SIZE = 50  # API limit per request

    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        payload = []
        for r in batch:
            parts = (r.get("name") or "").split(" ", 1)
            payload.append({
                "firstName": parts[0] if parts else "",
                "lastName": parts[1] if len(parts) > 1 else "",
                "address": r.get("mailing_address", r.get("address", "")),
                "city": r.get("mailing_city", r.get("city", "")),
                "state": r.get("mailing_state", r.get("state", "PA")),
                "zip": r.get("mailing_zip", r.get("zip_code", "")),
            })

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            for j, result in enumerate(results):
                rec = batch[j].copy()
                phones = result.get("phones", [])
                emails = result.get("emails", [])
                rec["phone"] = phones[0].get("number") if phones else None
                rec["email"] = emails[0].get("address") if emails else None
                rec["skip_traced"] = True
                enriched.append(rec)
        except Exception as e:
            log.error(f"BatchSkipTrace API error: {e}")
            enriched.extend(batch)  # Return unenriched on failure

        time.sleep(1)

    return enriched


# ─── TruePeopleSearch (free fallback for individuals) ─────────────────────────

def truepeoplesearch_lookup(name: str, city: str, state: str = "PA") -> Optional[dict]:
    """
    Attempt a free people search for individual owners.
    Rate-limited – use sparingly.
    """
    if not name or _classify_owner(name) != "Individual":
        return None

    try:
        encoded_name = requests.utils.quote(name)
        encoded_city = requests.utils.quote(f"{city}, {state}")
        url = f"https://www.truepeoplesearch.com/results?name={encoded_name}&citystatezip={encoded_city}"

        resp = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            return None

        # Extract phone numbers from response HTML (basic regex)
        phones = re.findall(r"\((\d{3})\)\s*(\d{3})-(\d{4})", resp.text)
        if phones:
            area, prefix, number = phones[0]
            return {"phone": f"({area}) {prefix}-{number}", "source": "truepeoplesearch"}
    except Exception as e:
        log.debug(f"TruePeopleSearch failed for {name!r}: {e}")

    return None


# ─── Orchestrator ─────────────────────────────────────────────────────────────

def enrich_owner(property_id: int, property_dict: dict, session) -> None:
    """
    Main entry: look up owner for a property and upsert into the DB.
    """
    from database import Owner  # avoid circular import at module level

    address = property_dict.get("address", "")
    city = property_dict.get("city", "")
    county = property_dict.get("county", "")
    zpid = property_dict.get("zpid")

    # 1. Try Zillow listing attribution
    owner_data = lookup_from_zillow_data(property_dict)

    # 2. Try county assessment portal
    if not owner_data:
        owner_data = lookup_monroe_county(address, zpid)

    # 3. If we have an individual name, try people search
    if owner_data and owner_data.get("owner_type") == "Individual" and not owner_data.get("phone"):
        people_data = truepeoplesearch_lookup(owner_data["name"], city)
        if people_data:
            owner_data["phone"] = people_data.get("phone")

    if not owner_data:
        log.debug(f"No owner data found for property_id={property_id}, address={address!r}")
        return

    # Upsert owner record
    existing = session.query(Owner).filter_by(property_id=property_id).first()
    if existing:
        for k, v in owner_data.items():
            if v is not None:
                setattr(existing, k, v)
    else:
        owner = Owner(
            property_id=property_id,
            name=owner_data.get("name"),
            owner_type=owner_data.get("owner_type", "Individual"),
            mailing_address=owner_data.get("mailing_address"),
            mailing_city=owner_data.get("mailing_city"),
            mailing_state=owner_data.get("mailing_state"),
            mailing_zip=owner_data.get("mailing_zip"),
            phone=owner_data.get("phone"),
            email=owner_data.get("email"),
            source=owner_data.get("source"),
            skip_traced=owner_data.get("skip_traced", False),
        )
        session.add(owner)

    session.commit()
    log.info(f"Owner saved for {address!r}: {owner_data.get('name')}")
