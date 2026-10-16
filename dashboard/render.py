"""Render one offline "Predicted response report" page for a scored output folder.

Usage:
    python dashboard/render.py <output_dir> [--no-open] [--reports-dir DIR] [--swipe-dir DIR]

Reads report.json, notes.json, segments.json, flags.json, source.json and
events.json from <output_dir>, checks them, and writes
reports/<YYYY-MM-DD>-<label>/report.html (the date of the first render: a re-render
of the same job overwrites its folder; one self-contained page: inline CSS,
SVG and JS, JSON inlined, images as data URIs, nothing loaded from the network).
The page opens on the snippet card (HOOK, HIGH, FLAT, TRY, TRY and one footnote);
everything else is folded below it. When the job's reel is in the swipe file
(swipe/reels/<shortcode>/reel.json), its public counts show in a strip of their
own above the card. Prints the path, then opens it in the default browser unless
--no-open.

Refuses with exit code 2 and a clear message when:
  - report.json (or predict_meta.json) says mock is not false,
  - notes.json is missing or breaks the notes contract,
  - the card breaks the card contract (validate_card),
  - text we wrote (template, notes, warnings, labels, card) has a banned word,
    names counts and the predicted response in one line, uses a cause word, or
    a gendered pronoun.
The reel's own transcript (words, word-hit phrases) is exempt: it is the
creator's speech, not ours. A short quote of it on the card is kept only when
the card line still passes every check.

The rule checks (check_mixed_layers, check_cause, check_pronouns,
check_pattern_line, check_sort_key, validate_card, no_decimals, find_banned)
are importable so every page type uses the same ones.

Time convention for notes (the page uses the same one, see page_range): whole
seconds as the clock shows them, and a range includes its last second. Rows
[0, 7) are written 0:00-0:06, a word span 32.991-34.051 is 0:32-0:34, and a
single second is 0:20. Each note's text must contain its own t_start-t_end
written this way, so the time button on the page matches the note.

Ideas that compare predicted lines between two reels or versions must say
"on one scale" (like for like, A vs B). Values relative to this reel's own
average can't be compared with another reel's.

Standard library only, plus ffmpeg (if on PATH) for small frame thumbnails.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import math
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
TEMPLATE_PATH = HERE / "template.html"
DEFAULT_REPORTS_ROOT = PROJECT_ROOT / "reports"
DEFAULT_SWIPE_ROOT = PROJECT_ROOT / "swipe"

FRAMING = "predicted average-brain response"
LINE_KEYS = ("seeing", "hearing", "language", "attention")
NOTE_LINES = set(LINE_KEYS) | {"combined"}
NOTE_KINDS = {"summary", "hook", "peak", "flat", "word"}
PURPOSES = {"test", "edit", "calibration"}
NOTE_TEXT_MAX = 320
NOTES_MIN, NOTES_MAX = 4, 10
TIME_RE = re.compile(r"(?<!\d)\d{1,2}:[0-5]\d(?!\d)")
JSON_SLOTS = ("REPORT", "NOTES", "SEGMENTS", "FLAGS", "SOURCE", "PAGE")
SLOT_RE = re.compile(r"__(" + "|".join(JSON_SLOTS) + r")_JSON__")

# Ban list (CLAUDE.md framing rule, SCORING.md section 16, the notes contract and the
# plan's wall: performance, verdict, rank and emotion words). Case-insensitive whole
# words; a trailing "s"/"es" plural is caught too. "outperform..." and "underperform..."
# are caught in every form below. "perform" alone stays allowed ("perform a test").
BANNED_WORDS_CI = (
    "views", "viral", "virality", "reach", "ctr", "watch time", "will perform", "view count",
    "engagement", "emotion", "emotional", "reward", "dopamine", "desire",
    "amygdala", "nacc", "score", "grade", "winner",
    "performance", "performing", "performed", "performs", "performer", "top performing", "proven", "winning",
    "best hook", "guaranteed", "rank", "ranked", "ranking",
)
# Emotion labels: TRIBE predicts no feelings, so none is ever named in our text. His own
# script lines may use these words (find_banned(..., emotions=False)).
EMOTION_WORDS = ("joy", "fear", "anger", "angry", "sad", "sadness", "happy", "happiness", "excitement", "excited",
                 "exciting", "surprise", "surprised", "surprising")
# Verdict words, banned only when written in capitals (so "post" in prose is fine).
BANNED_WORDS_CS = ("POST", "DEPLOY", "STRONG")
# A rating: a 0-100 or N/10 number, a "#1" or an ordinal place ("1st"). A pattern
# contrast ("outliers 1/10 vs normal 3/10") is a share of reels, not a rating.
RATING_PATTERNS = (
    r"(?<![\w.])\d{1,3}(?:\.\d+)?\s*(?:/|out of)\s*100(?![\w.])",
    r"(?<![\w.])0\s*(?:-|to|–)\s*100(?![\w.])",
    r"(?<![\w./])(?<!outliers )(?<!normal )\d{1,2}(?:\.\d+)?\s*(?:/|out of)\s*10(?![\w.\d])",
    r"(?<![&\w])#\d{1,2}(?![\w#])",
    r"(?<![\w.])\d+(?:st|nd|rd|th)(?![A-Za-z0-9])",
)


class RenderError(Exception):
    """The page was refused. The message says why."""


def _term_pattern(term: str) -> str:
    parts = [re.escape(p) for p in re.split(r"[\s-]+", term)]
    return r"[\s-]*".join(parts)


_BANNED_CI_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:" + "|".join(_term_pattern(t) for t in BANNED_WORDS_CI) + r")(?:e?s)?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_EMOTION_RE = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(EMOTION_WORDS) + r")s?(?![A-Za-z0-9])", re.IGNORECASE)
_BANNED_CS_RE = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(BANNED_WORDS_CS) + r")(?![A-Za-z0-9])")
_BANNED_PREFIX_RE = re.compile(r"(?<![A-Za-z0-9])(?:out|under)perform[A-Za-z]*", re.IGNORECASE)
_RATING_RE = re.compile("|".join(RATING_PATTERNS), re.IGNORECASE)


def find_banned(text: str, emotions: bool = True) -> list[str]:
    """Return the banned words or rating numbers found in text (empty when clean).
    emotions=False skips the emotion words (only for his own script lines)."""
    if not text:
        return []
    hits = [m.group(0) for m in _BANNED_CI_RE.finditer(text)]
    if emotions:
        hits += [m.group(0) for m in _EMOTION_RE.finditer(text)]
    hits += [m.group(0) for m in _BANNED_CS_RE.finditer(text)]
    hits += [m.group(0) for m in _BANNED_PREFIX_RE.finditer(text)]
    hits += [m.group(0) for m in _RATING_RE.finditer(text)]
    return hits


# ---------------------------------------------------------------- the wall (D20)
# Public counts and the predicted average-brain response never share a line, a sort,
# a chart or a total, and nothing is said to cause anything. Every page type (this
# report, the swipe board, reel cards, patterns, the script lab) runs these checks.

COUNT_TERMS_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:plays|likes|comments|medians?|outliers?|followers)(?![A-Za-z0-9])"
    r"|(?<![\w.])\d+(?:\.\d+)?[x×](?![A-Za-z0-9])", re.IGNORECASE)
BRAIN_TERMS_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:peak(?:s|ed|ing)?|high|higher|highest|flat|low|lower|lowest|seeing|hearing|language|attention"
    r"|brain|response|lanes?|tribe|predicted|spik(?:e|es|ed|ing)|activ(?:ation|ations|ity|ities|ated?|ates)"
    r"|neural|cortex|cortical)(?![A-Za-z0-9])", re.IGNORECASE)
# The one sentence allowed to name both layers: it says they are kept apart.
WALL_SENTENCE = ("Public counts (plays, likes, comments) and the predicted average-brain response are "
                 "separate layers: they never share a line, a sort or a chart.")
# "Driven by:" or "driven by <line name>" (which predicted lines make up a peak, inside one
# reel) is the one allowed form of "driven".
CAUSE_RE = re.compile(
    r"(?<![A-Za-z_])(?:because|that['’]?s why|that is why|which is why|is why|led to|leads to|lead to|drove|drives?"
    r"|driving|driven(?!\s+by\s*:|\s+by\s+(?:the\s+)?(?:seeing|hearing|language|attention|combined)\b)"
    r"|caused|causes|explains|due to|thanks to|as a result|results? in|resulted in|resulting in)(?![A-Za-z_])",
    re.IGNORECASE)
# Never infer a creator's pronouns: write the @handle or "the creator".
PRONOUN_RE = re.compile(r"(?<![A-Za-z])(?:she|he|her|hers|herself|his|him|himself)(?![A-Za-z])", re.IGNORECASE)
DECIMAL_RE = re.compile(r"(?<![\w.])\d*\.\d+")
CHIP_RE = re.compile(r"(?<![\d:])\d{1,2}:[0-5]\d(?:-\d{1,2}:[0-5]\d)?(?![\d:])")
PATTERN_CONTRAST_RE = re.compile(r"\boutliers (\d+)/(\d+) vs normal (\d+)/(\d+)(?!\d)")
PATTERN_NO_COMPARE = "outliers only, no comparison yet"
# The board may sort by these, never by any TRIBE field.
SORT_KEYS = {"x": "x", "x.plays": "x", "plays": "plays", "counts.plays": "plays", "posted": "posted",
             "duration": "duration", "duration_s": "duration", "facts.duration_s": "duration",
             "handle": "handle", "owner": "handle"}


def _items(texts, where: str) -> list[tuple[str, str]]:
    if isinstance(texts, str):
        return [(where, texts)]
    out = []
    for i, t in enumerate(texts or []):
        out.append(t if isinstance(t, tuple) else (f"{where}[{i}]", str(t)))
    return out


def check_mixed_layers(lines, allow: str = WALL_SENTENCE, where: str = "line") -> None:
    """Refuse any line that names both a public count and the predicted response.
    Lines are strings or (where, text) pairs; multi-line text is checked line by line.
    The one allow-listed framing sentence is skipped."""
    found = []
    for src, text in _items(lines, where):
        for n, line in enumerate(str(text).splitlines() or [""], 1):
            if allow:
                line = line.replace(allow, " ")
            counts = COUNT_TERMS_RE.findall(line)
            brain = BRAIN_TERMS_RE.findall(line)
            if counts and brain:
                at = f"{src} line {n}" if "\n" in str(text) else src
                found.append(f"{at}: counts {sorted(set(counts))} with brain {sorted(set(b.lower() for b in brain))}")
    if found:
        raise RenderError("counts and the predicted response share a line (the wall): " + "; ".join(found))


def check_cause(text, where: str = "text") -> None:
    """Refuse cause words ('because', 'that's why', 'led to', 'drove', 'caused', 'explains'...)."""
    found = [f"{src}: {sorted(set(m.group(0).lower() for m in CAUSE_RE.finditer(t)))}"
             for src, t in _items(text, where) if CAUSE_RE.search(t)]
    if found:
        raise RenderError("cause words in our text (nothing here shows a cause): " + "; ".join(found))


def check_pronouns(text, where: str = "text") -> None:
    """Refuse gendered pronouns in text we wrote about a creator."""
    found = [f"{src}: {sorted(set(m.group(0).lower() for m in PRONOUN_RE.finditer(t)))}"
             for src, t in _items(text, where) if PRONOUN_RE.search(t)]
    if found:
        raise RenderError("gendered pronoun in our text (use the @handle or 'the creator'): " + "; ".join(found))


def find_decimals(text: str) -> list[str]:
    return DECIMAL_RE.findall(text or "")


def no_decimals(text: str) -> bool:
    """True when the text has no decimal numbers (card prose uses whole numbers only)."""
    return not find_decimals(text)


def check_pattern_line(text: str) -> None:
    """A pattern line always shows its contrast: 'outliers k/n vs normal k/m', or says
    'outliers only, no comparison yet'. Never outliers alone as if the pattern works."""
    m = PATTERN_CONTRAST_RE.search(text or "")
    if m:
        k, n, j, mm = (int(g) for g in m.groups())
        if n == 0 or mm == 0 or k > n or j > mm:
            raise RenderError(f"pattern line has an impossible contrast {m.group(0)!r}: {text!r}")
        return
    if PATTERN_NO_COMPARE in (text or ""):
        return
    raise RenderError(f"pattern line needs 'outliers k/n vs normal k/m' or '{PATTERN_NO_COMPARE}': {text!r}")


def check_sort_key(key: str) -> str:
    """Return the board sort key (x, plays, posted, duration, handle; a leading '-' means
    descending). Refuses any TRIBE or brain field: brain output is never sorted on."""
    raw = str(key or "").strip()
    k = raw.lstrip("+-").lower()
    if "tribe" in k or BRAIN_TERMS_RE.search(k.replace(".", " ").replace("_", " ")):
        raise RenderError(f"never sort by a TRIBE or brain field: {raw!r}")
    if k not in SORT_KEYS:
        raise RenderError(f"unknown sort key {raw!r}: use one of {sorted(set(SORT_KEYS.values()))}")
    return ("-" if raw.startswith("-") else "") + SORT_KEYS[k]


# ---------------------------------------------------------------- loading

def _load_json(path: Path, what: str, required: bool = True):
    if not path.exists():
        if required:
            raise RenderError(f"{what} not found: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RenderError(f"{what} could not be read as JSON ({path}): {e}") from e


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def clip_end(report: dict) -> float:
    """Last second covered by the clip: analysed length or the last row's end."""
    rows = report.get("time_s") or []
    seconds = (report.get("clip") or {}).get("seconds") or 0
    last = (rows[-1] + 1) if rows and _finite(rows[-1]) else 0
    return max(float(seconds) if _finite(seconds) else 0.0, float(last))


def last_second(report: dict) -> int:
    """The last whole second on the page's time axis."""
    return max(0, math.ceil(clip_end(report) - 1e-6) - 1)


def fmt_clock(s: int) -> str:
    return f"{s // 60}:{s % 60:02d}"


def page_range(a: float, b: float, last_sec: int) -> str:
    """The closed range of whole seconds a span touches, exactly as the page writes it
    (template.html fmtRange): [9, 12) -> 0:09-0:11, 32.991-34.051 -> 0:32-0:34, [20, 21) -> 0:20."""
    fa = min(max(math.floor(a + 1e-6), 0), last_sec)
    fb = min(max(math.ceil(b - 1e-6) - 1, fa), last_sec)
    return fmt_clock(fa) if fb == fa else f"{fmt_clock(fa)}-{fmt_clock(fb)}"


def _mentions_range(text: str, rng: str) -> bool:
    return re.search(r"(?<![\d:\-])" + re.escape(rng) + r"(?!\d|-\d)", text) is not None


# An idea that compares predicted lines across reels or versions (needs "on one scale").
_IDEA_AGAINST_THIS_RE = re.compile(
    r"\bthan (?:this|here|in this reel|this reel(?:'s)?)\b|\b(?:sits?|gets?) (?:shorter|longer|higher|lower)\b", re.IGNORECASE)
_IDEA_COMPARE_RE = re.compile(r"\bcompar(?:e|es|ed|ing)\b", re.IGNORECASE)
_IDEA_LINE_RE = re.compile(r"\b(?:seeing|hearing|language|attention|combined|lines?)\b", re.IGNORECASE)


def idea_needs_one_scale(idea: str) -> bool:
    """True when the idea compares predicted lines between reels or versions without saying 'one scale'."""
    if "one scale" in idea.lower():
        return False
    return bool(_IDEA_AGAINST_THIS_RE.search(idea) or (_IDEA_COMPARE_RE.search(idea) and _IDEA_LINE_RE.search(idea)))


def validate_report(report: dict, predict_meta: dict | None) -> None:
    if not isinstance(report, dict):
        raise RenderError("report.json is not a JSON object")
    if report.get("mock") is not False:
        raise RenderError(f"report.json mock is {report.get('mock')!r}, not false: refusing to render mock or fallback output")
    if predict_meta is not None and predict_meta.get("mock") is not False:
        raise RenderError(f"predict_meta.json mock is {predict_meta.get('mock')!r}, not false: refusing to render mock or fallback output")
    if report.get("framing") != FRAMING:
        raise RenderError(f"report.json framing must be {FRAMING!r}, got {report.get('framing')!r}")
    problems = []
    for key in ("job_id", "time_s", "per_second", "lines", "clip", "scale"):
        if key not in report:
            problems.append(f"missing '{key}'")
    if problems:
        raise RenderError("report.json breaks the report contract: " + "; ".join(problems))
    rows = len(report["time_s"])
    if rows == 0:
        raise RenderError("report.json has no rows (time_s is empty)")
    if report.get("purpose") not in PURPOSES:
        problems.append(f"purpose must be one of {sorted(PURPOSES)}")
    for k in LINE_KEYS:
        line = (report.get("lines") or {}).get(k)
        if not isinstance(line, dict):
            problems.append(f"missing lines.{k}")
            continue
        dz = line.get("display_z")
        if not isinstance(dz, list) or len(dz) != rows:
            problems.append(f"lines.{k}.display_z must have {rows} values")
        if not isinstance(line.get("label"), str) or not line.get("label"):
            problems.append(f"lines.{k}.label missing")
    if len(report["per_second"]) != rows:
        problems.append(f"per_second must have {rows} entries")
    if problems:
        raise RenderError("report.json breaks the report contract: " + "; ".join(problems))


def validate_notes(notes, report: dict) -> None:
    """Check notes.json against the notes contract. Raises RenderError listing every problem."""
    if notes is None:
        raise RenderError("notes.json is missing: Claude's notes must be written before the page is rendered")
    if not isinstance(notes, dict):
        raise RenderError("notes.json is not a JSON object")
    problems = []
    if notes.get("job_id") != report.get("job_id"):
        problems.append(f"job_id {notes.get('job_id')!r} does not match report.json {report.get('job_id')!r}")
    if notes.get("author") != "Claude":
        problems.append("author must be 'Claude'")
    scale_label = (report.get("scale") or {}).get("label")
    if notes.get("scale_label") != scale_label:
        problems.append(f"scale_label must be {scale_label!r}")
    items = notes.get("notes")
    if not isinstance(items, list):
        raise RenderError("notes.json breaks the notes contract: 'notes' must be a list")
    if not NOTES_MIN <= len(items) <= NOTES_MAX:
        problems.append(f"needs {NOTES_MIN} to {NOTES_MAX} notes, has {len(items)}")
    available = {k for k in LINE_KEYS if k in (report.get("lines") or {})}
    if "combined" in report:
        available.add("combined")
    end = clip_end(report)
    last_sec = last_second(report)
    seen_ids = set()
    for i, n in enumerate(items):
        where = f"note {i + 1}"
        if not isinstance(n, dict):
            problems.append(f"{where} is not an object")
            continue
        nid = n.get("id")
        where = f"note {nid!r}" if nid else where
        if not isinstance(nid, str) or not nid:
            problems.append(f"{where}: id missing")
        elif nid in seen_ids:
            problems.append(f"{where}: duplicate id")
        seen_ids.add(nid)
        if n.get("kind") not in NOTE_KINDS:
            problems.append(f"{where}: kind must be one of {sorted(NOTE_KINDS)}")
        a, b = n.get("t_start"), n.get("t_end")
        own_range = None
        if not (_finite(a) and _finite(b)):
            problems.append(f"{where}: t_start and t_end must be numbers")
        elif not (0 <= a < b <= end + 1e-6):
            problems.append(f"{where}: time range {a}-{b} must have t_start < t_end inside the clip (0 to {end:g} s)")
        else:
            own_range = page_range(a, b, last_sec)
        lines = n.get("lines")
        if not isinstance(lines, list) or not lines:
            problems.append(f"{where}: must cite at least one line")
        else:
            bad = [k for k in lines if k not in NOTE_LINES or k not in available]
            if bad:
                problems.append(f"{where}: lines not in report.json: {bad}")
        text = n.get("text")
        if not isinstance(text, str) or not text.strip():
            problems.append(f"{where}: text missing")
        else:
            if len(text) > NOTE_TEXT_MAX:
                problems.append(f"{where}: text is {len(text)} chars (max {NOTE_TEXT_MAX})")
            if not TIME_RE.search(text):
                problems.append(f"{where}: text must mention its time as m:ss or m:ss-m:ss")
            elif own_range and not _mentions_range(text, own_range):
                problems.append(f"{where}: text must mention its own time range as the page writes it, "
                                f"'{own_range}' (whole seconds, last second included)")
        idea = n.get("idea_to_test")
        if idea is not None and (not isinstance(idea, str) or not idea.startswith("Test:")):
            problems.append(f"{where}: idea_to_test must be null or start with 'Test:'")
        elif isinstance(idea, str) and idea_needs_one_scale(idea):
            problems.append(f"{where}: idea_to_test compares predicted lines across reels or versions: make it like for like "
                            "and say 'on one scale' (A vs B), never against this reel's own-average values")
    summaries = [n for n in items if isinstance(n, dict) and n.get("kind") == "summary"]
    if not summaries:
        problems.append("a summary note is required")
    else:
        s = " ".join(str(n.get("text") or "") for n in summaries).lower().replace("’", "'")
        if "own average" not in s:
            problems.append("summary must say dips and peaks are relative to this reel's own average")
        if not (("average brain" in s or "average-brain" in s) and "audience" in s):
            problems.append("summary must say the model predicts an average brain, not his audience")
    if problems:
        raise RenderError("notes.json breaks the notes contract: " + "; ".join(problems))


# ---------------------------------------------------------------- snippet card (D18)
# Shared by this report page and the swipe reel cards. HOOK comes from shape and facts
# only (never the TRIBE hook values: on an outlier those read as a weakness that may not
# exist). HIGH/FLAT come from report.json. TRY lines are Claude's "Test:" ideas about his
# draft. Public counts sit in their own strip above the card, never in a card line.

CARD_TAGS_TRIBE = ("HOOK", "HIGH", "FLAT", "TRY", "TRY")
CARD_TAGS_FACTS = ("HOOK", "BEATS", "PACE", "TRY", "TRY")
CARD_LINE_MAX = 140
CARD_FOOTNOTE = "HIGH/FLAT: predicted average-brain response, vs this reel's own average."
EDGE_S = 2
SHAPE_SHOWN = ("accepted", "suggested")
_HOOK_FORBIDDEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:seeing|hearing|language|attention|combined|lines?|brain|response|peaks?|flat|lanes?)(?![A-Za-z0-9])",
    re.IGNORECASE)
