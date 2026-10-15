"""Swipe file CLI: competitor reels as counts, facts and shape.

Usage (from the Tribe folder):
    python -m strategist.reel import-vault [--no-transcribe] [--model small.en]
    python -m strategist.reel add <reel-url> [--yes] [--no-media]
    python -m strategist.reel add @handle [--limit 30] [--yes] [--no-media]
    python -m strategist.reel tag <sc> --from <json> [--force]
    python -m strategist.reel accept <sc> <field|all>
    python -m strategist.reel reject <sc> <field>
    python -m strategist.reel discount <sc> --reason "..."   (or --clear)
    python -m strategist.reel link-tribe <sc> <job_id> [--force]
    python -m strategist.reel list

Money: add calls Apify (apify~instagram-scraper, public posts only, no login). It
prints the estimate and does nothing without --yes. Every pull is logged to
swipe/fetch-log.jsonl. Apify spend is outside the Modal cap. import-vault spends
nothing: it reads VAULT's earlier pulls and never writes to VAULT.

Other creators' content is links, numbers and shapes only. Transcripts, the
caption's first line and at most 4 stills live only in swipe/reels/<sc>/private/.
A reel video is downloaded only into a temp folder outside Tribe, to transcribe
and grab stills, and is deleted straight after. No video is ever written under swipe/.

Fields for accept/reject: hook_shape, format, cta, beats, beats.<n> (and "all" for accept).
Exit codes: 0 ok, 2 refused (bad input, a rule check, or a paid step without --yes).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from . import store, transcribe
from .store import StoreError
from .transcribe import TranscribeError

APIFY_ACTOR = "apify~instagram-scraper"   # public posts only; no Instagram login on our side
APIFY_URL = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items?timeout=240"
USD_PER_LINK = 0.003      # one reel link (plan, Build step 8)
USD_PER_POST = 0.0027     # VAULT scrapers/ig.py: about $0.0027 per item, so about $0.08 for 30 posts
MAX_VIDEO_BYTES = 300 << 20
ENV_FILE = store.PROJECT_ROOT / ".env"     # APIFY_TOKEN lives here; read, never printed
MAX_STILLS = 4
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".wav", ".m4a", ".mp3", ".part"}
FRAME_RE = re.compile(r"^frame-\d+-(\d+(?:\.\d+)?)s\.jpg$")
SRT_TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
JOB_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{8}$")
FIELD_RE = re.compile(r"^(hook_shape|format|cta|beats)(?:\.(\d+))?$")
# The TRIBE run of this reel (the M1 cost test). Linked on import when the folder exists.
AUTO_LINK = {}

# CTA heuristics on the reel's own words, most specific first. The comment and DM
# keyword gates inflate comment counts (VAULT OUTLIERS.md rule 4), so they set flags.gated_cta.
_Q = "[\"'\u201c\u201d\u2018\u2019]"   # straight and curly quotes
_APOS = "(?:'|\u2019)?"
CTA_PATTERNS = (
    ("comment-keyword", re.compile(
        rf"\bcomment\s+(?:the\s+word\s+)?{_Q}?[\w-]+{_Q}?[,.!]?\s+(?:and|&)\s+"
        rf"(?:i{_APOS}ll|i\s+will|we{_APOS}ll|you{_APOS}ll|get)\b"
        rf"|\bcomment\s+{_Q}[^\"\u201d]{{1,30}}{_Q}", re.IGNORECASE)),
    ("dm-keyword", re.compile(rf"\b(?:dm|message)\s+me\s+(?:the\s+word\s+)?{_Q}?\w+|\bsend\s+me\s+a\s+dm\b",
                              re.IGNORECASE)),
    ("link-in-bio", re.compile(r"\blink\s+(?:is\s+)?in\s+(?:my\s+|the\s+|our\s+)?bio\b", re.IGNORECASE)),
    ("link", re.compile(r"\b[a-z0-9-]+\.(?:com|ai|io|co|org|net|app)/[\w/-]*", re.IGNORECASE)),
    ("follow", re.compile(r"\bfollow\s+(?:me\s+|us\s+)?(?:for|to)\b", re.IGNORECASE)),
    ("save", re.compile(r"\bsave\s+(?:this|it)\b", re.IGNORECASE)),
    ("comment", re.compile(r"\bcomment\s+(?:below|down\s+below)\b", re.IGNORECASE)),
    ("share", re.compile(r"\bshare\s+(?:this|it)\s+with\b", re.IGNORECASE)),
)
REPEATED_COMMENT_MIN = 3   # this many identical one-word top comments suggests an on-screen keyword gate


class ReelError(Exception):
    """A reel command was refused. The message says why."""


# ---------------------------------------------------------------- small helpers

def fmt_clock(t: float) -> str:
    s = max(0, int(math.floor(float(t) + 1e-9)))
    return f"{s // 60}:{s % 60:02d}"


def fmt_num(v) -> str:
    if v is None:
        return "?"
    return f"{v:,.1f}" if isinstance(v, float) and not float(v).is_integer() else f"{int(v):,}"


def first_line(text: str | None) -> str:
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")


def reel_url(sc: str) -> str:
    return f"https://www.instagram.com/reel/{sc}/"


def instagram_code(url: str) -> str:
    """Shortcode of a public post link (ported from backend/tribe_app.py _instagram_code)."""
    m = re.match(r"^https?://(?:www\.|m\.)?instagram\.com/(?:(?!share/)[^/?#]+/)?(?:p|tv|reels?)/(?!audio/)"
                 r"([A-Za-z0-9_-]+)", url or "")
    return m.group(1) if m else ""


def assert_no_video(*roots: Path) -> None:
    """No video or audio file may exist under the swipe or drafts folders."""
    roots = roots or (store.SWIPE, store.DRAFTS)
    found = [str(p) for r in roots if Path(r).is_dir() for p in Path(r).rglob("*")
             if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    if found:
        raise ReelError("video/audio files found where none may exist: " + ", ".join(found[:5]))


def check_text(texts: list[tuple[str, str]], counts_allowed: bool = False) -> None:
    """Shared rule checks from dashboard/render.py on text we (or Claude) wrote."""
    try:
        render = store.rules()
    except Exception as e:  # a broken render.py must not let unchecked text through
        raise ReelError(f"dashboard/render.py could not be loaded for the rule checks ({type(e).__name__}: {e})")
    hits = [f"{where}: {render.find_banned(text)}" for where, text in texts if render.find_banned(text)]
    if hits:
        raise ReelError("banned words: " + "; ".join(hits))
    if not counts_allowed and hasattr(render, "COUNT_TERMS_RE"):
        counts = [f"{where}: {text!r}" for where, text in texts if render.COUNT_TERMS_RE.search(text)]
        if counts:
            raise ReelError("shape labels carry no counts (plays, likes, comments, x, outlier): " + "; ".join(counts))
    try:
        for name in ("check_cause", "check_pronouns"):
            if hasattr(render, name):
                getattr(render, name)(texts)
    except render.RenderError as e:
        raise ReelError(str(e))


# ---------------------------------------------------------------- Apify (paid, gated)

def env_value(name: str) -> str:
    """One value from the environment or the Tribe .env file. Never printed or logged."""
    if os.environ.get(name, "").strip():
        return os.environ[name].strip()
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                return value.strip().strip('"').strip("'")
    return ""


def gate(what: str, est_usd: float, yes: bool) -> bool:
    """Print the cost estimate; go ahead only with --yes."""
    print(f"Paid step: {what}.")
    print(f"Estimate: about ${est_usd:.3f} of Apify credit ({APIFY_ACTOR}), outside the Modal cap. "
          "Logged to swipe/fetch-log.jsonl.")
    if not yes:
        print("Not run. Add --yes to go ahead.")
        return False
    return True


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text


def apify_items(body: dict, token: str) -> list[dict]:
    """POST one run-sync request (request shape from backend/tribe_app.py _download_via_apify)."""
    req = urllib.request.Request(APIFY_URL, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            items = json.load(r)
    except urllib.error.HTTPError as e:  # the status only, never the request headers
        raise ReelError(f"Apify refused the request (HTTP {e.code})") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        msg = f"Apify could not be reached or answered badly ({type(e).__name__}: {e})"
        raise ReelError(_scrub(msg, token)) from None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def fetch(body: dict, what: str, est_usd: float) -> list[dict]:
    token = env_value("APIFY_TOKEN")
    if not token:
        raise ReelError("APIFY_TOKEN is not set in Tribe/.env")
    try:
        items = apify_items(body, token)
    except ReelError:
        store.log_fetch(what, 0, est_usd, APIFY_ACTOR, False)
        raise
    store.log_fetch(what, len(items), est_usd, APIFY_ACTOR, bool(items))
    return items


def download_video(url: str, dest: Path) -> Path:
    """Download a public reel video into a temp folder (ported from backend/tribe_app.py)."""
    part = dest.with_suffix(".part")
    size = 0
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as f:
            expected = int(r.headers.get("Content-Length") or 0)
            while chunk := r.read(1 << 20):
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise ReelError("that reel video is over 300 MB")
                f.write(chunk)
    except (urllib.error.URLError, OSError) as e:
        raise ReelError(f"the reel video could not be downloaded ({type(e).__name__})") from None
    if expected and size != expected:
        raise ReelError(f"the reel download was cut off ({size} of {expected} bytes); try again")
    part.replace(dest)
    return dest


def probe_duration(video: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 3)
    except ValueError:
        return None


def grab_still(video: Path, t: float, out: Path) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-nostdin", "-ss", f"{max(0.0, t):.2f}", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=720:-2", "-q:v", "4", str(out)], capture_output=True)
    return r.returncode == 0 and out.is_file()


# ---------------------------------------------------------------- facts

def _joined(words: list[dict]) -> tuple[str, list[int]]:
    parts, starts, pos = [], [], 0
    for w in words:
        starts.append(pos)
        parts.append(w["text"])
        pos += len(w["text"]) + 1
    return " ".join(parts), starts


def read_srt(path: Path) -> list[dict]:
    """Subtitle segments [{start, end, text}] from an .srt file (VAULT's AssemblyAI output)."""
    if not Path(path).is_file():
        return []
    segs = []
    for block in re.split(r"\n\s*\n", Path(path).read_text(encoding="utf-8-sig").strip()):
        m = SRT_TIME_RE.search(block)
        if m:
            h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(g) for g in m.groups())
            text = " ".join(block[m.end():].split())
            segs.append({"start": h1 * 3600 + m1 * 60 + s1 + ms1 / 1000,
                         "end": h2 * 3600 + m2 * 60 + s2 + ms2 / 1000, "text": text})
    return segs


