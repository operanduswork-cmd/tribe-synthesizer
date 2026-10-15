r"""The hosted copy (D25): what may leave the laptop for the private dashboard, and the
privacy scan that guards it.

Each swipe page is built by strategist/render.py with hosted=True and then projected
here field by field into strategist/hosted_schema/<kind>.schema.json: nothing reaches
a payload unless a projection names it. TRIBE pages are built from report.json
directly (display_z lines, time_s, peaks, flat stretches, the scale label and the
framing only); peak.png is checked as a PNG under 1 MB and leaves without its text
chunks. Brain pages and their binary assets (D28: per-second maps on one colour scale per
reel, area means, the shared mesh and atlas lookups) come from strategist/brain_assets.py
for the same linked jobs; an asset holds numbers only, so it is checked by its structure
(magic, header, exact length, value ranges), never byte-scanned for text.
strategist/sync.py writes, pushes and audits what this module builds.

Stays on the laptop (D25, D28): transcripts, captions, word lists, stills, HIGH quotes
(the hosted HIGH line ends "· quote stays on the laptop"), quoted spans in notes,
copy-check shared runs (only where they sit in his draft), PROOF.md file names, every
laptop path (local_path, video_uri, facts.source, links to local pages), preds.npy and
the full-precision per-vertex output.

A TRIBE note with a quoted span, or with any 4-word run from that reel's private
transcript, caption or words, is dropped before the card is built, so the card
falls back to fact_ideas. Every payload is then checked, and one problem refuses
the whole bundle (fail closed):
  - its schema (strategist/contract.py check_page, quiet: a refusal never repeats a value);
  - the dashboard/render.py rule checks on every shown string (his own script lines
    and PROOF rows get banned words and the wall only, as on the lab page), plus the
    layer wall: a counts string never names the brain layer and a brain string
    never names counts (D20);
  - no laptop path, private folder, .env, .npy or data: image anywhere;
  - no 4-word run (case and punctuation ignored, strategist/copycheck.py words())
    from any private transcript, caption, words.json or TRIBE job words. A run that
    is in our own source text (render templates, shape labels, rule messages) is ours,
    not a leak. Problems name the page, the field and where the run came from,
    never the words;
  - no 6-word run from anything the copy check compares his drafts with, VAULT included
    (copycheck.corpus(): repurpose media and transcripts, LinkedIn posts by others, IG
    captions, COPY-VAULT examples), and no copy-check hit whose shared run is still in
    the draft (a hosted span would mark a creator's words in his line). So a copy-check
    shared run never leaves (D25): he rewrites it on the laptop, checks again, then syncs.

Standard library, plus numpy through strategist/brain_assets.py.
"""

from __future__ import annotations

import ast
import csv
import datetime as dt
import functools
import io
import json
import re
import struct
import zlib
from pathlib import Path

from . import brain_assets, contract, copycheck, render, store

R = render.R
V = 1
RUN_N = 4                       # a shared run this long is a leak
IMAGE_MAX = 1024 * 1024         # web/db images: PNG, 1 MB at most
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PNG_DROP = {b"tEXt", b"zTXt", b"iTXt", b"tIME", b"eXIf"}   # text and metadata chunks never leave
JOB_RE = render.JOB_RE
IG_URL_RE = re.compile(r"^https://www\.instagram\.com/([A-Za-z0-9._]{1,30}/)?(reel|reels|p)/[A-Za-z0-9_-]{5,40}/?$")
COMBINED_LABEL = "Combined (locates moments only)"
# Pages sync.py builds and keeps in step with the laptop. spend is the runner's (ledger, Apify usage).
SYNC_KINDS = ("board", "reel", "patterns", "lab", "tribe", "brain", "meta")
# Anywhere in a payload, in any string: a laptop path, a private folder, a secret file, raw
# output or an inlined image.
LEAK_RE = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|\\|file:/|/Users/|/home/|OneDrive|AppData|private/|\.env\b"
                     r"|\.npy\b|data:image", re.IGNORECASE)
# A quoted span in a note: straight or curly double quotes, curly single quotes, guillemets,
# or straight single quotes that are not apostrophes.
QUOTE_RE = re.compile(r'"[^"\n]{1,300}"|“[^”\n]{1,300}”|‘[^’\n]{1,300}’|«[^»\n]{1,300}»'
                      r"|(?<![A-Za-z0-9])'[^'\n]{2,300}'(?![A-Za-z0-9])")
# Fields that hold ids, codes or links, not prose: the rule checks skip them (the schema
# pins their format); the path and private-run scans still read them.
ID_FIELDS = {"sc", "shortcode", "handle", "owner", "who", "id", "job_id", "url", "key", "anchor", "chip", "time",
             "where", "row", "pattern_id", "slug", "cmd", "recreate", "local_cmd", "this_but", "replace", "check",
             "render"}
