"""The dashboard database (Neon Postgres), as the laptop runner sees it (D25, D26).

The runner connects as the tribe_runner role with TRIBE_RUNNER_DATABASE_URL. The value is
read from os.environ only; load_env() copies it there from the Tribe .env first (as
strategist/reel.py env_value reads keys) and never prints it. The site (web/) has its own
role and URL; see web/db/roles.sql.

The tables are in web/db/migrations/0000_init.sql, 0001_brain_assets.sql and
0002_reel_videos.sql. connect() refuses to run when schema_meta.version is not
EXPECTED_SCHEMA, so a runner never writes to a schema it doesn't know (deploy order: migrate,
grants-0001.sql and grants-0002.sql, then the runner).

Every helper below takes an open connection and runs one statement, so with the
autocommit connection from connect() each one is atomic on its own. Group several (a
sync push) in `with conn.transaction():`. The helpers need only conn.execute(sql, params)
returning a cursor with fetchone / fetchall / rowcount, so the tests use a fake
connection; psycopg is imported only inside connect().

What goes in: pages are the cleaned hosted projection only (strategist/hosted.py, checked
against strategist/hosted_schema/ before upsert), images are PNGs under 1 MB, brain assets
are gzip binaries in the layouts of web/contracts/brain-assets.json (keys, kinds, mime and
size caps read from that file), reel video rows say where each reel's video sits in the
private Blob store (strategist/media.py push writes them; the video never goes in the
database), and job events are fixed lines from EVENT_LINES (raw logs stay on the laptop).
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import re
import urllib.parse
from pathlib import Path

from . import store

EXPECTED_SCHEMA = 3
DSN_ENV = "TRIBE_RUNNER_DATABASE_URL"
ENV_FILE = store.PROJECT_ROOT / ".env"     # read for DSN_ENV only, never printed
JOB_KINDS_PATH = store.PROJECT_ROOT / "web" / "contracts" / "job-kinds.json"
BRAIN_ASSETS_PATH = store.PROJECT_ROOT / "web" / "contracts" / "brain-assets.json"

PAGE_KINDS = ("board", "reel", "patterns", "lab", "tribe", "meta", "spend", "brain")
STATUSES = ("queued", "running", "done", "failed", "interrupted", "refused", "cancelled")
LIVE = ("queued", "running")
FINAL = ("done", "failed", "interrupted", "refused", "cancelled")
LEASE_S = 90            # a running job's lease; the runner renews it every 30 s
LINE_MAX = 300          # job_events.line and jobs.refusal
RESULT_MAX = 65536      # bytes of jobs.result JSON
IMAGE_MAX = 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PAGE_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
IMAGE_KEY_RE = re.compile(r"^[A-Za-z0-9_./-]{1,120}$")
SETTING_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
WORD_RE = re.compile(r"^[a-z0-9_]{1,40}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
# reel_videos (0002_reel_videos.sql): the same CHECKs, so a bad row is refused before it is sent.
REEL_VIDEO_SC_RE = re.compile(r"^[A-Za-z0-9_-]{5,20}$")
REEL_VIDEO_PATH_RE = re.compile(r"^reels/[A-Za-z0-9_-]{5,20}-[0-9a-f]{8}\.mp4$")
REEL_VIDEO_MAX_BYTES = 60_000_000
REEL_VIDEO_SECONDS = (1.0, 600.0)
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
UNIQUE_VIOLATION = "23505"

# The only lines a job's progress shows on the site. Fields take whole numbers, money
# (usd) or one lower-case word (code); nothing scraped and no free text goes in.
EVENT_LINES = {
    "started": "Started.",
    "step": "Step {n} of {total}.",
    "estimate": "Estimate about ${usd:.3f}.",
    "refused": "Refused: {code}.",
    "apify_started": "Apify run started.",
    "apify_done": "Apify run finished: {n} items.",
    "transcribing": "Transcribing on the laptop.",
    "stills": "Taking stills on the laptop.",
    "coach_started": "Coach started.",
    "coach_done": "Coach finished.",
    "checking": "Checking the draft.",
    "patterns": "Rebuilding the patterns.",
    "gpu_wait": "Waiting for a GPU on Modal.",
    "gpu_run": "TRIBE deep read running on Modal.",
    "lanes": "Building the lanes.",
    "clip_deleted": "Clip copies deleted from Modal.",
    "syncing": "Pushing pages to the dashboard.",
    "synced": "Pushed {n} pages, removed {gone}.",
    "cancel_seen": "Cancel seen: stopping.",
    "cancelled": "Cancelled.",
    "interrupted": "Interrupted: the runner stopped before the job finished.",
    "failed": "Failed: {code}.",
    "done": "Done.",
}


class DbError(Exception):
    """A database step was refused. The message says why and never holds the URL."""


# ---------------------------------------------------------------- the URL

def load_env(names=(DSN_ENV,), path: Path | None = None) -> list[str]:
    """Copy the named keys from the Tribe .env into os.environ, unless already set there.
    Returns the names it set. Never prints or logs a value."""
    path = Path(path) if path else ENV_FILE
    done = []
    if not path.is_file():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key in names and not os.environ.get(key, "").strip():
            value = value.strip().strip('"').strip("'")
            if value:
                os.environ[key] = value
                done.append(key)
    return done


def dsn_value() -> str:
    url = os.environ.get(DSN_ENV, "").strip()
    if not url:
        raise DbError(f"{DSN_ENV} is not set: put the runner's database URL in the Tribe .env "
                      "(it is read, never printed)")
    return url


def scrub(text: str, url: str) -> str:
    """The text with the URL and its password replaced by ***."""
    out = str(text)
    try:
        pw = urllib.parse.urlsplit(url).password
    except ValueError:
        pw = None
    for secret in (url, pw, urllib.parse.quote(pw or "", safe="") if pw else None):
        if secret:
            out = out.replace(secret, "***")
    return out


def connect(dsn: str | None = None, check: bool = True):
    """An autocommit psycopg 3 connection as tribe_runner, schema version checked."""
    try:
        import psycopg
    except ImportError:
        raise DbError('psycopg is not installed: pip install "psycopg[binary]"') from None
    url = dsn or dsn_value()
    try:
        conn = psycopg.connect(url, autocommit=True, connect_timeout=10, application_name="tribe-runner")
    except psycopg.Error as e:
        raise DbError(f"could not reach the dashboard database ({type(e).__name__}: {scrub(e, url)})") from None
    if check:
        try:
            check_schema(conn)
        except BaseException:
            conn.close()
            raise
    return conn


def check_schema(conn) -> int:
    row = conn.execute("SELECT version FROM schema_meta WHERE id = 1").fetchone()
    got = row[0] if row else None
    if got != EXPECTED_SCHEMA:
        raise DbError(f"the database schema is version {got}, and this runner expects {EXPECTED_SCHEMA}: "
                      "apply web/db/migrations, or update the runner, before running jobs")
    return got


# ---------------------------------------------------------------- pages and images

def canonical_json(obj) -> str:
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except ValueError as e:
        raise DbError(f"not valid JSON for the database: {e}") from None


def page_hash(page: dict) -> str:
    """sha256 of the page's canonical JSON: the same page always gives the same hash."""
    return hashlib.sha256(canonical_json(page).encode("utf-8")).hexdigest()