_TRY_DRAFT_RE = re.compile(r"\byour (?:draft|script)\b", re.IGNORECASE)
_TRUST_RE = re.compile(r"\btrust\b", re.IGNORECASE)
_LOW_TAG_RE = re.compile(r"(?<![A-Za-z])LOW(?![A-Za-z])")
IG_CODE_RE = re.compile(r"instagram\.com/(?:[A-Za-z0-9_.]+/)?(?:reels?|p|tv)/([A-Za-z0-9_-]{5,})", re.IGNORECASE)
_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,64}$")


def card_line_text(line: dict) -> str:
    """One card line exactly as it reads on the page: tag, time chip, text."""
    return " ".join(str(p) for p in (line.get("tag"), line.get("time"), line.get("text")) if p)


def _card_line_problems(line: dict) -> list[str]:
    tag = line.get("tag") or "line"
    text = line.get("text")
    if not isinstance(text, str) or not text.strip():
        return [f"{tag}: text missing"]
    full = card_line_text(line)
    p = []
    if len(full) > CARD_LINE_MAX:
        p.append(f"{tag}: {len(full)} chars (max {CARD_LINE_MAX})")
    time = line.get("time")
    if time is not None and not (isinstance(time, str) and CHIP_RE.fullmatch(time)):
        p.append(f"{tag}: time chip {time!r} must be m:ss or m:ss-m:ss")
    chips = CHIP_RE.findall(full)
    if len(chips) > 1:
        p.append(f"{tag}: {len(chips)} times {chips} (one time chip per line)")
    if find_decimals(full):
        p.append(f"{tag}: decimals {find_decimals(full)} (whole numbers only in card prose)")
    for what, found in (("banned words", find_banned(full)),
                        ("cause words", [m.group(0) for m in CAUSE_RE.finditer(full)]),
                        ("gendered pronouns", [m.group(0) for m in PRONOUN_RE.finditer(full)]),
                        ("the word Trust", [m.group(0) for m in _TRUST_RE.finditer(full)]),
                        ("LOW (use FLAT)", [m.group(0) for m in _LOW_TAG_RE.finditer(full)])):
        if found:
            p.append(f"{tag}: {what} {sorted(set(found))}")
    counts = COUNT_TERMS_RE.findall(full)
    if counts:
        p.append(f"{tag}: counts {sorted(set(counts))} belong in the counts strip above the card, never in a card line")
    if tag == "HOOK" and _HOOK_FORBIDDEN_RE.search(text):
        p.append(f"HOOK: built from shape and facts only, never the predicted lines "
                 f"({sorted(set(m.group(0).lower() for m in _HOOK_FORBIDDEN_RE.finditer(text)))})")
    if tag == "TRY":
        if not text.startswith("Test:"):
            p.append("TRY: must start 'Test:'")
        elif not _TRY_DRAFT_RE.search(text):
            p.append("TRY: must be about your draft (say 'your draft')")
        if idea_needs_one_scale(text):
            p.append("TRY: compares predicted lines across reels or versions without 'on one scale'")
    if tag == "FLAT" and line.get("edge") and "lower confidence" not in text:
        p.append("FLAT: an edge stretch must say 'lower confidence'")
    return p