# His own words on the lab page (script lines, PROOF rows, check messages that quote them):
# banned words and the wall only, as strategist/render.py checks them.
HIS_WORDS = re.compile(r"^/(beats/\d+/(say|on_screen)|variants/\d+/line|issues/\d+/message|proof/\d+/(fact|caveat))$")
# Our own source text: a run found here was written by us, not taken from a creator.
OWN_SOURCES = ("strategist/render.py", "strategist/hosted.py", "strategist/shapes.py", "strategist/lab.py",
               "strategist/patterns.py", "dashboard/render.py", "scoring/score.py", "strategist/brain_assets.py")


class HostedError(Exception):
    """A hosted payload was refused. The message says which page and field, never private words."""


# ---------------------------------------------------------------- private runs

def runs(text, n: int = RUN_N) -> set[str]:
    """Every n-word run of text, normalised like the copy check (case, punctuation, apostrophes)."""
    return copycheck.runs(copycheck.words(str(text or "")), n)


@functools.lru_cache(maxsize=2)
def own_runs(n: int = RUN_N) -> frozenset:
    """n-word runs of the string literals in our own source files (see OWN_SOURCES)."""
    out = set()
    for rel in OWN_SOURCES:
        path = store.PROJECT_ROOT / rel
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out |= runs(node.value, n)
    return frozenset(out)


