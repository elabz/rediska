"""Offline geocoding service with haversine distance calculation.

Multi-tier lookup: timezone → alias → US state → country → GeoNames cities.
No external API calls; fully offline.
"""

import csv
import math
import re
from pathlib import Path
from typing import Optional

from rediska_core.config import get_settings

# ---------------------------------------------------------------------------
# Tier 1: Timezone abbreviations → representative coordinates
# ---------------------------------------------------------------------------
TIMEZONE_COORDS: dict[str, tuple[float, float]] = {
    "est": (40.0, -75.2),
    "eastern": (40.0, -75.2),
    "east coast": (40.0, -75.2),
    "cst": (41.9, -87.6),
    "central": (41.9, -87.6),
    "mst": (39.7, -105.0),
    "mountain": (39.7, -105.0),
    "pst": (34.0, -118.2),
    "pacific": (34.0, -118.2),
    "west coast": (34.0, -118.2),
    "utc": (51.5, -0.1),
    "gmt": (51.5, -0.1),
    "akst": (61.2, -149.9),
    "hst": (21.3, -157.8),
}

# ---------------------------------------------------------------------------
# Tier 2: Regional slang / aliases
# ---------------------------------------------------------------------------
ALIAS_COORDS: dict[str, tuple[float, float]] = {
    "sepa": (40.0, -75.3),
    "nepa": (41.4, -75.7),
    "dmv": (38.9, -77.0),
    "nova": (38.9, -77.2),
    "northern virginia": (38.9, -77.2),
    "nnj": (40.9, -74.2),
    "cnj": (40.4, -74.5),
    "snj": (39.8, -75.0),
    "li": (40.8, -73.3),
    "long island": (40.8, -73.3),
    "philly": (39.95, -75.17),
    "nyc": (40.71, -74.01),
    "new york city": (40.71, -74.01),
    "sf": (37.77, -122.42),
    "san francisco": (37.77, -122.42),
    "la": (34.05, -118.24),
    "los angeles": (34.05, -118.24),
    "socal": (34.0, -118.2),
    "norcal": (37.8, -122.4),
    "dfw": (32.9, -97.0),
    "bay area": (37.6, -122.1),
    "tristate": (40.7, -74.2),
    "tri-state": (40.7, -74.2),
}

# ---------------------------------------------------------------------------
# Tier 3: US states (abbreviation + full name) → centroid
# ---------------------------------------------------------------------------
US_STATE_COORDS: dict[str, tuple[float, float]] = {
    "al": (32.8, -86.8), "alabama": (32.8, -86.8),
    "ak": (64.2, -152.5), "alaska": (64.2, -152.5),
    "az": (34.3, -111.7), "arizona": (34.3, -111.7),
    "ar": (34.8, -92.2), "arkansas": (34.8, -92.2),
    "ca": (36.8, -119.4), "california": (36.8, -119.4),
    "co": (39.0, -105.5), "colorado": (39.0, -105.5),
    "ct": (41.6, -72.7), "connecticut": (41.6, -72.7),
    "de": (39.0, -75.5), "delaware": (39.0, -75.5),
    "fl": (28.6, -82.5), "florida": (28.6, -82.5),
    "ga": (32.7, -83.4), "georgia": (32.7, -83.4),
    "hi": (20.8, -156.3), "hawaii": (20.8, -156.3),
    "id": (44.4, -114.6), "idaho": (44.4, -114.6),
    "il": (40.0, -89.2), "illinois": (40.0, -89.2),
    "in": (39.8, -86.2), "indiana": (39.8, -86.2),
    "ia": (42.0, -93.5), "iowa": (42.0, -93.5),
    "ks": (38.5, -98.3), "kansas": (38.5, -98.3),
    "ky": (37.8, -85.3), "kentucky": (37.8, -85.3),
    "la": (31.0, -91.8), "louisiana": (31.0, -91.8),
    "me": (45.3, -69.0), "maine": (45.3, -69.0),
    "md": (39.0, -76.7), "maryland": (39.0, -76.7),
    "ma": (42.2, -71.5), "massachusetts": (42.2, -71.5),
    "mi": (44.3, -84.5), "michigan": (44.3, -84.5),
    "mn": (46.3, -94.3), "minnesota": (46.3, -94.3),
    "ms": (32.7, -89.7), "mississippi": (32.7, -89.7),
    "mo": (38.5, -92.5), "missouri": (38.5, -92.5),
    "mt": (47.0, -109.6), "montana": (47.0, -109.6),
    "ne": (41.5, -99.8), "nebraska": (41.5, -99.8),
    "nv": (39.9, -116.8), "nevada": (39.9, -116.8),
    "nh": (43.7, -71.6), "new hampshire": (43.7, -71.6),
    "nj": (40.2, -74.7), "new jersey": (40.2, -74.7),
    "nm": (34.4, -106.1), "new mexico": (34.4, -106.1),
    "ny": (42.9, -75.5), "new york": (42.9, -75.5),
    "nc": (35.6, -79.4), "north carolina": (35.6, -79.4),
    "nd": (47.4, -100.5), "north dakota": (47.4, -100.5),
    "oh": (40.4, -82.8), "ohio": (40.4, -82.8),
    "ok": (35.6, -97.5), "oklahoma": (35.6, -97.5),
    "or": (44.0, -120.5), "oregon": (44.0, -120.5),
    "pa": (40.9, -77.8), "pennsylvania": (40.9, -77.8),
    "ri": (41.7, -71.5), "rhode island": (41.7, -71.5),
    "sc": (33.9, -80.9), "south carolina": (33.9, -80.9),
    "sd": (44.4, -100.2), "south dakota": (44.4, -100.2),
    "tn": (35.9, -86.4), "tennessee": (35.9, -86.4),
    "tx": (31.5, -99.4), "texas": (31.5, -99.4),
    "ut": (39.3, -111.7), "utah": (39.3, -111.7),
    "vt": (44.1, -72.6), "vermont": (44.1, -72.6),
    "va": (37.5, -78.9), "virginia": (37.5, -78.9),
    "wa": (47.4, -120.5), "washington state": (47.4, -120.5),
    "wv": (38.6, -80.6), "west virginia": (38.6, -80.6),
    "wi": (44.6, -89.8), "wisconsin": (44.6, -89.8),
    "wy": (43.0, -107.6), "wyoming": (43.0, -107.6),
    "dc": (38.9, -77.0), "washington dc": (38.9, -77.0),
    "washington d.c.": (38.9, -77.0),
}

