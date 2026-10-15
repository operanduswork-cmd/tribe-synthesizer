"""The laptop runner: runs the dashboard's queued jobs on this laptop (D25, D26).

Usage (from the Tribe folder):
    python -m strategist.runner                 # serve until stopped (Ctrl+C)
    python -m strategist.runner --once          # startup checks, run what is queued now, exit
    python -m strategist.runner --dry           # list queued jobs and what the runner would do; writes nothing
    python -m strategist.runner --print-task-xml   # a Task Scheduler entry for pythonw at logon (printed, not installed)
        python -m strategist.runner --print-task-xml | Out-File -Encoding Unicode tribe-runner.xml
        schtasks /Create /TN "Tribe runner" /XML tribe-runner.xml

How it works:
  - One copy only: %LOCALAPPDATA%\\Tribe\\runner.lock (exit 3 when another runner holds it).
  - It waits on the Upstash wake list (WAKE_KEY; the site pushes to it after inserting a
    job) for up to 50 s, then claims jobs from Postgres (strategist/db.py: SKIP LOCKED, a
    90 s lease renewed every 30 s while the job runs). Upstash's REST API may refuse a
    blocking pop; the runner then polls the list every POLL_S seconds instead. Between
    wakes it leaves the database alone (so Neon can sleep), except a fallback check every
    FALLBACK_POLL_S. Each wait refreshes HEARTBEAT_KEY (expires after 90 s) and
    LAST_SEEN_KEY, so the site can say "Runner: online / last seen ...".
  - On startup (and before each claim round) running jobs whose lease ran out become
    interrupted. A paid job never runs again on its own; a free job is queued once more
    (idem_key "retry:<id>"), and a retry is never retried.
  - Every claimed job goes through strategist/jobs.py admit(): the allow-list, stage
    gating, argument checks, Pause, the confirm, the re-estimate, the daily and monthly
    limits and the Modal/Apify caps. A refusal closes the job with a fixed code and line.
  - Only the stage 1 kinds in EXECUTORS run, in this process, by calling the existing CLI
    entry points with argument lists inside store.locked(): reel.build_parser() + cmd_*,
    patterns.main, lab.main and strategist.sync main(["push"]). After a job that changes
    data, the runner pushes the pages (sync push).
  - Raw output goes to %LOCALAPPDATA%\\Tribe\\logs\\<job>.log on this laptop; the site gets
    only the fixed lines in db.EVENT_LINES, never captured output.
  - For later stages: run_process() runs a child from an argument list (never a shell)
    and kills its whole tree on cancel (taskkill /T /F /PID); keep_awake() keeps the PC
    from sleeping during a paid job (SetThreadExecutionState).

Secrets: TRIBE_RUNNER_DATABASE_URL and the Upstash REST URL/token are copied from the
Tribe .env into this process by db.load_env (never printed); the Apify token is read by
strategist/reel.py env_value only when a paid Apify job is checked. Exit codes: 0 ok,
2 refused (setup missing), 3 another runner is running.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import importlib
import importlib.util
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

from . import contract, db, jobs, lab, media, patterns, reel, store
from .store import StoreError
from .transcribe import TranscribeError

APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Tribe"
LOG_DIR = APP_DIR / "logs"
LOCK_FILE = APP_DIR / "runner.lock"
LEDGER_MIRROR = APP_DIR / "ledger"          # local copy of the tribe-runs ledger/ (stage 3)

# The Upstash names come from web/contracts/runner.json, the file web/lib/redis.ts reads.
_KEYS = contract.load_runner_keys()
WAKE_KEY = _KEYS["wake_key"]                # the site LPUSHes here after inserting a job
HEARTBEAT_KEY = _KEYS["heartbeat_key"]      # ISO time, expires after HEARTBEAT_TTL_S
LAST_SEEN_KEY = _KEYS["last_seen_key"]      # ISO time, no expiry
HEARTBEAT_TTL_S = int(_KEYS["heartbeat_ttl_s"])
WAIT_S = int(_KEYS["wait_s"])               # one wait on the wake list
POLL_S = 8                                  # list polling when the REST API refuses a blocking pop
FALLBACK_POLL_S = 15 * 60                   # check the queue now and then even without a wake
NO_WAKE_POLL_S = 120                        # queue check interval when Upstash is not set up
LEASE_RENEW_S = 30
MAX_PER_ROUND = 50
UPSTASH_ENV = (("KV_REST_API_URL", "KV_REST_API_TOKEN"), ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"))
ENV_NAMES = (db.DSN_ENV,) + tuple(n for pair in UPSTASH_ENV for n in pair)

# Stage 1: the free jobs, each an in-process CLI call (cli_argv), plus the two paid import
# kinds (D31): run_import() pulls the posts, rebuilds the patterns and fetches the new videos.
IMPORT_KINDS = ("reel.add_link", "reel.add_handle")
STAGE1 = ("reel.accept", "reel.reject", "reel.discount", "patterns.build", "lab.check", "sync.push") + IMPORT_KINDS
CHANGES_DATA = ("reel.accept", "reel.reject", "reel.discount", "patterns.build", "lab.check") + IMPORT_KINDS
OK_RC = {"lab.check": (0, 1)}               # lab check exits 1 when a check failed: the draft says which
REEL_CMDS = {"accept": "cmd_accept", "reject": "cmd_reject", "discount": "cmd_discount"}
KIND_EVENT = {"patterns.build": "patterns", "lab.check": "checking", "sync.push": "syncing",
              "reel.add_link": "apify_started", "reel.add_handle": "apify_started"}

# Windows process flags and power states.
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
SHELL_LAUNCHERS = ("cmd", "cmd.exe", "command.com")

log = logging.getLogger("tribe.runner")


class RunnerError(Exception):
    """The runner can't start or can't go on. The message never holds a secret."""


class WakeError(RunnerError):
    """Upstash could not be reached or refused the token. status is the HTTP status, if any."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class WakeUnsupported(WakeError):
    """Upstash answered a blocking pop with an error (its REST API may not take them)."""


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------- one runner only

