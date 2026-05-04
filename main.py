#!/usr/bin/env python
"""
HaBIQ – Pocono Mountains Real Estate Research Tool
CLI entry point.

Usage:
  python main.py collect          Fetch properties from Zillow
  python main.py collect --dry    Preview without saving to DB
  python main.py owners           Enrich with owner / contact info
  python main.py all              collect + owners
  python main.py serve            Start the web UI (default: http://localhost:5000)
  python main.py seed             Load sample data for UI testing (no API key needed)
"""
import logging
import click

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


@click.group()
def cli():
    """HaBIQ Real Estate Research Tool – Pocono Mountains, PA"""
    pass


@cli.command()
@click.option("--dry", is_flag=True, help="Preview results without saving to database")
def collect(dry):
    """Fetch multi-family properties from Zillow API."""
    from data_collector import collect_properties
    n = collect_properties(dry_run=dry)
    click.echo(f"\nDone: {n} properties {'previewed' if dry else 'saved'}.")


@cli.command()
def owners():
    """Enrich properties with owner name and contact data."""
    from data_collector import enrich_all_owners
    n = enrich_all_owners()
    click.echo(f"\nDone: owner data enriched for {n} properties.")


@cli.command()
def all():
    """Run full pipeline: collect properties then enrich owners."""
    from data_collector import collect_properties, enrich_all_owners
    click.echo("Step 1/2 – Collecting properties...")
    n1 = collect_properties()
    click.echo(f"\n  -> Saved {n1} properties\n")
    click.echo("Step 2/2 - Enriching owner data...")
    n2 = enrich_all_owners()
    click.echo(f"\n  -> Enriched {n2} owners")
    click.echo(f"\nDone. Open http://localhost:5000 to view the map.")


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=5000, help="Port to listen on")
@click.option("--debug", is_flag=True, help="Enable Flask debug mode")
def serve(host, port, debug):
    """Start the web UI."""
    import webbrowser
    from app import app
    click.echo(f"Starting HaBIQ at http://{host}:{port}")
    click.echo("Press Ctrl+C to stop.\n")
    webbrowser.open(f"http://{host}:{port}", new=2)
    app.run(host=host, port=port, debug=debug)


