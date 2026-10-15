-- Tribe dashboard: the two database roles. Applied by hand by the database owner on a fresh
-- install, after migrations/0000_init.sql, 0001_brain_assets.sql and 0002_reel_videos.sql (a
-- database that already has the roles gets the brain_assets grants from grants-0001.sql and the
-- reel_videos grants from grants-0002.sql instead). Safe to run as-is: both roles start with
-- PASSWORD NULL, so neither can log in until a password is set with the ALTER ROLE lines at the
-- bottom.
-- Never commit a real password: set it in a psql session or the Neon console, and keep it
-- only in the Vercel env (web URL, marked Sensitive) and the laptop .env (runner URL).
--
-- tribe_web     the Next.js app on Vercel: reads pages, images, brain_assets, reel_videos, jobs,
--               job_events, settings and schema_meta (never writes brain_assets or reel_videos);
--               inserts jobs (a paid kind only unconfirmed); updates only
--               jobs.confirmed_at (once, to now(), on a queued job) and jobs.cancel_requested
--               (false to true, queued or running rows); flips the Pause switch only through
--               set_paused(boolean).
-- tribe_runner  the laptop runner (strategist/db.py): all DML on these tables.

CREATE ROLE tribe_web LOGIN PASSWORD NULL CONNECTION LIMIT 20;
CREATE ROLE tribe_runner LOGIN PASSWORD NULL CONNECTION LIMIT 5;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON pages, images, brain_assets, reel_videos, jobs, job_events, settings, schema_meta FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO tribe_web, tribe_runner;

-- ---------------------------------------------------------------- tribe_web
GRANT SELECT ON pages, images, brain_assets, reel_videos, jobs, job_events, settings, schema_meta TO tribe_web;
GRANT INSERT (kind, args, estimate_usd, idem_key, confirmed_at) ON jobs TO tribe_web;
GRANT UPDATE (confirmed_at, cancel_requested) ON jobs TO tribe_web;
GRANT EXECUTE ON FUNCTION set_paused(boolean) TO tribe_web;

-- ---------------------------------------------------------------- tribe_runner
GRANT SELECT, INSERT, UPDATE, DELETE ON pages, images, brain_assets, reel_videos, jobs, job_events, settings,
  schema_meta TO tribe_runner;
GRANT USAGE, SELECT ON SEQUENCE job_events_id_seq TO tribe_runner;

-- ---------------------------------------------------------------- row rules on jobs
-- The owner bypasses these; both app roles are bound by them.
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY jobs_runner_all ON jobs TO tribe_runner USING (true) WITH CHECK (true);
CREATE POLICY jobs_web_read ON jobs FOR SELECT TO tribe_web USING (true);
-- A paid kind (the list matches the paid kinds in web/contracts/job-kinds.json, checked by
-- strategist/test_contract.py) is always inserted unconfirmed: only a later confirm click can
-- be his go (D26). A free job is inserted confirmed, at the database's own time.
CREATE POLICY jobs_web_insert ON jobs FOR INSERT TO tribe_web
  WITH CHECK (status = 'queued' AND NOT cancel_requested AND started_at IS NULL AND result IS NULL
              AND (confirmed_at IS NULL
                   OR (kind NOT IN ('reel.add_link', 'reel.add_handle', 'tribe.lanes')
                       AND confirmed_at BETWEEN now() - interval '1 minute' AND now() + interval '1 minute')));
CREATE POLICY jobs_web_update ON jobs FOR UPDATE TO tribe_web
  USING (status IN ('queued', 'running'))
  WITH CHECK (status IN ('queued', 'running'));

-- What a row policy can't check, because it can't see the old row. For tribe_web only:
--   confirmed_at is set once, on a queued and uncancelled job, in a later transaction than the
--   insert, and always to the database's now() (a confirm can't be dated ahead to dodge the
--   30-minute expiry, moved, or taken back);
--   cancel_requested goes from false to true, never back.
CREATE FUNCTION jobs_web_guard() RETURNS trigger
  LANGUAGE plpgsql SET search_path = public, pg_temp
  AS $$
BEGIN
  IF current_user <> 'tribe_web' THEN
    RETURN NEW;
  END IF;
  IF OLD.cancel_requested AND NOT NEW.cancel_requested THEN
    RAISE EXCEPTION 'jobs_web_guard: a cancel stays' USING ERRCODE = '42501';
  END IF;
  IF NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at THEN
    IF OLD.confirmed_at IS NOT NULL OR NEW.confirmed_at IS NULL OR OLD.status <> 'queued'
       OR OLD.cancel_requested OR NEW.cancel_requested OR now() <= OLD.created_at THEN
      RAISE EXCEPTION 'jobs_web_guard: confirm refused' USING ERRCODE = '42501';
    END IF;
    NEW.confirmed_at := now();
  END IF;
  RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION jobs_web_guard() FROM PUBLIC;
CREATE TRIGGER jobs_web_guard BEFORE UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION jobs_web_guard();

-- ---------------------------------------------------------------- passwords (placeholders)
-- Run these by hand with real values; never save the real values in this file.
-- ALTER ROLE tribe_web PASSWORD '<TRIBE_WEB_PASSWORD>';
-- ALTER ROLE tribe_runner PASSWORD '<TRIBE_RUNNER_PASSWORD>';
