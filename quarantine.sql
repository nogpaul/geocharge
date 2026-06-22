-- Detect and quarantine stations with suspect coordinates.
-- Rule: identical coordinates appearing under more than one distinct city
-- indicate placeholder/default coordinates (a real data-quality problem in
-- the source registry), NOT legitimate co-located chargers (same coords +
-- same city are left untouched).
-- Run AFTER ingest.py, as the geocharge_app user. Idempotent and atomic.

BEGIN;

UPDATE stations
SET is_suspect = TRUE,
    suspect_reason = 'shared coordinates across multiple cities'
WHERE location IN (
    SELECT location
    FROM stations
    GROUP BY location
    HAVING COUNT(DISTINCT city) > 1
);

INSERT INTO stations_quarantine
SELECT *, now()
FROM stations
WHERE is_suspect;

DELETE FROM stations
WHERE is_suspect;

COMMIT;