def _read(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""


def _json(path: Path):
    try:
        return json.loads(_read(path) or "null")
    except ValueError:
        return None


def _texts(items, *keys) -> str:
    return " ".join(str(it.get(k) or "") for it in items or [] if isinstance(it, dict) for k in keys)


def job_sources(job: str):
    """(label, text) for the words a TRIBE job heard: report.json words, word hits and stretched
    words, events.json words and sentences, segments.json words, clip.tsv."""
    d = store.OUTPUTS / job
    report = _json(d / "report.json") or {}
    if isinstance(report, dict):
        yield f"TRIBE job {job} report words", _texts(report.get("words"), "text")
        yield f"TRIBE job {job} word hits", _texts(report.get("word_hits"), "phrase")
        yield f"TRIBE job {job} stretched words", _texts(report.get("stretched_words"), "text")
    events = _json(d / "events.json")
    items = events.get("words") if isinstance(events, dict) else events
    yield f"TRIBE job {job} events words", _texts(items, "text")
    sentences = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and it.get("sentence") and it["sentence"] not in sentences:
            sentences.append(it["sentence"])
    yield f"TRIBE job {job} events sentences", " | ".join(str(s) for s in sentences)
    segments = _json(d / "segments.json")
    yield f"TRIBE job {job} segments", " | ".join(
        " ".join(str(w) for w in s.get("words") or [] if isinstance(w, str))
        for s in segments if isinstance(s, dict)) if isinstance(segments, list) else ""
    tsv = _read(d / "clip.tsv")
    if tsv:
        rows = list(csv.DictReader(io.StringIO(tsv), delimiter="\t"))
        yield f"TRIBE job {job} clip words", " ".join(str(r.get("text") or "") for r in rows)
        yield f"TRIBE job {job} clip sentences", " | ".join(dict.fromkeys(str(r.get("sentence") or "") for r in rows))


def reel_sources(sc: str, owner: str = "?"):
    """(label, text) for one swipe reel's private files."""
    priv = store.private_dir(sc)
    for p in sorted(priv.glob("*.txt")) if priv.is_dir() else []:
        yield f"@{owner} {sc} {p.stem}", _read(p)
    words = _json(priv / "words.json")
    yield f"@{owner} {sc} words", _texts(words if isinstance(words, list) else [], "text")


def private_sources(sc: str | None = None):
    """(label, text) for every private text on the laptop, or for one reel (its files and its
    linked TRIBE job). Labels name where a text came from and never hold its words."""
    reels = store.list_reels(include_archived=True)   # the privacy scan covers archived reels too
    if sc is not None:
        reels = [r for r in reels if r.get("shortcode") == sc]
    jobs = []
    for reel in reels:
        if not store.SHORTCODE_RE.match(str(reel.get("shortcode") or "")):
            continue
        yield from reel_sources(reel["shortcode"], reel.get("owner") or "?")
        job = str((reel.get("tribe") or {}).get("job_id") or "")
        if JOB_RE.match(job):
            jobs.append(job)
    if sc is None:
        for p in sorted((store.SWIPE / "creators" / "private").glob("*.items.json")):
            handle = p.name[:-len(".items.json")]
            items = _json(p)
            yield f"@{handle} captions", " | ".join(str(it.get("caption") or "") for it in items or []
                                                    if isinstance(it, dict))
        jobs = sorted(p.name for p in store.OUTPUTS.iterdir() if p.is_dir() and JOB_RE.match(p.name)) \
            if store.OUTPUTS.is_dir() else []
    for job in jobs:
        yield from job_sources(job)


class PrivateRuns:
    """The 4-word runs of private texts, each with the label of where it came from, and the
    copy check's 6-word runs of copy_sources (what it compares drafts with, VAULT included)."""

    def __init__(self, sources, copy_sources=()):
        self.where: dict[str, str] = {}
        for label, text in sources:
            # Texts joined with " | " never make a run across the join.
            for part in str(text or "").split(" | "):
                for g in runs(part):
                    self.where.setdefault(g, label)
        self.copied: dict[str, str] = {}
        for label, text in copy_sources:
            for g in runs(text, copycheck.N):
                self.copied.setdefault(g, label)

    def copy_hits(self, text) -> list[str]:
        """Where the copy check's shared 6-word runs in text came from (sorted labels)."""
        if not self.copied:
            return []
        found = (runs(text, copycheck.N) & self.copied.keys()) - own_runs(copycheck.N)
        return sorted({self.copied[g] for g in found})

    def copy_count(self, text) -> int:
        return len((runs(text, copycheck.N) & self.copied.keys()) - own_runs(copycheck.N)) if self.copied else 0

    def hits(self, text) -> list[str]:
        """Where the private runs in text came from (sorted labels; empty when clean)."""
        found = (runs(text) & self.where.keys()) - own_runs()
        return sorted({self.where[g] for g in found})

    def count(self, text) -> int:
        return len((runs(text) & self.where.keys()) - own_runs())


def reel_runs(sc: str) -> PrivateRuns:
    return PrivateRuns(private_sources(sc))


def private_runs() -> PrivateRuns:
    """What sync and the audit scan against: every private text on the laptop (4-word runs) and
    the copy check's whole corpus, VAULT included (6-word runs, read-only)."""
    return PrivateRuns(private_sources(), copycheck.corpus(include_vault=True))


def note_ok(note: dict, private: PrivateRuns) -> bool:
    """A TRIBE note may feed the hosted card only with no quoted span and no private 4-word run
    in its text or its idea."""
    for key in ("text", "idea_to_test"):
        value = note.get(key)
        if isinstance(value, str) and (QUOTE_RE.search(value) or private.count(value)):
            return False
    return True


# ---------------------------------------------------------------- small helpers

def ig_url(url, sc: str | None = None) -> str | None:
    """The public Instagram link, or the reel link built from the shortcode, or None."""
    if isinstance(url, str) and IG_URL_RE.match(url):
        return url
    return f"https://www.instagram.com/reel/{sc}/" if sc and store.SHORTCODE_RE.match(sc) else None


def date_or_none(value):
    s = str(value or "")[:10]
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else None


def datetime_or_none(value):
    t = store.parse_time(value)
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds") if t else None


def pick(d: dict, keys) -> dict:
    return {k: d.get(k) for k in keys}


def num(v):
    return v if R._finite(v) else None


# ---------------------------------------------------------------- projections

def project_board(page: dict) -> dict:
    def row(r):
        peer = r.get("peer")
        return {
            "sc": r["sc"], "handle": r["handle"], "url": ig_url(r.get("url"), r["sc"]),
            "meta": r["meta"], "counts": r["counts"], "as_of": r["as_of"],
            "peer": ({"ticks": list(peer["ticks"]), "median": peer["median"], "me": peer["me"],
                      "label": peer["caption"]} if peer else None),
            "shape": r["shape"], "badges": [pick(b, ("key", "label")) for b in r["badges"]],
            "discount": r.get("discount"), "recreate": r["recreate"],
            "sort": {"x": num(r["sort"].get("x")), "plays": num(r["sort"].get("plays")),
                     "posted": num(r["sort"].get("posted")), "duration": num(r["sort"].get("duration")),
                     "handle": r["sort"]["handle"]},
            "filter": {"two_x": bool(r["filter"]["two_x"]), "hook": r["filter"]["hook"],
                       "format": r["filter"]["format"], "length": r["filter"]["length"],
                       "flags": list(r["filter"]["flags"]), "tribe": bool(r["filter"]["tribe"])},
            "cells": pick(r["cells"], ("length", "posted", "plays", "x", "hook", "format", "cta", "flags", "tribe")),
        }
    opts = page["options"]
    return {
        "v": V, "rendered": page["rendered"], "stamp": list(page["stamp"]),
        "sorts": [pick(s, ("key", "field", "desc", "label")) for s in page["sorts"]],
        "default_sort": page["default_sort"],
        "options": {"hook": list(opts["hook"]), "format": list(opts["format"]), "length": list(opts["length"]),
                    "flags": [pick(f, ("key", "label")) for f in opts["flags"]]},
        "reels": [row(r) for r in page["reels"]],
        "creators": [{"handle": c["handle"], "items": list(c["items"])} for c in page["creators"]],
    }


def project_card(card: dict) -> dict:
    lines = []
    for ln in card["lines"]:
        out = pick(ln, ("tag", "time", "t", "text"))
        if ln.get("tag") == "FLAT" and "edge" in ln:
            out["edge"] = bool(ln["edge"])
        lines.append(out)
    counts = card.get("counts")
    return {"mode": card["mode"], "counts": pick(counts, ("text", "shortcode")) if counts else None,
            "lines": lines, "footnote": card.get("footnote")}


def project_reel(page: dict) -> dict:
    sc = page["shortcode"]
    return {
        "v": V, "rendered": page["rendered"], "shortcode": sc, "owner": page["owner"],
        "url": ig_url(page.get("url"), sc), "posted": date_or_none(page.get("posted")),
        "card": project_card(page["card"]), "discount": page.get("discount"), "recreate": page["recreate"],
        "beats": [pick(b, ("chip", "kind", "name", "suggested")) for b in page["beats"]],
        "beats_empty": page["beats_empty"],
        "tribe": pick(page["tribe"], ("job_id", "run_date", "missing")) if page.get("tribe") else None,
        "stamps": pick(page["stamps"], ("counts", "shape", "brain", "page")),
        "facts": [{"label": label, "value": value} for label, value in page["facts"]],
        "local_cmd": page["local_cmd"],
    }


PATTERN_FIELDS = ("id", "anchor", "kind", "level", "label", "family", "level_tag", "slot", "contrast", "by_creator",
                  "bars", "few", "suggested", "new", "zero", "lead", "show_new", "show_few", "same", "completeness",
                  "sources", "sources_empty", "uses", "use_links", "seen", "recreate")


def project_patterns(page: dict) -> dict:
    def item(p):
        out = pick(p, PATTERN_FIELDS)
        out["by_creator"] = list(p["by_creator"])
        out["bars"] = {"o": list(p["bars"]["o"]), "m": list(p["bars"]["m"])} if p.get("bars") else None
        out["sources"] = [{"sc": s["sc"], "who": s["who"], "url": ig_url(s.get("url")), "in_swipe": bool(s["in_swipe"]),
                           "counts": s["counts"]} for s in p["sources"]]
        out["use_links"] = [{"id": u["id"], "known": bool(u["known"])} for u in p["use_links"]]
        return out
    return {
        "v": V, "rendered": page["rendered"], "stamp": page["stamp"], "since": page["since"],
        "notes": list(page["notes"]), "lead": [pick(x, ("anchor", "kind", "text")) for x in page["lead"]],
        "population": list(page["population"]), "tabs": [pick(t, ("key", "label", "n", "new")) for t in page["tabs"]],
        "patterns": [item(p) for p in page["patterns"]],
    }


def project_lab(page: dict) -> dict:
    return {
        "v": V, **pick(page, ("rendered", "id", "slug", "kind", "status", "title", "updated", "checked", "stale",
                               "est_s", "target_s", "length_text")),
        "badges": [pick(b, ("name", "state", "text")) for b in page["badges"]],
        "beats": [{**pick(b, ("kind", "name", "chip", "start", "end", "say", "on_screen", "slot")),
                   "notes": [pick(n, ("n", "text")) for n in b["notes"]]} for b in page["beats"]],
        "variants": [pick(v, ("id", "shape", "family", "pattern", "pattern_id", "line", "why", "cmd"))
                     for v in page["variants"]],
        "patterns": [pick(p, ("id", "kind", "line", "known")) for p in page["patterns"]],
        "proof": [pick(p, ("row", "numbers", "fact", "caveat")) for p in page["proof"]],
        "issues": [pick(i, ("check", "level", "where", "message")) for i in page["issues"]],
        "hits": [{"kind": h["kind"], "where": h["where"], "span": list(h["span"]) if h.get("span") else None,
                  "count": h.get("count")} for h in page["hits"]],
        "commands": pick(page["commands"], ("this_but", "replace", "check", "render")),
    }


# ---------------------------------------------------------------- TRIBE pages and the peak image

def clean_png(data: bytes, what: str = "peak.png") -> bytes:
    """The PNG with its text and metadata chunks left out. Refuses anything that is not a whole,
    well-formed PNG (magic bytes, chunk CRCs, IHDR first, IEND last) or that ends up over 1 MB."""
    if not isinstance(data, (bytes, bytearray)) or bytes(data[:8]) != PNG_MAGIC:
        raise HostedError(f"{what}: not a PNG")
    out, i, first, last = [PNG_MAGIC], 8, None, None
    while i < len(data):
        if i + 12 > len(data):
            raise HostedError(f"{what}: cut short")
        n, = struct.unpack(">I", data[i:i + 4])
        kind, body = bytes(data[i + 4:i + 8]), bytes(data[i + 8:i + 8 + n])
        crc = bytes(data[i + 8 + n:i + 12 + n])
        if len(body) != n or len(crc) != 4 or struct.unpack(">I", crc)[0] != zlib.crc32(kind + body) & 0xFFFFFFFF:
            raise HostedError(f"{what}: a damaged chunk")
        first = first or kind
        last = kind
        if kind not in PNG_DROP:
            out.append(data[i:i + 12 + n])
        i += 12 + n
        if kind == b"IEND":
            break
    if first != b"IHDR" or last != b"IEND":
        raise HostedError(f"{what}: not a whole PNG")
    png = b"".join(bytes(c) for c in out)
    if len(png) > IMAGE_MAX:
        raise HostedError(f"{what}: {len(png)} bytes, over the {IMAGE_MAX} byte limit")
    return png


def image_key(job: str) -> str:
    return f"tribe/{job}/peak.png"


def tribe_page(job: str, link: dict | None = None) -> tuple[dict, bytes | None]:
    """One TRIBE job's hosted page and its peak picture (or None): lines, time, peaks, flat
    stretches, warnings, the scale label and the framing. No words, no peak values."""
    if not JOB_RE.match(job or ""):
        raise HostedError(f"not a TRIBE job id: {job!r}")
    d = store.OUTPUTS / job
    try:
        report = R._load_json(d / "report.json", f"{job} report.json")
        R.validate_report(report, R._load_json(d / "predict_meta.json", f"{job} predict_meta.json", required=False))
    except R.RenderError as e:
        raise HostedError(f"tribe {job}: {e}") from None
    link = link or {}
    src = report.get("source") or {}
    sc = link.get("shortcode") or R.shortcode_of(str(src.get("source_url") or ""))
    lines = {}
    for k in R.LINE_KEYS:
        line = report["lines"][k]
        lines[k] = {"label": line["label"], "display_z": [num(z) for z in line["display_z"]],
                    "trend": line.get("trend") if line.get("trend") in ("rising", "falling", "flat") else None}
    combined = report.get("combined") or {}
    # The combined line is where peaks and flat stretches are found (scoring/score.py shape_z).
    lines["combined"] = {"label": COMBINED_LABEL, "note": str(combined.get("note") or "locates moments only"),
                         "display_z": [num(z) for z in combined.get("display_z") or combined.get("shape_z") or []]}
    warnings = []
    for w in report.get("warnings") or []:
        if isinstance(w, dict):
            warnings.append({"code": str(w.get("code") or "note"), "text": str(w.get("text") or "")})
        elif isinstance(w, str) and w.strip():
            warnings.append({"code": "note", "text": w})
    png, peak_image = None, None
    bp = report.get("brain_picture") if isinstance(report.get("brain_picture"), dict) else {}
    path = (d / str(bp.get("path") or "")).resolve() if bp.get("path") else None
    if path and path.parent == d.resolve() and path.is_file() and R._finite(bp.get("t")):
        png = clean_png(path.read_bytes(), f"{job} peak.png")
        peak_image = {"key": image_key(job), "t": int(bp["t"])}
    page = {
        "v": V, "job_id": job, "shortcode": sc if sc and store.SHORTCODE_RE.match(sc) else None,
        "run_date": date_or_none(link.get("run_date")) or f"{job[:4]}-{job[4:6]}-{job[6:8]}",
        "framing": R.FRAMING,
        "scale": {"mode": (report.get("scale") or {}).get("mode"), "label": (report.get("scale") or {}).get("label")},
        "clip_s": num((report.get("clip") or {}).get("seconds")) or R.clip_end(report),
        "time_s": [num(t) for t in report["time_s"]],
        "lines": lines,
        "peaks": [{"t": int(p["t"]), "driving_lines": [k for k in p.get("driving_lines") or [] if k in R.LINE_KEYS],
                   "edge": bool(p.get("edge"))} for p in report.get("peaks") or [] if isinstance(p, dict)],
        "flat_stretches": [{"start": int(f["start"]), "end": int(f["end"]),
                            "driving_lines": [k for k in f.get("driving_lines") or [] if k in R.LINE_KEYS],
                            "edge": bool(f.get("edge"))} for f in report.get("flat_stretches") or []
                           if isinstance(f, dict)],
        "warnings": warnings,
        "peak_image": peak_image,
    }
    return page, png


# ---------------------------------------------------------------- meta and spend

def meta_page(reels: list[dict], handles: list[str], n_patterns: int, n_drafts: int, board_stamp: str,
              now: dt.datetime | None = None) -> dict:
    """The freshness line: one as-of and one sentence per layer, plus the counts of things."""
    now = now or dt.datetime.now(dt.timezone.utc)
    counts = sorted(d for d in (date_or_none((r.get("counts") or {}).get("as_of")) for r in reels) if d)
    added = sorted(t for t in (datetime_or_none(r.get("added_at")) for r in reels) if t)
    files = [store.reel_path(r["shortcode"]) for r in reels if store.SHORTCODE_RE.match(str(r.get("shortcode") or ""))]
    changed = sorted(store.file_time_iso(p) for p in files if p.is_file())
    accepted = labelled = 0
    for r in reels:
        a, n = render.shape_counts(r)
        accepted, labelled = accepted + a, labelled + n
    runs_on = sorted(d for d in (date_or_none((r.get("tribe") or {}).get("run_date")) for r in reels
                                 if isinstance(r.get("tribe"), dict)) if d)
    k = len(runs_on)
    doc = store.load_json(store.patterns_path()) or {}
    return {
        "v": V, "rendered_at": now.astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
        "layers": {
            "counts": {"as_of": counts[0] if counts else None, "text": board_stamp[:1].upper() + board_stamp[1:]},
            "facts": {"as_of": added[-1] if added else None, "text": "Facts fixed at ingest"},
            "shape": {"as_of": changed[-1] if changed else None,
                      "text": f"Shape labels: {accepted} of {labelled} accepted" if labelled else "Shape: not suggested yet"},
            "brain": {"as_of": runs_on[-1] if runs_on else None,
                      "text": (f"TRIBE run {runs_on[-1]}, {k} reel{'' if k == 1 else 's'}" if k
                               else "No TRIBE run yet")},
        },
        "n": {"reels": len(reels), "creators": len(handles), "patterns": n_patterns, "drafts": n_drafts,
              "tribe_reads": k},
        "patterns_built_at": datetime_or_none(doc.get("updated_at")) if isinstance(doc, dict) else None,
    }


def spend_page(modal_usd=None, apify_usd=None, now: dt.datetime | None = None) -> dict:
    """The month's spend, for the runner to push (it reads the ledger and Apify's usage);
    None is shown as not read yet. sync.py never pushes it, so it never overwrites the runner's."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    limits = contract.load_job_kinds()["limits"]
    return {"v": V, "month": now.strftime("%Y-%m"),
            "modal_usd": round(modal_usd, 4) if R._finite(modal_usd) else None,
            "modal_cap_usd": float(limits["modal_cap_usd"]),
            "apify_usd": round(apify_usd, 4) if R._finite(apify_usd) else None,
            "apify_cap_usd": float(limits["apify_cap_usd"]), "as_of": now.isoformat(timespec="seconds")}


# ---------------------------------------------------------------- checks

def _strings(obj, path: str = ""):
    if isinstance(obj, str):
        yield path or "/", obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}/{i}")


def page_problems(kind: str, page, private: PrivateRuns | None = None) -> list[str]:
    """Every reason this payload may not leave the laptop (empty when it may). Never quotes
    private words: a problem names the field and where a shared run came from."""
    try:
        key = contract.page_key(kind, page) if isinstance(page, dict) else "?"
    except contract.ContractError:
        key = "?"
    where = f"{kind}/{key}"
    try:
        contract.check_page(kind, page, quiet=True)
    except contract.ContractError as e:
        return [f"{where}: {e}"]
    out = brain_assets.page_problems(page) if kind == "brain" else []
    schema = contract.load_schema(kind)
    shown = contract.layer_strings(page, schema)
    prose = [(path, layer, text) for path, layer, text in shown if path.rsplit("/", 1)[-1] not in ID_FIELDS]
    his = [(f"{where} {p}", t) for p, _, t in prose if kind == "lab" and HIS_WORDS.match(p)]
    ours = [(f"{where} {p}", t) for p, _, t in prose if not (kind == "lab" and HIS_WORDS.match(p))]
    for check, items in ((R.check_authored, ours), (lambda x: R.check_banned(x, emotions=False), his),
                         (R.check_mixed_layers, his)):
        try:
            if items:
                check(items)
        except R.RenderError as e:
            out.append(f"{where}: {e}")
    for path, layer, text in prose:   # the wall, by layer (D20)
        if layer == "counts" and R.BRAIN_TERMS_RE.search(text.replace(R.WALL_SENTENCE, " ")):
            out.append(f"{where} {path}: a counts string names the brain layer")
        if layer == "brain" and R.COUNT_TERMS_RE.search(text):
            out.append(f"{where} {path}: a brain string names counts")
    if kind == "lab":   # a copy-check shared run still in his draft: its span would mark a creator's words
        for i, h in enumerate(page.get("hits") or []):
            if isinstance(h, dict) and h.get("kind") == "copy" and h.get("span"):
                out.append(f"{where} /hits/{i}: the copy check found a shared 6-word run still in the draft"
                           f" ({h.get('where')}); rewrite it on the laptop and check again")
    for path, text in _strings(page):
        hit = LEAK_RE.search(text)
        if hit:
            out.append(f"{where} {path}: a laptop path or private file ({hit.group(0)!r})")
        if private is not None and not (path.endswith("/url") and IG_URL_RE.match(text)):
            labels = private.hits(text)
            if labels:
                out.append(f"{where} {path}: {private.count(text)} 4-word run(s) shared with " + ", ".join(labels))
            labels = private.copy_hits(text)
            if labels:
                out.append(f"{where} {path}: {private.copy_count(text)} 6-word run(s) the copy check finds in "
                           + ", ".join(labels))
    return out


def check_payload(kind: str, page: dict, private: PrivateRuns | None = None) -> dict:
    problems = page_problems(kind, page, private)
    if problems:
        raise HostedError("refused: " + "; ".join(problems))
    return page


# ---------------------------------------------------------------- the bundle

def build_all(today: dt.date | None = None, now: dt.datetime | None = None,
              private: PrivateRuns | None = None) -> dict:
    """Every hosted page, image and brain asset, checked. Returns {"pages": [(kind, key, page)],
    "images": {key: png}, "assets": {key: brain_assets.Asset}}. Raises HostedError listing every
    problem: one bad page refuses the bundle. A linked job with preds.npy gets a brain page; when
    the atlas or the mesh is missing that refuses the bundle too (never a silent wipe)."""
    from . import lab
    now = now or dt.datetime.now(dt.timezone.utc)
    today = today or now.astimezone().date()
    private = private if private is not None else private_runs()
    pages, images, assets, problems = [], {}, {}, []

    def add(kind, build):
        try:
            page = build()
        except (HostedError, brain_assets.BrainError, R.RenderError, store.StoreError, contract.ContractError,
                KeyError, TypeError) as e:
            problems.append(f"{kind}: could not build ({type(e).__name__}: {e})")
            return None
        found = page_problems(kind, page, private)
        if found:
            problems.extend(found)
            return None
        pages.append((kind, contract.page_key(kind, page), page))
        return page

    def board():
        page, texts = render.build_board_page(today=today, hosted=True)
        R.check_authored(texts)
        return project_board(page)
    board_page = add("board", board)

    reels = store.list_reels()
    for reel in reels:
        sc = reel.get("shortcode")

        def one(sc=sc):
            mine = reel_runs(sc)
            page, texts = render.build_reel_page(sc, today=today, hosted=True, keep_note=lambda n: note_ok(n, mine))
            R.check_authored(texts)
            return project_reel(page)
        add("reel", one)

    def patterns():
        page, texts = render.build_patterns_page(today=today, hosted=True)
        R.check_authored(texts)
        return project_patterns(page)
    pat_page = add("patterns", patterns)

    drafts = lab.list_drafts()
    for d in drafts:
        def one_lab(did=d.get("id")):
            page, texts = render.build_lab_page(str(did), today=today, hosted=True)
            R.check_authored(texts)
            return project_lab(page)
        add("lab", one_lab)

    jobs = set()
    for reel in reels:
        link = reel.get("tribe") if isinstance(reel.get("tribe"), dict) else None
        job = str((link or {}).get("job_id") or "")
        if not job or job in jobs or not (store.OUTPUTS / job / "report.json").is_file():
            continue   # a link whose folder is gone: the reel card says missing
        jobs.add(job)

        def one_tribe(job=job, link=dict(link, shortcode=reel.get("shortcode"))):
            page, png = tribe_page(job, link)
            if png is not None:
                images[image_key(job)] = png
            return page
        add("tribe", one_tribe)
        if not (store.OUTPUTS / job / "preds.npy").is_file():
            continue   # no per-vertex output on the laptop: no brain page (and its assets go)

        def one_brain(job=job, link=dict(link, shortcode=reel.get("shortcode"))):
            page, made = brain_assets.build(job, link)
            assets.update(made)
            return page
        add("brain", one_brain)

    handles = sorted({str(r.get("owner")) for r in reels if r.get("owner")}
                     | {p.stem for p in (store.SWIPE / "creators").glob("*.json")})
    add("meta", lambda: meta_page(reels, handles, len((pat_page or {}).get("patterns") or []), len(drafts),
                                  (board_page or {}).get("stamp", ["", "counts as of: unknown"])[1], now))
    if problems:
        raise HostedError("refused, nothing leaves the laptop: " + "; ".join(problems))
    return {"pages": pages, "images": images, "assets": assets}


def asset_rows(assets) -> dict:
    """Bundle assets (brain_assets.Asset) or database rows, as {key: {kind, mime, data, raw_bytes,
    hash[, raw]}} for brain_problems."""
    out = {}
    for key, a in (assets or {}).items():
        if isinstance(a, brain_assets.Asset):
            out[key] = {"kind": a.kind, "mime": a.mime, "data": a.data, "raw_bytes": a.raw_bytes, "hash": a.hash,
                        "raw": a.raw}
        else:
            out[key] = dict(a)
    return out


def brain_problems(pages, assets: dict) -> list[str]:
    """The brain assets and the checks across pages (push and audit): each asset's key, kind and mime
    agree, sha256(bytes) is its hash, it unpacks to raw_bytes and passes the structure check; every
    brain page has a tribe page for the same job with the same seconds and reel; every key a brain
    page names is stored with the page's sha256 and length; no asset is left without a page."""
    out = []
    pages = [(k, key, p) for k, key, p in pages or [] if isinstance(p, dict)]
    tribe = {key: p for k, key, p in pages if k == "tribe"}
    brain = {key: p for k, key, p in pages if k == "brain"}
    rows = {brain_assets.frames_key(key): len(p.get("time_s") or []) for key, p in brain.items()}
    for key, a in sorted(assets.items()):
        found, raw = brain_assets.stored_problems(key, a.get("kind"), a.get("mime"), a.get("data"),
                                                  a.get("raw_bytes"), a.get("hash"), rows.get(key))
        out += found
        if raw is not None and "raw" in a and raw != bytes(a["raw"]):
            out.append(f"asset {key}: its gzip does not unpack to its own bytes")
    used = set()
    for key, page in sorted(brain.items()):
        where = f"brain/{key}"
        twin = tribe.get(key)
        if twin is None:
            out.append(f"{where}: no tribe page for this job")
        elif twin.get("time_s") != page.get("time_s"):
            out.append(f"{where}: its seconds differ from the tribe page's")
        elif twin.get("shortcode") != page.get("shortcode"):
            out.append(f"{where}: names another reel than its tribe page")
        for name in ("frames", "mesh", "atlas"):
            ref = page.get(name) if isinstance(page.get(name), dict) else {}
            k = ref.get("key")
            used.add(k)
            a = assets.get(k)
            if a is None:
                out.append(f"{where} /{name}: asset {k} is not stored")
            elif a.get("hash") != ref.get("sha256"):
                out.append(f"{where} /{name}: asset {k} is stored with another hash")
            elif a.get("raw_bytes") != ref.get("bytes"):
                out.append(f"{where} /{name}: asset {k} unpacks to another length")
    for k in sorted(set(assets) - used):
        out.append(f"asset {k}: no brain page uses it")
    return out


def bundle_problems(bundle: dict, private: PrivateRuns | None = None) -> list[str]:
    """The privacy scan over a whole bundle (pages, images and brain assets), as push runs it."""
    private = private if private is not None else private_runs()
    out = []
    for kind, key, page in bundle.get("pages") or []:
        out += page_problems(kind, page, private)
        try:
            if contract.page_key(kind, page) != key:
                out.append(f"{kind}/{key}: stored under the wrong key")
        except contract.ContractError as e:
            out.append(f"{kind}/{key}: {e}")
    for key, png in (bundle.get("images") or {}).items():
        if not re.match(r"^tribe/\d{8}-\d{6}-[0-9a-f]{8}/peak\.png$", key):
            out.append(f"image {key}: not a peak picture key")
        try:
            if clean_png(png, f"image {key}") != bytes(png):
                out.append(f"image {key}: holds text or metadata chunks")
        except HostedError as e:
            out.append(str(e))
    out += brain_problems(bundle.get("pages"), asset_rows(bundle.get("assets")))
    return out


def size_of(page: dict) -> int:
    """Bytes of the page's canonical JSON (what the database stores)."""
    return len(json.dumps(page, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8"))
