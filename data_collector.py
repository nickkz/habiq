"""
Main data collection orchestrator.

Primary source: RentCast API (set RENTCAST_API_KEY in .env)
Fallback:       Zillow via RapidAPI (set RAPIDAPI_KEY + ZILLOW_HOST in .env)

Run via main.py:
  python main.py collect   – fetch property listings
  python main.py owners    – enrich with owner / contact data
  python main.py all       – run both steps
"""
import os
import logging
from datetime import datetime

from database import init_db, get_session, Property, Owner, SaleHistory
from config import SEARCH_LOCATIONS, MAX_PRICE

log = logging.getLogger(__name__)

RENTCAST_KEY = os.getenv("RENTCAST_API_KEY", "")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")


def upsert_property(session, parsed: dict) -> Property:
    """Insert or update a Property record. Returns the ORM object."""
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
        "property_type", "unit_count", "status", "days_on_market",
        "hoa_fee", "has_hoa",
        "zillow_url", "redfin_url", "description", "photos", "source",
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
            date = datetime.fromisoformat(str(date_str).replace("Z", ""))
        except Exception:
            continue

        existing = session.query(SaleHistory).filter_by(
            property_id=prop.id, date=date, price=price
        ).first()
        if not existing:
            session.add(SaleHistory(
                property_id=prop.id,
                date=date,
                price=price,
                event=event.get("event"),
                buyer=event.get("buyer"),
                seller=event.get("seller"),
                source=event.get("source", "api"),
            ))

    session.commit()
    return prop


def _save_inline_owner(session, prop: Property, parsed: dict):
    """If the API returned owner info directly in the listing, save it."""
    name = parsed.get("_owner_name")
    if not name:
        return
    existing = session.query(Owner).filter_by(property_id=prop.id).first()
    if existing:
        return
    from owner_lookup import _classify_owner
    session.add(Owner(
        property_id=prop.id,
        name=name,
        owner_type=_classify_owner(name),
        phone=parsed.get("_owner_phone"),
        email=parsed.get("_owner_email"),
        source="rentcast_listing",
    ))
    session.commit()


def collect_properties(dry_run: bool = False) -> int:
    """
    Fetch qualifying properties and store in DB.
    Uses RentCast if RENTCAST_API_KEY is set, otherwise Zillow.
    Returns number of properties saved.
    """
    init_db()

    if RENTCAST_KEY:
        return _collect_rentcast(dry_run)
    elif RAPIDAPI_KEY:
        log.warning("RENTCAST_API_KEY not set – falling back to Zillow/RapidAPI.")
        return _collect_zillow(dry_run)
    else:
        log.error(
            "No API key configured.\n"
            "  Set RENTCAST_API_KEY in your .env file.\n"
            "  Get a free key at: https://app.rentcast.io/app/api-access\n"
            "  Or run: python main.py seed   (to load demo data)"
        )
        return 0


def _collect_rentcast(dry_run: bool) -> int:
    from rentcast_client import RentCastClient
    client = RentCastClient()
    session = get_session()
    saved = 0

    log.info("=== Collecting via RentCast API ===")
    try:
        properties = client.fetch_pocono_properties()
    except Exception as e:
        log.error(f"RentCast collection failed: {e}")
        session.close()
        return 0

    for p in properties:
        if dry_run:
            print(f"  [DRY RUN] {p['address']}, {p['city']} – ${p.get('price', 0):,.0f}")
            saved += 1
            continue
        try:
            prop = upsert_property(session, p)
            _save_inline_owner(session, prop, p)
            saved += 1
            log.info(f"  Saved: {p['address']}, {p['city']}")
        except Exception as e:
            log.error(f"  DB error for {p.get('address')}: {e}")
            session.rollback()

    session.close()
    log.info(f"\nRentCast: {saved} properties {'previewed' if dry_run else 'saved/updated'}.")
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
            log.error(f"Failed to fetch {location}: {e}")
            continue

        for p in properties:
            p.setdefault("county", location.replace(", PA", ""))
            if dry_run:
                print(f"  [DRY RUN] {p['address']}, {p['city']} – ${p.get('price', 0):,.0f}")
                saved += 1
                continue
            try:
                upsert_property(session, p)
                saved += 1
            except Exception as e:
                log.error(f"  DB error for {p.get('address')}: {e}")
                session.rollback()

    session.close()
    log.info(f"\nZillow: {saved} properties {'previewed' if dry_run else 'saved/updated'}.")
    return saved


def enrich_all_owners() -> int:
    """
    For all properties without owner data, attempt owner lookup.
    Returns number of properties enriched.
    """
    init_db()
    session = get_session()

    props_without_owner = (
        session.query(Property)
        .outerjoin(Owner)
        .filter(Owner.id.is_(None))
        .all()
    )

    log.info(f"Enriching owner data for {len(props_without_owner)} properties...")
    enriched = 0

    from owner_lookup import enrich_owner
    for prop in props_without_owner:
        prop_dict = {
            "address": prop.address,
            "city": prop.city,
            "state": prop.state,
            "zip_code": prop.zip_code,
            "county": prop.county,
            "zpid": prop.zpid,
        }
        try:
            enrich_owner(prop.id, prop_dict, session)
            enriched += 1
        except Exception as e:
            log.error(f"Owner lookup failed for property_id={prop.id}: {e}")

    session.close()
    log.info(f"Owner data enriched for {enriched} properties.")
    return enriched