def check_page_key(kind: str, key: str) -> None:
    if kind not in PAGE_KINDS:
        raise DbError(f"not a page kind: {kind!r} (one of {', '.join(PAGE_KINDS)})")
    if not isinstance(key, str) or not PAGE_KEY_RE.match(key):
        raise DbError(f"not a page key: {key!r}")


UPSERT_PAGE = (
    "INSERT INTO pages (kind, key, v, json, hash, updated_at) VALUES (%s, %s, %s, %s::jsonb, %s, now()) "
    "ON CONFLICT (kind, key) DO UPDATE SET v = EXCLUDED.v, json = EXCLUDED.json, hash = EXCLUDED.hash, "
    "updated_at = now() WHERE pages.hash IS DISTINCT FROM EXCLUDED.hash")


def upsert_page(conn, kind: str, key: str, v: int, page: dict, hash: str | None = None) -> bool:
    """Insert or replace one page. True when the row changed (a same-hash page is left alone)."""
    check_page_key(kind, key)
    if not isinstance(page, dict):
        raise DbError(f"{kind}/{key}: a page is a JSON object")
    if not isinstance(v, int) or isinstance(v, bool) or v < 1 or page.get("v") != v:
        raise DbError(f"{kind}/{key}: v must be a positive whole number and match the page's own v")
    body = canonical_json(page)
    digest = hash or hashlib.sha256(body.encode("utf-8")).hexdigest()
    if not HASH_RE.match(digest):
        raise DbError(f"{kind}/{key}: hash must be 64 lower-case hex characters")
    return conn.execute(UPSERT_PAGE, (kind, key, v, body, digest)).rowcount == 1


