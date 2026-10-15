-- Tribe dashboard: schema version 2 (D28, the brain view). Hand-checked; applied once by the
-- database owner after 0000_init.sql, then web/db/grants-0001.sql. The runner (strategist/db.py
-- EXPECTED_SCHEMA = 2) refuses to run until both are in. Deploy order: this file, the grants, the
-- runner, the web.
--
-- pages gains the brain kind (one brain page per linked TRIBE job, keyed by job id), and
-- brain_assets holds the binary files behind the brain view, gzip at rest: per-second frames per
-- job and the shared mesh and atlas lookups. Their layouts, key format and size caps are in
-- web/contracts/brain-assets.json; strategist/test_contract.py checks this file against it.
-- Nothing in a row spans two jobs (D21): a frames key names exactly one job. No text inside.

ALTER TABLE pages DROP CONSTRAINT pages_kind_check;
--> statement-breakpoint
ALTER TABLE pages ADD CONSTRAINT pages_kind_check
  CHECK (kind IN ('board', 'reel', 'patterns', 'lab', 'tribe', 'meta', 'spend', 'brain'));
--> statement-breakpoint

CREATE TABLE brain_assets (
  key text PRIMARY KEY CHECK (key ~ '^(tribe/[0-9]{8}-[0-9]{6}-[0-9a-f]{8}/frames\.i8|shared/(fsaverage5-inflated|atlas)-v[0-9]{1,3}\.bin)$'),
  kind text NOT NULL CHECK (kind IN ('frames', 'mesh', 'atlas')),
  mime text NOT NULL CHECK (mime = 'application/octet-stream'),
  encoding text NOT NULL DEFAULT 'gzip' CHECK (encoding = 'gzip'),
  bytes bytea NOT NULL CHECK (octet_length(bytes) BETWEEN 18 AND 2097152),
  raw_bytes integer NOT NULL CHECK (raw_bytes BETWEEN 16 AND 4194304),
  hash text NOT NULL CHECK (hash ~ '^[0-9a-f]{64}$'),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT brain_assets_kind_matches CHECK (
       (kind = 'frames' AND key ~ '/frames\.i8$')
    OR (kind = 'mesh' AND key ~ '^shared/fsaverage5-inflated-')
    OR (kind = 'atlas' AND key ~ '^shared/atlas-'))
);
--> statement-breakpoint
REVOKE ALL ON brain_assets FROM PUBLIC;
--> statement-breakpoint
UPDATE schema_meta SET version = 2 WHERE id = 1;
