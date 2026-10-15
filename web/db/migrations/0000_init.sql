-- Tribe dashboard: first schema (version 1). Hand-checked; applied once by the database owner.
-- Text columns with CHECK, never Postgres enums. The lists below must match
-- strategist/hosted_schema/*.schema.json (page kinds), web/contracts/job-kinds.json (job kinds)
-- and strategist/db.py (statuses); strategist/test_contract.py checks that they do.
-- Roles and grants are in web/db/roles.sql (applied by hand, passwords never committed).

CREATE TABLE schema_meta (
  id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  version integer NOT NULL CHECK (version > 0)
);
--> statement-breakpoint
INSERT INTO schema_meta (id, version) VALUES (1, 1);
--> statement-breakpoint

-- One row per hosted page: the cleaned projection only (strategist/hosted.py), pushed by the runner.
CREATE TABLE pages (
  kind text NOT NULL CHECK (kind IN ('board', 'reel', 'patterns', 'lab', 'tribe', 'meta', 'spend')),
  key text NOT NULL CHECK (key ~ '^[A-Za-z0-9_.-]{1,80}$'),
  v integer NOT NULL CHECK (v > 0),
  json jsonb NOT NULL CHECK (jsonb_typeof(json) = 'object'),
  hash text NOT NULL CHECK (hash ~ '^[0-9a-f]{64}$'),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, key)
);
--> statement-breakpoint

-- The TRIBE peak picture only: a PNG under 1 MB.
CREATE TABLE images (
  key text PRIMARY KEY CHECK (key ~ '^[A-Za-z0-9_./-]{1,120}$'),
  mime text NOT NULL CHECK (mime = 'image/png'),
  bytes bytea NOT NULL CHECK (octet_length(bytes) BETWEEN 8 AND 1048576),
  hash text NOT NULL CHECK (hash ~ '^[0-9a-f]{64}$'),
  updated_at timestamptz NOT NULL DEFAULT now()
);
--> statement-breakpoint

-- The queue. The site inserts (and confirms or cancels); the laptop runner does the rest.
CREATE TABLE jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind text NOT NULL CHECK (kind IN (
    'reel.accept', 'reel.reject', 'reel.discount', 'patterns.build', 'lab.check', 'sync.push',
    'coach.new_draft', 'coach.this_but', 'coach.replace', 'coach.tag_shapes',
    'reel.add_link', 'reel.add_handle', 'tribe.lanes')),
  args jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(args) = 'object' AND octet_length(args::text) <= 4096),
  estimate_usd numeric(8, 4) NOT NULL DEFAULT 0 CHECK (estimate_usd >= 0 AND estimate_usd <= 10),
  idem_key text CHECK (idem_key IS NULL OR idem_key ~ '^[A-Za-z0-9_.:-]{8,120}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  confirmed_at timestamptz,
  cancel_requested boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'running', 'done', 'failed', 'interrupted', 'refused', 'cancelled')),
  lease_until timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  result jsonb CHECK (result IS NULL OR octet_length(result::text) <= 65536),
  error_code text CHECK (error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_]{1,40}$'),
  refusal text CHECK (refusal IS NULL OR char_length(refusal) <= 300),
  CONSTRAINT jobs_running_check CHECK (status <> 'running' OR (started_at IS NOT NULL AND lease_until IS NOT NULL)),
  CONSTRAINT jobs_finished_check CHECK (status IN ('queued', 'running') OR finished_at IS NOT NULL)
);
--> statement-breakpoint

-- A double click (same idem_key) can't queue the same job twice while one is live.
CREATE UNIQUE INDEX jobs_idem_live ON jobs (idem_key)
  WHERE idem_key IS NOT NULL AND status IN ('queued', 'running');
--> statement-breakpoint

-- One paid job at a time (D26): at most one running row of a paid kind.
CREATE UNIQUE INDEX jobs_one_running_paid ON jobs ((true))
  WHERE status = 'running' AND kind IN ('reel.add_link', 'reel.add_handle', 'tribe.lanes');
--> statement-breakpoint

CREATE INDEX jobs_queued ON jobs (created_at, id) WHERE status = 'queued';
--> statement-breakpoint
CREATE INDEX jobs_created ON jobs (created_at DESC);
--> statement-breakpoint

-- Fixed progress lines only (strategist/db.py EVENT_LINES). Raw logs stay on the laptop.
CREATE TABLE job_events (
  id bigserial PRIMARY KEY,
  job_id uuid NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
  at timestamptz NOT NULL DEFAULT now(),
  line text NOT NULL CHECK (char_length(line) BETWEEN 1 AND 300)
);
--> statement-breakpoint
CREATE INDEX job_events_job ON job_events (job_id, id);
--> statement-breakpoint

CREATE TABLE settings (
  key text PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]{1,40}$'),
  value jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
--> statement-breakpoint
INSERT INTO settings (key, value) VALUES ('paused', 'false'::jsonb);
--> statement-breakpoint

-- The site's Pause switch: the only way tribe_web changes settings (see roles.sql).
CREATE FUNCTION set_paused(p boolean) RETURNS void
  LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp
  AS $$ UPDATE public.settings SET value = to_jsonb(p), updated_at = now() WHERE key = 'paused' $$;
--> statement-breakpoint
REVOKE ALL ON FUNCTION set_paused(boolean) FROM PUBLIC;