def delete_missing(conn, kind: str, keys, allow_empty: bool = False) -> list[str]:
    """Delete the pages of this kind whose key is not in keys (their source is gone).
    An empty keys list deletes every page of the kind, so it needs allow_empty=True."""
    keys = sorted(set(keys))
    check_page_key(kind, "index")
    for k in keys:
        check_page_key(kind, k)
    if not keys and not allow_empty:
        raise DbError(f"refusing to delete every {kind} page: no keys given (allow_empty=True if meant)")
    rows = conn.execute("DELETE FROM pages WHERE kind = %s AND NOT (key = ANY(%s)) RETURNING key",
                        (kind, keys)).fetchall()
    return sorted(r[0] for r in rows)


UPSERT_IMAGE = (
    "INSERT INTO images (key, mime, bytes, hash, updated_at) VALUES (%s, 'image/png', %s, %s, now()) "
    "ON CONFLICT (key) DO UPDATE SET bytes = EXCLUDED.bytes, hash = EXCLUDED.hash, updated_at = now() "
    "WHERE images.hash IS DISTINCT FROM EXCLUDED.hash")


def check_png(data: bytes, key: str = "image") -> bytes:
    if not isinstance(data, (bytes, bytearray)) or not bytes(data[:8]) == PNG_MAGIC:
        raise DbError(f"{key}: not a PNG")
    if len(data) > IMAGE_MAX:
        raise DbError(f"{key}: {len(data)} bytes, over the {IMAGE_MAX} byte limit")
    return bytes(data)


def upsert_image(conn, key: str, data: bytes) -> bool:
    if not isinstance(key, str) or not IMAGE_KEY_RE.match(key):
        raise DbError(f"not an image key: {key!r}")
    data = check_png(data, key)
    return conn.execute(UPSERT_IMAGE, (key, data, hashlib.sha256(data).hexdigest())).rowcount == 1


def delete_missing_images(conn, keys) -> list[str]:
    keys = sorted(set(keys))
    for k in keys:
        if not IMAGE_KEY_RE.match(k):
            raise DbError(f"not an image key: {k!r}")
    rows = conn.execute("DELETE FROM images WHERE NOT (key = ANY(%s)) RETURNING key", (keys,)).fetchall()
    return sorted(r[0] for r in rows)


def list_pages(conn, kind: str | None = None) -> list[dict]:
    """Every stored page (or one kind's) as {kind, key, v, page, hash}, for the sync audit."""
    if kind is None:
        rows = conn.execute("SELECT kind, key, v, json, hash FROM pages ORDER BY kind, key").fetchall()
    else:
        check_page_key(kind, "index")
        rows = conn.execute("SELECT kind, key, v, json, hash FROM pages WHERE kind = %s ORDER BY key",
                            (kind,)).fetchall()
    out = []
    for k, key, v, body, digest in rows:
        try:
            page = json.loads(body) if isinstance(body, (str, bytes)) else body
        except ValueError:
            page = None
        out.append({"kind": k, "key": key, "v": v, "page": page, "hash": digest})
    return out