# ---------------------------------------------------------------------------
# Tier 4: Countries (name + common codes) → capital coordinates
# ---------------------------------------------------------------------------
COUNTRY_COORDS: dict[str, tuple[float, float]] = {
    "canada": (45.4, -75.7), "ca_country": (45.4, -75.7),
    "uk": (51.5, -0.1), "united kingdom": (51.5, -0.1), "england": (51.5, -0.1),
    "gb": (51.5, -0.1), "britain": (51.5, -0.1),
    "ireland": (53.3, -6.3), "ie": (53.3, -6.3),
    "france": (48.9, 2.3), "fr": (48.9, 2.3),
    "germany": (52.5, 13.4), "de_country": (52.5, 13.4),
    "spain": (40.4, -3.7), "es": (40.4, -3.7),
    "italy": (41.9, 12.5), "it": (41.9, 12.5),
    "netherlands": (52.4, 4.9), "nl": (52.4, 4.9),
    "belgium": (50.8, 4.4), "be": (50.8, 4.4),
    "portugal": (38.7, -9.1), "pt": (38.7, -9.1),
    "sweden": (59.3, 18.1), "se": (59.3, 18.1),
    "norway": (59.9, 10.7), "no": (59.9, 10.7),
    "denmark": (55.7, 12.6), "dk": (55.7, 12.6),
    "finland": (60.2, 24.9), "fi": (60.2, 24.9),
    "poland": (52.2, 21.0), "pl": (52.2, 21.0),
    "austria": (48.2, 16.4), "at": (48.2, 16.4),
    "switzerland": (46.9, 7.4), "ch": (46.9, 7.4),
    "australia": (-33.9, 151.2), "au": (-33.9, 151.2),
    "new zealand": (-41.3, 174.8), "nz": (-41.3, 174.8),
    "japan": (35.7, 139.7), "jp": (35.7, 139.7),
    "south korea": (37.6, 127.0), "kr": (37.6, 127.0), "korea": (37.6, 127.0),
    "china": (39.9, 116.4), "cn": (39.9, 116.4),
    "india": (28.6, 77.2), "in_country": (28.6, 77.2),
    "brazil": (-15.8, -47.9), "br": (-15.8, -47.9),
    "mexico": (19.4, -99.1), "mx": (19.4, -99.1),
    "argentina": (-34.6, -58.4), "ar_country": (-34.6, -58.4),
    "colombia": (4.7, -74.1), "co_country": (4.7, -74.1),
    "russia": (55.8, 37.6), "ru": (55.8, 37.6),
    "south africa": (-33.9, 18.4), "za": (-33.9, 18.4),
    "egypt": (30.0, 31.2), "eg": (30.0, 31.2),
    "nigeria": (9.1, 7.5), "ng": (9.1, 7.5),
    "philippines": (14.6, 121.0), "ph": (14.6, 121.0),
    "thailand": (13.8, 100.5), "th": (13.8, 100.5),
    "vietnam": (21.0, 105.8), "vn": (21.0, 105.8),
    "indonesia": (-6.2, 106.8), "id_country": (-6.2, 106.8),
    "turkey": (39.9, 32.9), "tr": (39.9, 32.9),
    "israel": (31.8, 35.2), "il": (31.8, 35.2),
    "saudi arabia": (24.7, 46.7), "sa": (24.7, 46.7),
    "uae": (24.5, 54.4), "united arab emirates": (24.5, 54.4),
    "singapore": (1.3, 103.8), "sg": (1.3, 103.8),
    "europe": (50.1, 14.4),
    "asia": (35.0, 105.0),
    "africa": (0.0, 25.0),
    "south america": (-15.0, -60.0),
}

