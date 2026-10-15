r"""Swipe pages: the board, one card per reel, the patterns page and one script lab page per draft.

Usage (from the Tribe folder):
    python -m strategist.render all | board | reel <sc> | patterns | lab <draft_id> [--open]

Writes offline pages (one self-contained HTML each: inline CSS, SVG and JS, JSON
inlined, nothing loaded from the network, works over file://):
    reports/swipe/index.html          the board: every swipe reel, public counts and shape only
    reports/swipe/reels/<sc>.html     one reel: counts strip, snippet card, then folds
    reports/swipe/patterns.html       hooks, structures, CTAs, formats, each with its contrast
    reports/swipe/lab/<id>.html       one draft: beats, numbered margin notes, unordered variants,
                                      length, check badges, PROOF rows
reports/ is in .gitignore. A reel card quotes a few of the creator's words (the
HIGH quote, word hits) and shows the private stills from swipe/reels/<sc>/private/
by file path: the page itself holds no still and no transcript. It is still a
private page, never shared or published. Keep the project outside any cloud-synced
folder, so "private" means it stays on the laptop.

Every string we wrote goes through the dashboard/render.py rule checks before a page
is written (banned words, the counts/brain wall, cause words, pronouns, the card
contract, the sort-key guard). A violation refuses the page and says why. The
creator's own words (transcript, word-hit phrases) are not ours and are exempt, as
on the report page.

The card comes from dashboard/render.py build_card: HOOK, HIGH, FLAT, TRY, TRY when
a TRIBE job is linked (report.json of that job), else HOOK, BEATS, PACE, TRY, TRY.
TRY lines are Claude's notes on the linked run when they fit, else "Test:" ideas
built from this reel's shape and facts (never from its counts).

Building and writing are split: each page has build_<page>_page(..., hosted=False)
returning (page, texts), the page dict and every string we wrote on it, and
render_<page> passes those to write_page. hosted=True builds the copy that may leave
the laptop (D25), which strategist/hosted.py projects field by field into
strategist/hosted_schema/: no stills, transcript, word hits, HIGH quote, copy-check
runs, links to local pages or file paths, and on a reel card only the TRIBE notes the
caller's keep_note passes (none without one), so the card falls back to fact_ideas.

Exit codes: 0 ok, 2 refused. Standard library only.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import os
import re
import sys
import urllib.parse
import webbrowser
from pathlib import Path

from . import shapes, store

R = store.rules()   # dashboard/render.py: the shared rule checks and the card builder
RenderError = R.RenderError

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
SLOT = "__PAGE_JSON__"
JOB_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{8}$")
STILL_RE = re.compile(r"^\d+-([a-z]+)-(\d+(?:\.\d+)?)s\.jpg$")
STILL_ROLES = {"open": "open", "early": "early", "mid": "middle", "cta": "call to action",
               "peak": "near the TRIBE top peak second"}
STILL_NEAR_S = 2.5     # a card time chip opens a still taken this close to it
MAX_STILLS = 4
VIDEO_PATH_RE = re.compile(r"\.(?:mp4|mov|m4v|webm|mkv|avi|wav|m4a|mp3)\b", re.IGNORECASE)
# Board sorts as (key, label). Every key passes R.check_sort_key: counts, dates, length
# and handle only, never a TRIBE field. The board shows no rank numbers.
SORTS = (("-x", "x vs own median, largest first"), ("-plays", "plays, most first"),
         ("-posted", "posted, newest first"), ("-duration", "length, longest first"),
         ("handle", "handle, A to Z"))
DEFAULT_SORT = "-x"
FLAG_LABELS = (("thin_baseline", "thin baseline"), ("paid", "paid partnership"), ("gated_cta", "gated CTA"),
               ("discounted", "discounted"), ("under_2x", "under 2x · taste, not proof"),
               ("fresh", "fresh when pulled: counts still settling"), ("over_60s", "over 60 s"))
LENGTHS = ("under 30 s", "30-60 s", "over 60 s")   # over 60 s: more than store.OVER_S
LEFT_OUT = (("pinned", "pinned"), ("paid", "paid"), ("fresh", "under 48 h"), ("target", "the swipe reel itself"),
            ("not_reel", "not a reel"))
PRIVATE_NOTE = ("Private here means it stays on this laptop (keep the project outside cloud-synced folders): "
                "never shared, uploaded or published.")
# Always-valid fallbacks, so a reel with almost no facts still gets two TRY lines.
GENERIC_IDEAS = ("Test: in your draft, say the main point in the first sentence.",
                 "Test: read your draft aloud once and cut every line you trip over.")
# The hosted copy (hosted=True): the HIGH line keeps its place and says where the quote is.
HIGH_QUOTE = ' · said: "'
HOSTED_QUOTE = " · quote stays on the laptop"
HOSTED_BY = "strategist.hosted"
# A file or folder path in a source note ("VAULT research/raw/ig-x.json"): left out of the hosted copy.
PATH_TOKEN_RE = re.compile(r"(?:[A-Za-z]:)?[\w.~-]*(?:[/\\][\w.~-]+)+[/\\]?"
                           r"|[\w.~-]+\.(?:jsonl?|txt|md|csv|tsv|npy|npz|png|jpe?g|srt|html?|mp4|mov|m4v|webm|mkv|"
                           r"avi|wav|m4a|mp3)\b", re.IGNORECASE)


def strip_paths(text: str) -> str:
    """text without file or folder paths (and what's left of their brackets), for the hosted copy."""
    out = PATH_TOKEN_RE.sub("", str(text or ""))
    out = re.sub(r"\(\s*\)", "", out)
    return re.sub(r"\s+([,.;:)])", r"\1", re.sub(r"\s{2,}", " ", out)).strip(" ,;:")


# ---------------------------------------------------------------- small helpers

def reports_root(root=None) -> Path:
    return Path(root) if root else store.PROJECT_ROOT / "reports"


def pages_dir(root=None) -> Path:
    return reports_root(root) / "swipe"


def _finite(v) -> bool:
    return R._finite(v)


def fmt_int(v) -> str:
    return f"{int(round(v)):,}" if _finite(v) else "?"


def fmt_x(v) -> str:
    return f"{v:.1f}x" if _finite(v) else "no x yet"


def clock(s) -> str:
    return R.fmt_clock(max(0, int(math.floor(s + 1e-6)))) if _finite(s) else "?"


def day(iso) -> str:
    return str(iso)[:10] if iso else "unknown"


def cta_label(kind) -> str:
    s = re.sub(r"[-_\s]+", " ", str(kind or "")).strip()
    return re.sub(r"(?i)\bdm\b", "DM", s)


def shape_label(shape, field) -> tuple[str, str] | None:
    """(label, status) of one shape field that is suggested or accepted (rejected ones are hidden)."""
    v = (shape or {}).get(field)
    if not isinstance(v, dict) or v.get("status") not in R.SHAPE_SHOWN:
        return None
    raw = v.get("id") if field == "hook_shape" else v.get("value")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return (cta_label(raw) if field == "cta" else R._shape_label(raw)), v["status"]


def labelled(shape, field) -> str | None:
    got = shape_label(shape, field)
    return got[0] + ("" if got[1] == "accepted" else " (suggested)") if got else None


def baseline_size(creator) -> str:
    return R.baseline_label((creator or {}).get("baseline"))


def load_creator(handle) -> dict | None:
    try:
        return store.load_creator(handle)
    except store.StoreError:
        return None


def with_baseline(reel, creator) -> dict:
    """A shallow copy carrying the creator's baseline, for the one shared x (dashboard/render.py exact_x)."""
    return dict(reel, _baseline=(creator or {}).get("baseline"))


def exact_x(reel, creator):
    """plays / the creator's own median plays, unrounded (reel.json keeps 2 decimals). Every
    page, the TRIBE report page included, prints this same value."""
    return R.exact_x(with_baseline(reel, creator))


def display_reel(reel, creator) -> dict:
    """A copy for display: the creator's baseline (for x and its label), the CTA type in words."""
    shown = copy.deepcopy(reel)
    shown["_baseline"] = (creator or {}).get("baseline")
    cta = (shown.get("facts") or {}).get("cta")
    if isinstance(cta, dict) and cta.get("type"):
        cta["type"] = cta_label(cta["type"])
    return shown


def counts_strip(reel, creator) -> dict | None:
    return R.counts_strip(display_reel(reel, creator))


def write_page(template_name: str, page: dict, texts: list[tuple[str, str]], out: Path) -> Path:
    """Check every authored string, fill the template's one JSON slot, write the page."""
    template = (TEMPLATES / template_name).read_text(encoding="utf-8")
    if template.count(SLOT) != 1:
        raise RenderError(f"{template_name} must contain {SLOT} exactly once")
    R.check_authored([(template_name, template)] + texts)
    html = template.replace(SLOT, R.to_script_json(page, "page data"))
    hit = VIDEO_PATH_RE.search(html)
    if hit:
        raise RenderError(f"a video or audio path would end up on the page ({hit.group(0)!r}): links, numbers and shapes only")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8", newline="\n")
    return out


# ---------------------------------------------------------------- reel card

def fact_ideas(reel) -> list[str]:
    """'Test:' ideas for his draft from this reel's shape and facts, never its counts.
    The card keeps the first two that pass every card check."""
    facts = reel.get("facts") or {}
    shape = reel.get("shape") or {}
    out = []
    hook = shape_label(shape, "hook_shape")
    if hook:
        out.append(f"Test: open your draft with the same hook shape ({hook[0]}), in your own words.")
    beats = [b for b in shape.get("beats") or []
             if isinstance(b, dict) and b.get("status") in R.SHAPE_SHOWN and b.get("name")]
    # This reel's own middle beat (demo, else proof, else the longest), so each card's ideas differ.
    middle = [b for b in beats if b.get("kind") not in ("hook", "cta")
              and _finite(b.get("start")) and _finite(b.get("end")) and b["end"] > b["start"]]
    pick = next((b for kind in ("demo", "proof") for b in middle if b.get("kind") == kind), None)
    pick = pick or max(middle, key=lambda b: b["end"] - b["start"], default=None)
    if pick and round(pick["end"] - pick["start"]) >= 1:
        out.append(f"Test: in your draft, give the {pick['kind']} beat about {round(pick['end'] - pick['start'])} "
                   f"seconds, like this reel's {pick['name']}.")
    if len(beats) >= 2:
        out.append("Test: map your draft onto the same beats: " + " → ".join(str(b["name"]) for b in beats) + ".")
        out.append("Test: map your draft onto the same beat order: " + " → ".join(shapes.structure_kinds(beats)) + ".")
    cta = shape_label(shape, "cta")
    cta = cta[0] if cta else cta_label(((facts.get("cta") or {}).get("type")))
    if cta and cta.lower() in ("none", "no cta", "no call to action", "no ask"):
        out.append("Test: try your draft both with no call to action and with one short one at the end.")
    elif cta:
        out.append(f"Test: end your draft on one call to action ({cta}) and nothing after it.")
    fw = facts.get("first_word_s")
    if _finite(fw):
        out.append("Test: in your draft, say the first word inside the first second, with no silent intro." if fw < 1
                   else "Test: in your draft, try two openings: talking from the first second, and a silent visual open.")
    if facts.get("text_on_screen_0s") is True:
        out.append("Test: put one short line of text on screen in the first second of your draft.")
    if _finite(facts.get("words_per_s")):
        out.append(f"Test: read your draft aloud at about {round(facts['words_per_s'])} words a second and time it.")
    if _finite(facts.get("duration_s")):
        out.append(f"Test: keep your draft to about {round(facts['duration_s'])} seconds read aloud.")
    return out + list(GENERIC_IDEAS)


def tribe_context(reel) -> dict | None:
    """The linked TRIBE job (report, notes, events), checked like the report page checks it.
    Mock output is refused. A link whose job folder is gone is kept as missing."""
    link = reel.get("tribe")
    if not isinstance(link, dict) or not link.get("job_id"):
        return None
    job = str(link["job_id"])
    if not JOB_RE.match(job):
        raise RenderError(f"reel {reel.get('shortcode')} links a bad TRIBE job id {job!r}")
    d = store.OUTPUTS / job
    ctx = {"job_id": job, "run_date": link.get("run_date") or f"{job[:4]}-{job[4:6]}-{job[6:8]}", "missing": True}
    report = R._load_json(d / "report.json", f"{job} report.json", required=False)
    if report is None:
        return ctx
    R.validate_report(report, R._load_json(d / "predict_meta.json", f"{job} predict_meta.json", required=False))
    notes = R._load_json(d / "notes.json", f"{job} notes.json", required=False)
    if notes is not None:
        R.validate_notes(notes, report)
    ctx.update(missing=False, report=report, notes=notes,
               events=R._load_json(d / "events.json", f"{job} events.json", required=False))
    return ctx


def hosted_tribe(tribe, keep_note=None) -> dict | None:
    """A copy of the TRIBE context for the hosted card: only the notes keep_note passes
    (none when there is no keep_note), so the card falls back to fact_ideas."""
    if not tribe or tribe["missing"]:
        return tribe
    notes = tribe.get("notes")
    if isinstance(notes, dict):
        kept = [n for n in notes.get("notes") or [] if isinstance(n, dict) and keep_note and keep_note(n)]
        notes = dict(notes, notes=kept)
    return dict(tribe, notes=notes)


def hosted_high(card: dict) -> dict:
    """The HIGH line without the creator's words: '... · quote stays on the laptop' where the quote was."""
    for ln in card.get("lines") or []:
        text = ln.get("text") if isinstance(ln, dict) else None
        if isinstance(text, str) and ln.get("tag") == "HIGH" and HIGH_QUOTE in text:
            ln["text"] = text[:text.index(HIGH_QUOTE)] + HOSTED_QUOTE
    return card


def build_reel_card(reel, creator, tribe, hosted: bool = False) -> dict:
    shown = display_reel(reel, creator)
    ideas = fact_ideas(reel)
    if tribe and not tribe["missing"]:
        notes = [n for n in ((tribe.get("notes") or {}).get("notes") or []) if isinstance(n, dict)]
        card = R.build_card(tribe["report"], notes + ideas, tribe.get("events"), None, shown)
    else:
        card = R.build_card(None, ideas, None, None, shown)
    if hosted:
        hosted_high(card)
    card["counts"] = counts_strip(reel, creator)
    R.validate_card(card)
    return card


def last_sec_of(reel, tribe) -> int:
    if tribe and not tribe["missing"]:
        return R.last_second(tribe["report"])
    d = (reel.get("facts") or {}).get("duration_s")
    return max(0, math.ceil(d - 1e-6) - 1) if _finite(d) else 3599


def chip_bounds(chip: str) -> tuple[int, int]:
    def secs(c):
        m, s = c.split(":")
        return int(m) * 60 + int(s)
    a, _, b = chip.partition("-")
    return secs(a), secs(b or a)


def still_src(path: Path, page_dir: Path) -> str:
    """A link to a private still, relative to the page. The page holds no copy of it, so the
    HTML file alone carries none of the creator's frames (shared alone, it shows no stills)."""
    try:
        rel = Path(os.path.relpath(path, page_dir)).as_posix()
    except ValueError:   # another drive on Windows
        return path.resolve().as_uri()
    return urllib.parse.quote(rel, safe="/._-")


def load_stills(sc, last_sec, page_dir: Path) -> list[dict]:
    """At most 4 private stills (jpg only) linked by file path, each with a time chip and a role."""
    d = store.private_dir(sc) / "stills"
    out = []
    for p in sorted(d.glob("*.jpg")) if d.is_dir() else []:
        with open(p, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                continue
        m = STILL_RE.match(p.name)
        t = float(m.group(2)) if m else None
        out.append({"src": still_src(p, page_dir), "t": t,
                    "chip": R.page_range(t, t + 1e-3, last_sec) if t is not None else None,
                    "caption": STILL_ROLES.get(m.group(1), m.group(1)) if m else "still"})
        if len(out) == MAX_STILLS:
            break
    return sorted(out, key=lambda s: s["t"] if s["t"] is not None else math.inf)


def link_chips_to_stills(card, stills) -> None:
    """A card time chip opens the still taken nearest to it (within 2.5 s), when there is one."""
    timed = [(i, s["t"]) for i, s in enumerate(stills) if _finite(s.get("t"))]
    for ln in card["lines"]:
        ln["still"] = None
        if not ln.get("time") or not timed:
            continue
        a, b = chip_bounds(ln["time"])
        dist = [(max(a - t, t - (b + 1), 0), i) for i, t in timed]
        best = min(dist)
        if best[0] <= STILL_NEAR_S:
            ln["still"] = best[1]


def hit_items(report, last_sec) -> list[dict]:
    out = []
    for h in sorted((h for h in report.get("word_hits") or [] if isinstance(h, dict)), key=lambda h: h.get("start") or 0):
        if _finite(h.get("start")) and _finite(h.get("end")) and str(h.get("phrase") or "").strip():
            out.append({"chip": R.page_range(h["start"], max(h["end"], h["start"] + 0.01), last_sec),
                        "text": str(h["phrase"]).strip(), "ghost": bool(h.get("ghost_flag"))})
    return out


def tribe_report_href(job: str, page_dir: Path, root=None) -> str | None:
    """Relative link to the TRIBE report page rendered for this job (newest one), if any."""
    found = []
    for p in reports_root(root).glob("*/report.html"):
        if p.parent.name == "swipe":
            continue
        try:
            if f'"job_id":"{job}"' in p.read_text(encoding="utf-8"):
                found.append(p)
        except OSError:
            continue
    if not found:
        return None
    best = max(found, key=lambda p: p.stat().st_mtime)
    return Path(os.path.relpath(best, page_dir)).as_posix()


def shape_counts(reel) -> tuple[int, int]:
    """(accepted, labelled) over hook shape, format, CTA and each beat."""
    shape = reel.get("shape") or {}
    labels = [shape.get(f) for f in ("hook_shape", "format", "cta") if isinstance(shape.get(f), dict)]
    labels += [b for b in shape.get("beats") or [] if isinstance(b, dict)]
    return sum(1 for v in labels if v.get("status") == "accepted"), len(labels)


def recreate_cmd(sc: str) -> str:
    """The same kind of command as the patterns page: /script makes the draft from this reel's shape."""
    return f"/script new from-{sc}"


def stamp_parts(reel, tribe, today, by: str = "strategist.render") -> dict:
    """One freshness stamp per layer (counts, shape, brain) plus the page's own."""
    counts = reel.get("counts") or {}
    src = "VAULT (an earlier Apify pull)" if "VAULT" in str(counts.get("as_of_note") or "") else "Apify"
    accepted, labelled_n = shape_counts(reel)
    return {"counts": f"counts from {src}, {R.as_of_text(counts)}",
            "shape": (f"shape suggested by Claude, accepted by you: {accepted} of {labelled_n} labels" if labelled_n
                      else "shape: not suggested yet"),
            "brain": f"TRIBE run {tribe['run_date']}" if tribe else "no TRIBE run",
            "page": f"page made by {by} on {today}"}


def layer_stamps(reel, tribe, today) -> str:
    return " · ".join(stamp_parts(reel, tribe, today).values())


def fact_rows(reel, tails: bool = True) -> list[list[str]]:
    """[label, value] rows; tails=True adds where each fact came from (a source note that can
    name laptop files, so the hosted copy leaves it out)."""
    facts = reel.get("facts") or {}
    src = facts.get("source") or {}
    cta = facts.get("cta") or {}
    on = facts.get("text_on_screen_0s")

    def tail(key):
        return f" ({src[key]})" if tails and src.get(key) else ""
    rows = [
        ["Length", (clock(facts.get("duration_s")) if _finite(facts.get("duration_s")) else "unknown") + tail("duration_s")],
        ["First word", (f"at {clock(facts['first_word_s'])}" if _finite(facts.get("first_word_s")) else "no speech found")
         + tail("words")],
        ["Pace", (f"about {round(facts['words_per_s'])} words a second" if _finite(facts.get("words_per_s"))
                  else "not measured") + tail("words_per_s")],
        ["Call to action", (cta_label(cta.get("type")) + (f" at about {clock(cta['t'])}" if _finite(cta.get("t")) else
                                                           ", time unknown") if cta.get("type") else "none found")
         + tail("cta")],
        ["Text at 0:00", ("yes" if on is True else "no" if on is False else "unknown") + tail("text_on_screen_0s")],
    ]
    return rows


def reel_page_path(sc: str, root=None) -> Path:
    return pages_dir(root) / "reels" / f"{sc}.html"


def build_reel_page(sc: str, root=None, today: dt.date | None = None, hosted: bool = False,
                    keep_note=None) -> tuple[dict, list[tuple[str, str]]]:
    """The reel card page and the strings we wrote on it. hosted=True: no stills, transcript,
    word hits or report link, fact rows without their source notes, stamps one per layer, the
    HIGH line without its quote and only the TRIBE notes keep_note passes."""
    sc = store.check_shortcode(sc)
    reel = store.load_reel(sc)
    creator = load_creator(reel.get("owner"))
    tribe = tribe_context(reel)
    card = build_reel_card(reel, creator, hosted_tribe(tribe, keep_note) if hosted else tribe, hosted)
    last_sec = last_sec_of(reel, tribe)
    today = (today or dt.date.today()).isoformat()
    out = reel_page_path(sc, root)
    texts = R.card_texts(card)

    if not hosted:
        stills = load_stills(sc, last_sec, out.parent)
        link_chips_to_stills(card, stills)
        for s in stills:
            texts.append((f"still {s['chip']}", s["caption"]))

    beats = [{"chip": R.page_range(b["start"], b["end"], last_sec), "kind": b.get("kind") or "",
              "name": b.get("name") or "", "suggested": b.get("status") != "accepted"} for b in R.swipe_beats(reel)]
    texts += [(f"beat {b['chip']}", f"{b['kind']} {b['name']}") for b in beats]
    if hosted:   # the site has its own Tag shapes button
        beats_empty = (f"No beats tagged yet. Claude suggests them, and you accept them with "
                       f"python -m strategist.reel accept {sc} beats.")
    else:
        beats_empty = (f"No beats tagged yet. Claude suggests them with python -m strategist.reel tag {sc} --from "
                       f"<json>, and you accept them with python -m strategist.reel accept {sc} beats.")

    discount = reel.get("discount") if isinstance(reel.get("discount"), dict) else None
    disc_text = (f"Discounted by hand on {day(discount.get('at'))}: {discount.get('reason')}" if discount else None)
    recreate = recreate_cmd(sc)
    if hosted:
        stamps = stamp_parts(reel, tribe, today, HOSTED_BY)
        facts = fact_rows(reel, tails=False)
        texts.append(("beats empty", beats_empty))
        texts += [(f"stamp {k}", v) for k, v in stamps.items()]
        texts += [(f"fact {k}", f"{k}: {v}") for k, v in facts]
        if disc_text:
            texts.append(("discount", disc_text))
        page = {
            "rendered": today, "shortcode": sc, "owner": reel.get("owner") or "", "url": reel.get("url") or "",
            "posted": day(reel.get("posted")), "card": card, "discount": disc_text, "recreate": recreate,
            "beats": beats, "beats_empty": beats_empty,
            "tribe": ({"job_id": tribe["job_id"], "run_date": tribe["run_date"], "missing": tribe["missing"]}
                      if tribe else None),
            "stamps": stamps, "facts": facts, "local_cmd": f"python -m strategist.render reel {sc} --open",
        }
        return page, texts

    linked = bool(tribe and not tribe["missing"])
    if linked:
        transcript = {"mode": "hits", "items": hit_items(tribe["report"], last_sec),
                      "note": "Phrases said while the predicted language line was high for this reel. "
                              "Coarse timing: one value per second.",
                      "empty": "No word hits in this reel."}
    else:
        # No TRIBE read means no word hits, and the transcript itself never goes into a page.
        has = (store.private_dir(sc) / "transcript.txt").is_file() or bool(store.load_words(sc))
        transcript = {"mode": "hits", "items": [],
                      "note": "Word hits come from a TRIBE deep read, and this reel has none.",
                      "empty": (f"The transcript stays private in swipe/reels/{sc}/private/ and is not copied into this "
                                "page. Scripts borrow the shape, never the words.") if has
                      else "No transcript for this reel yet."}
    texts += [("transcript note", transcript["note"]), ("transcript empty", transcript["empty"])]

    if linked:
        href = tribe_report_href(tribe["job_id"], out.parent, root)
        lanes = {"href": href, "text": f"Open the TRIBE report for job {tribe['job_id']} (lanes, words, all moments)"
                 if href else f"The TRIBE report page for job {tribe['job_id']} is not rendered yet: "
                              f"python dashboard/render.py outputs/{tribe['job_id']}",
                 "note": "Its lanes are on this reel's own scale, never compared with another reel."}
    elif tribe:
        lanes = {"href": None, "text": f"TRIBE job {tribe['job_id']} is linked, but its folder is not on this laptop "
                                       f"(outputs/{tribe['job_id']}).", "note": ""}
    else:
        lanes = {"href": None, "text": "No TRIBE deep read for this reel. It is optional and asks before spending.",
                 "note": ""}
    texts += [("lanes", lanes["text"]), ("lanes note", lanes["note"])]

    about = {
        "framing": ("Predicted average-brain response: an average brain, not the creator's audience and not yours."
                    if linked else None),
        "lines": [
            "HOOK uses facts and the hook shape only. "
            + ("HIGH and FLAT are high or low for this reel only, against its own average, and not tested against "
               "any retention graph." if linked else "BEATS and PACE come from Claude's shape tags and the timed transcript."),
            "TRY lines are things to test in your draft, not fixes: Claude's notes on the TRIBE run when they fit, "
            "else built from this reel's shape and facts, never from its counts.",
            R.WALL_SENTENCE,
            "Private page: never share, upload or publish this file. It quotes a few of the creator's words, and its "
            f"stills load from swipe/reels/{sc}/private/stills/ (the page itself holds no copy). " + PRIVATE_NOTE,
        ],
        "stamps": layer_stamps(reel, tribe, today),
        "facts": fact_rows(reel),
    }
    if about["framing"]:
        texts.append(("about framing", about["framing"]))
    texts += [(f"about {i}", t) for i, t in enumerate(about["lines"])]
    texts.append(("about stamps", about["stamps"]))
    texts += [(f"fact {k}", f"{k}: {v}") for k, v in about["facts"]]

    if disc_text:
        texts.append(("discount", disc_text))
    page = {
        "rendered": today, "shortcode": sc, "owner": reel.get("owner") or "", "url": reel.get("url") or "",
        "posted": day(reel.get("posted")), "board_href": "../index.html",
        "card": card, "discount": disc_text, "recreate": recreate,
        "beats": beats, "beats_empty": beats_empty, "transcript": transcript, "stills": stills,
        "lanes": lanes, "about": about,
    }
    return page, texts


def render_reel(sc: str, root=None, today: dt.date | None = None, log=print) -> Path:
    """reports/swipe/reels/<sc>.html. Raises RenderError when refused."""
    page, texts = build_reel_page(sc, root, today)
    return write_page("card.html", page, texts, reel_page_path(page["shortcode"], root))


# ---------------------------------------------------------------- board

def length_bucket(d) -> str:
    if not _finite(d):
        return "unknown"
    return LENGTHS[0] if d < 30 else LENGTHS[1] if d <= store.OVER_S else LENGTHS[2]


def peer_bar(reel, creator) -> dict | None:
    """Where this reel's plays sit among the creator's own baseline reels, on a log scale."""
    plays = (reel.get("counts") or {}).get("plays")
    median = (((creator or {}).get("baseline") or {}).get("median") or {}).get("plays")
    if not (_finite(plays) and plays > 0 and _finite(median) and median > 0):
        return None
    peers = sorted(r["plays"] for r in store.baseline_reels(creator["handle"]) if _finite(r.get("plays")) and r["plays"] > 0)
    vals = peers + [plays, median]
    lo, hi = min(vals) / 1.25, max(vals) * 1.25
    if hi / lo < 4:
        lo, hi = lo / 2, hi * 2
    span = math.log(hi) - math.log(lo)

    def pos(v):
        return round((math.log(v) - math.log(lo)) / span, 4)
    own = f"short ticks: {len(peers)} own reels" if peers else "no reel list kept"
    # The legend sits once in the board's About fold; this caption is the strip's screen-reader label.
    return {"ticks": [pos(v) for v in peers], "median": pos(median), "me": pos(plays),
            "caption": f"dot: this reel · tall tick: own median · {own} · log scale"}


def flag_label(reel, key: str) -> str:
    """A board flag's words; a keyword gate guessed from repeated comments says so."""
    label = dict(FLAG_LABELS)[key]
    return label + ", guessed from comments" if key == "gated_cta" and R.cta_inferred(reel) else label


def board_reel(reel, creator) -> dict:
    counts = reel.get("counts") or {}
    facts = reel.get("facts") or {}
    shape = reel.get("shape") or {}
    x = exact_x(reel, creator)
    flags = [k for k, _ in FLAG_LABELS if (reel.get("flags") or {}).get(k) is True]
    if reel.get("discount"):
        flags.append("discounted")
    hook, fmt = shape_label(shape, "hook_shape"), shape_label(shape, "format")
    cta = labelled(shape, "cta") or (cta_label((facts.get("cta") or {}).get("type")) or "none found")
    size = baseline_size(creator)
    posted = reel.get("posted")
    pt = store.parse_time(posted)
    discount = reel.get("discount") if isinstance(reel.get("discount"), dict) else None
    return {
        "sc": reel["shortcode"], "handle": "@" + str(reel.get("owner") or "?"), "href": f"reels/{reel['shortcode']}.html",
        "url": reel.get("url") or "",
        "meta": f"{clock(facts.get('duration_s'))} · posted {day(posted)}",
        "counts": f"{fmt_int(counts.get('plays'))} plays · {fmt_x(x)} own median" + (f" ({size})" if size else ""),
        "as_of": R.as_of_text(counts),
        "peer": peer_bar(reel, creator),
        "shape": " · ".join([f"hook: {labelled(shape, 'hook_shape') or 'not tagged'}",
                             f"format: {labelled(shape, 'format') or 'not tagged'}", f"CTA: {cta}"]),
        "badges": [{"key": k, "label": flag_label(reel, k)} for k in [k for k, _ in FLAG_LABELS if k in flags]],
        "discount": f"discount: {discount.get('reason')}" if discount else None,
        "tribe": f"TRIBE read {(reel.get('tribe') or {}).get('run_date') or ''}".strip() if reel.get("tribe") else None,
        "recreate": recreate_cmd(reel["shortcode"]),
        # Sort values: only the board's allowed keys, never a TRIBE field.
        "sort": {"x": x, "plays": counts.get("plays") if _finite(counts.get("plays")) else None,
                 "posted": pt.timestamp() if pt else None,
                 "duration": facts.get("duration_s") if _finite(facts.get("duration_s")) else None,
                 "handle": str(reel.get("owner") or "").lower()},
        "filter": {"two_x": bool(reel.get("outlier")), "hook": hook[0] if hook else "", "format": fmt[0] if fmt else "",
                   "length": length_bucket(facts.get("duration_s")), "flags": flags, "tribe": bool(reel.get("tribe"))},
        "cells": {"length": clock(facts.get("duration_s")), "posted": day(posted), "plays": fmt_int(counts.get("plays")),
                  "x": fmt_x(x) + (f" ({size})" if size else ""),
                  "hook": labelled(shape, "hook_shape") or "not tagged", "format": labelled(shape, "format") or "not tagged",
                  "cta": cta, "flags": "; ".join(flag_label(reel, k) for k in [k for k, _ in FLAG_LABELS if k in flags])
                  or "none", "tribe": "yes" if reel.get("tribe") else "no"},
    }


def board_reel_texts(r: dict) -> list[tuple[str, str]]:
    where = f"board {r['sc']}"
    out = [(f"{where} meta", r["meta"]), (f"{where} counts", r["counts"]), (f"{where} as of", r["as_of"]),
           (f"{where} shape", r["shape"])]
    out += [(f"{where} badge", b["label"]) for b in r["badges"]]
    for key in ("discount", "tribe"):
        if r.get(key):
            out.append((f"{where} {key}", r[key]))
    if r.get("peer"):
        out.append((f"{where} peer", r["peer"]["caption"]))
    out += [(f"{where} cell {k}", v) for k, v in r["cells"].items()]
    return out


def creator_rows(handles, hosted: bool = False) -> list[dict]:
    """One row per creator: baseline size, median, left-out counts, window, pull date, source.
    hosted=True drops file paths from the source note."""
    rows = []
    for h in handles:
        c = load_creator(h)
        if not c:
            rows.append({"handle": "@" + h, "items": ["no baseline yet"]})
            continue
        b = c.get("baseline") or {}
        w = b.get("window") or {}
        excluded = b.get("excluded") or {}
        unit = "reels" if b.get("kind") == "reels only" else "posts"
        rows.append({"handle": "@" + h, "items": [
            f"baseline: {b.get('n')} {unit} ({b.get('kind')}{', thin: under 20' if b.get('thin') else ''})",
            f"median plays {fmt_int((b.get('median') or {}).get('plays'))}",
            "left out: " + ", ".join(f"{label} {len(excluded.get(k) or [])}" for k, label in LEFT_OUT),
            f"window {w.get('from')} to {w.get('to')}" if w.get("from") else "window: unknown",
            (f"file date {day(b.get('pulled_at'))} (pull date unknown)"
             if str(b.get("pulled_at_note") or "").startswith("pull date unknown")
             else f"pulled {day(b.get('pulled_at'))}" + (f" ({b['pulled_at_note']})" if b.get("pulled_at_note") else "")),
            f"source: {(strip_paths(b.get('source')) if hosted else b.get('source')) or 'unknown'}",
        ]})
    return rows


def fetch_rows() -> tuple[list[dict], float]:
    rows, total = [], 0.0
    path = store.fetch_log_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        est = row.get("est_usd") if _finite(row.get("est_usd")) else 0.0
        total += est
        rows.append({"at": str(row.get("at") or "")[:16].replace("T", " "), "what": str(row.get("what") or ""),
                     "detail": f"{row.get('items', '?')} items · est ${est:.3f} · {row.get('actor') or '?'} · "
                               f"{'ok' if row.get('ok') else 'failed'}"})
    rows.reverse()
    return rows, total


def build_board_page(root=None, today: dt.date | None = None,
                     hosted: bool = False) -> tuple[dict, list[tuple[str, str]]]:
    """The board page and the strings we wrote on it. hosted=True: no nav, fetch log or
    About fold (the site has its own), and creator sources without file paths."""
    sorts = []
    for key, label in SORTS:
        field = R.check_sort_key(key)
        sorts.append({"key": key, "field": field.lstrip("-"), "desc": field.startswith("-"), "label": label})
    default = R.check_sort_key(DEFAULT_SORT)
    if default not in {s["key"] for s in sorts}:
        raise RenderError(f"default sort {DEFAULT_SORT!r} is not one of the board's sorts")

    reels = store.list_reels()
    handles = sorted({str(r.get("owner")) for r in reels if r.get("owner")}
                     | {p.stem for p in (store.SWIPE / "creators").glob("*.json")})
    creators = {h: load_creator(h) for h in handles}
    rows = [board_reel(r, creators.get(r.get("owner"))) for r in reels]
    rows.sort(key=lambda r: -(r["sort"]["x"] if r["sort"]["x"] is not None else -1))
    as_of = sorted(day(r.get("counts", {}).get("as_of")) for r in reels if (r.get("counts") or {}).get("as_of"))
    unknown_pull = any(str((r.get("counts") or {}).get("as_of_note") or "").startswith("pull date unknown")
                       for r in reels)
    when = "" if not as_of else as_of[0] if as_of[0] == as_of[-1] else f"{as_of[0]} to {as_of[-1]}"
    as_of_text = ("as of: unknown" if not when else
                  f"file dates {when} (pull dates unknown)" if unknown_pull else f"as of {when}")
    k, n = len(handles), len(rows)
    header = "Swipe file"
    stamp = [f"{k} creator{'' if k == 1 else 's'} · {n} reel{'' if n == 1 else 's'}",
             f"counts {as_of_text}, refreshed by hand"]
    options = {
        "hook": sorted({r["filter"]["hook"] for r in rows if r["filter"]["hook"]}),
        "format": sorted({r["filter"]["format"] for r in rows if r["filter"]["format"]}),
        "length": [b for b in LENGTHS if any(r["filter"]["length"] == b for r in rows)],
        "flags": [{"key": key, "label": label} for key, label in FLAG_LABELS
                  if any(key in r["filter"]["flags"] for r in rows)],
    }
    rendered = (today or dt.date.today()).isoformat()
    texts = [("stamp", t) for t in stamp] + [(f"sort {s['key']}", s["label"]) for s in sorts]
    texts += [("option hook", o) for o in options["hook"]] + [("option format", o) for o in options["format"]]
    for r in rows:
        texts += board_reel_texts(r)
    if hosted:
        creators_rows = creator_rows(handles, hosted=True)
        for c in creators_rows:
            texts += [(f"creator {c['handle']}", t) for t in c["items"]]
        return {"rendered": rendered, "stamp": stamp, "sorts": sorts, "default_sort": default, "options": options,
                "reels": rows, "creators": creators_rows}, texts
    # Links to the other swipe pages (render all writes one lab page per draft).
    nav = [{"text": "Patterns", "href": "patterns.html"}] + [
        {"text": f"Draft: {str(d.get('slug') or d['id']).replace('-', ' ')}"
                 + (" (example)" if d.get("status") == "example" else ""), "href": f"lab/{d['id']}.html"}
        for d in _drafts() if d.get("id")]
    fetch, total = fetch_rows()
    about = [
        "plays: the public play count (Apify videoPlayCount). x: plays divided by the creator's own median plays "
        "(reels only; pinned, paid, under 48 h and the swipe reel itself left out).",
        "2x+: x of 2 or more and not discounted (VAULT research/OUTLIERS.md rule 1). Under 2x: taste, not proof.",
        "Thin baseline: under 20 reels. Gated CTA: a comment or DM keyword gate, which inflates the comment count. "
        "Discounted: marked by hand, with a reason.",
        "Counts are a snapshot as of the date shown and change after it. A file date means the pull date was "
        "never recorded: the counts are from that day or earlier.",
        "Refresh by hand, one creator at a time: python -m strategist.reel add @handle (it prints the cost first "
        "and runs only with --yes).",
        "The strip on each card: the dot is this reel, the tall tick is the creator's own median and the short "
        "ticks are the creator's own baseline reels, on a log scale.",
        "TRIBE read: a deep read exists for that reel. It shows on that reel's card only, on that reel's own "
        "scale, and is never compared across reels or sorted on.",
        R.WALL_SENTENCE,
        "Private pages: the reel cards quote a few of the creators' words. " + PRIVATE_NOTE,
    ]
    creators_rows = creator_rows(handles)
    page = {
        "rendered": rendered, "header": header, "stamp": stamp, "nav": nav,
        "sorts": sorts, "default_sort": default, "options": options, "lengths": list(LENGTHS),
        "reels": rows, "creators": creators_rows, "fetch": fetch, "fetch_total": f"Logged estimates: ${total:.3f} "
        "in all (Apify, outside the Modal cap).", "about": about,
    }
    texts = [("header", header), ("fetch total", page["fetch_total"])] + texts
    texts += [(f"nav {i}", item["text"]) for i, item in enumerate(nav)]
    for c in creators_rows:
        texts += [(f"creator {c['handle']}", t) for t in c["items"]]
    texts += [(f"fetch {f['at']}", f"{f['what']} · {f['detail']}") for f in fetch]
    texts += [(f"about {i}", t) for i, t in enumerate(about)]
    return page, texts


def render_board(root=None, today: dt.date | None = None, log=print) -> Path:
    """reports/swipe/index.html. Raises RenderError when refused."""
    page, texts = build_board_page(root, today)
    return write_page("board.html", page, texts, pages_dir(root) / "index.html")


# ---------------------------------------------------------------- patterns

PATTERN_TABS = (("hook", "Hooks"), ("structure", "Structures"), ("cta", "CTAs"), ("format", "Formats"))
NEW_DAYS = 7           # a pattern first seen in a build this recent gets the NEW tag
LEAD_GAP = 0.10        # the short list on top: outlier share at least 10 points above the normal share
LEFT_OUT_PATTERNS = (("paid", "paid"), ("pinned", "pinned"), ("fresh", "under 48 h"), ("discounted", "discounted"),
                     ("no_post_list", "no post list"), ("baseline_not_checked", "baseline not re-checked"))
LEVEL_HEADS = {"caption": "Caption level · every reel in each creator's pull",
               "spoken": "Spoken level · hand-tagged reels only"}


def contrast_text(contrast: dict, level: str, who: str = "") -> str:
    """'outliers k/n vs normal k/m', or 'k of n (tagged) outliers · outliers only, no comparison yet'."""
    o, nm = contrast["outliers"], contrast.get("normal") or {}
    if nm.get("m"):
        text = f"outliers {o['k']}/{o['n']} vs normal {nm['k']}/{nm['m']}"
    else:
        text = f"{o['k']} of {o['n']} {'tagged ' if level == 'spoken' else ''}outliers · {R.PATTERN_NO_COMPARE}"
    return f"{who} {text}".strip()


def pattern_sources(p: dict, swipe: dict, creators: dict, base: dict, hosted: bool = False) -> list[dict]:
    """The outlier reels that carry a pattern, with plays and x: the counts layer, in its own list.
    hosted=True gives each its public Instagram link (url, or None) and in_swipe, not a page link."""
    out = []
    for sc in p.get("reels") or []:
        if sc in swipe:
            reel = swipe[sc]
            creator = creators.get(reel.get("owner"))
            plays, x = (reel.get("counts") or {}).get("plays"), exact_x(reel, creator)
            owner, href, external = reel.get("owner"), f"reels/{sc}.html", False
            public = reel.get("url")
        elif sc in base:
            row, owner = base[sc]
            creator = creators.get(owner)
            # The same x the outlier split used: against the creator's other reels (this one left out),
            # or the stored median when the post list is too short to leave one out.
            plays, x = row.get("plays"), row.get("x_exact")
            median = (((creator or {}).get("baseline") or {}).get("median") or {}).get("plays")
            if x is None and _finite(plays) and _finite(median) and median > 0:
                x = plays / median
            href = row.get("url") if re.match(r"^https://", str(row.get("url") or "")) else None
            external, public = True, href
        else:
            continue
        size = baseline_size(creator)
        counts = f"{fmt_int(plays)} plays · {fmt_x(x)} own median" + (f" ({size})" if size else "")
        if hosted:   # an Instagram link or nothing
            out.append({"sc": sc, "who": f"@{owner}", "url": public if R.shortcode_of(str(public or "")) else None,
                        "in_swipe": not external, "counts": counts})
        else:
            out.append({"sc": sc, "who": f"@{owner}", "href": href, "external": external, "counts": counts})
    return out


def recreate_slug(pid: str) -> str:
    value = pid.split(".", 2)[-1]
    return "try-" + re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:40].rstrip("-")


def build_patterns_page(root=None, today: dt.date | None = None,
                        hosted: bool = False) -> tuple[dict, list[tuple[str, str]]]:
    """The patterns page and the strings we wrote on it. hosted=True: sources carry their public
    link, a draft that used a pattern is known or not, and no page-level About fold or links."""
    from . import patterns as pat
    try:
        doc = pat.build(write=False)
    except (pat.PatternError, store.StoreError) as e:
        raise RenderError(f"patterns: {e}") from None
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=NEW_DAYS)).isoformat()
    swipe = {r["shortcode"]: r for r in store.list_reels()}
    handles = sorted({p.stem for p in (store.SWIPE / "creators").glob("*.json")})
    creators = {h: load_creator(h) for h in handles}
    base = {}
    for h in handles:
        for row in store.baseline_reels(h):
            base[row["shortcode"]] = (row, h)
    all_drafts = _drafts()
    drafts = {d.get("id") for d in all_drafts}
    # "you used it" shows once he has drafts of his own (worked examples don't count).
    his_drafts = any(d.get("status") == "draft" for d in all_drafts)
    by_id = {p["id"]: p for p in doc["patterns"]}
    names = {}
    for p in doc["patterns"]:
        names[(p["kind"], p["label"])] = names.get((p["kind"], p["label"]), 0) + 1

    items, texts = [], []
    for p in doc["patterns"]:
        level = p["contrast"]["level"]
        contrast = contrast_text(p["contrast"], level)
        R.check_pattern_line(contrast)
        by_creator = [contrast_text(v, level, f"@{h}") for h, v in sorted((p.get("by_creator") or {}).items())]
        for line in by_creator:
            R.check_pattern_line(line)
        o, nm = p["contrast"]["outliers"], p["contrast"].get("normal") or {}
        uses = [u for u in p.get("his_uses") or []]
        seen = sorted({d for d in (p.get("first_seen"), p.get("last_seen")) if d})
        same = by_id.get(p.get("same_reels_as") or "")
        item = {
            "id": p["id"], "anchor": "p-" + re.sub(r"[^A-Za-z0-9-]+", "-", p["id"]), "kind": p["kind"], "level": level,
            # Two patterns of one kind with one label (caption and spoken) say their level in the name.
            "label": p["label"] + (f" · {level}" if names[(p["kind"], p["label"])] > 1 else ""),
            "family": p.get("family") or "", "level_tag": p.get("level_tag") or level,
            "slot": p.get("slot") or "", "contrast": contrast, "by_creator": by_creator,
            "bars": ({"o": [o["k"], o["n"]], "m": [nm["k"], nm["m"]]} if nm.get("m") else None),
            "few": bool(p.get("few_reels")), "suggested": p.get("labels") == "suggested",
            "new": str(p.get("added_at") or "")[:10] >= since,
            # No counted outlier carries it: folded away, with no Recreate button.
            "zero": o["k"] == 0,
            "lead": bool(nm.get("m") and o["k"] >= 1 and o["k"] / o["n"] - nm["k"] / nm["m"] >= LEAD_GAP),
            "same": (f"Same reels as {same['label']} ({shapes.KIND_LABELS.get(same['kind'], same['kind'])}, "
                     f"{same.get('level_tag') or level}): one signal, listed under both.") if same else None,
            "completeness": "completeness unknown: only the reels tagged so far" if level == "spoken" else None,
            "sources": pattern_sources(p, swipe, creators, base, hosted),
            "sources_empty": "No outlier in the counted reels carries it. Only normal reels do." if nm.get("k")
            else "No outlier in the counted reels carries it.",
            "uses": (None if not (his_drafts or uses) else "you used it: never" if not uses else
                     f"you used it: {len(uses)} draft{'' if len(uses) == 1 else 's'}"),
            "use_links": [{"id": u, "known": u in drafts} if hosted else
                          {"id": u, "href": f"lab/{u}.html" if u in drafts else None} for u in uses],
            "seen": ("seen " + " to ".join(seen)) if seen else None,
            "recreate": f"/script new {recreate_slug(p['id'])} --pattern {p['id']}" if o["k"] >= 1 else None,
        }
        items.append(item)
        where = f"pattern {p['id']}"
        texts += [(f"{where} label", item["label"]), (f"{where} family", item["family"]),
                  (f"{where} level", item["level_tag"]), (f"{where} slot", item["slot"]),
                  (f"{where} contrast", contrast), (f"{where} empty", item["sources_empty"])]
        texts += [(f"{where} creator", t) for t in by_creator]
        texts += [(f"{where} source {s['sc']}", f"{s['who']} {s['sc']} · {s['counts']}") for s in item["sources"]]
        for key in ("seen", "completeness", "same", "uses", "recreate"):
            if item[key]:
                texts.append((f"{where} {key}", item[key]))

    # One page-level note instead of the same badge on every card.
    all_new = bool(items) and all(i["new"] for i in items)
    all_few = bool(items) and all(i["few"] for i in items)
    for i in items:
        i["show_new"], i["show_few"] = i["new"] and not all_new, i["few"] and not all_few
    notes = []
    if all_few:
        notes.append("Every pattern rests on few reels (under 5 on a side): shapes to test in your draft, not proof.")
    if all_new:
        first = min((str(p.get("added_at") or "")[:10] for p in doc["patterns"]), default="")
        notes.append(f"All {len(items)} patterns are new: first built on {first}.")
    lead = [{"anchor": i["anchor"], "kind": i["kind"],
             "text": f"{shapes.KIND_LABELS.get(i['kind'], i['kind'])}: {i['label']} ({i['level_tag']}) · {i['contrast']}"}
            for i in items if i["lead"]]
    for line in lead:
        R.check_pattern_line(line["text"])
    lead_note = (f"Seen in a share of outliers at least {round(LEAD_GAP * 100)} points above the share of normal "
                 "reels. Each is a shape to test in your draft, never proof that it works.")

    pop = doc.get("population") or {}
    cap, sp = pop.get("caption") or {}, pop.get("spoken") or {}
    cap_left = ", ".join(f"{label} {len(cap.get('left_out', {}).get(k) or [])}" for k, label in LEFT_OUT_PATTERNS
                         if (cap.get("left_out") or {}).get(k))
    sp_left = ", ".join(f"{label} {len(sp.get('left_out', {}).get(k) or [])}" for k, label in LEFT_OUT_PATTERNS
                        if (sp.get("left_out") or {}).get(k))
    who = ", ".join("@" + h for h in sorted(cap.get("creators") or {})) or "no creator pull yet"
    n_out, n_norm = len(sp.get("outliers") or []), len(sp.get("normal") or [])
    population = [
        f"Caption level: {cap.get('outliers', 0)} outliers vs {cap.get('normal', 0)} normal reels from {who}. "
        f"Left out: {cap_left or 'none'}.",
        f"Spoken level: {n_out} tagged outlier{'' if n_out == 1 else 's'} and {n_norm} tagged normal "
        f"reel{'' if n_norm == 1 else 's'}. A comparison starts at "
        f"{sp.get('compare_from') or 'a few tagged normal reels'}. Left out: {sp_left or 'none'}.",
    ]
    if cap.get("borderline"):
        population.append("Near the 2x line (1.9x to 2.1x own median), so a small swing in plays could move them "
                          "between the groups: " + ", ".join(cap["borderline"]) + ".")
    n_new = sum(1 for i in items if i["new"])
    tabs = [{"key": k, "label": label, "n": sum(1 for i in items if i["kind"] == k),
             "new": sum(1 for i in items if i["kind"] == k and i["new"]) if not all_new else 0}
            for k, label in PATTERN_TABS]
    header = "Patterns"
    stamp = (f"{len(items)} pattern{'' if len(items) == 1 else 's'}"
             + ("" if all_new else f" · {n_new} new since {since}")
             + f" · from the swipe file as of {today.isoformat()} · shapes and public post data only")
    if hosted:
        texts += [("stamp", stamp)] + [(f"note {i}", t) for i, t in enumerate(notes)]
        texts += [(f"lead {i}", t["text"]) for i, t in enumerate(lead)]
        texts += [(f"population {i}", t) for i, t in enumerate(population)] + [(f"tab {t['key']}", t["label"])
                                                                               for t in tabs]
        return {"rendered": today.isoformat(), "stamp": stamp, "since": since, "notes": notes, "lead": lead,
                "population": population, "tabs": tabs, "patterns": items}, texts
    completeness = ("The caption level counts each creator's last public pull only, and the spoken level counts "
                    "only the reels tagged so far.")
    about = [
        "An outlier is a reel at 2x or more the creator's own median plays (VAULT research/OUTLIERS.md rule 1), each "
        "reel against the median of the creator's other reels (this reel left out). Normal reels are the same "
        "creators' other reels in the same pull.",
        "Every pattern shows outliers k/n vs normal k/m, or says outliers only, no comparison yet. A pattern is a "
        "shape to test in your draft, never proof that it works.",
        "Few reels: under 5 reels on either side. NEW: first seen in a build in the last 7 days.",
        "Seen only in normal reels: no counted outlier carries the pattern. Those fold away, with no Recreate button.",
        "Plays and x show only in each pattern's list of source reels.",
        "Patterns come from shapes and public post data only. Deep reads are never used here.",
        "Recreate copies a /script command for Claude, since this offline page can't call Claude. Rebuild the "
        "patterns with python -m strategist.patterns build.",
    ]
    texts += [("header", header), ("stamp", stamp), ("completeness", completeness), ("lead note", lead_note)]
    texts += [(f"note {i}", t) for i, t in enumerate(notes)] + [(f"lead {i}", t["text"]) for i, t in enumerate(lead)]
    texts += [(f"population {i}", t) for i, t in enumerate(population)]
    texts += [(f"about {i}", t) for i, t in enumerate(about)]
    texts += [(f"tab {t['key']}", t["label"]) for t in tabs] + [(f"level {k}", v) for k, v in LEVEL_HEADS.items()]
    page = {"rendered": today.isoformat(), "header": header, "stamp": stamp, "since": since,
            "completeness": completeness, "notes": notes, "lead": lead, "lead_note": lead_note,
            "population": population, "tabs": tabs, "levels": LEVEL_HEADS, "patterns": items, "about": about,
            "board_href": "index.html"}
    return page, texts


