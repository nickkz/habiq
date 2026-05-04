"""
Flask web application – HaBIQ Real Estate Research Tool.
"""
import json
import logging
from datetime import datetime

from flask import Flask, render_template, jsonify, request, abort
from flask_cors import CORS

from database import init_db, get_session, Property, Owner, SaleHistory
from config import FLASK_SECRET_KEY, FLASK_HOST, FLASK_PORT, FLASK_DEBUG, MAP_CENTER_LAT, MAP_CENTER_LNG, MAP_ZOOM

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── NOI Model ────────────────────────────────────────────────────────────────
_VACANCY_RATE     = 0.05   # 5% vacancy allowance
_TAX_RATE         = 0.015  # 1.5% of value/yr  (PA Pocono avg effective rate)
_MAINTENANCE_RATE = 0.01   # 1% of value/yr
_INSURANCE_RATE   = 0.005  # 0.5% of value/yr


def _noi_details(price, zestimate, rent_zestimate):
    """Return full NOI breakdown dict, or None if data is insufficient."""
    value = price or zestimate
    if not rent_zestimate or not value:
        return None
    gross_rent  = rent_zestimate * 12
    vacancy     = gross_rent * _VACANCY_RATE
    egi         = gross_rent - vacancy
    taxes       = value * _TAX_RATE
    maintenance = value * _MAINTENANCE_RATE
    insurance   = value * _INSURANCE_RATE
    expenses    = taxes + maintenance + insurance
    noi         = egi - expenses
    cap_rate    = round(noi / value * 100, 2)
    return {
        "gross_rent":  round(gross_rent),
        "vacancy":     round(vacancy),
        "egi":         round(egi),
        "taxes":       round(taxes),
        "maintenance": round(maintenance),
        "insurance":   round(insurance),
        "expenses":    round(expenses),
        "noi":         round(noi),
        "cap_rate":    cap_rate,
    }

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
CORS(app)

init_db()


# ─── Page Routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template(
        "index.html",
        map_lat=MAP_CENTER_LAT,
        map_lng=MAP_CENTER_LNG,
        map_zoom=MAP_ZOOM,
    )


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.route("/api/properties")
def api_properties():
    """
    GeoJSON endpoint.
    Filters: min_price, max_price, min_beds, county, status,
             market_status (on_market|off_market), property_type
    """
    session = get_session()
    q = session.query(Property)

    min_price     = request.args.get("min_price", type=float)
    max_price     = request.args.get("max_price", type=float)
    min_beds      = request.args.get("min_beds", type=int)
    min_noi       = request.args.get("min_noi", type=int)
    county        = request.args.get("county")
    status        = request.args.get("status")
    market_status = request.args.get("market_status")
    property_type = request.args.get("property_type")

    if min_price:     q = q.filter(Property.price >= min_price)
    if max_price:     q = q.filter(Property.price <= max_price)
    if min_beds:      q = q.filter(Property.beds >= min_beds)
    if county:        q = q.filter(Property.county.ilike(f"%{county}%"))
    if status:        q = q.filter(Property.status == status)
    if market_status: q = q.filter(Property.market_status == market_status)
    if property_type and property_type != "all":
        from sqlalchemy import or_
        if property_type == "multi":
            q = q.filter(or_(
                Property.property_type.ilike("%multi%"),
                Property.property_type.ilike("%duplex%"),
                Property.property_type.ilike("%triplex%"),
                Property.property_type.ilike("%fourplex%"),
                Property.property_type.ilike("%apartment%"),
            ))
        else:
            q = q.filter(Property.property_type.ilike(f"%{property_type}%"))

    properties = q.all()

    # NOI filter applied in Python (computed field, not a DB column)
    if min_noi is not None:
        properties = [
            p for p in properties
            if (nd := _noi_details(p.price, p.zestimate, p.rent_zestimate)) and nd["noi"] >= min_noi
        ]
    features = []
    for prop in properties:
        if prop.latitude is None or prop.longitude is None:
            continue
        owner = prop.owners[0] if prop.owners else None
        # First photo thumbnail
        import json as _json
        first_photo = None
        try:
            photos = _json.loads(prop.photo_urls or prop.photos or "[]")
            first_photo = photos[0] if photos else None
        except Exception:
            pass

        nd = _noi_details(prop.price, prop.zestimate, prop.rent_zestimate)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [prop.longitude, prop.latitude]},
            "properties": {
                "id": prop.id,
                "address": prop.address,
                "city": prop.city,
                "county": prop.county,
                "price": prop.price,
                "zestimate": prop.zestimate,
                "rent_zestimate": prop.rent_zestimate,
                "beds": prop.beds,
                "baths": prop.baths,
                "sqft": prop.sqft,
                "property_type": prop.property_type,
                "status": prop.status,
                "market_status": prop.market_status or "on_market",
                "days_on_market": prop.days_on_market,
                "zillow_url": prop.zillow_url,
                "first_photo": first_photo,
                "noi": nd["noi"] if nd else None,
                "cap_rate": nd["cap_rate"] if nd else None,
                "owner_name":  owner.name if owner else None,
                "owner_phone": owner.phone if owner else None,
                "owner_email": owner.email if owner else None,
                "owner_type":  owner.owner_type if owner else None,
            },
        })

    session.close()
    return jsonify({"type": "FeatureCollection", "features": features})


@app.route("/api/property/<int:property_id>")
def api_property_detail(property_id: int):
    """Full property detail including all owner info and sale history."""
    session = get_session()
    prop = session.query(Property).filter_by(id=property_id).first()

    if not prop:
        session.close()
        abort(404, description="Property not found")

    data = prop.to_dict()
    data["noi_details"] = _noi_details(prop.price, prop.zestimate, prop.rent_zestimate)
    session.close()
    return jsonify(data)


@app.route("/api/stats")
def api_stats():
    session = get_session()
    total      = session.query(Property).count()
    on_market  = session.query(Property).filter(Property.market_status == "on_market").count()
    off_market = session.query(Property).filter(Property.market_status == "off_market").count()
    with_owner = session.query(Property).join(Owner).distinct().count()
    with_phone = session.query(Property).join(Owner).filter(Owner.phone.isnot(None)).distinct().count()
    session.close()
    return jsonify({
        "total_properties": total,
        "on_market":        on_market,
        "off_market":       off_market,
        "with_owner_info":  with_owner,
        "with_phone":       with_phone,
    })


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """
    Trigger a background data refresh.
    In production you'd run this in a Celery task or thread.
    """
    import threading
    from data_collector import collect_properties, enrich_all_owners

    def run():
        collect_properties()
        enrich_all_owners()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return jsonify({"status": "refresh started"})


@app.route("/api/counties")
def api_counties():
    """List of distinct counties in the database."""
    session = get_session()
    rows = session.query(Property.county).distinct().all()
    session.close()
    return jsonify([r[0] for r in rows if r[0]])


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info(f"Starting HaBIQ on http://{FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
