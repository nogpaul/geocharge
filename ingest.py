"""
GeoCharge ingestion script.

Reads the Bundesnetzagentur Ladesäulenregister CSV from data/,
cleans it, and upserts station rows into the `stations` table.

Run idempotently — re-running on the same (or updated) file
brings the database to the desired state without duplicates.
"""

import os
import sys
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

# --- Configuration -------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"

# Pick the most recently modified Ladesaeulenregister file in data/.
# This way we don't hardcode a filename that changes each release.
csv_candidates = sorted(
    DATA_DIR.glob("Ladesaeulenregister_BNetzA_*.csv"),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)
if not csv_candidates:
    sys.exit("No Ladesaeulenregister CSV found in data/.")
CSV_PATH = csv_candidates[0]
print(f"Reading {CSV_PATH.name}")

load_dotenv()  # reads .env into os.environ

DB_CONN_STRING = (
    f"host={os.environ['DB_HOST']} "
    f"port={os.environ['DB_PORT']} "
    f"dbname={os.environ['DB_NAME']} "
    f"user={os.environ['DB_USER']} "
    f"password={os.environ['DB_PASSWORD']}"
)

# --- Extract -------------------------------------------------------------

# The German CSV: Windows-1252 encoding, semicolon separator,
# comma as decimal mark, 9 metadata rows before the real header.
df = pd.read_csv(
    CSV_PATH,
    encoding="cp1252",
    sep=";",
    decimal=",",
    skiprows=10,
    dtype=str,            # read everything as text first, parse explicitly later
    keep_default_na=False, # treat empty cells as "" not NaN — we control nulls ourselves
)

print(f"Read {len(df):,} rows from CSV")

# --- Transform -----------------------------------------------------------

# Map the German column names to our schema's English ones.
COLUMN_MAP = {
    "Ladeeinrichtungs-ID":              "id",
    "Betreiber":                        "operator",
    "Anzeigename (Karte)":              "display_name",
    "Status":                           "status",
    "Art der Ladeeinrichtung":          "station_type",
    "Anzahl Ladepunkte":                "num_chargepoints",
    "Nennleistung Ladeeinrichtung [kW]": "rated_power_kw",
    "Inbetriebnahmedatum":              "commissioned",
    "Straße":                           "street",
    "Hausnummer":                       "house_number",
    "Postleitzahl":                     "postal_code",
    "Ort":                              "city",
    "Kreis/kreisfreie Stadt":           "district",
    "Bundesland":                       "state",
    "Breitengrad":                      "latitude",
    "Längengrad":                       "longitude",
}
df = df[list(COLUMN_MAP.keys())].rename(columns=COLUMN_MAP)

def parse_german_number(s: str) -> float | None:
    """Convert '48,442398' or '22,5' to a float; '' to None."""
    s = s.strip()
    if not s:
        return None
    return float(s.replace(",", "."))

def parse_german_date(s: str) -> str | None:
    """Convert '11.01.2020' (DD.MM.YYYY) to ISO '2020-01-11'; '' to None."""
    s = s.strip()
    if not s:
        return None
    day, month, year = s.split(".")
    return f"{year}-{month}-{day}"

def parse_int(s: str) -> int | None:
    s = s.strip()
    return int(s) if s else None

# Parse the typed columns once, so the rows we send to Postgres are clean.
df["id"]                = df["id"].map(parse_int)
df["num_chargepoints"]  = df["num_chargepoints"].map(parse_int)
df["rated_power_kw"]    = df["rated_power_kw"].map(parse_german_number)
df["commissioned"]      = df["commissioned"].map(parse_german_date)
df["latitude"]          = df["latitude"].map(parse_german_number)
df["longitude"]         = df["longitude"].map(parse_german_number)

# Drop rows missing what we absolutely need: a primary key and a location.
before = len(df)
df = df.dropna(subset=["id", "latitude", "longitude"])
dropped = before - len(df)
if dropped:
    print(f"Skipped {dropped} rows missing id or coordinates")

# --- Load ----------------------------------------------------------------

INSERT_SQL = """
INSERT INTO stations (
    id, operator, display_name, status, station_type,
    num_chargepoints, rated_power_kw, commissioned,
    street, house_number, postal_code, city, district, state,
    location
)
VALUES (
    %(id)s, %(operator)s, %(display_name)s, %(status)s, %(station_type)s,
    %(num_chargepoints)s, %(rated_power_kw)s, %(commissioned)s,
    %(street)s, %(house_number)s, %(postal_code)s, %(city)s, %(district)s, %(state)s,
    ST_SetSRID(ST_MakePoint(%(longitude)s, %(latitude)s), 4326)
)
ON CONFLICT (id) DO UPDATE SET
    operator         = EXCLUDED.operator,
    display_name     = EXCLUDED.display_name,
    status           = EXCLUDED.status,
    station_type     = EXCLUDED.station_type,
    num_chargepoints = EXCLUDED.num_chargepoints,
    rated_power_kw   = EXCLUDED.rated_power_kw,
    commissioned     = EXCLUDED.commissioned,
    street           = EXCLUDED.street,
    house_number     = EXCLUDED.house_number,
    postal_code      = EXCLUDED.postal_code,
    city             = EXCLUDED.city,
    district         = EXCLUDED.district,
    state            = EXCLUDED.state,
    location         = EXCLUDED.location;
"""

records = df.to_dict(orient="records")

with psycopg.connect(DB_CONN_STRING) as conn:
    with conn.cursor() as cur:
        cur.executemany(INSERT_SQL, records)
    conn.commit()

print(f"Upserted {len(records):,} stations into the database.")