def list_images(conn) -> list[dict]:
    """Every stored image as {key, mime, bytes, hash}, for the sync audit."""
    rows = conn.execute("SELECT key, mime, bytes, hash FROM images ORDER BY key").fetchall()
    return [{"key": key, "mime": mime, "bytes": bytes(data) if data is not None else b"", "hash": digest}
            for key, mime, data, digest in rows]


# ---------------------------------------------------------------- brain assets (D28)

@functools.lru_cache(maxsize=1)
def brain_contract() -> dict:
    """web/contracts/brain-assets.json: key format, kinds, mime, gzip magic and size caps."""
    return json.loads(BRAIN_ASSETS_PATH.read_text(encoding="utf-8"))


def check_brain_key(key, kind: str | None = None) -> str:
    """The key, or DbError unless it is a brain asset key (of this kind, when given)."""
    c = brain_contract()
    if not isinstance(key, str) or not re.fullmatch(c["key_pattern"], key):
        raise DbError(f"not a brain asset key: {key!r}")
    if kind is not None:
        if kind not in c["kinds"]:
            raise DbError(f"not a brain asset kind: {kind!r} (one of {', '.join(c['kinds'])})")
        if not re.fullmatch(c["kinds"][kind]["key_pattern"], key):
            raise DbError(f"{key}: not a {kind} key")
    return key


UPSERT_BRAIN_ASSET = (
    "INSERT INTO brain_assets (key, kind, mime, encoding, bytes, raw_bytes, hash, updated_at) "
    "VALUES (%s, %s, %s, 'gzip', %s, %s, %s, now()) "
    "ON CONFLICT (key) DO UPDATE SET kind = EXCLUDED.kind, mime = EXCLUDED.mime, encoding = EXCLUDED.encoding, "
    "bytes = EXCLUDED.bytes, raw_bytes = EXCLUDED.raw_bytes, hash = EXCLUDED.hash, updated_at = now() "
    "WHERE brain_assets.hash IS DISTINCT FROM EXCLUDED.hash")


def upsert_brain_asset(conn, key: str, kind: str, mime: str, data: bytes, raw_bytes: int,
                       hash: str | None = None) -> bool:
    """Insert or replace one brain asset (gzip bytes). True when the row changed. Refuses a key,
    kind or mime the contract file does not allow, data that is not gzip or is over the cap, and
    a hash that is not the sha256 of the data."""
    c = brain_contract()
    check_brain_key(key, kind)
    if mime != c["mime"]:
        raise DbError(f"{key}: mime must be {c['mime']}, not {mime!r}")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise DbError(f"{key}: data must be bytes")
    data = bytes(data)
    if data[:2] != bytes.fromhex(c["gzip_magic"]):
        raise DbError(f"{key}: not gzip data")
    lo, hi = c["stored_bytes"]["min"], c["stored_bytes"]["max"]
    if not lo <= len(data) <= hi:
        raise DbError(f"{key}: {len(data)} bytes, outside {lo} to {hi}")
    lo, hi = c["raw_bytes"]["min"], c["raw_bytes"]["max"]
    if not isinstance(raw_bytes, int) or isinstance(raw_bytes, bool) or not lo <= raw_bytes <= hi:
        raise DbError(f"{key}: raw_bytes must be a whole number from {lo} to {hi}")
    digest = hashlib.sha256(data).hexdigest()
    if hash is not None and hash != digest:
        raise DbError(f"{key}: hash is not the sha256 of the data")
    return conn.execute(UPSERT_BRAIN_ASSET, (key, kind, mime, data, raw_bytes, digest)).rowcount == 1


def brain_asset_hashes(conn) -> dict[str, str]:
    """{key: hash} for every stored brain asset (push skips the ones that did not change)."""
    return {key: digest for key, digest in conn.execute("SELECT key, hash FROM brain_assets ORDER BY key").fetchall()}


