"""Job kinds, argument checks and the D26 limits, as the laptop runner applies them.

The allow-list is web/contracts/job-kinds.json (loaded through strategist/contract.py, the
same file the site's zod checks read). The site only offers what is enabled there; the
runner re-checks everything here before a claimed job starts, and refuses with a fixed
code and one fixed line (REFUSALS). The line is what the site shows; the detail (which
argument, which number) stays in the laptop log.

Arguments get three checks, strictest last:
  1. the kind's JSON Schema in job-kinds.json (contract.check_job_args);
  2. every pattern again as a full match on ASCII (contract.validate uses re.search, where
     "$" also matches before a trailing newline), no value that starts with a dash or a
     dash lookalike (argparse and PowerShell would read it as a flag), and free text
     (a discount reason, coach text) limited to letters, digits, spaces and plain
     punctuation: no quotes, shell characters, slashes, control, format or bidi
     characters, compatibility forms (NFKC) or words that mix scripts;
  3. the store's own checks (store.check_shortcode, store.check_handle, lab ID/slug rules),
     and a reason must also pass the hosted display-text rule (no paths or file names).

The limits (D26) are pure functions over Facts, so the tests need no database:
  one paid job running at a time; at most $1 and 10 paid jobs a calendar day (laptop
  time); at most 4 TRIBE deep reads a calendar month (D21); a paid job's confirm expires
  after 30 min, may not be dated ahead and must come after the insert; the runner's own
  estimate may not be higher than the confirmed one; the Pause switch; kinds with
  enabled=false (stage gating) and kinds this runner has no executor for. Caps: Modal
  month to date (backend/ledger.py over a local copy of the ledger) plus the job may not
  pass $30, and Apify's monthly usage (its API, read before reel.add_*) plus the job may
  not pass $4.50. A cap that can't be read refuses (fails closed).

Standard library only. Apify is reached only by apify_month_usd(), and only for paid
Apify kinds; the token comes from strategist/reel.py env_value() and is never printed.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
import importlib.util
import json
import math
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

from . import contract, lab, reel, store
from .contract import ContractError
from .store import StoreError

LIMITS = contract.load_job_kinds()["limits"]
PLATFORM = contract.load_job_kinds()["platform"]
CONFIRM_TTL = dt.timedelta(minutes=LIMITS["confirm_expires_min"])
CLOCK_SKEW = dt.timedelta(minutes=2)   # laptop clock vs the database clock that stamps a confirm
HANDLE_POSTS = 30          # reel add @handle default --limit; the estimate assumes it
# The Import page's estimates include the new reels' videos (D31): a link is the post pull
# ($0.003) plus one video re-pull ($0.003); a handle is 30 posts ($0.081) plus the Apify
# video fallback, capped at VIDEO_CAP_USD per job.
IMPORT_ESTIMATE_USD = {"reel.add_link": 0.006, "reel.add_handle": 0.10}
VIDEO_CAP_USD = 0.02       # most the Apify video fallback may spend in one import job
EPS_USD = 1e-9

APIFY_LIMITS_URL = "https://api.apify.com/v2/users/me/limits"   # data.current.monthlyUsageUsd
LEDGER_PY = store.PROJECT_ROOT / "backend" / "ledger.py"
LEDGER_VOLUME = "tribe-runs"
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$", re.ASCII)

STATUSES = ("queued", "running", "done", "failed", "interrupted", "refused", "cancelled")
FINAL = ("done", "failed", "interrupted", "refused", "cancelled")
TRANSITIONS = {
    "queued": ("running", "cancelled", "refused"),
    "running": ("done", "failed", "interrupted", "refused", "cancelled"),
}
IDEM_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,120}$", re.ASCII)   # jobs.idem_key CHECK in 0000_init.sql
RETRY_PREFIX = "retry:"

# Free-text arguments, and whether a newline is allowed. Every other string argument is
# an identifier and must have a pattern or enum in job-kinds.json.
FREE_TEXT = {"reason": False, "brief": True, "text": True, "replace": True, "with": True}
TEXT_PUNCT = set(".,:!?'()+#@-_=’‘")          # plus letters, digits, marks and space
DASHES = set("-‐‑‒–—―−﹘﹣－")   # PowerShell reads –-― as "-"
TRAVERSAL_RE = re.compile(r"\.\.|^~")
ID_FIELDS_SC = ("sc", "from_sc")

# Fixed refusal lines (the site shows them; checked against dashboard/render.py rules in the tests).
REFUSALS = {
    "unknown_kind": "Not a job kind the runner knows.",
    "paused": "The runner is paused. Unpause it, then queue the job again.",
    "kind_disabled": "This job kind is not switched on yet.",
    "kind_not_built": "This runner can't run this job kind yet.",
    "bad_args": "The job's arguments failed the runner's checks.",
    "not_confirmed": "This job has no confirm click.",
    "confirm_expired": f"The confirm is over {LIMITS['confirm_expires_min']} minutes old. Confirm it again.",
    "confirm_bad_time": "The confirm time does not fit this job, so it did not start. Queue it again.",
    "estimate_higher": "The runner's estimate is higher than the confirmed one. Check it and confirm again.",
    "paid_busy": "Another paid job is running. One paid job runs at a time.",
    "daily_usd_cap": f"This would pass the ${LIMITS['paid_usd_per_day']:.2f} a day limit for paid jobs.",
    "daily_job_cap": f"{LIMITS['paid_jobs_per_day']} paid jobs already ran today, the daily limit.",
    "tribe_month_cap": f"{LIMITS['tribe_reads_per_month']} deep reads already ran this month, the monthly limit.",
    "modal_cap": f"This would pass the ${LIMITS['modal_cap_usd']:.2f} monthly Modal cap.",
    "modal_spend_unknown": "This month's Modal spend could not be read, so the paid job did not start.",
    "apify_cap": f"This would pass ${LIMITS['apify_cap_usd']:.2f} of Apify usage this month.",
    "apify_usage_unknown": "Apify usage could not be read, so the paid job did not start.",
}


class Refusal(Exception):
    """A job the runner will not start. code and line go to the database; detail stays local."""

    def __init__(self, code: str, detail: str = ""):
        if code not in REFUSALS:
            raise ValueError(f"not a refusal code: {code!r}")
        self.code, self.line, self.detail = code, REFUSALS[code], detail
        super().__init__(f"{code}: {detail or self.line}")


class UsageError(Exception):
    """A spend figure could not be read. The message never holds a token."""


# ---------------------------------------------------------------- kinds

def kinds() -> dict:
    """job-kinds.json kinds, by name."""
    return {k["kind"]: k for k in contract.load_job_kinds()["kinds"]}


def spec(kind) -> dict:
    found = kinds().get(kind) if isinstance(kind, str) else None
    if found is None:
        raise Refusal("unknown_kind", f"kind {str(kind)[:60]!r}")
    return found


def paid_kinds() -> list[str]:
    return sorted(k for k, s in kinds().items() if s["paid"])


def estimate(kind: str, args: dict) -> float:
    """The runner's own estimate in USD (D26: refused when higher than the confirmed one)."""
    s = spec(kind)
    if not s["paid"]:
        return 0.0
    if kind in IMPORT_ESTIMATE_USD:
        return IMPORT_ESTIMATE_USD[kind]
    return float(s["estimate_usd"])


