import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Keys ─────────────────────────────────────────────────────────────────
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
BATCH_SKIP_TRACE_KEY = os.getenv("BATCH_SKIP_TRACE_KEY", "")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-prod")

# ─── Database ─────────────────────────────────────────────────────────────────
DATABASE_PATH = os.path.join(os.path.dirname(__file__), "habiq.db")

# ─── Search Parameters ────────────────────────────────────────────────────────
MAX_PRICE = 400_000

# Zillow homeType values for multi-family
MULTI_FAMILY_TYPES = ["MultiFamily2To4"]

# Pocono Mountains – 4 primary counties
SEARCH_LOCATIONS = [
    "Monroe County, PA",
    "Pike County, PA",
    "Wayne County, PA",
    "Carbon County, PA",
]

# Pocono Mountains area ZIP codes (Monroe + Pike + southern Wayne + Carbon)
POCONO_ZIPS = [
    # Monroe County
    "18301", "18302", "18321", "18322", "18324", "18326", "18327",
    "18331", "18334", "18344", "18346", "18347", "18349", "18350",
    "18352", "18353", "18355", "18360", "18370", "18372",
    # Pike County
    "18328", "18337", "18338", "18340", "18341", "18342", "18343",
    "18371", "18373", "18374", "18375",
    # Wayne County (southern)
    "18414", "18415", "18426", "18428", "18431", "18435", "18436",
    "18438", "18443", "18445", "18447", "18449", "18451", "18452",
    # Carbon County
    "18210", "18216", "18229", "18235", "18240", "18250", "18255",
]

# ─── Map ──────────────────────────────────────────────────────────────────────
MAP_CENTER_LAT = 41.1534
MAP_CENTER_LNG = -75.2021
MAP_ZOOM = 10

# ─── Flask ────────────────────────────────────────────────────────────────────
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