class InstanceLock:
    """A lock file held for the runner's whole life (msvcrt on Windows, fcntl elsewhere;
    the same helpers as store.locked)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.f = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, "a+b")
        if not store._try_lock(f):
            f.close()
            return False
        self.f = f
        return True

    def release(self) -> None:
        if self.f is not None:
            store._unlock(self.f)
            self.f = None


# ---------------------------------------------------------------- Upstash (REST, urllib)

def check_upstash_url(url: str) -> str:
    """Only an https *.upstash.io base URL, so the token is never sent anywhere else."""
    parts = urllib.parse.urlsplit((url or "").strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host.endswith(".upstash.io") or parts.query or parts.fragment \
            or parts.path not in ("", "/") or parts.username or parts.password:
        raise WakeError("the Upstash REST URL in .env is not an https://<name>.upstash.io address")
    return f"https://{parts.netloc}"


class Wake:
    """The wake list and the runner heartbeat on Upstash Redis, over its REST API."""

    def __init__(self, url: str, token: str, opener=None, poll_s: float = POLL_S,
                 sleep=time.sleep, clock=time.monotonic):
        if not token:
            raise WakeError("the Upstash REST token is empty")
        self.url, self._token = check_upstash_url(url), token
        self.opener = opener or urllib.request.urlopen
        self.poll_s, self.sleep, self.clock = poll_s, sleep, clock
        self.blocking = None     # None: not tried yet; False: the REST API refused BLPOP, poll instead

    @classmethod
    def from_env(cls, **kw) -> "Wake | None":
        for url_name, token_name in UPSTASH_ENV:
            url, token = os.environ.get(url_name, "").strip(), os.environ.get(token_name, "").strip()
            if url and token:
                return cls(url, token, **kw)
        return None

    def _scrub(self, text: str) -> str:
        return str(text).replace(self._token, "***")

    def _post(self, path: str, body, timeout: float):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Authorization": f"Bearer {self._token}",
                                              "Content-Type": "application/json"})
        try:
            with self.opener(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:   # the status (and Upstash's error text), never the headers
            if e.code in (401, 403):
                raise WakeError(f"Upstash refused the token (HTTP {e.code})", e.code) from None
            try:
                answer = json.loads(e.read().decode("utf-8", "replace"))
            except (ValueError, OSError, AttributeError):
                answer = None
            if isinstance(answer, dict) and "error" in answer:
                return answer
            raise WakeError(f"Upstash answered HTTP {e.code}", e.code) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise WakeError(self._scrub(f"Upstash could not be reached ({type(e).__name__}: {e})")) from None

    def cmd(self, *args, timeout: float = 15.0):
        answer = self._post("", [str(a) for a in args], timeout)
        if not isinstance(answer, dict):
            raise WakeError("Upstash answered something that is not a JSON object")
        if "error" in answer:
            raise WakeError(self._scrub(f"Upstash refused {args[0]}: {str(answer['error'])[:200]}"))
        return answer.get("result")

    def beat(self, at: str) -> None:
        answer = self._post("/pipeline", [["SET", HEARTBEAT_KEY, at, "EX", str(HEARTBEAT_TTL_S)],
                                          ["SET", LAST_SEEN_KEY, at]], 15.0)
        if not isinstance(answer, list) or any(not isinstance(a, dict) or "error" in a for a in answer):
            raise WakeError("Upstash refused the heartbeat")

    def wait(self, timeout_s: float = WAIT_S) -> bool:
        """True when the site pushed a wake within timeout_s (the list is then cleared, so a
        burst of clicks is one wake), False when the time ran out."""
        if self.blocking is not False:
            try:
                got = self._blpop(timeout_s)
                self.blocking = True
            except WakeUnsupported:
                log.info("Upstash REST refused a blocking pop; polling the wake list every %s s", self.poll_s)
                self.blocking = False
            else:
                return self._woke(got)
        deadline = self.clock() + timeout_s
        while True:
            if self._woke(self.cmd("LPOP", WAKE_KEY)):
                return True
            left = deadline - self.clock()
            if left <= 0:
                return False
            self.sleep(min(self.poll_s, left))

    def _blpop(self, timeout_s: float):
        try:
            answer = self._post("", ["BLPOP", WAKE_KEY, str(int(timeout_s))], timeout_s + 15)
        except WakeError as e:
            # a client error other than the token, or a hang past the pop's own timeout:
            # treat as "no blocking pop over REST" and poll instead
            hung = "timed out" in str(e).lower() or "timeout" in str(e).lower()
            if hung or (e.status is not None and 400 <= e.status < 500 and e.status not in (401, 403)):
                raise WakeUnsupported(str(e)) from None
            raise
        if not isinstance(answer, dict) or "error" in answer:
            raise WakeUnsupported("BLPOP refused")
        return answer.get("result")

    def _woke(self, got) -> bool:
        if got is None:
            return False
        self.cmd("DEL", WAKE_KEY)
        return True

    def push(self) -> None:
        """What the site does after inserting a job (for a manual test from this laptop)."""
        self.cmd("LPUSH", WAKE_KEY, "1")


# ---------------------------------------------------------------- the queue (Postgres)

PAID_STATS = (
    "SELECT count(*) FILTER (WHERE status = 'running' AND kind = ANY(%s)), "
    "count(*) FILTER (WHERE kind = ANY(%s) AND started_at >= %s), "
    "COALESCE(sum(estimate_usd) FILTER (WHERE kind = ANY(%s) AND started_at >= %s), 0), "
    "count(*) FILTER (WHERE kind = 'tribe.lanes' AND started_at >= %s) "
    "FROM jobs WHERE id <> %s AND status IN ('running', 'done', 'failed', 'interrupted')")

RETRY_INSERT = (
    "INSERT INTO jobs (kind, args, estimate_usd, idem_key, confirmed_at) "
    "SELECT kind, args, estimate_usd, %s, now() FROM jobs "
    "WHERE id = %s AND status = 'interrupted' AND NOT cancel_requested "
    "AND NOT EXISTS (SELECT 1 FROM jobs l WHERE l.idem_key = %s AND l.status IN ('queued', 'running')) "
    "RETURNING id")

LIST_QUEUED = (
    "SELECT " + ", ".join(db.JOB_COLS) + " FROM jobs WHERE status = 'queued' AND NOT cancel_requested "
    "ORDER BY created_at, id LIMIT %s")


class DbQueue:
    """The runner's view of the jobs table, through strategist/db.py. Reconnects lazily
    after reset() (Neon closes idle connections when it sleeps)."""

    def __init__(self, connect=None):
        self._connect = connect or db.connect
        self._conn = None
        self._guard = threading.RLock()

    def conn(self):
        with self._guard:
            if self._conn is None or getattr(self._conn, "closed", False):
                self._conn = self._connect()
            return self._conn

    def reset(self) -> None:
        with self._guard:
            if self._conn is not None:
                with contextlib.suppress(Exception):
                    self._conn.close()
            self._conn = None

    def claim(self):
        return db.claim_next(self.conn())

    def heartbeat(self, job_id):
        return db.heartbeat(self.conn(), job_id)

    def finish(self, job_id, status, **kw) -> bool:
        return db.finish(self.conn(), job_id, status, **kw)

    def add_event(self, job_id, key, **params) -> str:
        return db.add_event(self.conn(), job_id, key, **params)

    def interrupt_stale(self) -> list[str]:
        return db.interrupt_stale(self.conn())

    def cancel_queued(self) -> list[str]:
        return db.cancel_queued(self.conn())

    def is_paused(self) -> bool:
        return db.is_paused(self.conn())

    def paid_stats(self, job_id, day: dt.datetime, month: dt.datetime) -> dict:
        paid = jobs.paid_kinds()
        row = self.conn().execute(PAID_STATS, (paid, paid, day, paid, day, month, db.check_job_id(job_id))).fetchone()
        return {"running_other": int(row[0]), "today_n": int(row[1]), "today_usd": float(row[2] or 0),
                "tribe_month_n": int(row[3])}

    def retry_interrupted(self, job_id) -> str | None:
        """Queue an interrupted free job once more (jobs.should_retry). The new job's id, or None."""
        job_id = db.check_job_id(job_id)
        row = self.conn().execute("SELECT kind, idem_key, cancel_requested FROM jobs WHERE id = %s",
                                  (job_id,)).fetchone()
        if not row or not jobs.should_retry(row[0], row[1], bool(row[2])):
            return None
        key = jobs.retry_key(job_id)
        try:
            new = self.conn().execute(RETRY_INSERT, (key, job_id, key)).fetchone()
        except Exception as e:
            if getattr(e, "sqlstate", None) == db.UNIQUE_VIOLATION:
                return None    # its retry was queued in the same instant (jobs_idem_live)
            raise
        return str(new[0]) if new else None

    def list_queued(self, limit: int = 20) -> list[dict]:
        return [db.job_row(r) for r in self.conn().execute(LIST_QUEUED, (int(limit),)).fetchall()]


