-- GeoCharge database schema.
-- Run once against a fresh `geocharge` database (with the postgis
-- extension already created) to build all tables and indexes.
-- Idempotent: safe to re-run; uses IF NOT EXISTS throughout.

-- Main serving table: one row per registered charging installation.
CREATE TABLE IF NOT EXISTS stations (
    id               BIGINT PRIMARY KEY,
    operator         TEXT,
    display_name     TEXT,
    status           TEXT,
    station_type     TEXT,
    num_chargepoints INTEGER,
    rated_power_kw   NUMERIC(6,2),
    commissioned     DATE,
    street           TEXT,
    house_number     TEXT,
    postal_code      TEXT,
    city             TEXT,
    district         TEXT,
    state            TEXT,
    location         GEOMETRY(POINT, 4326) NOT NULL,
    is_suspect       BOOLEAN NOT NULL DEFAULT FALSE,
    suspect_reason   TEXT
);

-- Quarantine table: same shape as stations, plus when it was quarantined.
CREATE TABLE IF NOT EXISTS stations_quarantine (
    LIKE stations INCLUDING ALL,
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Spatial index for fast nearest-neighbour and bounding-box queries.
CREATE INDEX IF NOT EXISTS stations_location_idx
    ON stations USING GIST (location);