def render_patterns(root=None, today: dt.date | None = None, log=print) -> Path:
    """reports/swipe/patterns.html. Raises RenderError when refused."""
    page, texts = build_patterns_page(root, today)
    return write_page("patterns.html", page, texts, pages_dir(root) / "patterns.html")


# ---------------------------------------------------------------- script lab

HOOK_PAIR = [
    "Not built yet (D23). The idea: record two takes of your opening as voice memos, and TRIBE reads both from "
    "the audio alone, with no video model, on one scale.",
    "It would show the predicted average-brain response to each take: an average brain, not your audience, and "
    "never a pick between the takes.",
    "Cost when it is built: about $0.03 to $0.07 per run (an estimate). It asks before spending.",
    "Only your own recordings go in. Never another creator's reel, and never across reels.",
]
LAB_ABOUT = [
    "Scripts borrow a pattern's shape, never its words: every line goes through the 6-word copy check against the "
    "swipe file, the linked TRIBE job words and the VAULT corpus.",
    "Numbers: only ones found in a usable row of VAULT linkedin/PROOF.md, listed under PROOF rows used.",
    "Variants are unordered things to test, and none is a pick.",
    "Length is an estimate at 2.5 words a second, read aloud, including any off-camera lines.",
    "Buttons copy a /script command for Claude, since this offline page can't call Claude.",
    "Private page: drafts/ and reports/ are in .gitignore and never published. " + PRIVATE_NOTE,
]