def find_cta(words, transcript, caption, comments, segments=None) -> tuple[dict | None, str]:
    """CTA type and time from the reel's own words; the second value says where it was found.

    Time comes from the timed words; failing that, from a subtitle segment, placed by
    the match's position in the segment's text (an estimate, and said so)."""
    joined, starts = _joined(words or [])
    for kind, rx in CTA_PATTERNS:
        where, t = [], None
        spoken = list(rx.finditer(joined)) if words else []
        in_seg = [(seg, m) for seg in segments or [] for m in rx.finditer(seg["text"])]
        if spoken:
            i = max(j for j, s in enumerate(starts) if s <= spoken[-1].start())
            t = words[i]["start"]
            where.append(f"spoken at {fmt_clock(t)} (timed transcript)")
        elif in_seg:
            seg, m = in_seg[-1]
            t = seg["start"] + (seg["end"] - seg["start"]) * m.start() / max(len(seg["text"]), 1)
            where.append(f"spoken at about {fmt_clock(t)} (estimated inside a subtitle segment; "
                         "not in the timed words)")
        elif transcript and rx.search(transcript):
            where.append("transcript (untimed)")
        if caption and rx.search(caption):
            where.append("caption")
        if where:
            return {"type": kind, "t": round(t, 2) if t is not None else None}, "heuristic: " + ", ".join(where)
    n = store.repeated_comment_count(comments)
    if n >= REPEATED_COMMENT_MIN:
        return ({"type": "comment-keyword", "t": None},
                f"inferred: {n} of the top comments are one repeated word (a keyword gate shown on screen is "
                "likely); not found in the caption or transcript")
    return None, "none found in the caption or transcript"


