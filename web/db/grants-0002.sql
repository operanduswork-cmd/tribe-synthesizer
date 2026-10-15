-- Tribe dashboard: grants for migrations/0002_reel_videos.sql on the live database. Applied by
-- hand by the database owner right after that migration (a fresh install gets the same grants
-- from roles.sql). tribe_web only reads the reel video rows; the laptop runner writes them.

GRANT SELECT ON reel_videos TO tribe_web;
GRANT SELECT, INSERT, UPDATE, DELETE ON reel_videos TO tribe_runner;