def _drafts() -> list[dict]:
    from . import lab
    return lab.list_drafts()


def _shown_quote(text: str) -> str | None:
    """A PROOF.md quote is his proof bank, not our text: shown only when it has no banned word
    and doesn't put counts next to brain words."""
    if not text or R.find_banned(text):
        return None
    try:
        R.check_mixed_layers([("proof", text)])
    except RenderError:
        return None
    return text


def check_badge(name: str, res, stale: bool) -> dict:
    if not isinstance(res, dict):
        return {"name": name, "state": "unchecked", "text": "not checked yet"}
    errs = [i for i in res.get("issues") or [] if isinstance(i, dict) and i.get("level") == "error"]
    warns = [i for i in res.get("issues") or [] if isinstance(i, dict) and i.get("level") == "warning"]
    if name == "Copy check":
        copies = [h for h in res.get("hits") or [] if isinstance(h, dict) and h.get("kind") == "copy"]
        text = ("clean: no shared 6-word runs, no em dashes" if res.get("ok") else
                f"{len(copies)} shared 6-word run{'' if len(copies) == 1 else 's'}, "
                f"{res.get('em_dashes') or 0} em dash{'' if (res.get('em_dashes') or 0) == 1 else 'es'}: rewrite them")
    else:
        text = ("ok" if res.get("ok") else f"{len(errs)} to fix") + (f" · {len(warns)} to look at" if warns else "")
    return {"name": name, "state": "stale" if stale else ("ok" if res.get("ok") else "fix"), "text": text}


