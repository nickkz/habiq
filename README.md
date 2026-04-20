# HaBIQ – Pocono Mountains Real Estate Research Tool

Finds **multi-family properties < $400K with no HOA** across Monroe, Pike, Wayne, and Carbon counties, PA. Displays them on an interactive map with owner name, phone, email, sale history, and Zillow valuation.

## Quick Start (demo data – no API key needed)

```
cd C:\dev\habiq
python main.py seed     # load 5 sample properties
python main.py serve    # opens browser at http://localhost:5000
```

## Full Setup (live Zillow data)

### 1. Install dependencies
```
pip install -r requirements.txt
```

### 2. Get a RapidAPI key
1. Sign up at https://rapidapi.com
2. Subscribe to the **zillow56** API (free tier: 50 requests/month)
3. Copy your key from the API dashboard

### 3. Configure
```
copy .env.example .env
# Edit .env and set RAPIDAPI_KEY=your_key_here
```

### 4. Collect data
```
python main.py collect       # fetch properties from Zillow
python main.py owners        # look up owner contact info
python main.py serve         # launch map UI
```

Or run everything at once:
```
python main.py all
```

## Owner Contact Data

Owner data comes from three sources (in priority order):

| Source | What it provides | Cost |
|--------|-----------------|------|
| Zillow listing attribution | Listing agent name + phone | Free |
| Monroe County assessment portal | Owner name + mailing address | Free (public records) |
| BatchSkipTracing API | Phone + email for individuals | ~$0.15/record |

To enable skip-tracing:
1. Sign up at https://batchskiptracing.com
2. Set `BATCH_SKIP_TRACE_KEY=your_key` in `.env`

For LLC/corporate owners, the tool shows the entity name. Look up the registered agent at:
https://www.corporations.pa.gov/search/corpsearch

## Map UI Features

- **Color-coded markers**: green (<$200K), yellow ($200-300K), red ($300-400K)
- **Filters**: price range, min beds, county, listing status
- **Click any marker** → see owner name, phone, email, sale history chart, Zillow Zestimate, GRM, estimated cap rate
- **Refresh Data** button triggers a live re-pull from Zillow

## CLI Commands

| Command | Description |
|---------|-------------|
| `python main.py seed` | Load demo data (no API key needed) |
| `python main.py collect` | Fetch live property listings |
| `python main.py collect --dry` | Preview without saving to DB |
| `python main.py owners` | Enrich all properties with owner info |
| `python main.py all` | Run collect + owners |
| `python main.py serve` | Launch web UI |

## Project Structure

```
habiq/
├── main.py              CLI entry point
├── app.py               Flask web server
├── config.py            Configuration & API keys
├── database.py          SQLAlchemy models (SQLite)
├── zillow_client.py     Zillow API via RapidAPI
├── owner_lookup.py      Owner research & skip trace
├── data_collector.py    Collection orchestrator
├── templates/index.html Map UI
├── static/css/style.css Dark theme stylesheet
├── static/js/map.js     Leaflet map + UI logic
└── habiq.db             SQLite database (auto-created)
```

## Adding More Counties

Edit `SEARCH_LOCATIONS` in `config.py`:
```python
SEARCH_LOCATIONS = [
    "Monroe County, PA",
    "Pike County, PA",
    "Wayne County, PA",
    "Carbon County, PA",
    "Luzerne County, PA",   # add more here
]
```