# ---------------------------------------------------------------- arguments

@functools.lru_cache(maxsize=None)
def _full(pattern: str):
    """The contract's ^...$ pattern as a full match on ASCII (no trailing-newline slack)."""
    body = pattern[1:] if pattern.startswith("^") else pattern
    body = body[:-1] if body.endswith("$") and not body.endswith("\\$") else body
    return re.compile(f"(?:{body})", re.ASCII)


def _starts_with_dash(text: str) -> bool:
    return bool(text) and text[0] in DASHES


def _script(ch: str) -> str:
    try:
        return unicodedata.name(ch).split(" ", 1)[0]
    except ValueError:
        return "?"


@functools.lru_cache(maxsize=1)
def _display_text_schema() -> tuple[dict, dict]:
    root = contract.load_schema("reel")
    return {"$ref": "#/$defs/text"}, root


def check_free_text(name: str, value: str, multiline: bool, max_len: int) -> str:
    """Free text the runner passes on as data (never as a command): one line unless
    multiline, letters, digits, marks, spaces and plain punctuation only."""
    if not value or value != value.strip():
        raise Refusal("bad_args", f"{name}: empty, or spaces at the start or end")
    if len(value) > max_len:
        raise Refusal("bad_args", f"{name}: {len(value)} characters, over {max_len}")
    if unicodedata.normalize("NFKC", value) != value:
        raise Refusal("bad_args", f"{name}: compatibility or lookalike characters (NFKC changes it)")
    lines = value.split("\n")
    if len(lines) > 1 and not multiline:
        raise Refusal("bad_args", f"{name}: one line only")
    for line in lines:
        if _starts_with_dash(line.strip()):
            raise Refusal("bad_args", f"{name}: a line may not start with a dash (read as a flag)")
    for ch in value:
        if ch == "\n" or ch == " " or ch in TEXT_PUNCT:
            continue
        if unicodedata.category(ch)[0] not in "LNM":
            raise Refusal("bad_args", f"{name}: character U+{ord(ch):04X} is not allowed")
    if TRAVERSAL_RE.search(value):
        raise Refusal("bad_args", f"{name}: looks like a path")
    for word in re.findall(r"[^\W\d_]+", value):
        scripts = {_script(ch) for ch in word if unicodedata.category(ch)[0] == "L"}
        if len(scripts) > 1:
            raise Refusal("bad_args", f"{name}: a word mixes scripts ({', '.join(sorted(scripts))})")
    schema, root = _display_text_schema()
    errs = contract.validate(value, schema, root)
    if errs:
        raise Refusal("bad_args", f"{name}: not display text ({errs[0]})")
    return value