def validate_card(card) -> None:
    """Check a snippet card against the card contract. Raises RenderError listing every problem."""
    if not isinstance(card, dict) or not isinstance(card.get("lines"), list):
        raise RenderError("card breaks the card contract: needs a 'lines' list")
    p = []
    mode = card.get("mode")
    if mode not in ("tribe", "facts"):
        p.append("mode must be 'tribe' or 'facts'")
    want = CARD_TAGS_TRIBE if mode == "tribe" else CARD_TAGS_FACTS
    lines = card["lines"]
    tags = tuple(ln.get("tag") if isinstance(ln, dict) else None for ln in lines)
    if tags != want:
        p.append(f"lines must be {', '.join(want)} in that order, got {', '.join(map(str, tags))}")
    seen = {}
    for ln in lines:
        if not isinstance(ln, dict):
            p.append("every line must be an object")
            continue
        p += _card_line_problems(ln)
        for c in CHIP_RE.findall(card_line_text(ln)):
            if c in seen:
                p.append(f"{ln.get('tag')}: time {c} is already on the card ({seen[c]}); each time appears once")
            seen.setdefault(c, ln.get("tag"))
    foot = card.get("footnote")
    if mode == "tribe" and foot != CARD_FOOTNOTE:
        p.append(f"footnote must be {CARD_FOOTNOTE!r}")
    if mode == "facts" and foot and BRAIN_TERMS_RE.search(foot):
        p.append("a card without a TRIBE run has no HIGH/FLAT footnote")
    counts = card.get("counts")
    if counts is not None:
        text = counts.get("text") if isinstance(counts, dict) else None
        if not isinstance(text, str) or not text.strip():
            p.append("counts strip: text missing")
        else:
            brain = BRAIN_TERMS_RE.findall(text)
            if brain:
                p.append(f"counts strip: never mentions the predicted response ({sorted(set(brain))})")
            for what, found in (("banned words", find_banned(text)),
                                ("cause words", [m.group(0) for m in CAUSE_RE.finditer(text)]),
                                ("gendered pronouns", [m.group(0) for m in PRONOUN_RE.finditer(text)])):
                if found:
                    p.append(f"counts strip: {what} {sorted(set(found))}")
    if p:
        raise RenderError("card breaks the card contract: " + "; ".join(p))


