-- Tribe dashboard: schema version 3 (D30, the reel videos). Hand-checked; applied once by the
-- database owner after 0000_init.sql and 0001_brain_assets.sql, then web/db/grants-0002.sql. The
-- runner (strategist/db.py EXPECTED_SCHEMA = 3) refuses to run until both are in. Deploy order:
-- this file, the grants, the runner, the web.
--
-- reel_videos records where each swipe reel's video sits in the Vercel Blob store (private
-- access, played only through the login-locked site). The video itself never goes in the
-- database. One row per reel: its shortcode, the blob pathname (the shortcode and the first 8
-- hex characters of the file's sha256), the sha256, the size and the length in seconds.
-- strategist/media.py push writes the rows (as tribe_runner); the site only reads them.
-- No counts and no brain values in this table.

CREATE TABLE reel_videos (
  shortcode text PRIMARY KEY CHECK (shortcode ~ '^[A-Za-z0-9_-]{5,20}$'),
  pathname text NOT NULL CHECK (pathname ~ '^reels/[A-Za-z0-9_-]{5,20}-[0-9a-f]{8}\.mp4$'),
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  bytes integer NOT NULL CHECK (bytes BETWEEN 1 AND 60000000),
  duration_s real NOT NULL CHECK (duration_s BETWEEN 1 AND 600),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT reel_videos_pathname_matches
    CHECK (pathname = 'reels/' || shortcode || '-' || left(sha256, 8) || '.mp4')
);
--> statement-breakpoint
REVOKE ALL ON reel_videos FROM PUBLIC;
--> statement-breakpoint
UPDATE schema_meta SET version = 3 WHERE id = 1;
