"""
SQLAlchemy models and database helpers.
"""
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship, Session
from config import DATABASE_PATH

Base = declarative_base()
_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(f"sqlite:///{DATABASE_PATH}", echo=False)
    return _engine


def init_db():
    Base.metadata.create_all(get_engine())


def get_session() -> Session:
    return Session(get_engine())


# ─── Models ───────────────────────────────────────────────────────────────────

class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True)
    zpid = Column(String, unique=True, index=True)          # Zillow property ID
    address = Column(String, nullable=False)
    city = Column(String)
    state = Column(String)
    zip_code = Column(String)
    county = Column(String)

    latitude = Column(Float)
    longitude = Column(Float)

    price = Column(Float)                                   # Listed / last sale price
    zestimate = Column(Float)                               # Zillow Zestimate
    rent_zestimate = Column(Float)

    beds = Column(Integer)
    baths = Column(Float)
    sqft = Column(Integer)
    lot_size_sqft = Column(Integer)
    year_built = Column(Integer)

    property_type = Column(String)                          # MultiFamily2To4, etc.
    unit_count = Column(Integer)
    status = Column(String)                                 # FOR_SALE, RECENTLY_SOLD
    days_on_market = Column(Integer)

    hoa_fee = Column(Float, default=0)                      # 0 = no HOA
    has_hoa = Column(Boolean, default=False)

    zillow_url = Column(String)
    redfin_url = Column(String)
    description = Column(Text)
    photos = Column(Text)                                   # JSON list of photo URLs

    source = Column(String, default="zillow")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    owners = relationship("Owner", back_populates="property", cascade="all, delete-orphan")
    sale_history = relationship("SaleHistory", back_populates="property",
                                cascade="all, delete-orphan", order_by="SaleHistory.date.desc()")

    def to_dict(self):
        return {
            "id": self.id,
            "zpid": self.zpid,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "zip_code": self.zip_code,
            "county": self.county,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "price": self.price,
            "zestimate": self.zestimate,
            "rent_zestimate": self.rent_zestimate,
            "beds": self.beds,
            "baths": self.baths,
            "sqft": self.sqft,
            "lot_size_sqft": self.lot_size_sqft,
            "year_built": self.year_built,
            "property_type": self.property_type,
            "unit_count": self.unit_count,
            "status": self.status,
            "days_on_market": self.days_on_market,
            "hoa_fee": self.hoa_fee,
            "has_hoa": self.has_hoa,
            "zillow_url": self.zillow_url,
            "redfin_url": self.redfin_url,
            "description": self.description,
            "owners": [o.to_dict() for o in self.owners],
            "sale_history": [s.to_dict() for s in self.sale_history],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Owner(Base):
    __tablename__ = "owners"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)

    name = Column(String)
    owner_type = Column(String)          # Individual, LLC, Corporation, Trust
    mailing_address = Column(String)
    mailing_city = Column(String)
    mailing_state = Column(String)
    mailing_zip = Column(String)

    phone = Column(String)
    email = Column(String)
    linkedin_url = Column(String)

    source = Column(String)              # county_records, skip_trace, manual
    skip_traced = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    property = relationship("Property", back_populates="owners")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "owner_type": self.owner_type,
            "mailing_address": self.mailing_address,
            "mailing_city": self.mailing_city,
            "mailing_state": self.mailing_state,
            "mailing_zip": self.mailing_zip,
            "phone": self.phone,
            "email": self.email,
            "source": self.source,
            "skip_traced": self.skip_traced,
        }


class SaleHistory(Base):
    __tablename__ = "sale_history"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)

    date = Column(DateTime)
    price = Column(Float)
    event = Column(String)               # Sold, Listed, Price Change, etc.
    buyer = Column(String)
    seller = Column(String)
    source = Column(String)

    property = relationship("Property", back_populates="sale_history")

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "price": self.price,
            "event": self.event,
            "buyer": self.buyer,
            "seller": self.seller,
            "source": self.source,
        }