def delete_missing_brain_assets(conn, keys) -> list[str]:
    """Delete the brain assets whose key is not in keys (no brain page uses them any more)."""
    keys = sorted(set(keys))
    for k in keys:
        check_brain_key(k)
    rows = conn.execute("DELETE FROM brain_assets WHERE NOT (key = ANY(%s)) RETURNING key", (keys,)).fetchall()
    return sorted(r[0] for r in rows)


def list_brain_assets(conn) -> list[dict]:
    """Every stored brain asset as {key, kind, mime, encoding, bytes, raw_bytes, hash}, for the sync audit."""
    rows = conn.execute("SELECT key, kind, mime, encoding, bytes, raw_bytes, hash FROM brain_assets "
                        "ORDER BY key").fetchall()
    return [{"key": key, "kind": kind, "mime": mime, "encoding": enc,
             "bytes": bytes(data) if data is not None else b"", "raw_bytes": raw, "hash": digest}
            for key, kind, mime, enc, data, raw, digest in rows]


# ---------------------------------------------------------------- reel videos (D30)

def reel_video_pathname(shortcode: str, sha256: str) -> str:
    """The Blob pathname of a reel's video: reels/<shortcode>-<first 8 hex of its sha256>.mp4."""
    return f"reels/{check_reel_video_sc(shortcode)}-{str(sha256)[:8]}.mp4"


def check_reel_video_sc(shortcode) -> str:
    if not isinstance(shortcode, str) or not REEL_VIDEO_SC_RE.fullmatch(shortcode):
        raise DbError(f"not a reel video shortcode: {shortcode!r}")
    return shortcode


UPSERT_REEL_VIDEO = (
    "INSERT INTO reel_videos (shortcode, pathname, sha256, bytes, duration_s, updated_at) "
    "VALUES (%s, %s, %s, %s, %s, now()) "
    "ON CONFLICT (shortcode) DO UPDATE SET pathname = EXCLUDED.pathname, sha256 = EXCLUDED.sha256, "
    "bytes = EXCLUDED.bytes, duration_s = EXCLUDED.duration_s, updated_at = now() "
    "WHERE reel_videos.sha256 IS DISTINCT FROM EXCLUDED.sha256 "
    "OR reel_videos.pathname IS DISTINCT FROM EXCLUDED.pathname "
    "OR reel_videos.bytes IS DISTINCT FROM EXCLUDED.bytes "
    "OR reel_videos.duration_s IS DISTINCT FROM EXCLUDED.duration_s")


def upsert_reel_video(conn, shortcode: str, pathname: str, sha256: str, size: int, duration_s: float) -> bool:
    """Insert or replace one reel's video row. True when the row changed (the same file is left
    alone). Refuses what the table's CHECKs refuse, and a pathname that is not
    reels/<shortcode>-<sha8>.mp4 for this shortcode and sha256."""
    check_reel_video_sc(shortcode)
    if not isinstance(sha256, str) or not HASH_RE.fullmatch(sha256):
        raise DbError(f"{shortcode}: sha256 must be 64 lower-case hex characters")
    if not isinstance(pathname, str) or not REEL_VIDEO_PATH_RE.fullmatch(pathname):
        raise DbError(f"{shortcode}: not a reel video pathname: {pathname!r}")
    if pathname != reel_video_pathname(shortcode, sha256):
        raise DbError(f"{shortcode}: the pathname must be {reel_video_pathname(shortcode, sha256)}, not {pathname}")
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= REEL_VIDEO_MAX_BYTES:
        raise DbError(f"{shortcode}: bytes must be a whole number from 1 to {REEL_VIDEO_MAX_BYTES}")
    lo, hi = REEL_VIDEO_SECONDS
    if (isinstance(duration_s, bool) or not isinstance(duration_s, (int, float))
            or not math.isfinite(duration_s) or not lo <= duration_s <= hi):
        raise DbError(f"{shortcode}: duration_s must be from {lo:g} to {hi:g} seconds")
    params = (shortcode, pathname, sha256, size, round(float(duration_s), 3))
    return conn.execute(UPSERT_REEL_VIDEO, params).rowcount == 1


