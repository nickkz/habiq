"""
Test your API keys before running a full collect.

  python diagnose_api.py                  (reads from .env)
  python diagnose_api.py RENTCAST_KEY     (test RentCast key directly)
"""
import sys
import os
import time
import json
import requests
from dotenv import load_dotenv

load_dotenv()

def fmt(body: str, limit=200) -> str:
    return body[:limit] + ("…" if len(body) > limit else "")

# ── RentCast ──────────────────────────────────────────────────────────────────
rc_key = sys.argv[1] if len(sys.argv) > 1 else os.getenv("RENTCAST_API_KEY", "")

print("\n=== RentCast API ===")
if not rc_key:
    print("  RENTCAST_API_KEY not set. Get a free key at:")
    print("  https://app.rentcast.io/app/api-access\n")
else:
    print(f"  Key: {rc_key[:6]}...{rc_key[-4:]}")
    url = "https://api.rentcast.io/v1/listings/sale"
    params = {
        "zipCode": "18360",           # Stroudsburg, PA
        "propertyType": "Multi Family",
        "maxPrice": "400000",
        "status": "Active",
        "limit": "5",
    }
    try:
        resp = requests.get(url, headers={"X-Api-Key": rc_key}, params=params, timeout=15)
        body = ""
        try:
            data = resp.json()
            count = len(data) if isinstance(data, list) else len(data.get("data", []))
            body = f"{count} listings returned"
        except Exception:
            body = fmt(resp.text)

        mark = "OK" if resp.status_code == 200 else f"HTTP {resp.status_code}"
        print(f"  [{mark}] GET /listings/sale?zipCode=18360&propertyType=Multi+Family")
        print(f"          {body}")

        if resp.status_code == 200:
            print("\n  RentCast is working! Run:")
            print("    python main.py collect")
        elif resp.status_code == 401:
            print("\n  401 = invalid key. Double-check RENTCAST_API_KEY in .env")
        elif resp.status_code == 403:
            print("\n  403 = key valid but plan doesn't include this endpoint.")
            print("  Check your plan at https://app.rentcast.io/app/api-access")
    except Exception as e:
        print(f"  [ERROR] {e}")

# ── RapidAPI / Zillow (optional fallback) ─────────────────────────────────────
rapi_key = os.getenv("RAPIDAPI_KEY", "")
zillow_host = os.getenv("ZILLOW_HOST", "zillow56.p.rapidapi.com")

print(f"\n=== RapidAPI / Zillow (fallback) ===")
if not rapi_key:
    print("  RAPIDAPI_KEY not set (optional if using RentCast).")
else:
    print(f"  Key : {rapi_key[:6]}...{rapi_key[-4:]}")
    print(f"  Host: {zillow_host}")
    url = f"https://{zillow_host}/search"
    params = {"location": "18360", "home_type": "MultiFamily2To4", "price_max": "400000"}
    try:
        resp = requests.get(url,
            headers={"x-rapidapi-key": rapi_key, "x-rapidapi-host": zillow_host},
            params=params, timeout=15)
        try:
            data = resp.json()
            count = len(data.get("results", data.get("props", [])))
            body = f"{count} results"
        except Exception:
            body = fmt(resp.text)
        mark = "OK" if resp.status_code == 200 else f"HTTP {resp.status_code}"
        print(f"  [{mark}] GET /search  → {body}")
    except Exception as e:
        print(f"  [ERROR] {e}")

print()