def check_identifier(name: str, value: str, prop: dict) -> str:
    """An identifier argument: its pattern or enum as a full ASCII match, no leading dash."""
    if not value.isascii() or not value.isprintable():
        raise Refusal("bad_args", f"{name}: identifiers are printable ASCII")
    if _starts_with_dash(value):
        raise Refusal("bad_args", f"{name}: may not start with a dash (read as a flag)")
    if "enum" in prop:
        if value not in prop["enum"]:
            raise Refusal("bad_args", f"{name}: not one of {prop['enum']}")
    elif "pattern" in prop:
        if not _full(prop["pattern"]).fullmatch(value):
            raise Refusal("bad_args", f"{name}: does not match {prop['pattern']}")
    else:
        raise Refusal("bad_args", f"{name}: no pattern in job-kinds.json, so the runner takes no value")
    if TRAVERSAL_RE.search(value) or "/" in value or "\\" in value:
        raise Refusal("bad_args", f"{name}: looks like a path")
    return value


def validate(kind, args) -> dict:
    """The job's arguments, checked (see the module docstring). Raises Refusal."""
    s = spec(kind)
    if not isinstance(args, dict):
        raise Refusal("bad_args", "arguments are a JSON object")
    try:
        contract.check_job_args(kind, args)
    except ContractError as e:
        raise Refusal("bad_args", str(e)[:300]) from None
    props = s["args"]["properties"]
    clean = {}
    for name, value in args.items():
        prop = props[name]
        if not isinstance(value, str):
            raise Refusal("bad_args", f"{name}: every argument is a string")
        if name in FREE_TEXT:
            clean[name] = check_free_text(name, value, FREE_TEXT[name], int(prop.get("maxLength", 200)))
        else:
            clean[name] = check_identifier(name, value, prop)
    try:   # the store's own rules too, so no argument is wider than what it accepts
        for name in ID_FIELDS_SC:
            if name in clean:
                store.check_shortcode(clean[name])
        if "handle" in clean:
            store.check_handle(clean["handle"])
    except StoreError as e:
        raise Refusal("bad_args", str(e)) from None
    if "draft_id" in clean and not lab.ID_RE.match(clean["draft_id"]):
        raise Refusal("bad_args", "draft_id: not a lab draft id")
    if "slug" in clean and not lab.SLUG_RE.match(clean["slug"]):
        raise Refusal("bad_args", "slug: not a lab slug")
    return clean


# ---------------------------------------------------------------- job states and leases

def check_transition(old: str, new: str) -> str:
    if new not in TRANSITIONS.get(old, ()):
        raise ValueError(f"a job can't go from {old!r} to {new!r}")
    return new


def lease_expired(lease_until: dt.datetime | None, now: dt.datetime) -> bool:
    return lease_until is None or lease_until < now


def retry_key(job_id: str) -> str:
    key = f"{RETRY_PREFIX}{job_id}"
    if not IDEM_RE.match(key):
        raise ValueError(f"not a usable retry key: {key!r}")
    return key