def _lines_phrase(keys) -> str:
    keys = [k for k in LINE_KEYS if k in (keys or [])]
    if len(keys) == len(LINE_KEYS):
        return "all four lines"
    if not keys:
        return "combined line"
    if len(keys) == 1:
        return f"{keys[0]} line"
    return ", ".join(keys[:-1]) + f" and {keys[-1]} lines"


def _first_word_start(events, report) -> float | None:
    for src in ((events or {}).get("words") if isinstance(events, dict) else None, (report or {}).get("words")):
        for w in src or []:
            if (isinstance(w, dict) and str(w.get("text") or "").strip() and _finite(w.get("start"))
                    and not w.get("ghost")):
                return float(w["start"])
    return None


def _second_chip(t: float, last_sec: int) -> str:
    return page_range(t, t + 1e-3, last_sec)


def _shape_label(shape_id: str) -> str:
    """How a shape id reads on a page: the readable label from strategist/shapes.py when the
    id is in that vocabulary, else the id with its hyphens as spaces."""
    try:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.append(str(PROJECT_ROOT))
        from strategist import shapes
        return shapes.label(shape_id)
    except ImportError:
        return re.sub(r"[_\s]+", " ", re.sub(r"(?<=\w)-(?=\w)", " ", shape_id)).strip()