# ---------------------------------------------------------------- executors (stage 1, in process)

def cli_argv(kind: str, args: dict) -> tuple[str, list[str]]:
    """The module and argument list for a stage 1 job. The arguments are already checked by
    jobs.validate (no value starts with a dash); a reason goes in as --reason=<text>."""
    if kind == "reel.accept":
        return "reel", ["accept", args["sc"], args["field"]]
    if kind == "reel.reject":
        return "reel", ["reject", args["sc"], args["field"]]
    if kind == "reel.discount":
        return "reel", ["discount", args["sc"], f"--reason={args['reason']}"]
    if kind == "patterns.build":
        return "patterns", ["build"]
    if kind == "lab.check":
        return "lab", ["check", args["draft_id"]]
    if kind == "sync.push":
        return "sync", ["push"]
    raise RunnerError(f"no command for {kind}")


def _quiet(out, fn, *a) -> int:
    """Run fn with stdout and stderr in the job's log; argparse's exit becomes its code."""
    out.flush()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            rc = fn(*a)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 2
    return 0 if rc is None else int(rc)


def _reel_call(argv: list[str]) -> int:
    ns = reel.build_parser().parse_args(argv)
    try:
        if ns.cmd == "add":   # the two import kinds: a handle or a link built from a shortcode
            return reel.cmd_add_handle(ns.target, ns) if ns.target.startswith("@") else reel.cmd_add_url(ns.target, ns)
        return getattr(reel, REEL_CMDS[ns.cmd])(ns)
    except (reel.ReelError, StoreError, TranscribeError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


def run_cli(kind: str, args: dict, out) -> int:
    module, argv = cli_argv(kind, args)
    if module == "reel":
        return _quiet(out, _reel_call, argv)
    if module == "patterns":
        return _quiet(out, patterns.main, argv)
    if module == "lab":
        return _quiet(out, lab.main, argv)
    raise RunnerError(f"{kind} is not an in-process CLI job")


def run_sync(out) -> int | None:
    """strategist.sync main(["push"]). None when the module is not there yet."""
    if importlib.util.find_spec("strategist.sync") is None:
        return None
    sync = importlib.import_module("strategist.sync")
    return _quiet(out, sync.main, ["push"])


class Cancelled(Exception):
    """The cancel click (or a lost lease) was seen between two steps of a job."""


class ImportContext:
    """What an import job may use: should_stop() (the lease saw a cancel), event() (a fixed
    progress line) and kill (how to end a child's whole tree, replaceable in tests)."""

    def __init__(self, should_stop=lambda: False, event=lambda key, **p: None, kill=None):
        self.should_stop, self.event = should_stop, event
        self.kill = kill or kill_tree

    def check(self) -> None:
        if self.should_stop():
            self.event("cancel_seen")
            raise Cancelled()


def cancellable_run_tool(ctx: ImportContext, popen=subprocess.Popen, poll_s: float = 0.5):
    """A drop-in for media.run_tool (ffmpeg, ffprobe, yt-dlp) that watches for a cancel while the
    child runs and kills the child's whole tree, then raises Cancelled."""
    def run_tool(cmd, *, cwd=None, timeout=None, env=None):
        argv = check_argv(cmd)
        kw = {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW} if os.name == "nt" \
            else {"start_new_session": True}
        proc = popen(argv, shell=False, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", close_fds=True, **kw)
        started = time.monotonic()
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=poll_s)
                return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                pass
            if ctx.should_stop():
                ctx.kill(proc.pid)
                with contextlib.suppress(Exception):
                    proc.communicate(timeout=10)
                ctx.event("cancel_seen")
                raise Cancelled()
            if timeout is not None and time.monotonic() - started > timeout:
                ctx.kill(proc.pid)
                with contextlib.suppress(Exception):
                    proc.communicate(timeout=10)
                raise subprocess.TimeoutExpired(argv, timeout)
    return run_tool


def import_target(kind: str, args: dict) -> tuple[str, str]:
    """(target for reel add, label). The link is built here from the shortcode, never taken from the site."""
    if kind == "reel.add_link":
        return reel.reel_url(store.check_shortcode(args["sc"])), args["sc"]
    if kind == "reel.add_handle":
        handle = store.check_handle(args["handle"])
        return f"@{handle}", f"@{handle}"
    raise RunnerError(f"{kind} is not an import job")


def _fetch_log_rows() -> list[dict]:
    path = store.fetch_log_path()
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def run_import(kind: str, args: dict, out, ctx: ImportContext | None = None) -> int:
    """reel.add_link / reel.add_handle (D31), inside store.locked() (the runner holds it):
      1. reel.cmd_add_url / cmd_add_handle (limit 30) with yes=True: the Apify post pull, and the
         temp video for the timed words and stills (deleted at once);
      2. patterns.build;
      3. media.fetch_one for each new reel: free sources first, then the Apify re-pull, capped at
         jobs.VIDEO_CAP_USD for the whole job.
    The runner pushes the pages afterwards (sync.push). Cancel is checked between steps and kills a
    running ffmpeg/yt-dlp tree. Returns 0, or the pull's own non-zero code when it was refused."""
    ctx = ctx or ImportContext()
    target, label = import_target(kind, args)
    before = {r["shortcode"] for r in store.list_reels(include_archived=True)}
    log_before = len(_fetch_log_rows())
    ctx.check()
    argv = ["add", target, "--yes"] + (["--limit", str(jobs.HANDLE_POSTS)] if kind == "reel.add_handle" else [])
    rc = _quiet(out, _reel_call, argv)
    items = sum(int(r.get("items") or 0) for r in _fetch_log_rows()[log_before:])
    ctx.event("apify_done", n=items)
    if rc != 0:
        return rc
    ctx.event("transcribing")
    ctx.event("stills")
    ctx.check()
    if kind == "reel.add_link":
        new = [args["sc"]] if store.reel_path(args["sc"]).is_file() else []
    else:
        new = sorted({r["shortcode"] for r in store.list_reels(include_archived=True)} - before)
    out.write(f"{label}: new reels {', '.join(new) or 'none'}\n")
    rc = _quiet(out, patterns.main, ["build"])
    ctx.check()
    if rc != 0:
        return rc
    spent_before = media.apify_spent()
    opts = argparse.Namespace(force=False, allow_apify=True, yes=True, max_usd=spent_before + jobs.VIDEO_CAP_USD)
    missing = 0
    saved = media.run_tool
    media.run_tool = cancellable_run_tool(ctx)
    try:
        for sc in new:
            ctx.check()
            try:
                got = media.fetch_one(sc, opts, lambda t: out.write(f"{t}\n"))
                out.write(f"{sc}: video {got.get('source')}\n")
            except (media.MediaError, StoreError, reel.ReelError) as e:
                missing += 1
                out.write(f"{sc}: no video ({e})\n")
    finally:
        media.run_tool = saved
    out.write(f"{len(new) - missing} of {len(new)} new reels have a video; Apify video re-pulls this job "
              f"${media.apify_spent() - spent_before:.3f} of ${jobs.VIDEO_CAP_USD:.2f}\n")
    return 0


run_import.wants_ctx = True
EXECUTORS = {kind: (run_import if kind in IMPORT_KINDS else run_cli) for kind in STAGE1 if kind != "sync.push"}


# ---------------------------------------------------------------- child processes (later stages)

def check_argv(argv) -> list[str]:
    """A child command as an argument list: never a shell string, never cmd.exe or a .bat/.cmd
    file (cmd re-parses its arguments), no NUL characters."""
    if not isinstance(argv, (list, tuple)) or not argv or not all(isinstance(a, str) for a in argv):
        raise RunnerError("a command is a non-empty list of strings")
    if any("\x00" in a for a in argv):
        raise RunnerError("a command argument holds a NUL character")
    name = Path(argv[0]).name.lower()
    if name in SHELL_LAUNCHERS or name.endswith((".bat", ".cmd")):
        raise RunnerError(f"{argv[0]!r} would re-parse its arguments through cmd")
    return list(argv)


def kill_tree(pid: int, run=subprocess.run) -> None:
    """Kill a child and everything it started (taskkill /T /F on Windows)."""
    pid = int(pid)
    if os.name == "nt":
        run(["taskkill", "/T", "/F", "/PID", str(pid)], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        import signal
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)


def run_process(argv, out, should_cancel=lambda: False, timeout_s: float | None = None, poll_s: float = 0.5,
                popen=subprocess.Popen, kill=kill_tree, env=None, cwd=None):
    """Run a child to the end with its output in the job's log. Returns its exit code, or
    "cancelled" / "timeout" after killing its whole tree."""
    argv = check_argv(argv)
    out.flush()
    kw = {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW} if os.name == "nt" \
        else {"start_new_session": True}
    proc = popen(argv, shell=False, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                 env=env, cwd=cwd, close_fds=True, **kw)
    started = time.monotonic()
    while True:
        rc = proc.poll()
        if rc is not None:
            return rc
        why = "cancelled" if should_cancel() else (
            "timeout" if timeout_s is not None and time.monotonic() - started > timeout_s else None)
        if why:
            kill(proc.pid)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(10)
            return why
        time.sleep(poll_s)


@contextlib.contextmanager
def keep_awake():
    """Keep the PC from sleeping while the block runs (a paid job). Windows only; a no-op
    elsewhere. The display may still turn off."""
    k32 = None
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetThreadExecutionState.argtypes = [ctypes.c_uint32]
        k32.SetThreadExecutionState.restype = ctypes.c_uint32
        if not k32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
            log.warning("SetThreadExecutionState refused; the PC may sleep during this job")
    try:
        yield
    finally:
        if k32 is not None:
            k32.SetThreadExecutionState(ES_CONTINUOUS)


# ---------------------------------------------------------------- the lease

class Lease:
    """Renews a running job's lease every LEASE_RENEW_S on a side thread, and notices a
    cancel click (cancel) or a lost lease (lost)."""

    def __init__(self, runner: "Runner", job_id: str, every_s: float = LEASE_RENEW_S):
        self.runner, self.job_id, self.every_s = runner, job_id, every_s
        self.cancel, self.lost, self._stop = threading.Event(), threading.Event(), threading.Event()
        self._thread = threading.Thread(target=self._loop, name=f"lease-{job_id[:8]}", daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(10)

    def _loop(self):
        while not self._stop.wait(self.every_s):
            self.renew()

    def renew(self) -> None:
        try:
            state = self.runner.queue.heartbeat(self.job_id)
        except Exception as e:   # noqa: BLE001 - a missed renewal is logged; the lease lasts 90 s
            log.warning("lease renewal for %s failed: %s", self.job_id, type(e).__name__)
            return
        if state is None:
            self.lost.set()
        elif state.get("cancel_requested"):
            self.cancel.set()
        self.runner.beat()

    def should_stop(self) -> bool:
        return self.cancel.is_set() or self.lost.is_set()


# ---------------------------------------------------------------- the runner

class Runner:
    def __init__(self, queue, wake: Wake | None = None, executors=None, sync=run_sync, log_dir: Path = None,
                 clock=now_utc, apify_usd=None, modal_usd=None, lease_s: float = LEASE_RENEW_S):
        self.queue, self.wake = queue, wake
        self.executors = EXECUTORS if executors is None else executors
        self.built = tuple(self.executors) + (("sync.push",) if sync is not None else ())
        self.sync = sync
        self.log_dir = Path(log_dir or LOG_DIR)
        self.clock = clock
        self.apify_usd = apify_usd or (lambda: jobs.apify_month_usd())
        self.modal_usd = modal_usd or (lambda now: jobs.modal_month_usd(LEDGER_MIRROR, now))
        self.lease_s = lease_s
        self.stopping = threading.Event()

    # -- small helpers

    def beat(self) -> None:
        if self.wake is None:
            return
        try:
            self.wake.beat(self.clock().isoformat(timespec="seconds"))
        except WakeError as e:
            log.warning("heartbeat not sent: %s", e)

    def event(self, job_id: str, key: str, **params) -> None:
        try:
            self.queue.add_event(job_id, key, **params)
        except Exception as e:   # noqa: BLE001 - a lost progress line never stops a job
            log.warning("event %s for %s not written: %s", key, job_id, type(e).__name__)

    def close(self, job_id: str, status: str, **kw) -> None:
        if not self.queue.finish(job_id, status, **kw):
            log.warning("job %s was already closed (lease lost?) when it ended %s", job_id, status)

    def facts(self, job: dict) -> jobs.Facts:
        s = jobs.spec(job.get("kind"))
        now = self.clock()
        f = jobs.Facts(now=now, paused=self.queue.is_paused())
        if s["paid"]:
            st = self.queue.paid_stats(job["id"], jobs.day_start(now), jobs.month_start(now))
            f.paid_running_other, f.paid_today_n = st["running_other"], st["today_n"]
            f.paid_today_usd, f.tribe_month_n = st["today_usd"], st["tribe_month_n"]
            f.modal_usd = lambda: self.modal_usd(now)
            f.apify_usd = self.apify_usd
        return f

    # -- rounds

    def housekeeping(self) -> None:
        """Expired leases become interrupted (free jobs retried once); cancelled queued jobs close."""
        for job_id in self.queue.interrupt_stale():
            self.event(job_id, "interrupted")
            retry = self.queue.retry_interrupted(job_id)
            log.info("job %s interrupted (lease ran out)%s", job_id, f"; queued again as {retry}" if retry else "")
        for job_id in self.queue.cancel_queued():
            self.event(job_id, "cancelled")
            log.info("job %s cancelled before it started", job_id)

    def round(self) -> int:
        """Housekeeping, then every job that can be claimed now. Returns how many ran."""
        self.housekeeping()
        n = 0
        while n < MAX_PER_ROUND and not self.stopping.is_set():
            job = self.queue.claim()
            if not job:
                break
            self.run_job(job)
            n += 1
        return n

    def safe_round(self) -> int:
        """round(), reconnecting once if the database connection dropped (Neon sleeps).
        A second failure is logged and the runner waits for the next wake."""
        for attempt in (1, 2):
            try:
                return self.round()
            except Exception as e:   # noqa: BLE001 - most likely a dropped connection
                first = str(e).splitlines()[0][:200] if str(e) else ""
                log.warning("queue round failed (%s: %s)%s", type(e).__name__, first,
                            "; reconnecting" if attempt == 1 else "; waiting for the next wake")
                self.queue.reset()
        return 0

    def serve(self, once: bool = False) -> None:
        self.beat()
        self.safe_round()
        if once:
            return
        last = time.monotonic()
        while not self.stopping.is_set():
            self.beat()
            if self.wake is None:
                woke = self.stopping.wait(NO_WAKE_POLL_S) is False
            else:
                try:
                    woke = self.wake.wait(WAIT_S)
                except WakeError as e:
                    log.warning("wake wait failed: %s", e)
                    self.stopping.wait(10)
                    woke = False
            if woke or time.monotonic() - last >= FALLBACK_POLL_S:
                self.safe_round()
                last = time.monotonic()

    # -- one job

    def run_job(self, job: dict) -> str:
        """Admit, run and close one claimed job. Returns its final status."""
        job_id = job["id"]
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with open(self.log_dir / f"{db.check_job_id(job_id)}.log", "a", encoding="utf-8", newline="\n") as out:
            out.write(f"== {self.clock().isoformat(timespec='seconds')} job {job_id} {job.get('kind')}\n")
            self.event(job_id, "started")
            try:
                args = jobs.admit(job, self.facts(job), built=self.built)
            except jobs.Refusal as r:
                out.write(f"refused: {r.code}: {r.detail or r.line}\n")
                self.close(job_id, "refused", error_code=r.code, refusal=r.line)
                self.event(job_id, "refused", code=r.code)
                return "refused"
            kind = job["kind"]
            paid = jobs.spec(kind)["paid"]
            with Lease(self, job_id, self.lease_s) as lease, (keep_awake() if paid else contextlib.nullcontext()):
                lease.renew()
                if lease.should_stop():
                    status = "cancelled" if lease.cancel.is_set() else "interrupted"
                    out.write(f"{status} before it started\n")
                    self.close(job_id, status, error_code=None if status == "cancelled" else "lease_lost")
                    self.event(job_id, "cancelled" if status == "cancelled" else "interrupted")
                    return status
                status, code, result = self._execute(kind, args, out, lease)
            out.write(f"-> {status}{f' ({code})' if code else ''}\n")
            self.close(job_id, status, error_code=code, result=result)
            if status == "cancelled":
                self.event(job_id, "cancelled")
            else:
                self.event(job_id, "done" if status == "done" else "failed", **({"code": code} if code else {}))
            return status

    def _execute(self, kind: str, args: dict, out, lease: Lease) -> tuple[str, str | None, dict]:
        job_steps = 2 if kind in CHANGES_DATA else 1
        try:
            with store.locked():
                if kind in KIND_EVENT:
                    self.event_for(lease, KIND_EVENT[kind])
                if kind == "sync.push":
                    rc = self._sync(out)
                    if rc is None:
                        return "failed", "sync_missing", {}
                    return ("done", None, {"rc": rc}) if rc == 0 else ("failed", "sync_failed", {"rc": rc})
                self.event_for(lease, "step", n=1, total=job_steps)
                fn = self.executors[kind]
                if getattr(fn, "wants_ctx", False):
                    ctx = ImportContext(lease.should_stop, lambda key, **p: self.event_for(lease, key, **p))
                    rc = fn(kind, args, out, ctx)
                else:
                    rc = fn(kind, args, out)
                if rc not in OK_RC.get(kind, (0,)):
                    return "failed", "cli_refused", {"rc": rc}
                result = {"rc": rc, "synced": False}
                self.event_for(lease, "step", n=2, total=job_steps)
                self.event_for(lease, "syncing")
                synced = self._sync(out)
                result["synced"] = synced == 0
                if synced != 0:
                    self.event_for(lease, "failed", code="sync_missing" if synced is None else "sync_failed")
                return "done", None, result
        except Cancelled:
            out.write("cancelled by the cancel click\n")
            return "cancelled", None, {}
        except store.LockTimeout as e:
            out.write(f"{e}\n")
            return "failed", "lock_busy", {}
        except Exception:   # noqa: BLE001 - the traceback stays in the laptop log
            out.write(traceback.format_exc())
            return "failed", "crashed", {}

    def event_for(self, lease: Lease, key: str, **params) -> None:
        self.event(lease.job_id, key, **params)

    def _sync(self, out) -> int | None:
        if self.sync is None:
            return None
        try:
            return self.sync(out)
        except Exception:   # noqa: BLE001
            out.write(traceback.format_exc())
            return 1

    # -- dry run

    def dry(self, write=print) -> int:
        """What the runner would do with the queued jobs now. Reads only; caps not read."""
        write(f"Paused: {'yes' if self.queue.is_paused() else 'no'}")
        write(f"Upstash: {'set up' if self.wake else 'not set up (the queue is polled every 120 s)'}")
        queued = self.queue.list_queued()
        write(f"Queued jobs: {len(queued)}")
        for job in queued:
            try:
                f = self.facts(job)
                f.modal_usd = f.apify_usd = 0.0
                jobs.admit(job, f, built=self.built)
                verdict = "would run" + (" (Modal/Apify caps are read only on a real run)"
                                         if jobs.spec(job["kind"])["paid"] else "")
            except jobs.Refusal as r:
                verdict = f"would refuse: {r.code} ({r.detail or r.line})"
            write(f"  {job['id']}  {job.get('kind')}  {verdict}")
        return 0


# ---------------------------------------------------------------- Task Scheduler entry

def task_xml(python: Path | None = None, workdir: Path | None = None, user: str | None = None) -> str:
    """A Task Scheduler task that starts pythonw -m strategist.runner at logon (printed only)."""
    exe = Path(python or sys.executable)
    pyw = exe.with_name("pythonw.exe")
    exe = pyw if pyw.is_file() else exe
    workdir = Path(workdir or store.PROJECT_ROOT)
    user = user or (f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"
                    if os.environ.get("USERDOMAIN") and os.environ.get("USERNAME") else os.environ.get("USERNAME", ""))
    user_xml = f"\n      <UserId>{escape(user)}</UserId>" if user else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Tribe laptop runner: runs the dashboard's queued jobs (python -m strategist.runner).</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>{user_xml}
      <Delay>PT30S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">{user_xml}
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(exe))}</Command>
      <Arguments>-m strategist.runner</Arguments>
      <WorkingDirectory>{escape(str(workdir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


# ---------------------------------------------------------------- entry

def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("tribe")
    root.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(LOG_DIR / "runner.log", maxBytes=1 << 20, backupCount=3,
                                              encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root.addHandler(fh)
    if sys.stderr is not None:   # pythonw has no console
        root.addHandler(logging.StreamHandler(sys.stderr))


def say(text: str) -> None:
    if sys.stdout is not None:
        print(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strategist.runner", description="Tribe laptop runner")
    ap.add_argument("--once", action="store_true", help="run what is queued now, then exit")
    ap.add_argument("--dry", action="store_true", help="show what would run; write nothing")
    ap.add_argument("--print-task-xml", action="store_true", help="print a Task Scheduler entry (not installed)")
    args = ap.parse_args(argv)
    if args.print_task_xml:
        say(task_xml())
        return 0
    setup_logging()
    lock = None
    if not args.dry:
        lock = InstanceLock(LOCK_FILE)
        if not lock.acquire():
            say(f"refused: another runner is already running (it holds {LOCK_FILE.name})")
            return 3
    try:
        db.load_env(ENV_NAMES)
        queue = DbQueue()
        try:
            queue.conn()
            wake = Wake.from_env()
        except (db.DbError, RunnerError) as e:
            say(f"refused: {e}")
            return 2
        if wake is None:
            log.warning("Upstash is not set up (KV_REST_API_URL / KV_REST_API_TOKEN in .env): "
                        "no heartbeat, and the queue is checked every %s s", NO_WAKE_POLL_S)
        runner = Runner(queue, wake)
        if args.dry:
            return runner.dry(say)
        log.info("runner started%s", " (--once)" if args.once else "")
        try:
            runner.serve(once=args.once)
        except KeyboardInterrupt:
            log.info("runner stopped (Ctrl+C); a running job's lease runs out and it shows as interrupted")
        return 0
    finally:
        if lock is not None:
            lock.release()


if __name__ == "__main__":
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
