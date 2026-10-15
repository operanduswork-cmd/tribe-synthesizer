-- Tribe dashboard: grants for migrations/0001_brain_assets.sql on the live database. Applied by
-- hand by the database owner right after that migration (a fresh install gets the same grants
-- from roles.sql). tribe_web only reads the brain assets; the laptop runner writes them.

GRANT SELECT ON brain_assets TO tribe_web;
GRANT SELECT, INSERT, UPDATE, DELETE ON brain_assets TO tribe_runner;
