"""
GeoCharge API.

Exposes the stations database over HTTP.
Run locally with:  fastapi dev api.py
"""

import os

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from psycopg.rows import dict_row
from fastapi.staticfiles import StaticFiles
load_dotenv()

DB_CONN_STRING = (
    f"host={os.environ['DB_HOST']} "
    f"port={os.environ['DB_PORT']} "
    f"dbname={os.environ['DB_NAME']} "
    f"user={os.environ['DB_USER']} "
    f"password={os.environ['DB_PASSWORD']}"
)

app = FastAPI(title="GeoCharge API")


@app.get("/health")
def health():
    """Liveness check — is the API up and can it reach the database?"""
    with psycopg.connect(DB_CONN_STRING) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/stations/nearby")
def stations_nearby(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    limit: int = Query(default=10, ge=1, le=100),
):
    """Return the nearest charging stations to a point, as GeoJSON."""
    sql = """
        SELECT
            id, operator, display_name, status, station_type,
            num_chargepoints, rated_power_kw,
            street, house_number, postal_code, city, state,
            ST_X(location) AS lon,
            ST_Y(location) AS lat,
            ROUND(
                (ST_Distance(
                    location::geography,
                    ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography
                ))::numeric
            ) AS distance_m
        FROM stations
        ORDER BY location::geography <->
                 ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography
        LIMIT %(limit)s;
    """
    with psycopg.connect(DB_CONN_STRING) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, {"lat": lat, "lon": lon, "limit": limit})
            rows = cur.fetchall()

    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row.pop("lon"), row.pop("lat")],
            },
            "properties": row,
        }
        for row in rows
    ]
    return {"type": "FeatureCollection", "features": features}

app.mount("/", StaticFiles(directory="static", html=True), name="static")