def _hook_line(report, events, reel, last_sec: int) -> dict:
    """Shape, then the facts that are known, then 'first word at' with its time chip after it."""
    facts = (reel or {}).get("facts") or {}
    hs = ((reel or {}).get("shape") or {}).get("hook_shape") or {}
    fw = facts.get("first_word_s") if _finite(facts.get("first_word_s")) else _first_word_start(events, report)
    parts = []
    if isinstance(hs.get("id"), str) and hs["id"].strip() and hs.get("status") in SHAPE_SHOWN:
        parts.append(_shape_label(hs["id"]) + (" (suggested)" if hs.get("status") != "accepted" else ""))
    else:
        parts.append("hook shape not tagged yet")
    on = facts.get("text_on_screen_0s")
    if on in (True, False):   # left out while unknown
        parts.append("text on screen at start: " + ("yes" if on else "no"))
    parts.append("first word at" if fw is not None else "no speech found")
    t = math.floor(fw + 1e-6) if fw is not None else None
    return {"tag": "HOOK", "time": _second_chip(fw, last_sec) if fw is not None else None, "t": t, "text": " · ".join(parts)}


def top_peak(report: dict) -> dict | None:
    peaks = [p for p in report.get("peaks") or [] if isinstance(p, dict) and _finite(p.get("t"))]
    return max(peaks, key=lambda p: (p.get("value") or 0, -p["t"])) if peaks else None


def preferred_flat(report: dict) -> dict | None:
    """The deepest flat stretch away from the edges; an edge one only when there is no other."""
    flats = [f for f in report.get("flat_stretches") or [] if isinstance(f, dict) and _finite(f.get("start"))]
    pool = [f for f in flats if not f.get("edge")] or flats
    return min(pool, key=lambda f: (f.get("mean") if _finite(f.get("mean")) else 0, f["start"])) if pool else None


def _peak_quote(report: dict, t: int) -> list[str]:
    out = []
    for w in report.get("words") or []:
        if isinstance(w, dict) and t in (w.get("rows") or []) and not w.get("ghost") and not w.get("stretched"):
            out.append(str(w.get("text") or "").strip())
    return [w for w in out if w]


# A quote word that would read as our own verdict next to HIGH (a creator may talk about
# brains or "the strongest response"): such words never go into the card's quote.
_QUOTE_SKIP_RE = re.compile(
    r"(?<![A-Za-z])(?:predict\w*|respon\w*|brains?|neural|activ\w*|peak\w*|strong\w*|best|top|most|highest|better"
    r"|winn\w*|perform\w*)(?![A-Za-z])", re.IGNORECASE)


def _quote_windows(words: list[str], longest: int = 6, shortest: int = 2):
    """Runs of 2 to `longest` words with no verdict-like word, longest and earliest first."""
    ok = [not (_QUOTE_SKIP_RE.search(w) or BRAIN_TERMS_RE.search(w)) for w in words]
    for n in range(min(len(words), longest), shortest - 1, -1):
        for i in range(len(words) - n + 1):
            if all(ok[i:i + n]):
                yield words[i:i + n]


def _high_line(report: dict, peak, last_sec: int) -> dict:
    if not peak:
        return {"tag": "HIGH", "time": None, "t": None, "text": "no peak in this reel"}
    base = f"{_lines_phrase(peak.get('driving_lines'))} high for this reel"
    if peak.get("edge"):
        base += " · edge second, lower confidence"
    line = {"tag": "HIGH", "time": _second_chip(peak["t"], last_sec), "t": peak["t"]}
    words = _peak_quote(report, int(peak["t"]))
    # The quote is the reel's own speech: kept only when the whole line still passes the card checks.
    for run in _quote_windows(words):
        q = " ".join(run).strip(" ,.;:!?\"'“”")
        cand = dict(line, text=f"{base} · said: \"…{q}…\"")
        if q and not _card_line_problems(cand):
            return cand
    return dict(line, text=base + (" · no clear speech in this second" if not words else ""))


def _flat_line(report: dict, flat, last_sec: int) -> dict:
    if not flat:
        return {"tag": "FLAT", "time": None, "t": None, "text": "no flat stretch in this reel"}
    text = f"{_lines_phrase(flat.get('driving_lines'))} low for this reel"
    end = clip_end(report)
    edge = bool(flat.get("edge"))
    if edge:
        side = [s for s, on in (("first", flat["start"] < EDGE_S), ("last", flat.get("end", 0) > end - EDGE_S)) if on]
        text += f" · {' and '.join(side) or 'edge'} {EDGE_S} s, lower confidence"
    if flat.get("overlaps_black"):
        text += " · overlaps black frames"
    return {"tag": "FLAT", "time": page_range(flat["start"], flat.get("end", flat["start"] + 1), last_sec),
            "t": flat["start"], "text": text, "edge": edge}


def _beats_line(reel) -> dict:
    beats = [b for b in ((reel or {}).get("shape") or {}).get("beats") or []
             if isinstance(b, dict) and b.get("status") in SHAPE_SHOWN and (b.get("name") or b.get("kind"))]
    if not beats:
        return {"tag": "BEATS", "time": None, "t": None, "text": "beats: not tagged yet"}
    text = " → ".join(str(b.get("name") or b.get("kind")) for b in beats)
    if any(b.get("status") != "accepted" for b in beats):
        text += " (suggested)"
    return {"tag": "BEATS", "time": None, "t": None, "text": text}