def build_facts(words, duration_s, duration_src, words_src, caption, transcript, comments, segments=None) -> dict:
    cta, cta_src = find_cta(words, transcript, caption, comments, segments)
    words = [w for w in words or [] if re.search(r"\w", str(w.get("text") or ""))]   # a lone "." is no word
    span = words[-1]["stop"] - words[0]["start"] if len(words) > 1 else 0
    return {
        "duration_s": round(float(duration_s), 2) if duration_s else None,
        "first_word_s": round(words[0]["start"], 2) if words else None,
        "words_per_s": round(len(words) / span, 2) if span > 0 else None,
        "text_on_screen_0s": None,
        "cta": cta,
        "source": {
            "duration_s": duration_src if duration_s else None,
            "words": words_src if words else None,
            "words_per_s": "words / (last word end - first word start)" if span > 0 else None,
            "cta": cta_src,
            "text_on_screen_0s": "not checked",
        },
    }


def refresh_word_facts(reel: dict, words: list[dict], words_src: str) -> None:
    """Re-derive first word, pace and CTA time after the timed transcript changed."""
    old = reel.get("facts") or {}
    priv = store.private_dir(reel["shortcode"])
    caption = (priv / "caption.txt").read_text(encoding="utf-8") if (priv / "caption.txt").is_file() else ""
    tpath = priv / "transcript.txt"
    transcript_text = tpath.read_text(encoding="utf-8") if tpath.is_file() else ""
    new = build_facts(words, old.get("duration_s"), (old.get("source") or {}).get("duration_s"), words_src,
                      caption, transcript_text, [])
    # The first import saw the full caption and the top comments; keep its CTA unless the words now time it.
    if old.get("cta") and not (new["cta"] and new["cta"]["t"] is not None):
        new["cta"], new["source"]["cta"] = old["cta"], (old.get("source") or {}).get("cta")
    new["text_on_screen_0s"] = old.get("text_on_screen_0s")
    reel["facts"] = new


# ---------------------------------------------------------------- stills

def still_targets(duration, cta_t, peak_t) -> list[tuple[str, float]]:
    """0.5 s, 2 s, then the CTA and the TRIBE top peak (or the middle) as the up-to-2 extra."""
    wanted = [("open", 0.5), ("early", 2.0)]
    if cta_t is not None:
        wanted.append(("cta", cta_t))
    if peak_t is not None:
        wanted.append(("peak", peak_t))
    elif duration:
        wanted.append(("mid", duration / 2))
    return wanted


def _clear_stills(out_dir: Path) -> None:
    if out_dir.is_dir():
        for p in out_dir.glob("*.jpg"):
            p.unlink()


def copy_vault_stills(media_dir: Path, out_dir: Path, duration, cta_t, peak_t) -> list[str]:
    """Copy at most 4 of VAULT's keyframes (jpg only, never the video), nearest each target time."""
    frames = []
    for f in sorted(media_dir.glob("frame-*.jpg")) if media_dir.is_dir() else []:
        m = FRAME_RE.match(f.name)
        if m:
            frames.append((float(m.group(1)), f))
    _clear_stills(out_dir)
    chosen, used = [], set()
    for role, t in still_targets(duration, cta_t, peak_t):
        free = [fr for fr in frames if fr[1] not in used]
        if not free or len(chosen) >= MAX_STILLS:
            break
        tf, f = min(free, key=lambda fr: abs(fr[0] - t))
        used.add(f)
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"{len(chosen) + 1}-{role}-{tf:.1f}s.jpg"
        shutil.copyfile(f, out_dir / name)
        chosen.append(name)
    return chosen


def grab_stills(video: Path, out_dir: Path, duration, cta_t, peak_t=None) -> list[str]:
    _clear_stills(out_dir)
    chosen = []
    for role, t in still_targets(duration, cta_t, peak_t)[:MAX_STILLS]:
        if duration:
            t = min(t, max(duration - 0.2, 0))
        name = f"{len(chosen) + 1}-{role}-{t:.1f}s.jpg"
        if grab_still(video, t, out_dir / name):
            chosen.append(name)
    return chosen


# ---------------------------------------------------------------- reel records

def make_counts(plays, likes, comments, as_of, note) -> dict:
    return {"plays": plays, "likes": likes, "comments": comments, "as_of": as_of, "as_of_note": note,
            "source_field": dict(store.SOURCE_FIELD)}


def new_reel(sc, owner, posted, counts, paid, facts, imported_from, old=None) -> dict:
    """A reel record in contract key order. Keeps the user's tags, discount, TRIBE link and added_at."""
    old = old or {}
    return {
        "shortcode": sc, "url": reel_url(sc), "owner": owner, "posted": posted, "type": "reel",
        "counts": counts, "x": {}, "outlier": False, "flags": {"paid": bool(paid)},
        "discount": old.get("discount"), "facts": facts, "shape": old.get("shape") or store.empty_shape(),
        "tribe": old.get("tribe"), "imported_from": imported_from, "added_at": old.get("added_at") or store.now_iso(),
    }