def text_at(doc, where: str):
    """The value at a copy-check 'where' ("beats[2].say", "variants[0].line") in a draft, or None."""
    node = doc
    for name, i in re.findall(r"([A-Za-z_]+)|\[(\d+)\]", where or ""):
        try:
            node = node[name] if name else node[int(i)]
        except (KeyError, IndexError, TypeError):
            return None
    return node


def run_span(text, run) -> list[int] | None:
    """[start, end) character offsets of a copy-check run (normalised words, strategist/copycheck.py
    words()) inside the draft text it was found in, or None. The hosted lab page shows where the
    shared run sits in his draft, never the run itself."""
    from . import copycheck as cc
    if not isinstance(text, str) or not isinstance(run, str) or not run.strip():
        return None
    chars = [(c2, i) for i, c in enumerate(text) for c2 in c.lower().translate(cc._APOSTROPHES) if c2 != "'"]
    flat = "".join(c for c, _ in chars)
    drop = {m.start() for m in cc._THOUSANDS_RE.finditer(flat)}
    chars = [ch for j, ch in enumerate(chars) if j not in drop]
    flat = "".join(c for c, _ in chars)
    tokens = [(m.group(0), chars[m.start()][1], chars[m.end() - 1][1] + 1) for m in cc._WORD_RE.finditer(flat)]
    want = run.split()
    for k in range(len(tokens) - len(want) + 1):
        if [t[0] for t in tokens[k:k + len(want)]] == want:
            return [tokens[k][1], tokens[k + len(want) - 1][2]]
    return None