def _pace_line(reel, last_sec: int) -> dict:
    facts = (reel or {}).get("facts") or {}
    parts, time, t = [], None, None
    if _finite(facts.get("words_per_s")):
        parts.append(f"about {round(facts['words_per_s'])} words a second")
    cta = facts.get("cta") if isinstance(facts.get("cta"), dict) else None
    if cta and cta.get("type"):
        parts.append(f"call to action: {cta['type']}" + (", guessed: not seen or heard" if cta_inferred(reel) else ""))
        if _finite(cta.get("t")):
            time, t = _second_chip(cta["t"], last_sec), math.floor(cta["t"] + 1e-6)
    return {"tag": "PACE", "time": time, "t": t, "text": " · ".join(parts) or "pace: not measured yet"}


def _ideas(notes) -> list[dict]:
    items = notes.get("notes") if isinstance(notes, dict) else notes
    out = []
    for n in items or []:
        if isinstance(n, str):
            out.append({"idea_to_test": n})
        elif isinstance(n, dict) and isinstance(n.get("idea_to_test"), str):
            out.append(n)
    return out


def _overlaps(n: dict, a: float, b: float) -> bool:
    return _finite(n.get("t_start")) and _finite(n.get("t_end")) and min(b, n["t_end"]) - max(a, n["t_start"]) > 1e-9


def _try_lines(notes, peak, flat, used: set, skip_flat: bool = False) -> list[dict]:
    def rank(n):
        if peak and n.get("kind") == "peak" and _overlaps(n, peak["t"], peak["t"] + 1):
            return 0
        if flat and n.get("kind") == "flat" and _overlaps(n, flat["start"], flat.get("end", flat["start"] + 1)):
            return 1
        return 2 if n.get("kind") == "hook" else 3
    out = []
    for n in sorted(_ideas(notes), key=lambda n: (rank(n), n.get("t_start") if _finite(n.get("t_start")) else 0)):
        if skip_flat and flat and n.get("kind") == "flat" and _overlaps(n, flat["start"], flat.get("end", flat["start"] + 1)):
            continue   # the reel speaks a call to action there that the timed words may have missed
        line = {"tag": "TRY", "time": None, "t": None, "text": n["idea_to_test"].strip()}
        chips = CHIP_RE.findall(card_line_text(line))
        if _card_line_problems(line) or used.intersection(chips) or any(o["text"] == line["text"] for o in out):
            continue
        used.update(chips)
        out.append(line)
        if len(out) == 2:
            return out
    raise RenderError("notes.json needs at least 2 idea_to_test lines that fit the card: start 'Test:', about "
                      f"your draft ('your draft'), at most {CARD_LINE_MAX - 4} characters, no decimals, at most "
                      "one time and no time already on the card")


def cta_inferred(reel) -> bool:
    """True when the reel's CTA type was guessed from repeated comments, not seen or heard."""
    src = (((reel or {}).get("facts") or {}).get("source") or {}).get("cta")
    return isinstance(src, str) and src.startswith("inferred")


def baseline_label(b) -> str:
    """'14 reels', or '11 posts, all types, not re-checked' for a baseline carried from another record."""
    b = b if isinstance(b, dict) else {}
    if not _finite(b.get("n")):
        return ""
    if b.get("kind") in (None, "reels only"):
        return f"{int(b['n'])} reels"
    return f"{int(b['n'])} posts, all types" + (", not re-checked" if "not re-checked" in str(b.get("source") or "") else "")


def exact_x(reel) -> float | None:
    """plays / the creator's own median plays, unrounded, so every page prints the same x.
    reel["_baseline"] is the creator's baseline (load_swipe_reel adds it); without it the
    stored x is used."""
    plays = ((reel or {}).get("counts") or {}).get("plays")
    median = ((((reel or {}).get("_baseline") or {}).get("median")) or {}).get("plays")
    if _finite(plays) and _finite(median) and median > 0:
        return plays / median
    x = ((reel or {}).get("x") or {}).get("plays")
    return x if _finite(x) else None


def as_of_text(counts) -> str:
    """'as of <date>', or 'file date <date> (pull date unknown)' when the pull date was never recorded."""
    counts = counts or {}
    if not counts.get("as_of"):
        return "as of: unknown"
    day = str(counts["as_of"])[:10]
    if str(counts.get("as_of_note") or "").startswith("pull date unknown"):
        return f"file date {day} (pull date unknown)"
    return f"as of {day}"


# Counts-layer flags in strip order. None of them names the predicted response.
STRIP_FLAGS = (("thin_baseline", "thin baseline"), ("paid", "paid"), ("gated_cta", "gated call to action"),
               ("fresh", "fresh when pulled, counts not settled"), ("under_2x", "under 2x: taste, not proof"))


def counts_strip(reel) -> dict | None:
    """The public counts for a reel in the swipe file, as one strip that sits above the card."""
    if not isinstance(reel, dict):
        return None
    counts = reel.get("counts") or {}
    facts = reel.get("facts") or {}
    flags = reel.get("flags") or {}
    parts = []
    if isinstance(reel.get("owner"), str) and reel["owner"].strip():
        parts.append("@" + reel["owner"].strip().lstrip("@"))
    if _finite(facts.get("duration_s")):
        parts.append(fmt_clock(int(facts["duration_s"])))
    if _finite(counts.get("plays")):
        parts.append(f"{int(counts['plays']):,} plays")
    x = exact_x(reel)
    if x is not None:
        size = baseline_label(reel.get("_baseline"))
        parts.append(f"{x:.1f}x own median" + (f" ({size})" if size else ""))
    for key, word in STRIP_FLAGS:
        if flags.get(key) is True:
            parts.append(word + (", guessed from comments" if key == "gated_cta" and cta_inferred(reel) else ""))
    if reel.get("discount"):
        parts.append("discounted")
    parts.append(as_of_text(counts))
    return {"text": " · ".join(parts), "shortcode": reel.get("shortcode")}


