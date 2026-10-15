"""Swipe store: the shared-contract JSON files under swipe/ (gitignored), written atomically.

Files (see the plan's shared contract):
    swipe/creators/<handle>.json            baseline, reels only
    swipe/creators/private/<handle>.items.json   trimmed public post list the baseline came from
    swipe/reels/<sc>/reel.json              counts, x, flags, facts, shape, TRIBE link
    swipe/reels/<sc>/private/               words.json, transcript.txt, caption.txt, stills/ (never exported)
    swipe/patterns.json, swipe/fetch-log.jsonl
    swipe/.lock                             held by locked(): one writer at a time

locked() is a file lock (msvcrt on Windows, fcntl elsewhere) that the CLI and the laptop
runner both take, re-entrant inside one process. save_reel, save_creator and the patterns
write take it themselves; a read-modify-write (load a reel, change it, save it) is only
safe when the caller holds it around the whole step, as the runner does for each job.

Baseline logic is ported from VAULT scrapers/ig.py (read for logic, never imported)
with three fixes: reels only (VAULT's "median of 29 posts" mixed every post type),
pinned / paid / under-48 h posts left out, and n plus every left-out shortcode
recorded. An outlier is x.plays >= 2 against the creator's own median (VAULT
research/OUTLIERS.md rule 1) and not discounted by hand.

Apify field names were checked against VAULT research/raw/ig-demo_creator_a.json and
ig-demo_creator_b.json: shortCode, productType ("clips" = reel), type, timestamp,
videoPlayCount, likesCount, commentsCount, isPinned (present only when pinned),
paidPartnership, videoDuration, caption, latestComments.

Standard library only.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import statistics
import sys
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SWIPE = PROJECT_ROOT / "swipe"
DRAFTS = PROJECT_ROOT / "drafts"
OUTPUTS = PROJECT_ROOT / "outputs"
# Optional private vault of your own notes and earlier pulls (read-only). Unset means no vault.
VAULT = Path(os.environ.get("TRIBE_VAULT_DIR") or Path.home() / "tribe-vault")   # read-only

THIN_N = 20            # baselines under 20 reels are thin (VAULT OUTLIERS.md rule 4)
OUTLIER_X = 2.0        # 2x the creator's own median (VAULT OUTLIERS.md rule 1)
FRESH_H = 48           # posts under 48 h old have unsettled counts (rule 4)
OVER_S = 60            # TRIBE input limit (CLAUDE.md "Inputs")
COUNT_KEYS = ("plays", "likes", "comments")
SOURCE_FIELD = {"plays": "videoPlayCount", "likes": "likesCount", "comments": "commentsCount"}
EXCLUDED_KEYS = ("pinned", "paid", "fresh", "target", "not_reel")
GATED_CTAS = {"comment-keyword", "dm-keyword"}   # keyword gates inflate comment counts (rule 4)
SHAPE_FIELDS = ("hook_shape", "format", "cta", "beats")
STATUSES = ("suggested", "accepted", "rejected")
SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]{5,40}$")
HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
LOCK_TIMEOUT_S = 30.0   # how long locked() waits for another Tribe process before refusing
ITEM_KEEP = ("shortCode", "url", "ownerUsername", "timestamp", "type", "productType", "isPinned",
             "paidPartnership", "videoPlayCount", "likesCount", "commentsCount", "videoDuration", "caption")


class StoreError(Exception):
    """A store operation was refused. The message says why."""


class LockTimeout(StoreError):
    """swipe/.lock stayed held by another Tribe process (the CLI or the runner)."""


# ---------------------------------------------------------------- time

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def file_time_iso(path: Path) -> str:
    return dt.datetime.fromtimestamp(Path(path).stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds")


def parse_time(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------- files

# ---------------------------------------------------------------- the swipe lock

_LOCK_GUARD = threading.RLock()   # threads of this process, one at a time
_LOCKS: dict[str, list] = {}      # lock path -> [open lock file, depth]


def lock_path() -> Path:
    return SWIPE / ".lock"


def _try_lock(f) -> bool:
    try:
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(f) -> None:
    try:
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass   # closing the file below releases it too
    finally:
        f.close()


@contextlib.contextmanager
def locked(timeout: float | None = None):
    """Hold swipe/.lock for the block: one writer at a time across the CLI and the runner.
    Re-entrant in one process, so a job holding it can still call save_reel. Waits up to
    timeout seconds (LOCK_TIMEOUT_S by default) for another process, then raises LockTimeout."""
    timeout = LOCK_TIMEOUT_S if timeout is None else timeout
    path = lock_path()
    key = str(path)
    if not _LOCK_GUARD.acquire(timeout=max(float(timeout), 0.0)):
        raise LockTimeout(f"swipe/ is busy in this process (waited {timeout:g} s for swipe/.lock)")
    try:
        held = _LOCKS.get(key)
        if held:
            held[1] += 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            f = open(path, "a+b")
            deadline = time.monotonic() + max(float(timeout), 0.0)
            while not _try_lock(f):
                if time.monotonic() >= deadline:
                    f.close()
                    raise LockTimeout(f"swipe/ is busy: another Tribe command or the runner holds swipe/.lock "
                                      f"(waited {timeout:g} s). Try again when it finishes.")
                time.sleep(0.05)
            _LOCKS[key] = held = [f, 1]
        try:
            yield path
        finally:
            held[1] -= 1
            if held[1] == 0:
                del _LOCKS[key]
                _unlock(held[0])
    finally:
        _LOCK_GUARD.release()


def load_json(path: Path, default=None):
    path = Path(path)
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, obj) -> Path:
    """Write JSON atomically: a temp file in the same folder, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, indent=1, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def save_text(path: Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)
    return path