def delete_reel_video(conn, shortcode: str) -> str | None:
    """Delete one reel's video row. Returns the pathname it held (to delete the Blob file),
    or None when there was no row."""
    row = conn.execute("DELETE FROM reel_videos WHERE shortcode = %s RETURNING pathname",
                       (check_reel_video_sc(shortcode),)).fetchone()
    return row[0] if row else None


def list_reel_videos(conn) -> list[dict]:
    """Every reel video row as {shortcode, pathname, sha256, bytes, duration_s}, by shortcode."""
    rows = conn.execute("SELECT shortcode, pathname, sha256, bytes, duration_s FROM reel_videos "
                        "ORDER BY shortcode").fetchall()
    return [{"shortcode": sc, "pathname": path, "sha256": digest, "bytes": int(size),
             "duration_s": float(dur)} for sc, path, digest, size, dur in rows]


# ---------------------------------------------------------------- job kinds

@functools.lru_cache(maxsize=1)
def job_kinds() -> dict:
    """web/contracts/job-kinds.json, by kind (the allow-list the site and the runner share)."""
    doc = json.loads(JOB_KINDS_PATH.read_text(encoding="utf-8"))
    return {k["kind"]: k for k in doc["kinds"]}


def paid_kinds() -> list[str]:
    return sorted(k for k, spec in job_kinds().items() if spec["paid"])


# ---------------------------------------------------------------- jobs

def check_job_id(job_id) -> str:
    job_id = str(job_id)
    if not UUID_RE.match(job_id):
        raise DbError(f"not a job id: {job_id!r}")
    return job_id


JOB_COLS = ("id", "kind", "args", "estimate_usd", "idem_key", "created_at", "confirmed_at")

# One statement: the oldest confirmed, uncancelled queued job, skipped when paused and, for a
# paid kind, while another paid job runs. SKIP LOCKED lets two runners never take one job;
# the jobs_one_running_paid index backs up the one-paid-job rule.
CLAIM = (
    "UPDATE jobs SET status = 'running', started_at = now(), lease_until = now() + %s * interval '1 second' "
    "WHERE id = (SELECT id FROM jobs WHERE status = 'queued' AND confirmed_at IS NOT NULL AND NOT cancel_requested "
    "AND NOT COALESCE((SELECT value = 'true'::jsonb FROM settings WHERE key = 'paused'), false) "
    "AND (NOT (kind = ANY(%s)) OR NOT EXISTS "
    "(SELECT 1 FROM jobs r WHERE r.status = 'running' AND r.kind = ANY(%s))) "
    "ORDER BY created_at, id FOR UPDATE SKIP LOCKED LIMIT 1) "
    "RETURNING " + ", ".join(JOB_COLS))


def job_row(row) -> dict:
    job = dict(zip(JOB_COLS, row))
    job["id"] = str(job["id"])
    if isinstance(job["args"], str):
        job["args"] = json.loads(job["args"])
    job["estimate_usd"] = float(job["estimate_usd"] or 0)
    return job


def claim_next(conn, lease_s: int = LEASE_S) -> dict | None:
    """Take the next job (status running, lease set) or None when there is none to take."""
    paid = paid_kinds()
    try:
        row = conn.execute(CLAIM, (int(lease_s), paid, paid)).fetchone()
    except Exception as e:
        if getattr(e, "sqlstate", None) == UNIQUE_VIOLATION:
            return None   # another runner started a paid job in the same instant
        raise
    return job_row(row) if row else None


def heartbeat(conn, job_id, lease_s: int = LEASE_S) -> dict | None:
    """Renew a running job's lease. None when the job is no longer running (lease lost);
    else {"cancel_requested": bool}, so the runner can stop a job he cancelled."""
    row = conn.execute("UPDATE jobs SET lease_until = now() + %s * interval '1 second' "
                       "WHERE id = %s AND status = 'running' RETURNING cancel_requested",
                       (int(lease_s), check_job_id(job_id))).fetchone()
    return {"cancel_requested": bool(row[0])} if row else None