def lab_hits(draft: dict, hosted: bool = False) -> list[dict]:
    """The copy-check hits. hosted=True: kind, where and the span of the shared run in his draft,
    never the run's words or where they came from."""
    out = []
    for h in (draft.get("copycheck") or {}).get("hits") or []:
        if not isinstance(h, dict):
            continue
        copy = h.get("kind") == "copy"
        if hosted:
            out.append({"kind": "copy" if copy else "em_dash", "where": h.get("where"),
                        "span": run_span(text_at(draft, h.get("where")), h.get("run")) if copy else None,
                        "count": None if copy else h.get("count")})
        else:
            out.append({"run": h.get("run"), "where": h.get("where"), "source": h.get("source")} if copy else
                       {"run": None, "where": h.get("where"), "source": f"{h.get('count')} em dash(es)"})
    return out


def lab_page_path(did: str, root=None) -> Path:
    return pages_dir(root) / "lab" / f"{did}.html"


def build_lab_page(draft_id: str, root=None, today: dt.date | None = None,
                   hosted: bool = False) -> tuple[dict, list[tuple[str, str]]]:
    """The script lab page and the strings we wrote on it. hosted=True: kind (draft or example),
    pattern ids and known flags instead of page links, PROOF rows without a file name, and
    copy-check hits as spans only."""
    from . import lab
    try:
        draft = lab.load_draft(draft_id)
        did = lab.resolve(draft_id).stem
    except lab.LabError as e:
        raise RenderError(str(e)) from None
    today = (today or dt.date.today()).isoformat()
    beats_in = [b for b in draft.get("beats") or [] if isinstance(b, dict)]
    est = draft.get("est_s") if _finite(draft.get("est_s")) else 0.0
    target = draft.get("target_s") if _finite(draft.get("target_s")) else None
    last_sec = max(1, math.ceil(max(est, target or 0)))
    stale = bool(draft.get("checked_sig")) and draft.get("checked_sig") != lab.content_sig(draft)
    texts, script = [], []

    beats = []
    for i, b in enumerate(beats_in):
        a, z = b.get("est_start"), b.get("est_end")
        chip = R.page_range(a, max(z, a + 1e-3), last_sec) if _finite(a) and _finite(z) else None
        notes = [{"n": n.get("n"), "text": str(n.get("text") or "")} for n in b.get("notes") or [] if isinstance(n, dict)]
        beats.append({"kind": str(b.get("kind") or ""), "name": str(b.get("name") or ""), "chip": chip,
                      "start": a if _finite(a) else 0, "end": z if _finite(z) else 0,
                      "say": str(b.get("say") or ""), "on_screen": str(b.get("on_screen") or ""),
                      "slot": str(b.get("slot") or ""), "notes": notes})
        texts += [(f"beat {i} name", f"{b.get('kind') or ''} {b.get('name') or ''}"), (f"beat {i} slot", beats[-1]["slot"])]
        texts += [(f"beat {i} note {n['n']}", n["text"]) for n in notes]
        script += [(f"beat {i} say", beats[-1]["say"]), (f"beat {i} on screen", beats[-1]["on_screen"])]

    known = lab.load_patterns()
    variants = []
    for v in draft.get("variants") or []:
        if not isinstance(v, dict):
            continue
        shape = str(v.get("shape") or "")
        fam = shapes.HOOK_SHAPES.get(shape, ("other",))[0]
        p = known.get(v.get("pattern_id") or "")
        shown = shapes.label(shape) if shape else "no shape"
        family = shapes.family_label(fam)
        variants.append({"id": str(v.get("id") or ""), "shape": shown,
                         # the family only when it adds something ("authority drop · Authority drop" reads twice)
                         "family": "" if family.lower() == shown.lower() else family,
                         "pattern": (f"{p['label']} · " + contrast_text(p["contrast"], p["contrast"]["level"])) if p
                         else "not in the swipe patterns yet",
                         "pattern_href": "../patterns.html#p-" + re.sub(r"[^A-Za-z0-9-]+", "-", p["id"]) if p else None,
                         "line": str(v.get("line") or ""), "why": str(v.get("why") or ""),
                         "cmd": f"/script {did} variant {v.get('id')} this but "})
        if hosted:   # the pattern's id instead of a link to the offline patterns page
            variants[-1] = {("pattern_id" if k == "pattern_href" else k): (p["id"] if p else None)
                            if k == "pattern_href" else val for k, val in variants[-1].items()}
        texts += [(f"variant {v.get('id')} shape", variants[-1]["shape"]), (f"variant {v.get('id')} why", variants[-1]["why"]),
                  (f"variant {v.get('id')} pattern", variants[-1]["pattern"])]
        script.append((f"variant {v.get('id')} line", variants[-1]["line"]))

    pats = []
    for pid in draft.get("pattern_ids") or []:
        p = known.get(pid)
        line = (p["label"] + " · " + contrast_text(p["contrast"], p["contrast"]["level"])) if p else \
            f"{pid}: not in " + ("the swipe patterns yet" if hosted else "swipe/patterns.json")
        if p:
            R.check_pattern_line(line)
        kind = shapes.KIND_LABELS.get((p or {}).get("kind"), "Pattern")
        pats.append({"id": pid, "kind": kind, "line": line, "known": bool(p)} if hosted else
                    {"id": pid, "kind": kind, "line": line,
                     "href": "../patterns.html#p-" + re.sub(r"[^A-Za-z0-9-]+", "-", pid) if p else None})
        texts.append((f"pattern {pid}", line))

    proof = []
    see = "(see the row in the proof bank on the laptop)" if hosted else "(see the row in PROOF.md)"
    for r in draft.get("proof_rows") or []:
        if isinstance(r, dict):
            proof.append({"row": str(r.get("row") or ""), "numbers": ", ".join(r.get("numbers") or []) or "no numbers",
                          "fact": _shown_quote(str(r.get("fact") or "")) or see,
                          "caveat": _shown_quote(str(r.get("caveat") or ""))})
        elif isinstance(r, str):
            proof.append({"row": r, "numbers": "not checked yet", "fact": see, "caveat": None})

    length = draft.get("length") if isinstance(draft.get("length"), dict) else None
    length_text = (length or {}).get("summary") or (f"about {round(est)} s read aloud" if est else "not estimated yet")
    if target:
        length_text += f" · target {round(target)} s"
    badges = [check_badge("Copy check", draft.get("copycheck"), stale),
              check_badge("Voice", draft.get("voice_check"), stale),
              check_badge("Rules", draft.get("rules_check"), stale),
              {"name": "Length", "state": "stale" if stale else ("ok" if (length or {}).get("status") == "ok" else
                                                                  "look" if length else "unchecked"),
               "text": f"about {round(est)} s of {round(target)} s" if target else f"about {round(est)} s"}]
    issues = []
    for key, name in (("voice_check", "voice"), ("rules_check", "rules")):
        for it in ((draft.get(key) or {}).get("issues") or []):
            if isinstance(it, dict):
                issues.append({"check": name, "level": it.get("level"), "where": it.get("where"),
                               "message": str(it.get("message") or "")})
    hits = lab_hits(draft, hosted)
    check_cmd = f"python -m strategist.lab check {did}"
    status = ("example: a worked example of the coach, not one of your drafts" if draft.get("status") == "example"
              else "draft")
    stale_text = f"Changed since the last check: run {check_cmd}" if stale else None
    if not draft.get("checked_at"):
        stale_text = f"Not checked yet: run {check_cmd}"
    commands = {"this_but": f"/script {did} this but ", "replace": f"/script {did} replace ",
                "check": check_cmd, "render": f"python -m strategist.render lab {did}"}
    texts += [("status", status), ("length", length_text)] + [(f"badge {b['name']}", f"{b['name']}: {b['text']}")
                                                               for b in badges]
    if hosted:
        page = {
            "rendered": today, "id": did, "slug": str(draft.get("slug") or did),
            "kind": "example" if draft.get("status") == "example" else "draft", "status": status,
            "title": str(draft.get("slug") or did).replace("-", " "),
            "updated": str(draft.get("updated_at") or "")[:10] or None,
            "checked": str(draft.get("checked_at") or "")[:10] or None, "stale": stale_text,
            "est_s": est, "target_s": target, "length_text": length_text, "badges": badges,
            "beats": beats, "variants": variants, "patterns": pats, "proof": proof,
            "issues": issues, "hits": hits, "commands": commands,
        }
    else:
        page = {
            "rendered": today, "id": did, "slug": str(draft.get("slug") or did), "status": status,
            "title": str(draft.get("slug") or did).replace("-", " "), "updated": str(draft.get("updated_at") or "")[:10],
            "checked": str(draft.get("checked_at") or "")[:10] or None, "stale": stale_text,
            "est_s": est, "target_s": target, "length_text": length_text, "badges": badges,
            "beats": beats, "variants": variants, "patterns": pats, "proof": proof,
            "issues": issues, "hits": hits, "commands": commands,
            "hook_pair": HOOK_PAIR, "about": LAB_ABOUT, "board_href": "../index.html",
            "patterns_href": "../patterns.html",
        }
        texts += [(f"hook pair {i}", t) for i, t in enumerate(HOOK_PAIR)]
        texts += [(f"about {i}", t) for i, t in enumerate(LAB_ABOUT)]
    if stale_text:
        texts.append(("stale", stale_text))
    for p in proof:
        texts.append((f"proof {p['row']}", f"{p['row']} · {p['numbers']}"))
    # His script lines and the check messages that quote them: banned words and the wall only
    # (his speech may say "because"); every other string we wrote gets every check.
    quoted = script + [(f"{i['check']} {i['where']}", i["message"]) for i in issues]
    R.check_banned(quoted, emotions=False)
    R.check_mixed_layers(quoted)
    return page, texts