def should_retry(kind: str, idem_key: str | None, cancel_requested: bool = False) -> bool:
    """After an interruption: paid jobs never run again on their own (they may have spent);
    a free job gets one retry, and a retry is never retried."""
    s = kinds().get(kind)
    if s is None or s["paid"] or cancel_requested:
        return False
    return not (idem_key or "").startswith(RETRY_PREFIX)


# ---------------------------------------------------------------- calendar (laptop time)

def local(now: dt.datetime) -> dt.datetime:
    return (now if now.tzinfo else now.replace(tzinfo=dt.timezone.utc)).astimezone()


def day_start(now: dt.datetime) -> dt.datetime:
    n = local(now)
    return n.replace(hour=0, minute=0, second=0, microsecond=0)


def month_start(now: dt.datetime) -> dt.datetime:
    return day_start(now).replace(day=1)


# ---------------------------------------------------------------- the limits

@dataclasses.dataclass
class Facts:
    """What admit() needs to know. Money figures may be callables, read only when a paid
    job of that billing gets that far; a callable that raises refuses (fails closed)."""
    now: dt.datetime
    paused: bool = False
    paid_running_other: int = 0      # paid jobs running, this one left out
    paid_today_n: int = 0            # paid jobs started today, this one left out
    paid_today_usd: float = 0.0
    tribe_month_n: int = 0           # tribe.lanes started this month, this one left out
    modal_usd: object = None         # Modal month to date: float, callable or None (unknown)
    apify_usd: object = None         # Apify usage this month: float, callable or None (unknown)


def _read(value, code: str) -> float:
    try:
        v = value() if callable(value) else value
    except Exception as e:   # noqa: BLE001 - any failure to read a cap refuses
        raise Refusal(code, f"{type(e).__name__}: {e}"[:300]) from None
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        raise Refusal(code, f"got {v!r}")
    return float(v)


def check_confirm(job: dict, now: dt.datetime, paid: bool) -> None:
    """A free job only needs a confirm time. A paid job's confirm is his click (D26): under 30 min
    old, not dated ahead (that would never expire), and later than the insert (a row confirmed as
    it was inserted had no separate click). roles.sql enforces the same for tribe_web."""
    at = job.get("confirmed_at")
    if at is None:
        raise Refusal("not_confirmed")
    if not paid:
        return
    if at > now + CLOCK_SKEW:
        raise Refusal("confirm_bad_time", f"confirmed {(at - now).total_seconds() / 60:.0f} min ahead of now")
    if now - at > CONFIRM_TTL:
        raise Refusal("confirm_expired", f"confirmed {(now - at).total_seconds() / 60:.0f} min ago")
    created = job.get("created_at")
    if not isinstance(created, dt.datetime) or at <= created:
        raise Refusal("confirm_bad_time", "confirmed no later than it was queued")


def check_estimate(confirmed_usd, runner_usd: float) -> None:
    try:
        confirmed = float(confirmed_usd)
    except (TypeError, ValueError):
        confirmed = math.nan
    if not math.isfinite(confirmed) or runner_usd > confirmed + EPS_USD:
        raise Refusal("estimate_higher", f"runner ${runner_usd:.4f} vs confirmed {confirmed_usd!r}")


def check_paid_running(n_other: int) -> None:
    if n_other + 1 > LIMITS["paid_running_max"]:
        raise Refusal("paid_busy", f"{n_other} other paid job(s) running")


def check_daily(n_today: int, usd_today: float, est: float) -> None:
    if usd_today + est > LIMITS["paid_usd_per_day"] + EPS_USD:
        raise Refusal("daily_usd_cap", f"${usd_today:.3f} today + ${est:.3f}")
    if n_today + 1 > LIMITS["paid_jobs_per_day"]:
        raise Refusal("daily_job_cap", f"{n_today} today")


def check_tribe_month(n_month: int) -> None:
    if n_month + 1 > LIMITS["tribe_reads_per_month"]:
        raise Refusal("tribe_month_cap", f"{n_month} this month")


def check_modal(month_usd: float, est: float) -> None:
    if month_usd + est > LIMITS["modal_cap_usd"] + EPS_USD:
        raise Refusal("modal_cap", f"${month_usd:.2f} so far + ${est:.2f}")