def build_card(report, notes, events, segments, swipe_reel=None) -> dict:
    """The snippet card: HOOK, HIGH, FLAT, TRY, TRY with a TRIBE run (report.json), or HOOK,
    BEATS, PACE, TRY, TRY without one (report is None). Returns lines, the footnote and,
    when the reel is in the swipe file, the counts strip. Raises RenderError when the
    notes hold fewer than 2 ideas that fit the card."""
    tribe = isinstance(report, dict)
    if tribe:
        last_sec = last_second(report)
    else:
        d = ((swipe_reel or {}).get("facts") or {}).get("duration_s")
        last_sec = max(0, math.ceil(d - 1e-6) - 1) if _finite(d) else 3599
    lines = [_hook_line(report, events, swipe_reel, last_sec)]
    peak = flat = None
    skip_flat = False
    if tribe:
        peak, flat = top_peak(report), preferred_flat(report)
        high = _high_line(report, peak, last_sec)
        if high.get("time") and high["time"] == lines[0].get("time"):
            # The peak is the first word's own second: each time appears once, so the HIGH line
            # drops its chip and says so in words (no quote, which would repeat the chip's second).
            base = f"{_lines_phrase(peak.get('driving_lines'))} high for this reel"
            high = {"tag": "HIGH", "time": None, "t": peak["t"], "text": base + " · same second as the first word"}
        lines += [high, _flat_line(report, flat, last_sec)]
        # An edge flat stretch that holds the reel's call to action is no "trailing off".
        cta_t = ((((swipe_reel or {}).get("facts") or {}).get("cta")) or {}).get("t")
        skip_flat = bool(flat and flat.get("edge") and _finite(cta_t)
                         and flat["start"] <= cta_t < flat.get("end", flat["start"] + 1))
    else:
        lines += [_beats_line(swipe_reel), _pace_line(swipe_reel, last_sec)]
    used = {c for ln in lines for c in CHIP_RE.findall(card_line_text(ln))}
    lines += _try_lines(notes, peak, flat, used, skip_flat)
    return {"mode": "tribe" if tribe else "facts", "counts": counts_strip(swipe_reel), "lines": lines,
            "footnote": CARD_FOOTNOTE if tribe else None}


def card_texts(card: dict) -> list[tuple[str, str]]:
    out = [(f"card {ln.get('tag')}", card_line_text(ln)) for ln in card.get("lines") or [] if isinstance(ln, dict)]
    if card.get("footnote"):
        out.append(("card footnote", card["footnote"]))
    if isinstance(card.get("counts"), dict):
        out.append(("counts strip", str(card["counts"].get("text") or "")))
    return out


def shortcode_of(url: str) -> str | None:
    m = IG_CODE_RE.search(url or "")
    return m.group(1) if m else None


def load_swipe_reel(source_url: str, swipe_root, log=print) -> dict | None:
    """swipe/reels/<shortcode>/reel.json for this job's source URL, if the reel is in the swipe file."""
    sc = shortcode_of(source_url)
    if not sc or swipe_root is None:
        return None
    path = Path(swipe_root) / "reels" / sc / "reel.json"
    if not path.is_file():
        return None
    try:
        reel = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log(f"Note: {path} could not be read, so no counts strip.")
        return None
    if not isinstance(reel, dict):
        return None
    reel = dict(reel)
    owner = str(reel.get("owner") or "").lstrip("@")
    if _HANDLE_RE.match(owner):
        creator = Path(swipe_root) / "creators" / f"{owner}.json"
        try:
            b = (json.loads(creator.read_text(encoding="utf-8")) or {}).get("baseline")
            if isinstance(b, dict):
                reel["_baseline"] = b   # for the one shared x and its baseline label
        except (OSError, ValueError, AttributeError):
            pass
    return reel


def swipe_beats(reel) -> list[dict]:
    out = []
    for b in ((reel or {}).get("shape") or {}).get("beats") or []:
        if isinstance(b, dict) and b.get("status") in SHAPE_SHOWN and _finite(b.get("start")) and _finite(b.get("end")):
            out.append({k: b.get(k) for k in ("start", "end", "kind", "name", "status")})
    return out


def authored_texts(template: str, report: dict, notes: dict) -> list[tuple[str, str]]:
    """Every piece of text we wrote that ends up on the page, with where it came from.
    The transcript (words, word-hit phrases, stretched words) and the source owner/URL are not ours."""
    out = [("template.html", template)]
    for key in ("label", "framing", "offset", "purpose"):
        if isinstance(report.get(key), str):
            out.append((f"report.{key}", report[key]))
    scale = report.get("scale") or {}
    if isinstance(scale.get("label"), str):
        out.append(("report.scale.label", scale["label"]))
    clip = report.get("clip") or {}
    if isinstance(clip.get("language"), str):
        out.append(("report.clip.language", clip["language"]))
    for w in report.get("warnings") or []:
        if isinstance(w, dict):
            out.append((f"report.warnings[{w.get('code')}]", str(w.get("text") or "")))
        else:
            out.append(("report.warnings", str(w)))
    for k, line in (report.get("lines") or {}).items():
        if isinstance(line, dict):
            for f in ("label", "trend"):
                if isinstance(line.get(f), str):
                    out.append((f"report.lines.{k}.{f}", line[f]))
    combined = report.get("combined") or {}
    if isinstance(combined.get("note"), str):
        out.append(("report.combined.note", combined["note"]))
    src = report.get("source") or {}
    if isinstance(src.get("fetched_via"), str):
        out.append(("report.source.fetched_via", src["fetched_via"]))
    if isinstance(notes.get("scale_label"), str):
        out.append(("notes.scale_label", notes["scale_label"]))
    for n in notes.get("notes") or []:
        if isinstance(n, dict):
            nid = n.get("id")
            out.append((f"note {nid}.text", str(n.get("text") or "")))
            if n.get("idea_to_test"):
                out.append((f"note {nid}.idea_to_test", str(n["idea_to_test"])))
    return out


def check_banned(texts: list[tuple[str, str]], emotions: bool = True) -> None:
    found = []
    for where, text in texts:
        hits = find_banned(text, emotions)
        if hits:
            found.append(f"{where}: {sorted(set(hits))}")
    if found:
        raise RenderError("banned words in our text: " + "; ".join(found))


def check_authored(texts: list[tuple[str, str]]) -> None:
    """Every rule check for text we wrote: banned words, the counts/brain wall, cause words, pronouns."""
    check_banned(texts)
    check_mixed_layers(texts)
    check_cause(texts)
    check_pronouns(texts)


# ---------------------------------------------------------------- assets

def _merged_source(report: dict, source: dict | None) -> dict:
    a = dict(source or {})
    b = report.get("source") or {}
    merged = {}
    for k in ("local_path", "source_url", "owner", "fetched_via", "sha256", "label"):
        merged[k] = b.get(k) or a.get(k) or ""
    return merged


