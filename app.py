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
    Return all qualifying properties as GeoJSON for the map.
    Query params: min_price, max_price, min_beds, county, status
    """
    session = get_session()
    q = session.query(Property)

    # Filters
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    min_beds = request.args.get("min_beds", type=int)
    county = request.args.get("county")
    status = request.args.get("status")

    if min_price:
        q = q.filter(Property.price >= min_price)
    if max_price:
        q = q.filter(Property.price <= max_price)
    if min_beds:
        q = q.filter(Property.beds >= min_beds)
    if county:
        q = q.filter(Property.county.ilike(f"%{county}%"))
    if status:
        q = q.filter(Property.status == status)

    properties = q.all()

    features = []
    for prop in properties:
        if prop.latitude is None or prop.longitude is None:
            continue

        owner = prop.owners[0] if prop.owners else None

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [prop.longitude, prop.latitude],
            },
            "properties": {
                "id": prop.id,
                "address": prop.address,
                "city": prop.city,
                "county": prop.county,
                "price": prop.price,
                "zestimate": prop.zestimate,
                "beds": prop.beds,
                "baths": prop.baths,
                "sqft": prop.sqft,
                "property_type": prop.property_type,
                "status": prop.status,
                "zillow_url": prop.zillow_url,
                "owner_name": owner.name if owner else None,
                "owner_phone": owner.phone if owner else None,
                "owner_email": owner.email if owner else None,
                "owner_type": owner.owner_type if owner else None,
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
    session.close()
    return jsonify(data)


@app.route("/api/stats")
def api_stats():
    """Summary statistics for the dashboard header."""
    session = get_session()
    total = session.query(Property).count()
    with_owner = (
        session.query(Property)
        .join(Owner)
        .distinct()
        .count()
    )
    with_phone = (
        session.query(Property)
        .join(Owner)
        .filter(Owner.phone.isnot(None))
        .distinct()
        .count()
    )
    session.close()

    return jsonify({
        "total_properties": total,
        "with_owner_info": with_owner,
        "with_phone": with_phone,
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