# Earth radius in miles
_EARTH_RADIUS_MI = 3958.8

# GeoNames cities index (lazy-loaded)
_cities_index: Optional[dict[str, tuple[float, float]]] = None
_CITIES_FILE = Path("/app/data/cities500.txt")


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in miles between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return _EARTH_RADIUS_MI * 2 * math.asin(math.sqrt(a))


def _load_cities() -> dict[str, tuple[float, float]]:
    """Load GeoNames cities500.txt into a dict keyed by lowercase name.

    File format is tab-separated. Columns used:
      1  name
      4  latitude
      5  longitude
      8  country code
      14 population
    We keep the largest-population entry per lowercase name.
    """
    global _cities_index
    if _cities_index is not None:
        return _cities_index

    index: dict[str, tuple[float, float, int]] = {}  # name → (lat, lon, pop)

    if not _CITIES_FILE.exists():
        _cities_index = {}
        return _cities_index

    with open(_CITIES_FILE, encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        for row in reader:
            if len(row) < 15:
                continue
            name = row[1].strip().lower()
            try:
                lat = float(row[4])
                lon = float(row[5])
                pop = int(row[14]) if row[14] else 0
            except (ValueError, IndexError):
                continue
            if name not in index or pop > index[name][2]:
                index[name] = (lat, lon, pop)

    _cities_index = {k: (v[0], v[1]) for k, v in index.items()}
    return _cities_index


def _normalize(s: str) -> str:
    """Lowercase, strip, collapse whitespace, remove leading # and trailing punctuation."""
    s = s.strip().lower()
    s = s.lstrip("#")
    s = re.sub(r"[.,!?;:]+$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _geocode(location_str: str) -> Optional[tuple[float, float, str]]:
    """Resolve location string to (lat, lon, tier) or None."""
    key = _normalize(location_str)
    if not key:
        return None

    # Tier 1: Timezones
    if key in TIMEZONE_COORDS:
        return (*TIMEZONE_COORDS[key], "timezone")

    # Tier 2: Aliases
    if key in ALIAS_COORDS:
        return (*ALIAS_COORDS[key], "alias")

    # Tier 3: US states
    if key in US_STATE_COORDS:
        return (*US_STATE_COORDS[key], "us_state")

    # Tier 4: Countries
    if key in COUNTRY_COORDS:
        return (*COUNTRY_COORDS[key], "country")

    # Tier 5: GeoNames cities
    cities = _load_cities()
    if key in cities:
        return (*cities[key], "city")

    return None


# Locations that always count as "near" regardless of distance.
# "online" = open to remote; "us"/"usa"/"united states" = too broad to penalize.
_ALWAYS_NEAR = {"online", "remote", "anywhere", "us", "usa", "united states"}


def classify_location(location_str: Optional[str]) -> dict:
    """Classify a location string as near/far based on haversine distance.

    Returns:
        dict with keys:
          - location_near (bool)
          - distance_miles (int or None)
          - geocoded (bool) – whether we resolved the string
    """
    if not location_str:
        return {"location_near": False, "distance_miles": None, "geocoded": False}

    key = _normalize(location_str)

    # Special cases: always near
    if key in _ALWAYS_NEAR:
        return {"location_near": True, "distance_miles": 0, "geocoded": True}

    settings = get_settings()
    home_lat = settings.home_latitude
    home_lon = settings.home_longitude
    threshold = settings.location_near_threshold_miles

    result = _geocode(location_str)
    if result is None:
        return {"location_near": False, "distance_miles": None, "geocoded": False}

    lat, lon, _tier = result
    dist = _haversine(home_lat, home_lon, lat, lon)
    return {
        "location_near": dist <= threshold,
        "distance_miles": round(dist),
        "geocoded": True,
    }