@cli.command()
def seed():
    """
    Load sample/demo data into the database so you can test the UI
    without a RapidAPI key.
    """
    import json
    from datetime import datetime, timedelta
    from database import init_db, get_session, Property, Owner, SaleHistory

    init_db()
    session = get_session()

    SAMPLE_PROPERTIES = [
        {
            "zpid": "demo-001",
            "address": "123 Mountain Rd",
            "city": "Stroudsburg",
            "state": "PA",
            "zip_code": "18360",
            "county": "Monroe County",
            "latitude": 41.0010,
            "longitude": -75.1940,
            "price": 289000,
            "zestimate": 295000,
            "rent_zestimate": 2800,
            "beds": 4,
            "baths": 2.0,
            "sqft": 2100,
            "year_built": 1988,
            "property_type": "MultiFamily2To4",
            "unit_count": 2,
            "status": "FOR_SALE", "market_status": "on_market",
            "days_on_market": 14, "hoa_fee": 0, "has_hoa": False,
            "zillow_url": "https://www.zillow.com",
            "description": "Duplex in great condition. Each unit has 2 bed/1 bath. Separate utilities.",
            "photo_urls": '["https://photos.zillowstatic.com/fp/demo1a.jpg","https://photos.zillowstatic.com/fp/demo1b.jpg"]',
        },
        {
            "zpid": "demo-002", "address": "456 Lake View Dr", "city": "East Stroudsburg",
            "state": "PA", "zip_code": "18301", "county": "Monroe County",
            "latitude": 41.0050, "longitude": -75.1820,
            "price": 349000, "zestimate": 360000, "rent_zestimate": 3400,
            "beds": 6, "baths": 3.0, "sqft": 3200, "year_built": 1995,
            "property_type": "Multi Family", "unit_count": 3,
            "status": "FOR_SALE", "market_status": "on_market",
            "days_on_market": 30, "hoa_fee": 0, "has_hoa": False,
            "zillow_url": "https://www.zillow.com",
            "description": "Triplex near Delaware Water Gap. All units occupied. Excellent cash flow.",
            "photo_urls": '[]',
        },
        {
            "zpid": "demo-003", "address": "789 Pocono Blvd", "city": "Mount Pocono",
            "state": "PA", "zip_code": "18344", "county": "Monroe County",
            "latitude": 41.1234, "longitude": -75.3456,
            "price": None, "zestimate": 210000, "rent_zestimate": 2100,
            "beds": 4, "baths": 2.0, "sqft": 1800, "year_built": 1975,
            "property_type": "Multi Family", "unit_count": 2,
            "status": "OFF_MARKET", "market_status": "off_market",
            "days_on_market": None, "hoa_fee": 0, "has_hoa": False,
            "zillow_url": None,
            "description": "Well-maintained duplex. Owner not listed – off-market opportunity.",
            "photo_urls": '[]',
        },
        {
            "zpid": "demo-004", "address": "22 Milford Pike", "city": "Milford",
            "state": "PA", "zip_code": "18337", "county": "Pike County",
            "latitude": 41.3211, "longitude": -74.7989,
            "price": 375000, "zestimate": 385000, "rent_zestimate": 3800,
            "beds": 8, "baths": 4.0, "sqft": 4200, "year_built": 2001,
            "property_type": "Multi Family", "unit_count": 4,
            "status": "FOR_SALE", "market_status": "on_market",
            "days_on_market": 7, "hoa_fee": 0, "has_hoa": False,
            "zillow_url": "https://www.zillow.com",
            "description": "Fourplex in Pike County. All units 2BR/1BA. Fully occupied.",
            "photo_urls": '[]',
        },
        {
            "zpid": "demo-005", "address": "91 Carbon Creek Rd", "city": "Jim Thorpe",
            "state": "PA", "zip_code": "18229", "county": "Carbon County",
            "latitude": 40.8785, "longitude": -75.7352,
            "price": None, "zestimate": 235000, "rent_zestimate": 2400,
            "beds": 4, "baths": 2.0, "sqft": 2000, "year_built": 1982,
            "property_type": "Multi Family", "unit_count": 2,
            "status": "OFF_MARKET", "market_status": "off_market",
            "days_on_market": None, "hoa_fee": 0, "has_hoa": False,
            "zillow_url": None,
            "description": "Historic Jim Thorpe duplex. Off-market – direct owner contact needed.",
            "photo_urls": '[]',
        },
    ]

    SAMPLE_OWNERS = [
        {"name": "Robert & Linda Meyers", "owner_type": "Individual",
         "mailing_address": "123 Mountain Rd", "mailing_city": "Stroudsburg",
         "mailing_state": "PA", "mailing_zip": "18360",
         "phone": "(570) 555-0101", "email": "rmeyers@example.com",
         "source": "seed_data"},
        {"name": "Pocono Properties LLC", "owner_type": "LLC",
         "mailing_address": "PO Box 1200", "mailing_city": "East Stroudsburg",
         "mailing_state": "PA", "mailing_zip": "18301",
         "phone": "(570) 555-0202", "email": "info@poconoproperties.example",
         "source": "seed_data"},
        {"name": "James Thornton", "owner_type": "Individual",
         "mailing_address": "45 Oak Lane", "mailing_city": "Mount Pocono",
         "mailing_state": "PA", "mailing_zip": "18344",
         "phone": "(570) 555-0303", "email": None,
         "source": "seed_data"},
        {"name": "Milford Real Estate Holdings LLC", "owner_type": "LLC",
         "mailing_address": "100 Broad St", "mailing_city": "Milford",
         "mailing_state": "PA", "mailing_zip": "18337",
         "phone": "(570) 555-0404", "email": "contact@milfordre.example",
         "source": "seed_data"},
        {"name": "Sarah & Dennis Park", "owner_type": "Individual",
         "mailing_address": "12 Maple Ave", "mailing_city": "Jim Thorpe",
         "mailing_state": "PA", "mailing_zip": "18229",
         "phone": "(570) 555-0505", "email": "sdpark@example.com",
         "source": "seed_data"},
    ]

    SALE_HISTORIES = [
        [{"date": "2019-06-15", "price": 215000, "event": "Sold"},
         {"date": "2023-01-10", "price": 279000, "event": "Listed"}],
        [{"date": "2015-03-22", "price": 280000, "event": "Sold"},
         {"date": "2024-08-05", "price": 345000, "event": "Listed"}],
        [{"date": "2010-11-01", "price": 140000, "event": "Sold"},
         {"date": "2022-04-20", "price": 185000, "event": "Price Change"},
         {"date": "2024-11-01", "price": 199000, "event": "Listed"}],
        [{"date": "2018-09-30", "price": 320000, "event": "Sold"},
         {"date": "2025-01-15", "price": 375000, "event": "Listed"}],
        [{"date": "2012-05-05", "price": 175000, "event": "Sold"},
         {"date": "2024-07-20", "price": 229000, "event": "Listed"}],
    ]

    for i, prop_data in enumerate(SAMPLE_PROPERTIES):
        existing = session.query(Property).filter_by(zpid=prop_data["zpid"]).first()
        if existing:
            click.echo(f"  Skip (exists): {prop_data['address']}")
            prop = existing
        else:
            prop = Property(**prop_data)
            session.add(prop)
            session.flush()

            # Add owner
            owner_data = SAMPLE_OWNERS[i]
            session.add(Owner(property_id=prop.id, **owner_data))

            # Add sale history
            for sh in SALE_HISTORIES[i]:
                session.add(SaleHistory(
                    property_id=prop.id,
                    date=datetime.fromisoformat(sh["date"]),
                    price=sh["price"],
                    event=sh["event"],
                    source="seed_data",
                ))

            click.echo(f"  Added: {prop_data['address']}, {prop_data['city']}")

    session.commit()
    session.close()
    click.echo(f"\nSeed data loaded. Run: python main.py serve")


if __name__ == "__main__":
    cli()
