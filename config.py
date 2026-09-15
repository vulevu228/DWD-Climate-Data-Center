"""
Static configuration for the DWD Climate Data Center (CDC) pipeline.

Deutscher Wetterdienst (DWD) publishes decades of German weather-station data
as plain files on a public HTTPS server - no account, no API key, no request
limit stated beyond "be reasonable". This file only holds constants: which
station networks to pull, where their files live on the server, and the local
folder layout. All the fetching/parsing logic lives in dwd_engine.py.

See API_ACCESS.txt for the full explanation of the server layout and how to
browse it by hand.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RAW = BASE_DIR / "raw"     # untouched downloads (zips + station lists), git-ignored
DATA = BASE_DIR / "data"   # parsed Parquet output - this is what Power BI reads
LOGS = BASE_DIR / "logs"   # Task Scheduler run log
for _p in (RAW, DATA, LOGS):
    _p.mkdir(exist_ok=True)

# Root of the "daily" resolution. Everything this project pulls sits one level
# below here: <DAILY_ROOT><network>/{historical,recent}/ plus a station list.
# DWD also publishes 1_minute, 10_minutes, hourly, monthly, annual and
# multi_annual as sibling folders of daily/ if more granularity is ever wanted.
DAILY_ROOT = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/"

# Four station networks pulled by this project. DWD runs more than these
# (solar, water_equiv/snow, weather_phenomena, ...) but these four cover the
# headline climate variables (temperature, rain, wind, soil) with the largest
# station counts, which is what makes a Germany-wide "mega dashboard" possible.
# Add a fifth network here (folder name only - see dwd_engine.list_dir, which
# discovers filenames itself rather than needing them hardcoded) and
# fetch_dwd_climate.py picks it up with no other code changes.
NETWORKS = {
    "kl": {
        "folder": "kl",
        "label": "General climate: mean/min/max temperature, rain, sunshine, "
                  "wind, pressure, humidity (~1,200 stations, some back to the 1780s)",
    },
    "more_precip": {
        "folder": "more_precip",
        "label": "Precipitation-only network - denser than kl, rain-gauge "
                  "stations with no other sensors (~5,500 stations)",
    },
    "soil_temperature": {
        "folder": "soil_temperature",
        "label": "Soil temperature at 5/10/20/50/100 cm depth",
    },
    "water_equiv": {
        "folder": "water_equiv",
        "label": "Snow depth and water equivalent",
    },
}

MISSING = -999   # DWD's code for "not measured" in every produkt_*.txt file
PAUSE = 0.2      # seconds between HTTP requests - politeness, not enforced by DWD
TIMEOUT = 60
RETRIES = 3