def append_jsonl(path: Path, row: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def check_shortcode(sc: str) -> str:
    if not SHORTCODE_RE.match(sc or ""):
        raise StoreError(f"not a reel shortcode: {sc!r}")
    return sc


def check_handle(handle: str) -> str:
    handle = (handle or "").lstrip("@")
    if not HANDLE_RE.match(handle):
        raise StoreError(f"not an Instagram handle: {handle!r}")
    return handle


def creator_path(handle: str) -> Path:
    return SWIPE / "creators" / f"{check_handle(handle)}.json"


def creator_items_path(handle: str) -> Path:
    return SWIPE / "creators" / "private" / f"{check_handle(handle)}.items.json"


def reel_dir(sc: str) -> Path:
    return SWIPE / "reels" / check_shortcode(sc)


def reel_path(sc: str) -> Path:
    return reel_dir(sc) / "reel.json"


def private_dir(sc: str) -> Path:
    return reel_dir(sc) / "private"


def patterns_path() -> Path:
    return SWIPE / "patterns.json"


def fetch_log_path() -> Path:
    return SWIPE / "fetch-log.jsonl"


def load_creator(handle: str) -> dict | None:
    return load_json(creator_path(handle))


def save_creator(creator: dict) -> Path:
    creator["updated_at"] = now_iso()
    with locked():
        return save_json(creator_path(creator["handle"]), creator)


def load_reel(sc: str) -> dict:
    reel = load_json(reel_path(sc))
    if reel is None:
        raise StoreError(f"no reel {sc} in the swipe file (swipe/reels/{sc}/reel.json)")
    return reel


def save_reel(reel: dict) -> Path:
    with locked():
        return save_json(reel_path(reel["shortcode"]), reel)


def list_reels(include_archived: bool = False) -> list[dict]:
    """Every swipe reel. Archived reels (reel.json "archived": true, D31) are skipped by default,
    which hides them from the board, patterns, reel pages and the hosted sync in one place.
    Their files stay on disk; media.py and the privacy scans pass include_archived=True."""
    root = SWIPE / "reels"
    if not root.is_dir():
        return []
    reels = []
    for p in sorted(root.glob("*/reel.json")):
        reel = json.loads(p.read_text(encoding="utf-8"))
        if reel.get("archived") and not include_archived:
            continue
        reels.append(reel)
    return reels


def load_words(sc: str) -> list[dict]:
    return load_json(private_dir(sc) / "words.json", []) or []


def log_fetch(what: str, items: int, est_usd: float, actor: str, ok: bool) -> dict:
    row = {"at": now_iso(), "what": what, "items": items, "est_usd": round(est_usd, 4), "actor": actor, "ok": ok}
    append_jsonl(fetch_log_path(), row)
    return row


# ---------------------------------------------------------------- Apify items

def is_reel(item: dict) -> bool:
    return item.get("productType") == "clips"


def is_pinned(item: dict) -> bool:
    return bool(item.get("isPinned"))


def is_paid(item: dict) -> bool:
    return bool(item.get("paidPartnership"))


def repeated_comment_count(comments) -> int:
    """How many top comments are the same single word (case and punctuation ignored).
    Several identical one-word comments suggest a keyword gate shown on screen."""
    words = [re.sub(r"[^\w]", "", str(c)).lower() for c in comments or [] if len(str(c).split()) == 1]
    words = [w for w in words if w]
    return Counter(words).most_common(1)[0][1] if words else 0


def trim_item(item: dict) -> dict:
    """The public fields the store keeps from one Apify post: no media URLs and no
    commenters' text (only how often one keyword repeats among the top comments)."""
    out = {k: item.get(k) for k in ITEM_KEEP if k in item}
    comments = [c.get("text") for c in (item.get("latestComments") or []) if isinstance(c, dict)]
    out["topCommentRepeat"] = repeated_comment_count(comments)
    return out


def med(xs):
    """Median of the values that are present (port of VAULT scrapers/ig.py med)."""
    xs = [x for x in xs if isinstance(x, (int, float)) and not isinstance(x, bool)]
    if not xs:
        return None
    m = statistics.median(xs)
    return int(m) if float(m).is_integer() else round(m, 1)


def exclusion(item: dict, pulled_at: dt.datetime | None, targets) -> str | None:
    """Why a post is left out of the baseline, or None when it counts."""
    if not is_reel(item):
        return "not_reel"
    if item.get("shortCode") in targets:
        return "target"
    if is_pinned(item):
        return "pinned"
    if is_paid(item):
        return "paid"
    posted = parse_time(item.get("timestamp"))
    if pulled_at and posted and pulled_at - posted < dt.timedelta(hours=FRESH_H):
        return "fresh"
    return None


def compute_baseline(items, *, pulled_at: str | None, pulled_at_note: str, source: str, targets=()) -> dict:
    """Creator baseline from one public post pull: reels only, own median per count."""
    targets = set(targets)
    pulled = parse_time(pulled_at)
    excluded = {k: [] for k in EXCLUDED_KEYS}
    kept = []
    for it in items:
        if not isinstance(it, dict) or it.get("error") or not it.get("shortCode"):
            continue
        reason = exclusion(it, pulled, targets)
        if reason:
            excluded[reason].append(it["shortCode"])
        else:
            kept.append(it)
    posted = sorted(str(it["timestamp"])[:10] for it in kept if it.get("timestamp"))
    return {
        "n": len(kept),
        "kind": "reels only",
        "window": {"from": posted[0], "to": posted[-1]} if posted else None,
        "median": {k: med([it.get(SOURCE_FIELD[k]) for it in kept]) for k in COUNT_KEYS},
        "excluded": excluded,
        "source": source,
        "pulled_at": pulled_at,
        "pulled_at_note": pulled_at_note,
        "thin": len(kept) < THIN_N,
    }


def baseline_items(creator: dict) -> list[dict]:
    """The trimmed posts that are in a creator's baseline (empty when no item list is kept)."""
    items = load_json(creator_items_path(creator["handle"]), []) or []
    gone = {sc for scs in (creator["baseline"].get("excluded") or {}).values() for sc in scs}
    return [it for it in items if is_reel(it) and it.get("shortCode") not in gone]


def baseline_reels(handle: str) -> list[dict]:
    """Reels in a creator's baseline with x and outlier, for the patterns contrast
    (outliers vs the same creator's normal reels). Captions are private data.

    Each reel's x is against the median of the creator's OTHER baseline reels (this
    reel left out), the same rule as a swipe reel's x against a baseline without it."""
    creator = load_creator(handle)
    if not creator:
        return []
    items = baseline_items(creator)
    plays_all = [it.get("videoPlayCount") for it in items]
    out = []
    for i, it in enumerate(items):
        sc = it["shortCode"]
        plays = it.get("videoPlayCount")
        others = med([p for j, p in enumerate(plays_all) if j != i])
        x = plays / others if isinstance(plays, (int, float)) and others else None
        reel = load_json(reel_path(sc)) if SHORTCODE_RE.match(sc) else None
        discounted = bool(reel and reel.get("discount"))
        out.append({"shortcode": sc, "url": it.get("url"), "posted": it.get("timestamp"), "plays": plays,
                    "likes": it.get("likesCount"), "comments": it.get("commentsCount"),
                    "duration_s": it.get("videoDuration"), "caption": it.get("caption") or "",
                    "x_plays": round(x, 2) if x is not None else None, "x_exact": x,
                    "outlier": x is not None and x >= OUTLIER_X and not discounted})
    return out


# ---------------------------------------------------------------- derived reel fields

def _x_vs(sc: str, creator: dict | None) -> str:
    if not creator:
        return "no baseline yet"
    b = creator["baseline"]
    if b.get("kind") != "reels only":
        return f"{b.get('source', 'other source')}: median of {b['n']} posts, all post types"
    left_out = any(sc in scs for scs in (b.get("excluded") or {}).values())
    tail = "this reel left out" if left_out else "this reel included"
    return f"own median of {b['n']} reels, reels only, {tail}"


def derive(reel: dict, creator: dict | None) -> dict:
    """Recompute x, outlier and flags from counts, the creator baseline, facts and discount."""
    b = (creator or {}).get("baseline") or {}
    median = b.get("median") or {}
    counts = reel.get("counts") or {}
    x, exact = {}, {}
    for k in COUNT_KEYS:
        c, m = counts.get(k), median.get(k)
        exact[k] = c / m if isinstance(c, (int, float)) and m else None
        x[k] = round(exact[k], 2) if exact[k] is not None else None
    x["vs"] = _x_vs(reel["shortcode"], creator)
    reel["x"] = x
    reel["outlier"] = bool(exact["plays"] is not None and exact["plays"] >= OUTLIER_X and not reel.get("discount"))
    facts = reel.get("facts") or {}
    cta = facts.get("cta") or {}
    posted, as_of = parse_time(reel.get("posted")), parse_time(counts.get("as_of"))
    flags = reel.setdefault("flags", {})
    flags.update({
        "thin_baseline": bool(b.get("thin", True)),
        "paid": bool(flags.get("paid")),
        "gated_cta": cta.get("type") in GATED_CTAS,
        "fresh": bool(posted and as_of and as_of - posted < dt.timedelta(hours=FRESH_H)),
        "over_60s": bool(facts.get("duration_s") and facts["duration_s"] > OVER_S),
        "under_2x": bool(exact["plays"] is not None and exact["plays"] < OUTLIER_X),
    })
    return reel


def empty_shape() -> dict:
    return {"hook_shape": None, "format": None, "cta": None, "beats": []}


def rules():
    """The shared rule checks in dashboard/render.py (banned words, cause words, pronouns)."""
    dash = str(PROJECT_ROOT / "dashboard")
    if dash not in sys.path:
        sys.path.insert(0, dash)
    import render
    return render