def tribe_link(sc: str, job: str, force: bool = False) -> dict:
    """Check a scored TRIBE job belongs to this reel and return the link record."""
    if not JOB_RE.match(job or ""):
        raise ReelError(f"not a TRIBE job id: {job!r}")
    d = store.OUTPUTS / job
    report = store.load_json(d / "report.json")
    if report is None:
        raise ReelError(f"no scored report for job {job} (run: python scoring/score.py outputs/{job})")
    if report.get("mock") is not False:
        raise ReelError(f"job {job} is mock output, never linked")
    if not (d / "events.json").is_file():
        raise ReelError(f"job {job} has no events.json (no timed words)")
    url = (store.load_json(d / "source.json", {}) or {}).get("source_url") or ""
    if not force and instagram_code(url) != sc:
        raise ReelError(f"job {job} is not this reel (its source is {url or 'a local file'}); add --force if it is")
    return {"job_id": job, "run_date": f"{job[:4]}-{job[4:6]}-{job[6:8]}", "scale": "within-reel"}


def top_peak_t(job: str) -> float | None:
    report = store.load_json(store.OUTPUTS / job / "report.json", {}) or {}
    peaks = [p for p in report.get("peaks") or [] if isinstance(p.get("t"), (int, float))]
    return max(peaks, key=lambda p: p.get("value") or 0)["t"] + 0.5 if peaks else None


def refresh_owner(handle: str) -> None:
    """Re-derive x, outlier and flags for every swipe reel of one creator."""
    creator = store.load_creator(handle)
    for reel in store.list_reels(include_archived=True):   # counts stay fresh while archived too
        if reel.get("owner") == handle:
            store.save_reel(store.derive(reel, creator))


def rebuild_creator(creator: dict, add_targets=()) -> dict:
    """Recompute a baseline after its target list grew (from the kept item list when there is one)."""
    b = creator["baseline"]
    targets = set((b.get("excluded") or {}).get("target", [])) | set(add_targets)
    items = store.load_json(store.creator_items_path(creator["handle"]))
    if items is None:  # numbers carried from elsewhere (VAULT record): only the list grows
        b.setdefault("excluded", {k: [] for k in store.EXCLUDED_KEYS})["target"] = sorted(targets)
        return creator
    creator["baseline"] = store.compute_baseline(items, pulled_at=b.get("pulled_at"), source=b.get("source"),
                                                 pulled_at_note=b.get("pulled_at_note", ""), targets=targets)
    return creator


# ---------------------------------------------------------------- import-vault (free, read-only)

def vault_record_creator(rec_path: Path, rec: dict) -> dict:
    """A creator with no raw post cache in VAULT (demo_creator_c): VAULT's numbers, marked not re-checked."""
    return {
        "handle": store.check_handle(rec["owner"]), "platform": "instagram",
        "baseline": {
            "n": rec.get("baseline_posts"),
            "kind": "all post types (VAULT record), not reels only",
            "window": None,
            "median": {"plays": rec.get("median_views"), "likes": rec.get("median_likes"),
                       "comments": rec.get("median_comments")},
            "excluded": {**{k: [] for k in store.EXCLUDED_KEYS}, "target": [rec["shortcode"]]},
            "source": "VAULT repurpose record, not re-checked",
            "pulled_at": store.file_time_iso(rec_path),
            "pulled_at_note": "pull date unknown (file date)",
            "thin": True,
        },
    }


def import_vault_reel(rec_path: Path, rec: dict, media_dir: Path, creator: dict, model: str | None) -> dict:
    sc = store.check_shortcode(rec["shortcode"])
    old = store.load_json(store.reel_path(sc)) or {}
    priv = store.private_dir(sc)
    store.save_text(priv / "caption.txt", first_line(rec.get("caption")) + "\n")
    if rec.get("transcript"):
        store.save_text(priv / "transcript.txt", rec["transcript"].strip() + "\n")

    job = (old.get("tribe") or {}).get("job_id") or AUTO_LINK.get(sc)
    link = None
    if job and (store.OUTPUTS / job).is_dir():
        try:
            link = tribe_link(sc, job)
        except ReelError as e:
            print(f"{sc}: TRIBE job {job} not linked ({e})")
    words, words_src = [], None
    old_src = ((old.get("facts") or {}).get("source") or {}).get("words")
    video = media_dir / "video.mp4"
    if link:
        words = transcribe.words_from_events(store.OUTPUTS / link["job_id"] / "events.json")
        words_src = f"TRIBE job {link['job_id']} events.json (WhisperX)"
    elif old_src and (priv / "words.json").is_file():
        words, words_src = store.load_words(sc), old_src
    elif model and video.is_file():
        print(f"{sc}: timed transcript with faster-whisper {model} on the CPU (reads VAULT's copy, writes nothing there)")
        try:
            words = transcribe.transcribe_media(video, model)
            words_src = f"faster-whisper {model} (local CPU) on VAULT's media copy"
        except TranscribeError as e:
            print(f"{sc}: no timed transcript ({e})")
    if words:
        store.save_json(priv / "words.json", words)

    facts = build_facts(words, rec.get("duration_s"), f"VAULT research/repurpose/data/{sc}.json duration_s (ffprobe)",
                        words_src, rec.get("caption"), rec.get("transcript"), rec.get("top_comments"),
                        read_srt(media_dir / "video.transcript.srt"))
    copy_vault_stills(media_dir, priv / "stills", facts["duration_s"], (facts["cta"] or {}).get("t"),
                    top_peak_t(link["job_id"]) if link else None)
    counts = make_counts(rec.get("views"), rec.get("likes"), rec.get("comments"), store.file_time_iso(rec_path),
                         "pull date unknown (file date); counts from VAULT's repurpose record")
    reel = new_reel(sc, rec["owner"], rec.get("date"), counts, rec.get("paid_partnership"), facts,
                    f"VAULT research/repurpose/data/{sc}.json", old)
    if link:
        reel["tribe"] = link
    store.save_reel(store.derive(reel, creator))
    return reel


