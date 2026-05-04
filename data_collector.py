"""
Data collection orchestrator.

Primary: RentCast API  (set RENTCAST_API_KEY in .env)
Fallback: Zillow/RapidAPI (set RAPIDAPI_KEY + ZILLOW_HOST in .env)
"""
import os
import logging
from datetime import datetime

from database import init_db, get_session, Property, Owner, SaleHistory
from config import SEARCH_LOCATIONS, MAX_PRICE

log = logging.getLogger(__name__)

RENTCAST_KEY = os.getenv("RENTCAST_API_KEY", "")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")


# ── DB helpers ────────────────────────────────────────────────────────────────

def upsert_property(session, parsed: dict) -> Property:
    zpid = parsed.get("zpid")
    prop = session.query(Property).filter_by(zpid=zpid).first() if zpid else None
    if prop is None:
        prop = Property()
        session.add(prop)

    for field in [
        "zpid", "address", "city", "state", "zip_code", "county",
        "latitude", "longitude",
        "price", "zestimate", "rent_zestimate",
        "beds", "baths", "sqft", "lot_size_sqft", "year_built",
        "property_type", "unit_count", "status", "market_status",
        "days_on_market", "hoa_fee", "has_hoa",
        "zillow_url", "redfin_url", "description",
        "photos", "photo_urls", "source",
    ]:
        val = parsed.get(field)
        if val is not None:
            setattr(prop, field, val)

    prop.updated_at = datetime.utcnow()
    session.flush()

    # Sale history
    for event in parsed.get("sale_history", []):
        date_str = event.get("date")
        price = event.get("price")
        if not date_str or not price:
            continue
        try:
            date = datetime.fromisoformat(str(date_str).replace("Z", "").split("T")[0])
        except Exception:
            continue
        if not session.query(SaleHistory).filter_by(property_id=prop.id, date=date, price=price).first():
            session.add(SaleHistory(
                property_id=prop.id, date=date, price=price,
                event=event.get("event"), buyer=event.get("buyer"),
                seller=event.get("seller"), source=event.get("source", "api"),
            ))

    session.commit()
    return prop


def _save_inline_owner(session, prop: Property, parsed: dict):
    name = parsed.get("_owner_name")
    if not name or session.query(Owner).filter_by(property_id=prop.id).first():
        return
    from owner_lookup import _classify_owner
    session.add(Owner(
        property_id=prop.id,
        name=name,
        owner_type=_classify_owner(name),
        mailing_address=parsed.get("_owner_mailing"),
        mailing_city=parsed.get("_owner_city"),
        mailing_state=parsed.get("_owner_state"),
        mailing_zip=parsed.get("_owner_zip"),
        phone=parsed.get("_owner_phone"),
        email=parsed.get("_owner_email"),
        source="rentcast_listing",
    ))
    session.commit()


# ── Collection entry points ───────────────────────────────────────────────────

def collect_properties(dry_run: bool = False, include_offmarket: bool = True) -> int:
    init_db()
    if RENTCAST_KEY:
        return _collect_rentcast(dry_run, include_offmarket)
    elif RAPIDAPI_KEY:
        log.warning("No RENTCAST_API_KEY – falling back to Zillow/RapidAPI.")
        return _collect_zillow(dry_run)
    else:
        log.error(
            "No API key set.\n"
            "  Get a free RentCast key: https://app.rentcast.io/app/api-access\n"
            "  Add to .env: RENTCAST_API_KEY=your_key\n"
            "  Or load demo data: python main.py seed"
        )
        return 0


def _collect_rentcast(dry_run: bool, include_offmarket: bool) -> int:
    from rentcast_client import RentCastClient
    client = RentCastClient()
    session = get_session()
    saved = 0

    # ── On-market ─────────────────────────────────────────────────────────────
    log.info("=== On-market listings ===")
    try:
        on_market = client.fetch_onmarket()
    except Exception as e:
        log.error(f"On-market fetch failed: {e}")
        on_market = []

    on_market_ids = set()
    for p in on_market:
        on_market_ids.add(p.get("zpid", ""))
        if dry_run:
            print(f"  [ON ] {p['address']}, {p['city']} – ${p.get('price', 0):,.0f}")
            saved += 1
            continue
        try:
            prop = upsert_property(session, p)
            _save_inline_owner(session, prop, p)
            saved += 1
        except Exception as e:
            log.error(f"DB error {p.get('address')}: {e}")
            session.rollback()

    # ── Off-market ────────────────────────────────────────────────────────────
    if include_offmarket:
        log.info("=== Off-market sweep ===")
        try:
            off_market = client.fetch_offmarket(on_market_ids)
        except Exception as e:
            log.error(f"Off-market fetch failed: {e}")
            off_market = []

        for p in off_market:
            if dry_run:
                print(f"  [OFF] {p['address']}, {p['city']} – est. ${p.get('zestimate', 0):,.0f}")
                saved += 1
                continue
            try:
                prop = upsert_property(session, p)
                _save_inline_owner(session, prop, p)
                saved += 1
            except Exception as e:
                log.error(f"DB error {p.get('address')}: {e}")
                session.rollback()

    session.close()
    log.info(f"\nTotal saved/updated: {saved}")
    return saved


def _collect_zillow(dry_run: bool) -> int:
    from zillow_client import ZillowClient, ZillowAPIError
    client = ZillowClient()
    session = get_session()
    saved = 0
    for location in SEARCH_LOCATIONS:
        log.info(f"\n=== Zillow: {location} ===")
        try:
            properties = client.fetch_and_filter(location)
        except ZillowAPIError as e:
            log.error(str(e))
            break
        except Exception as e:
            log.error(f"Failed {location}: {e}")
            continue
        for p in properties:
            p.setdefault("county", location.replace(", PA", ""))
            if dry_run:
                print(f"  {p['address']}, {p['city']} – ${p.get('price', 0):,.0f}")
                saved += 1
                continue
            try:
                upsert_property(session, p)
                saved += 1
            except Exception as e:
                log.error(f"DB error {p.get('address')}: {e}")
                session.rollback()
    session.close()
    return saved


def enrich_all_owners() -> int:
    init_db()
    session = get_session()
    props = (
        session.query(Property)
        .outerjoin(Owner)
        .filter(Owner.id.is_(None))
        .all()
    )
    log.info(f"Enriching owners for {len(props)} properties...")
    enriched = 0
    from owner_lookup import enrich_owner
    for prop in props:
        try:
            enrich_owner(prop.id, {
                "address": prop.address, "city": prop.city,
                "state": prop.state, "zip_code": prop.zip_code,
                "county": prop.county, "zpid": prop.zpid,
            }, session)
            enriched += 1
        except Exception as e:
            log.error(f"Owner lookup failed property_id={prop.id}: {e}")
    session.close()
    return enriched