def render_lab(draft_id: str, root=None, today: dt.date | None = None, log=print) -> Path:
    """reports/swipe/lab/<draft_id>.html. Raises RenderError when refused."""
    page, texts = build_lab_page(draft_id, root, today)
    return write_page("lab.html", page, texts, lab_page_path(page["id"], root))


def render_all(root=None, today: dt.date | None = None, log=print) -> list[Path]:
    paths = [render_board(root, today, log)]
    for reel in store.list_reels():
        paths.append(render_reel(reel["shortcode"], root, today, log))
    paths.append(render_patterns(root, today, log))
    for d in _drafts():
        paths.append(render_lab(d["id"], root, today, log))
    return [p for p in paths if p]


# One function per page; "reel" and "lab" take an argument.
PAGES = {
    "all": lambda arg, root: render_all(root),
    "board": lambda arg, root: [render_board(root)],
    "reel": lambda arg, root: [render_reel(arg, root)],
    "patterns": lambda arg, root: [p for p in [render_patterns(root)] if p],
    "lab": lambda arg, root: [p for p in [render_lab(arg, root)] if p],
}
NEEDS_ARG = {"reel": "a reel shortcode", "lab": "a draft id"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strategist.render", description="Render the offline swipe pages.")
    ap.add_argument("page", choices=list(PAGES))
    ap.add_argument("arg", nargs="?", help="reel shortcode (reel) or draft id (lab)")
    ap.add_argument("--open", action="store_true", help="open the (first) page in the browser")
    ap.add_argument("--reports-dir", default=None, help="where reports/ is (default: <project>/reports)")
    args = ap.parse_args(argv)
    if args.page in NEEDS_ARG and not args.arg:
        print(f"Refused: {args.page} needs {NEEDS_ARG[args.page]}", file=sys.stderr)
        return 2
    try:
        paths = PAGES[args.page](args.arg, args.reports_dir)
    except (RenderError, store.StoreError) as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2
    for p in paths:
        print(p)
    if args.open and paths:
        webbrowser.open(paths[0].resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