def cmd_import_vault(args) -> int:
    vault = store.VAULT
    raw_dir, data_dir = vault / "research" / "raw", vault / "research" / "repurpose" / "data"
    media_root = vault / "research" / "repurpose" / "media"
    if not data_dir.is_dir():
        raise ReelError(f"VAULT repurpose data not found: {data_dir}")
    records, skipped = [], []
    for p in sorted(data_dir.glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        if rec.get("product_type") != "clips":
            skipped.append(f"{rec.get('shortcode', p.stem)} ({rec.get('type')}/{rec.get('product_type')}, not a reel)")
            continue
        records.append((p, rec))

    creators, vault_medians = {}, {}
    for p, rec in records:
        vault_medians.setdefault(rec["owner"], (rec.get("median_views"), rec.get("baseline_posts")))
    for raw in sorted(raw_dir.glob("ig-*.json")) if raw_dir.is_dir() else []:
        handle = store.check_handle(raw.stem[3:])
        old = store.load_creator(handle)
        if old and not str(old["baseline"].get("source", "")).startswith("VAULT"):
            print(f"@{handle}: kept the newer Apify baseline ({old['baseline']['source']})")
            creators[handle] = old
            continue
        targets = set(((old or {}).get("baseline", {}).get("excluded") or {}).get("target", []))
        targets |= {rec["shortcode"] for _, rec in records if rec.get("owner") == handle}
        items = [store.trim_item(i) for i in json.loads(raw.read_text(encoding="utf-8"))
                 if isinstance(i, dict) and not i.get("error")]
        store.save_json(store.creator_items_path(handle), items)
        creator = {"handle": handle, "platform": "instagram", "baseline": store.compute_baseline(
            items, pulled_at=store.file_time_iso(raw), pulled_at_note="pull date unknown (file date)",
            source=f"VAULT research/raw/{raw.name} ({APIFY_ACTOR})", targets=targets)}
        store.save_creator(creator)
        creators[handle] = creator

    for p, rec in records:
        owner = store.check_handle(rec["owner"])
        if owner not in creators:
            old = store.load_creator(owner)
            keep = old and not str(old["baseline"].get("source", "")).startswith("VAULT")
            creators[owner] = old if keep else vault_record_creator(p, rec)
            if not keep:
                store.save_creator(creators[owner])
        import_vault_reel(p, rec, media_root / rec["shortcode"], creators[owner],
                        None if args.no_transcribe else args.model)

    store.log_fetch(f"import-vault: {len(creators)} creators, {len(records)} reels from VAULT's earlier pulls "
                    "(no new fetch)",
                    len(records), 0.0, "none (read VAULT files)", True)
    assert_no_video()
    print("\nCreators (baselines, reels only unless marked)")
    for handle, c in sorted(creators.items()):
        b = c["baseline"]
        line = (f"  @{handle}: n={b['n']} ({b['kind']}{', thin' if b['thin'] else ''}), "
                f"median plays {fmt_num(b['median']['plays'])}")
        vault_m, vault_n = vault_medians.get(handle, (None, None))
        if vault_m and b["median"]["plays"] and b["kind"] == "reels only":
            d = b["median"]["plays"] - vault_m
            line += (f"; VAULT used {fmt_num(vault_m)} (labelled '{vault_n} posts': every post type, pinned and paid "
                     f"videos in): {d:+,.1f} ({d / vault_m:+.1%})")
        print(line)
    print("Reels")
    for _, rec in records:
        r = store.load_reel(rec["shortcode"])
        x = r["x"].get("plays")
        print(f"  {r['shortcode']} @{r['owner']}: {fmt_num(r['counts']['plays'])} plays, "
              f"{x if x is not None else '?'}x own median (VAULT said {rec.get('x_views')}x), "
              f"outlier {'yes' if r['outlier'] else 'no'}")
    for s in skipped:
        print(f"  skipped {s}")
    return 0


# ---------------------------------------------------------------- add (paid, gated)

def reel_from_item(item: dict, as_of: str, imported_from: str, creator: dict | None, media: bool, model: str) -> dict:
    """A swipe reel from one Apify post; the video goes to a temp folder and is deleted."""
    sc = store.check_shortcode(item["shortCode"])
    old = store.load_json(store.reel_path(sc)) or {}
    priv = store.private_dir(sc)
    caption = item.get("caption") or ""
    comments = [c.get("text") if isinstance(c, dict) else c for c in item.get("latestComments") or []]
    store.save_text(priv / "caption.txt", first_line(caption) + "\n")
    words, words_src = [], None
    duration, dur_src = item.get("videoDuration"), "Apify videoDuration"
    facts = None
    if media and str(item.get("videoUrl", "")).startswith("https://"):
        with tempfile.TemporaryDirectory(prefix="strategist-video-") as tmp:
            video = download_video(item["videoUrl"], Path(tmp) / "reel.mp4")
            probed = probe_duration(video)
            if probed:
                duration, dur_src = probed, "ffprobe of the downloaded reel (video deleted after)"
            try:
                words = transcribe.transcribe_media(video, model)
                words_src = f"faster-whisper {model} (local CPU)"
            except TranscribeError as e:
                print(f"{sc}: no timed transcript ({e})")
            facts = build_facts(words, duration, dur_src, words_src, caption, "", comments)
            grab_stills(video, priv / "stills", facts["duration_s"], (facts["cta"] or {}).get("t"))
    if facts is None:
        facts = build_facts(words, duration, dur_src, words_src, caption, "", comments)
    if words:
        store.save_json(priv / "words.json", words)
        store.save_text(priv / "transcript.txt", " ".join(w["text"] for w in words) + "\n")
    counts = make_counts(item.get("videoPlayCount"), item.get("likesCount"), item.get("commentsCount"), as_of,
                         "Apify pull")
    reel = new_reel(sc, item.get("ownerUsername"), item.get("timestamp"), counts, store.is_paid(item), facts,
                    imported_from, old)
    store.save_reel(store.derive(reel, creator))
    return reel


def cmd_add_url(url: str, args) -> int:
    sc = instagram_code(url)
    if not sc:
        raise ReelError(f"not an Instagram reel link: {url!r}")
    store.check_shortcode(sc)
    if not gate(f"fetch 1 public reel link ({sc})", USD_PER_LINK, args.yes):
        return 2
    body = {"directUrls": [reel_url(sc)], "resultsType": "posts", "resultsLimit": 1, "addParentData": False}
    items = fetch(body, f"reel {sc}", USD_PER_LINK)
    item = next((i for i in items if i.get("shortCode") == sc and not i.get("error")), None)
    if item is None:
        raise ReelError("Apify found no public post for that link (private, deleted or wrong link)")
    if not store.is_reel(item):
        raise ReelError(f"{sc} is not a reel ({item.get('type')}/{item.get('productType')}); "
                        "the swipe file holds reels only")
    owner = store.check_handle(item.get("ownerUsername", ""))
    creator = store.load_creator(owner)
    if creator:
        creator = rebuild_creator(creator, [sc])
        store.save_creator(creator)
    reel_from_item(item, store.now_iso(), "Apify reel link", creator, not args.no_media, args.model)
    refresh_owner(owner)
    assert_no_video()
    r = store.load_reel(sc)
    print(f"added {sc} @{owner}: {fmt_num(r['counts']['plays'])} plays")
    if creator:
        print(f"  {r['x']['plays']}x own median ({r['x']['vs']}), outlier {'yes' if r['outlier'] else 'no'}")
    else:
        print(f"  no baseline for @{owner} yet, so no x. To add one: python -m strategist.reel add @{owner} "
              f"(about ${30 * USD_PER_POST:.2f}, asks first)")
    return 0


def cmd_add_handle(handle: str, args) -> int:
    handle = store.check_handle(handle)
    limit = max(1, min(int(args.limit), 100))
    est = limit * USD_PER_POST
    if not gate(f"pull the last {limit} public posts of @{handle}", est, args.yes):
        return 2
    body = {"directUrls": [f"https://www.instagram.com/{handle}/"], "resultsType": "posts",
            "resultsLimit": limit, "addParentData": False}
    items = [i for i in fetch(body, f"@{handle} last {limit} posts", est)
             if not i.get("error") and str(i.get("ownerUsername", "")).lower() == handle.lower() and i.get("shortCode")]
    if not items:
        raise ReelError(f"no public posts came back for @{handle} (private, renamed or empty)")
    pulled = store.now_iso()
    old = store.load_creator(handle)
    targets = set(((old or {}).get("baseline", {}).get("excluded") or {}).get("target", []))
    trimmed = [store.trim_item(i) for i in items]
    store.save_json(store.creator_items_path(handle), trimmed)
    creator = {"handle": handle, "platform": "instagram", "baseline": store.compute_baseline(
        trimmed, pulled_at=pulled, pulled_at_note="Apify pull", source=f"{APIFY_ACTOR}, last {limit} posts",
        targets=targets)}
    store.save_creator(creator)

    by_sc = {i["shortCode"]: i for i in items}
    for reel in store.list_reels(include_archived=True):
        it = by_sc.get(reel["shortcode"])
        if reel.get("owner") == handle and it:
            reel["counts"] = make_counts(it.get("videoPlayCount"), it.get("likesCount"), it.get("commentsCount"),
                                         pulled, "Apify pull")
            store.save_reel(store.derive(reel, creator))
    median = creator["baseline"]["median"]["plays"]
    new = []
    for it in store.baseline_items(creator):
        plays = it.get("videoPlayCount")
        if median and plays is not None and plays / median >= store.OUTLIER_X \
                and not store.reel_path(it["shortCode"]).is_file():
            reel_from_item(by_sc[it["shortCode"]], pulled, f"Apify @{handle} pull", creator,
                           not args.no_media, args.model)
            new.append(it["shortCode"])
    refresh_owner(handle)
    assert_no_video()
    b = creator["baseline"]
    print(f"@{handle}: n={b['n']} reels ({'thin, ' if b['thin'] else ''}reels only), median plays {fmt_num(median)}")
    print("  left out: " + ", ".join(f"{k} {len(v)}" for k, v in b["excluded"].items()))
    print(f"  new swipe reels at 2x or more: {', '.join(new) if new else 'none'}")
    return 0


# ---------------------------------------------------------------- shape: tag, accept, reject

def _shape_texts(data: dict) -> list[tuple[str, str]]:
    texts = []
    for f in ("hook_shape", "format", "cta"):
        v = data.get(f)
        if isinstance(v, dict):
            v = v.get("id") or v.get("value")
        if v is not None:
            texts.append((f, str(v)))
    for i, b in enumerate(data.get("beats") or []):
        texts += [(f"beats[{i}].name", str(b.get("name", ""))), (f"beats[{i}].kind", str(b.get("kind", "")))]
    return texts


def _beats(raw, duration) -> list[dict]:
    if not isinstance(raw, list):
        raise ReelError("beats must be a list of {start, end, kind, name}")
    out = []
    for i, b in enumerate(raw):
        try:
            start, end = float(b["start"]), float(b["end"])
            kind, name = str(b["kind"]).strip(), str(b["name"]).strip()
        except (KeyError, TypeError, ValueError):
            raise ReelError(f"beat {i} needs start, end, kind and name") from None
        if not (0 <= start < end) or (duration and end > duration + 1) or not kind or not name or len(name) > 80:
            raise ReelError(f"beat {i} has bad times or labels: {b}")
        out.append({"start": round(start, 2), "end": round(end, 2), "kind": kind, "name": name, "status": "suggested"})
    return out


def cmd_tag(args) -> int:
    reel = store.load_reel(store.check_shortcode(args.sc))
    data = json.loads(Path(args.from_path).read_text(encoding="utf-8"))
    data = data.get("shape", data) if isinstance(data, dict) else None
    if not isinstance(data, dict):
        raise ReelError("the tag file must be a JSON object with hook_shape, format, cta and/or beats")
    unknown = set(data) - set(store.SHAPE_FIELDS)
    if unknown:
        raise ReelError(f"unknown shape fields: {sorted(unknown)} (allowed: {', '.join(store.SHAPE_FIELDS)})")
    check_text(_shape_texts(data))
    shape = reel.get("shape") or store.empty_shape()
    changed, kept = [], []
    for f in store.SHAPE_FIELDS:
        if f not in data:
            continue
        cur = shape.get(f)
        accepted = (any(b.get("status") == "accepted" for b in cur or []) if f == "beats"
                    else bool(cur) and cur.get("status") == "accepted")
        if accepted and not args.force:
            kept.append(f)
            continue
        v = data[f]
        if f == "beats":
            shape[f] = _beats(v, (reel.get("facts") or {}).get("duration_s"))
        elif f == "hook_shape":
            shape[f] = {"id": str(v.get("id") if isinstance(v, dict) else v).strip(), "status": "suggested"}
        else:
            shape[f] = {"value": str(v.get("value") if isinstance(v, dict) else v).strip(), "status": "suggested"}
        changed.append(f)
    reel["shape"] = shape
    store.save_reel(reel)
    print(f"{args.sc}: suggested {', '.join(changed) or 'nothing'}"
          + (f"; kept accepted {', '.join(kept)} (add --force to replace)" if kept else ""))
    return 0


def set_status(reel: dict, field: str, status: str) -> list[str]:
    shape = reel.get("shape") or store.empty_shape()
    if field == "all":
        picks = [(f, None) for f in store.SHAPE_FIELDS]
    else:
        m = FIELD_RE.match(field or "")
        if not m:
            raise ReelError(f"unknown field {field!r} (hook_shape, format, cta, beats, beats.<n>, all)")
        picks = [(m.group(1), int(m.group(2)) if m.group(2) is not None else None)]
    done = []
    for f, idx in picks:
        if f == "beats":
            beats = shape.get("beats") or []
            if idx is not None and not 0 <= idx < len(beats):
                raise ReelError(f"there is no beat {idx} ({len(beats)} beats)")
            for i, b in enumerate(beats):
                if idx is None or i == idx:
                    b["status"] = status
                    done.append(f"beats.{i}")
        elif shape.get(f):
            shape[f]["status"] = status
            done.append(f)
    if not done:
        raise ReelError(f"nothing to {status[:-2] if status.endswith('ed') else status}: {field} has no suggestion yet")
    reel["shape"] = shape
    return done


def cmd_accept(args) -> int:
    reel = store.load_reel(store.check_shortcode(args.sc))
    done = set_status(reel, args.field, "accepted")
    store.save_reel(reel)
    print(f"{args.sc}: accepted {', '.join(done)}")
    return 0


def cmd_reject(args) -> int:
    if args.field == "all":
        raise ReelError("reject takes one field at a time")
    reel = store.load_reel(store.check_shortcode(args.sc))
    done = set_status(reel, args.field, "rejected")
    store.save_reel(reel)
    print(f"{args.sc}: rejected {', '.join(done)}")
    return 0


# ---------------------------------------------------------------- discount, link-tribe, list

def cmd_discount(args) -> int:
    reel = store.load_reel(store.check_shortcode(args.sc))
    if args.clear:
        reel["discount"] = None
    else:
        reason = (args.reason or "").strip()
        if not reason:
            raise ReelError('discount needs --reason "..." (or --clear)')
        check_text([("reason", reason)], counts_allowed=True)
        reel["discount"] = {"reason": reason, "by": "user", "at": store.now_iso()}
    store.save_reel(store.derive(reel, store.load_creator(reel["owner"])))
    state = "discount cleared" if args.clear else "discounted"
    print(f"{args.sc}: {state}; outlier {'yes' if reel['outlier'] else 'no'}")
    return 0


def cmd_link_tribe(args) -> int:
    sc = store.check_shortcode(args.sc)
    reel = store.load_reel(sc)
    link = tribe_link(sc, args.job_id, args.force)
    words = transcribe.words_from_events(store.OUTPUTS / link["job_id"] / "events.json")
    store.save_json(store.private_dir(sc) / "words.json", words)
    refresh_word_facts(reel, words, f"TRIBE job {link['job_id']} events.json (WhisperX)")
    reel["tribe"] = link
    store.save_reel(store.derive(reel, store.load_creator(reel["owner"])))
    print(f"{sc}: linked TRIBE job {link['job_id']} ({link['run_date']}), {len(words)} timed words")
    return 0


def _csv_handles(values) -> set[str]:
    """Handles from repeated or comma-separated --owners style values, checked."""
    out = set()
    for v in values or []:
        for h in str(v).split(","):
            if h.strip():
                out.add(store.check_handle(h.strip()))
    return out


def set_archived(sc: str, archived: bool) -> bool:
    """Set reel.json "archived" for one reel. True when it changed. Files and videos stay."""
    with store.locked():
        reel = store.load_reel(sc)
        if bool(reel.get("archived")) == archived:
            return False
        reel["archived"] = archived
        store.save_reel(reel)
        return True


def cmd_archive(args) -> int:
    """archive <sc>... | --owners a,b,c | --all-except-owner a,b,c: hide reels from the board,
    patterns, reel pages and the hosted sync. Nothing is deleted; unarchive restores them."""
    owners = _csv_handles(args.owners)
    keep = _csv_handles(args.all_except_owner)
    picked = [store.check_shortcode(sc) for sc in args.sc]
    if bool(picked) + bool(owners) + bool(keep) != 1:
        raise ReelError("name reel shortcodes, or --owners a,b,c, or --all-except-owner a,b,c (one of them)")
    if picked:
        targets = picked
    else:
        everything = store.list_reels(include_archived=True)
        targets = [r["shortcode"] for r in everything
                   if (r.get("owner") in owners if owners else r.get("owner") not in keep)]
    changed = [sc for sc in targets if set_archived(sc, True)]
    for sc in changed:
        print(f"archived {sc}")
    print(f"{len(changed)} archived, {len(targets) - len(changed)} already were. Videos and files kept; "
          "run sync push to take their pages off the dashboard.")
    return 0


def cmd_unarchive(args) -> int:
    targets = [store.check_shortcode(sc) for sc in args.sc]
    changed = [sc for sc in targets if set_archived(sc, False)]
    for sc in changed:
        print(f"unarchived {sc}")
    print(f"{len(changed)} unarchived, {len(targets) - len(changed)} were not archived.")
    return 0


def cmd_list(args) -> int:
    reels = store.list_reels()
    hidden = len(store.list_reels(include_archived=True)) - len(reels)
    handles = sorted({r.get("owner") for r in reels if r.get("owner")}
                     | {p.stem for p in (store.SWIPE / "creators").glob("*.json")})
    print("Creators")
    for h in handles:
        c = store.load_creator(h)
        if not c:
            print(f"  @{h}: no baseline yet")
            continue
        b = c["baseline"]
        print(f"  @{h}: n={b['n']} ({b['kind']}{', thin' if b['thin'] else ''}), median plays "
              f"{fmt_num(b['median']['plays'])}, pulled {str(b.get('pulled_at') or '?')[:10]} "
              f"({b.get('pulled_at_note')})")
    print("Reels (sorted by x vs own median, plays)" + (f"; {hidden} archived, not shown" if hidden else ""))
    for r in sorted(reels, key=lambda r: -((r.get("x") or {}).get("plays") or -1)):
        flags = [k for k, v in (r.get("flags") or {}).items() if v]
        state = "discounted" if r.get("discount") else ("outlier" if r.get("outlier") else "not an outlier")
        print(f"  {r['shortcode']}  @{r['owner']}  {str(r.get('posted') or '?')[:10]}  "
              f"{fmt_num(r['counts'].get('plays'))} plays  {(r.get('x') or {}).get('plays')}x  {state}"
              f"  flags: {', '.join(flags) or 'none'}")
    linked = [r for r in reels if r.get("tribe")]
    print("TRIBE deep reads linked (each read on its own scale, never compared across reels)")
    for r in linked:
        print(f"  {r['shortcode']}  job {r['tribe']['job_id']} ({r['tribe']['run_date']})")
    if not linked:
        print("  none")
    return 0


# ---------------------------------------------------------------- entry

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m strategist.reel", description="Competitor reel swipe file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import-vault", help="import VAULT's reels and creator pulls (free, read-only)")
    p.add_argument("--no-transcribe", action="store_true", help="skip local timed transcripts")
    p.add_argument("--model", default=transcribe.DEFAULT_MODEL)
    p = sub.add_parser("add", help="add a reel link or @handle via Apify (paid, needs --yes)")
    p.add_argument("target", help="a reel link or @handle")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--yes", action="store_true", help="go ahead with the paid Apify step")
    p.add_argument("--no-media", action="store_true", help="skip the temp video (no transcript or stills)")
    p.add_argument("--model", default=transcribe.DEFAULT_MODEL)
    p = sub.add_parser("tag", help="write Claude's suggested shape labels")
    p.add_argument("sc")
    p.add_argument("--from", dest="from_path", required=True)
    p.add_argument("--force", action="store_true", help="also replace accepted labels")
    for name in ("accept", "reject"):
        p = sub.add_parser(name)
        p.add_argument("sc")
        p.add_argument("field")
    p = sub.add_parser("discount", help="mark a reel's counts as not trustworthy (manual)")
    p.add_argument("sc")
    p.add_argument("--reason")
    p.add_argument("--clear", action="store_true")
    p = sub.add_parser("link-tribe", help="link a scored TRIBE job of this same reel")
    p.add_argument("sc")
    p.add_argument("job_id")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("archive", help="hide reels from the board, patterns and dashboard (nothing is deleted)")
    p.add_argument("sc", nargs="*", help="reel shortcodes")
    p.add_argument("--owners", action="append", help="archive every reel of these handles (a,b,c)")
    p.add_argument("--all-except-owner", action="append", dest="all_except_owner",
                   help="archive every reel except those of these handles (a,b,c)")
    p = sub.add_parser("unarchive", help="bring archived reels back")
    p.add_argument("sc", nargs="+")
    sub.add_parser("list")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "import-vault":
            return cmd_import_vault(args)
        if args.cmd == "add":
            return cmd_add_handle(args.target, args) if args.target.startswith("@") else cmd_add_url(args.target, args)
        return {"tag": cmd_tag, "accept": cmd_accept, "reject": cmd_reject, "discount": cmd_discount,
                "link-tribe": cmd_link_tribe, "list": cmd_list, "archive": cmd_archive,
                "unarchive": cmd_unarchive}[args.cmd](args)
    except (ReelError, StoreError, TranscribeError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