def _ffmpeg_frame(video: Path, t: float) -> bytes | None:
    cmd = [
        "ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(0.0, t):.3f}", "-i", str(video),
        "-frames:v", "1", "-vf", "scale=240:-2", "-q:v", "5",
        "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not r.stdout.startswith(b"\xff\xd8"):
        return None
    return r.stdout


def make_thumbs(report: dict, video: Path | None, log) -> dict:
    """Small JPEG frames at each peak and each flat-stretch midpoint, as data URIs."""
    if video is None:
        return {}
    if not shutil.which("ffmpeg"):
        log("Note: ffmpeg not on PATH, so no frame thumbnails.")
        return {}
    seconds = (report.get("clip") or {}).get("seconds")
    limit = float(seconds) - 0.1 if _finite(seconds) and seconds > 0.2 else None
    wanted = {}
    for p in report.get("peaks") or []:
        wanted[f"peak:{p['t']}"] = p["t"] + 0.5
    for f in report.get("flat_stretches") or []:
        wanted[f"flat:{f['start']}-{f['end']}"] = (f["start"] + f["end"]) / 2
    thumbs = {}
    for key, t in wanted.items():
        if limit is not None:
            t = min(t, limit)
        jpg = _ffmpeg_frame(video, t)
        if jpg:
            thumbs[key] = "data:image/jpeg;base64," + base64.b64encode(jpg).decode("ascii")
        else:
            log(f"Note: no thumbnail for {key} (ffmpeg could not read a frame).")
    return thumbs


def brain_image(report: dict, output_dir: Path, log) -> str | None:
    bp = report.get("brain_picture")
    if not isinstance(bp, dict) or not bp.get("path"):
        return None
    p = (output_dir / str(bp["path"])).resolve()
    if p.parent != output_dir.resolve():
        log(f"Note: brain picture path {bp['path']!r} is outside the output folder, skipped.")
        return None
    if not p.exists():
        log(f"Note: brain picture {p.name} not found, the popup is left out.")
        return None
    data = p.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        log(f"Note: {p.name} is not a PNG, the popup is left out.")
        return None
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def no_video_info(report: dict, src: dict, missing_path: str | None) -> dict:
    url = src.get("source_url") or ""
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = ""
    if missing_path:
        return {"text": "Video file not found on this laptop:", "path": missing_path, "url": ""}
    if report.get("purpose") == "test" and url:
        return {"text": "Video not kept on this laptop (another creator's reel). Open the original:", "url": url, "path": ""}
    if url:
        return {"text": "Video not kept on this laptop. Open the original:", "url": url, "path": ""}
    return {"text": "Video not kept on this laptop.", "url": "", "path": ""}


# ---------------------------------------------------------------- page

def to_script_json(obj, what: str) -> str:
    """JSON safe to sit inside <script type="application/json">."""
    try:
        s = json.dumps(obj, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    except ValueError as e:
        raise RenderError(f"{what} contains NaN or infinity, which the page cannot read") from e
    return s.replace("</", "<\\/").replace("<!--", "<\\u0021--")


def slugify(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", text or "").strip("-.")
    return s[:80] or "reel"


def report_folder(reports_root: Path, report: dict, today: dt.date) -> Path:
    """reports/<date>-<label>/ for this job. A re-render reuses the folder that already holds
    this job's page (the newest one), so the swipe card's link never points at a stale copy."""
    slug = slugify(report.get("label") or report.get("job_id"))
    job = report.get("job_id")
    found = []
    for p in Path(reports_root).glob(f"*-{slug}/report.html"):
        try:
            if job and f'"job_id":"{job}"' in p.read_text(encoding="utf-8"):
                found.append(p.parent)
        except OSError:
            continue
    if found:
        return max(found, key=lambda d: (d / "report.html").stat().st_mtime)
    return Path(reports_root) / f"{today.isoformat()}-{slug}"


def render(output_dir, reports_root=None, today: dt.date | None = None, open_browser: bool = False, log=print,
           swipe_root=None) -> Path:
    """Build the page. Returns the written report.html path. Raises RenderError when refused.
    swipe_root defaults to <project>/swipe; the counts strip shows when the job's reel is in it."""
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        raise RenderError(f"output folder not found: {output_dir}")
    report = _load_json(output_dir / "report.json", "report.json")
    predict_meta = _load_json(output_dir / "predict_meta.json", "predict_meta.json", required=False)
    validate_report(report, predict_meta)
    notes = _load_json(output_dir / "notes.json", "notes.json", required=False)
    validate_notes(notes, report)
    segments = _load_json(output_dir / "segments.json", "segments.json", required=False) or []
    flags = _load_json(output_dir / "flags.json", "flags.json", required=False) or {}
    source = _load_json(output_dir / "source.json", "source.json", required=False) or {}
    events = _load_json(output_dir / "events.json", "events.json", required=False)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    for slot in JSON_SLOTS:
        n = template.count(f"__{slot}_JSON__")
        if n != 1:
            raise RenderError(f"template.html must contain __{slot}_JSON__ exactly once (found {n})")

    src = _merged_source(report, source)
    swipe_reel = load_swipe_reel(src.get("source_url"), DEFAULT_SWIPE_ROOT if swipe_root is None else swipe_root, log)
    card = build_card(report, notes, events, segments, swipe_reel)
    validate_card(card)
    beats = swipe_beats(swipe_reel)
    texts = authored_texts(template, report, notes) + card_texts(card)
    texts += [(f"beat {b.get('kind')}", f"{b.get('kind') or ''} {b.get('name') or ''}") for b in beats]
    check_authored(texts)

    video_path = None
    missing = None
    if src.get("local_path"):
        p = Path(src["local_path"])
        if p.is_file():
            video_path = p.resolve()
        else:
            missing = str(p)
    today = today or dt.date.today()
    reports_root = Path(reports_root) if reports_root else DEFAULT_REPORTS_ROOT
    folder = report_folder(reports_root, report, today)
    swipe_href = None
    if swipe_reel and swipe_reel.get("shortcode"):
        card_page = reports_root / "swipe" / "reels" / f"{swipe_reel['shortcode']}.html"
        if card_page.is_file():
            swipe_href = Path(os.path.relpath(card_page, folder)).as_posix()
    page = {
        "rendered": today.isoformat(),
        # Another creator's reel: the page quotes their words, so it is never shared.
        "private": bool(swipe_reel) or report.get("purpose") == "test",
        "swipe_href": swipe_href,
        "video_uri": video_path.as_uri() if video_path else None,
        "video_path": str(video_path) if video_path else "",
        "no_video": None if video_path else no_video_info(report, src, missing),
        "thumbs": make_thumbs(report, video_path, log),
        "brain_img": brain_image(report, output_dir, log),
        "card": card,
        "beats": beats,
    }
    source_public = {k: src.get(k, "") for k in ("label", "owner", "source_url", "fetched_via", "sha256")}
    payload = {
        "REPORT": to_script_json(report, "report.json"),
        "NOTES": to_script_json(notes, "notes.json"),
        "SEGMENTS": to_script_json(segments, "segments.json"),
        "FLAGS": to_script_json(flags, "flags.json"),
        "SOURCE": to_script_json(source_public, "source.json"),
        "PAGE": to_script_json(page, "page data"),
    }
    html_out = SLOT_RE.sub(lambda m: payload[m.group(1)], template)

    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "report.html"
    out.write_text(html_out, encoding="utf-8")
    if open_browser:
        webbrowser.open(out.resolve().as_uri())
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render the offline predicted response report for one output folder.")
    ap.add_argument("output_dir", help="outputs/<job_id> folder with report.json and notes.json")
    ap.add_argument("--no-open", action="store_true", help="do not open the page in the browser")
    ap.add_argument("--reports-dir", default=None, help="where to write reports/<date>-<label>/ (default: <project>/reports)")
    ap.add_argument("--swipe-dir", default=None, help="swipe file for the counts strip (default: <project>/swipe)")
    args = ap.parse_args(argv)
    try:
        out = render(args.output_dir, reports_root=args.reports_dir, open_browser=not args.no_open, swipe_root=args.swipe_dir)
    except RenderError as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