def clean_line(text: str, what: str) -> str:
    text = str(text).strip()
    if not text or len(text) > LINE_MAX or CONTROL_RE.search(text):
        raise DbError(f"{what} must be one line of 1 to {LINE_MAX} characters")
    return text


def finish(conn, job_id, status: str, result: dict | None = None, error_code: str | None = None,
           refusal: str | None = None) -> bool:
    """Close a queued or running job. failed needs an error_code, refused a refusal line.
    False when the job was already closed."""
    if status not in FINAL:
        raise DbError(f"finish takes one of {', '.join(FINAL)}, not {status!r}")
    if error_code is not None and not ERROR_CODE_RE.match(error_code):
        raise DbError(f"not an error code: {error_code!r}")
    if status == "failed" and not error_code:
        raise DbError("a failed job needs an error_code")
    if status == "refused" and not refusal:
        raise DbError("a refused job needs a refusal line")
    refusal = clean_line(refusal, "refusal") if refusal is not None else None
    body = None
    if result is not None:
        if not isinstance(result, dict):
            raise DbError("result is a JSON object")
        body = canonical_json(result)
        if len(body.encode("utf-8")) > RESULT_MAX:
            raise DbError(f"result is over {RESULT_MAX} bytes")
    row = conn.execute("UPDATE jobs SET status = %s, finished_at = now(), lease_until = NULL, result = %s::jsonb, "
                       "error_code = %s, refusal = %s WHERE id = %s AND status IN ('queued', 'running') RETURNING id",
                       (status, body, error_code, refusal, check_job_id(job_id))).fetchone()
    return row is not None


def interrupt_stale(conn) -> list[str]:
    """Running jobs whose lease ran out (the runner died or the laptop slept) become interrupted."""
    rows = conn.execute("UPDATE jobs SET status = 'interrupted', finished_at = now(), lease_until = NULL, "
                        "error_code = 'lease_expired' WHERE status = 'running' AND lease_until < now() "
                        "RETURNING id").fetchall()
    return [str(r[0]) for r in rows]


def cancel_queued(conn) -> list[str]:
    """Queued jobs he cancelled before they started become cancelled."""
    rows = conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = now() "
                        "WHERE status = 'queued' AND cancel_requested RETURNING id").fetchall()
    return [str(r[0]) for r in rows]


def event_line(key: str, **params) -> str:
    """One fixed progress line. Fields take whole numbers, money (usd) or one lower-case word."""
    if key not in EVENT_LINES:
        raise DbError(f"not an event line: {key!r}")
    for name, value in params.items():
        if isinstance(value, bool) or not (
                (isinstance(value, int) and abs(value) < 10 ** 9)
                or (isinstance(value, float) and math.isfinite(value) and name == "usd")
                or (isinstance(value, str) and WORD_RE.match(value))):
            raise DbError(f"event {key}: field {name} must be a whole number, usd or one lower-case word")
    try:
        return clean_line(EVENT_LINES[key].format(**params), f"event {key}")
    except (KeyError, IndexError, ValueError) as e:
        raise DbError(f"event {key}: {type(e).__name__} {e}") from None


def add_event(conn, job_id, key: str, **params) -> str:
    line = event_line(key, **params)
    conn.execute("INSERT INTO job_events (job_id, line) VALUES (%s, %s)", (check_job_id(job_id), line))
    return line


# ---------------------------------------------------------------- settings

def settings_get(conn, key: str, default=None):
    if not SETTING_KEY_RE.match(key or ""):
        raise DbError(f"not a setting key: {key!r}")
    row = conn.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
    return row[0] if row else default


def settings_set(conn, key: str, value) -> None:
    if not SETTING_KEY_RE.match(key or ""):
        raise DbError(f"not a setting key: {key!r}")
    conn.execute("INSERT INTO settings (key, value, updated_at) VALUES (%s, %s::jsonb, now()) "
                 "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                 (key, canonical_json(value)))


def is_paused(conn) -> bool:
    return settings_get(conn, "paused", False) is True