def check_apify(month_usd: float, est: float) -> None:
    if month_usd + est > LIMITS["apify_cap_usd"] + EPS_USD:
        raise Refusal("apify_cap", f"${month_usd:.2f} so far + ${est:.3f}")


def admit(job: dict, facts: Facts, built=()) -> dict:
    """Every check before a claimed job starts, cheapest first. Returns the checked
    arguments; raises Refusal. built: the kinds this runner has an executor for."""
    s = spec(job.get("kind"))
    kind = s["kind"]
    if facts.paused:
        raise Refusal("paused")
    if not s["enabled"]:
        raise Refusal("kind_disabled", f"{kind} is stage {s['stage']}")
    if kind not in built:
        raise Refusal("kind_not_built", kind)
    args = validate(kind, job.get("args"))
    check_confirm(job, facts.now, s["paid"])
    if not s["paid"]:
        return args
    est = estimate(kind, args)
    check_estimate(job.get("estimate_usd"), est)
    check_paid_running(facts.paid_running_other)
    check_daily(facts.paid_today_n, facts.paid_today_usd, est)
    if kind == "tribe.lanes":
        check_tribe_month(facts.tribe_month_n)
    if s["billing"] == "modal":
        check_modal(_read(facts.modal_usd, "modal_spend_unknown"), est)
    if s["billing"] == "apify":
        check_apify(_read(facts.apify_usd, "apify_usage_unknown"), est)
    return args


# ---------------------------------------------------------------- spend readers

def apify_month_usd(token: str | None = None, opener=None, timeout: float = 20.0) -> float:
    """Apify's own figure for this month's usage in USD (GET /v2/users/me/limits), read for
    whatever APIFY_TOKEN is in Tribe/.env right now (never cached, so a switch to another
    account is picked up on the next check). It is that whole account's usage."""
    token = token if token is not None else reel.env_value("APIFY_TOKEN")
    if not token:
        raise UsageError("APIFY_TOKEN is not set in Tribe/.env")
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(APIFY_LIMITS_URL, headers={"Authorization": f"Bearer {token}"})
    try:
        with opener(req, timeout=timeout) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:   # the status only, never the request headers
        raise UsageError(f"Apify refused the usage request (HTTP {e.code})") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UsageError(f"Apify usage could not be read ({type(e).__name__}: {e})".replace(token, "***")) from None
    try:
        usd = body["data"]["current"]["monthlyUsageUsd"]
    except (KeyError, TypeError):
        raise UsageError("Apify answered without data.current.monthlyUsageUsd") from None
    if isinstance(usd, bool) or not isinstance(usd, (int, float)) or not math.isfinite(usd) or usd < 0:
        raise UsageError(f"Apify usage is not a number: {usd!r}")
    return float(usd)


@functools.lru_cache(maxsize=1)
def _ledger():
    """backend/ledger.py, loaded by path (backend/ is not a package)."""
    sp = importlib.util.spec_from_file_location("tribe_backend_ledger", LEDGER_PY)
    mod = importlib.util.module_from_spec(sp)
    sys.modules[sp.name] = mod   # dataclasses look the module up while it loads
    try:
        sp.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(sp.name, None)
        raise
    return mod


def modal_month_usd(ledger_root: Path, now: dt.datetime | None = None) -> float:
    """Modal month to date from a local copy of the ledger (the tribe-runs volume's ledger/
    folder; ledger_mirror_argv makes the copy). Unfinished runs count at their worst case."""
    root = Path(ledger_root)
    if not root.is_dir():
        raise UsageError("no local copy of the Modal ledger yet")
    led = _ledger()
    when = now or led.utc_now()
    try:
        return float(led.month_to_date_usd(root, when.astimezone(dt.timezone.utc)))
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise UsageError(f"the Modal ledger copy could not be read ({type(e).__name__})") from None


def ledger_mirror_argv(month: str, dest: Path) -> list[str]:
    """The argument list that copies one ledger month from the tribe-runs volume (stage 3;
    run only after `modal profile current` says your own profile). Never a shell string."""
    if not MONTH_RE.match(month or ""):
        raise ValueError(f"not a month: {month!r}")
    return ["modal", "volume", "get", "--force", LEDGER_VOLUME, f"ledger/{month}", str(Path(dest))]
