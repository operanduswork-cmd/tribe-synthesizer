"""Patterns across the swipe file: hooks, structures, CTAs and formats, each with its contrast.

Usage (from the Tribe folder):
    python -m strategist.patterns build [--dry-run]

Writes swipe/patterns.json (gitignored). Every pattern carries a contrast and a
checked line, never outliers alone as if a shape "works" (VAULT research/OUTLIERS.md
rule 5: compare against the creator's normal posts):

  level "caption"  every reel in a creator's public pull has caption-level data
                   (caption line 1 shape, caption length, CTA in the caption, reel
                   length), so the line reads "outliers k/n vs normal k/m", where
                   normal = the same creators' non-outlier reels in the baseline.
  level "spoken"   hook shape, format, CTA and beats are tagged by hand (suggested,
                   then accepted) on the imported reels, which are outliers so far.
                   Until enough normal reels of the same creators are tagged the
                   line says "outliers only, no comparison yet".

Left out of both groups (and listed in patterns.json "population"): paid
partnership reels, pinned reels, reels under 48 h old (counts not settled),
reels discounted by hand, reels whose creator has no post list (no normal
reels to compare against), and, at the spoken level, reels whose creator
baseline is not a re-checked reels-only one (their x is not comparable). An
outlier is 2x or more the creator's own median plays (strategist/store.py),
each reel against a median without itself, never a TRIBE value: this module
never reads reel["tribe"], and no count (plays, likes, x) is written into a
pattern.

Two patterns carried by exactly the same reels are one signal: the later one
gets "same_reels_as" (the first one's id) so a page can say so.

A pattern's first_seen / last_seen are the posted dates of the earliest and
latest counted reel that carries it; added_at is when the pattern first showed
up in a build (kept across rebuilds, for a NEW tag); his_uses are his drafts
(drafts/<id>.json with status "draft") that list the pattern id.

Standard library only.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from . import shapes, store
from .store import StoreError

LEVELS = ("caption", "spoken")
KIND_ORDER = ("hook", "structure", "cta", "format")
FEW_N = 5               # fewer reels than this on either side gets the "few reels" badge
COMPARE_MIN_M = 3       # spoken level: compare only once this many normal reels are tagged
SHOWN = ("suggested", "accepted")
BORDERLINE = (1.9, 2.1)   # x this close to the 2x line can flip with a small swing in plays


class PatternError(Exception):
    """The build was refused. The message says why."""


def first_line(text: str | None) -> str:
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")


def caption_cta(caption: str) -> str:
    """The first CTA type the caption carries (strategist/reel.py CTA_PATTERNS order), else "none"."""
    from .reel import CTA_PATTERNS
    return next((kind for kind, rx in CTA_PATTERNS if rx.search(caption or "")), "none")


def _date(posted) -> str | None:
    return str(posted)[:10] if posted else None


# ---------------------------------------------------------------- who is counted

def _left_out() -> dict:
    return {"paid": [], "pinned": [], "fresh": [], "discounted": [], "no_post_list": [], "baseline_not_checked": []}


def _why_left_out(reel: dict) -> str | None:
    flags = reel.get("flags") or {}
    if reel.get("discount"):
        return "discounted"
    if flags.get("fresh"):
        return "fresh"
    if flags.get("paid"):
        return "paid"
    return None


def archived_sets(reels: dict[str, dict]) -> tuple[set[str], set[str]]:
    """(archived shortcodes, creators whose swipe reels are all archived). Those creators' public
    pulls stay on disk but feed no pattern; a creator with any active reel still counts."""
    every = store.list_reels(include_archived=True)
    archived = {r["shortcode"] for r in every if r.get("archived") and r.get("shortcode")}
    active = {r.get("owner") for r in every if not r.get("archived")} | {r.get("owner") for r in reels.values()}
    owners = {r.get("owner") for r in every if r.get("archived")}
    return archived, {h for h in owners if h and h not in active}


def caption_population(reels: dict[str, dict]) -> tuple[list[dict], dict]:
    """Rows {shortcode, owner, posted, caption, caption_full, duration_s, outlier} for the
    caption-level contrast, and what was left out and why."""
    left, rows, with_list = _left_out(), [], set()
    archived, benched = archived_sets(reels)
    for p in sorted((store.SWIPE / "creators").glob("*.json")):
        creator = store.load_json(p) or {}
        handle = creator.get("handle")
        if not handle or handle in benched or not store.creator_items_path(handle).is_file():
            continue
        with_list.add(handle)
        excluded = (creator.get("baseline") or {}).get("excluded") or {}
        for why in ("paid", "pinned", "fresh"):
            left[why] += [sc for sc in excluded.get(why) or [] if sc not in reels]
        items = {it.get("shortCode"): it for it in store.load_json(store.creator_items_path(handle), []) or []
                 if isinstance(it, dict)}
        seen = set()
        for b in store.baseline_reels(handle):
            sc = b["shortcode"]
            if sc in archived:
                continue   # an archived reel is out of every pattern (D31)
            if sc in reels and reels[sc].get("discount"):
                continue   # listed below with the swipe reels
            seen.add(sc)
            rows.append({"shortcode": sc, "owner": handle, "posted": b.get("posted"), "caption": b.get("caption") or "",
                         "caption_full": True, "duration_s": b.get("duration_s"), "outlier": bool(b.get("outlier")),
                         "x": b.get("x_exact")})
        for sc, reel in sorted(reels.items()):
            if reel.get("owner") != handle or sc in seen:
                continue
            why = _why_left_out(reel) or ("pinned" if sc in (excluded.get("pinned") or []) else None)
            if why:
                left[why].append(sc)
                continue
            item = items.get(sc) or {}
            caption = item.get("caption")
            if caption is None:
                priv = store.private_dir(sc) / "caption.txt"
                caption = priv.read_text(encoding="utf-8") if priv.is_file() else ""
            rows.append({"shortcode": sc, "owner": handle, "posted": reel.get("posted"), "caption": caption,
                         "caption_full": "caption" in item,
                         "duration_s": (reel.get("facts") or {}).get("duration_s") or item.get("videoDuration"),
                         "outlier": bool(reel.get("outlier")), "x": (reel.get("x") or {}).get("plays")})
    for sc, reel in sorted(reels.items()):
        if reel.get("owner") not in with_list:
            left["no_post_list"].append(sc)
    return rows, left


def caption_features(row: dict) -> dict:
    """(kind, family key) -> value id for one reel's public post data."""
    return {
        ("hook", "opener"): shapes.caption_opener(first_line(row["caption"])),
        ("cta", "caption"): caption_cta(row["caption"]) if row["caption_full"] else None,
        ("format", "caption-length"): shapes.caption_length(row["caption"]) if row["caption_full"] else None,
        ("format", "reel-length"): shapes.reel_length(row.get("duration_s")),
    }


def _shape_value(shape: dict, field: str) -> str | None:
    if field == "beats":
        beats = [b for b in shape.get("beats") or [] if isinstance(b, dict) and b.get("status") in SHOWN]
        return shapes.structure_id(beats) or None
    v = shape.get(field) or {}
    if v.get("status") not in SHOWN:
        return None
    return (v.get("id") if field == "hook_shape" else v.get("value")) or None


def _labels_status(shape: dict, field: str) -> str:
    if field == "beats":
        beats = [b for b in shape.get("beats") or [] if isinstance(b, dict) and b.get("status") in SHOWN]
        return "accepted" if beats and all(b.get("status") == "accepted" for b in beats) else "suggested"
    return (shape.get(field) or {}).get("status") or "suggested"


SPOKEN_FIELDS = {"hook_shape": "hook", "beats": "structure", "cta": "cta", "format": "format"}


def _reels_only_baseline(handle) -> bool:
    try:
        creator = store.load_creator(handle) if handle else None
    except StoreError:
        return False
    return ((creator or {}).get("baseline") or {}).get("kind") == "reels only"


def spoken_population(reels: dict[str, dict]) -> tuple[list[dict], dict]:
    """Swipe reels with hand-tagged shape labels, with what was left out and why. A reel whose
    x comes from a baseline that is not a re-checked reels-only one (for example an VAULT
    record of every post type) is left out: its outlier label can't be compared."""
    left, rows = _left_out(), []
    for sc, reel in sorted(reels.items()):
        shape = reel.get("shape") or {}
        values = {f: _shape_value(shape, f) for f in SPOKEN_FIELDS}
        if not any(values.values()):
            continue
        why = _why_left_out(reel) or (None if _reels_only_baseline(reel.get("owner")) else "baseline_not_checked")
        if why:
            left[why].append(sc)
            continue
        rows.append({"shortcode": sc, "owner": reel.get("owner"), "posted": reel.get("posted"),
                     "outlier": bool(reel.get("outlier")), "values": values,
                     "status": {f: _labels_status(shape, f) for f in SPOKEN_FIELDS}})
    return rows, left


# ---------------------------------------------------------------- vocabulary lookups

def describe(kind: str, key: str, value: str, beats_text: str | None = None) -> tuple[str, str, str]:
    """(label, family, slot) for a pattern value, from strategist/shapes.py."""
    if key == "opener":
        lab, fam, slot, _ = shapes.CAPTION_OPENERS.get(value, (shapes.label(value), "other", "[not in the vocabulary yet]", ""))
        return lab, shapes.family_label(fam), slot
    if key in ("caption-length", "reel-length"):
        return shapes.LENGTH_LABELS.get(value, shapes.label(value)), shapes.family_label("length"), \
            shapes.LENGTH_LABELS.get(value, "")
    if kind == "cta":
        lab, slot, _ = shapes.CTA_TYPES.get(value, (shapes.label(value), "[not in the vocabulary yet]", ""))
        fam = "keyword-gate" if value in ("comment-keyword", "dm-keyword") else "other"
        return lab, ("Comment keyword gate" if fam == "keyword-gate" else "CTA"), slot
    if kind == "hook":
        fam, slot, _ = shapes.HOOK_SHAPES.get(value, ("other", "[not in the vocabulary yet]", ""))
        return shapes.label(value), shapes.family_label(fam), slot
    if kind == "format":
        slot, _ = shapes.FORMATS.get(value, ("[not in the vocabulary yet]", ""))
        return shapes.label(value), "Format", slot
    kinds = value.split("-")
    return " → ".join(kinds), "Beat sequence", " → ".join(f"[{k}]" for k in kinds)


LEVEL_TAGS = {("hook", "opener"): "caption line 1", ("cta", "caption"): "caption",
              ("format", "caption-length"): "caption", ("format", "reel-length"): "post data"}


def pattern_line(p: dict) -> str:
    """The one line a page shows for a pattern: label, then the contrast (never outliers alone)."""
    c = p["contrast"]
    o, nm = c["outliers"], c["normal"]
    head = f"{shapes.KIND_LABELS[p['kind']]} ({p['level_tag']}): {p['label']}"
    if p.get("labels") == "suggested":
        head += " (suggested)"
    if nm.get("m"):
        body = f"outliers {o['k']}/{o['n']} vs normal {nm['k']}/{nm['m']}"
    else:
        tagged = "tagged " if c["level"] == "spoken" else ""
        body = f"{o['k']} of {o['n']} {tagged}outliers · {render().PATTERN_NO_COMPARE}"
    return f"{head} · {body}" + (" · few reels" if p["few_reels"] else "")


def render():
    return store.rules()


# ---------------------------------------------------------------- building

def _span(rows: list[dict]) -> tuple[str | None, str | None]:
    dates = sorted(d for d in (_date(r.get("posted")) for r in rows) if d)
    return (dates[0], dates[-1]) if dates else (None, None)


def _pattern(kind, key, level, value, outl, normal, carriers, compare: bool, labels=None) -> dict:
    label, family, slot = describe(kind, key, value)
    k = sum(1 for r in outl if r["v"] == value)
    j = sum(1 for r in normal if r["v"] == value)
    by_creator = {}
    for h in sorted({r["owner"] for r in outl}):   # a creator with no outlier has no contrast to show
        ho = [r for r in outl if r["owner"] == h]
        hn = [r for r in normal if r["owner"] == h]
        by_creator[h] = {"outliers": {"k": sum(r["v"] == value for r in ho), "n": len(ho)},
                         "normal": {"k": sum(r["v"] == value for r in hn), "m": len(hn)} if compare else
                         {"k": None, "m": None}}
    first, last = _span(carriers)
    p = {
        "_carriers": sorted(r["shortcode"] for r in carriers),
        "id": f"{kind}.{level}.{value}",
        "family": family,
        "kind": kind,
        "slot": slot,
        "label": label,
        "level_tag": LEVEL_TAGS.get((kind, key), "spoken, tagged"),
        "reels": [r["shortcode"] for r in sorted(outl, key=lambda r: str(r.get("posted") or "")) if r["v"] == value],
        "contrast": {"outliers": {"k": k, "n": len(outl)},
                     "normal": {"k": j, "m": len(normal)} if compare else {"k": None, "m": None},
                     "level": level},
        "by_creator": by_creator,
        "few_reels": len(outl) < FEW_N or (compare and len(normal) < FEW_N),
        "first_seen": first,
        "last_seen": last,
        "his_uses": [],
    }
    if labels:
        p["labels"] = labels
    p["line"] = pattern_line(p)
    return p


def caption_patterns(rows: list[dict]) -> list[dict]:
    out = []
    feats = [(r, caption_features(r)) for r in rows]
    for (kind, key) in [("hook", "opener"), ("cta", "caption"), ("format", "caption-length"), ("format", "reel-length")]:
        known = [dict(r, v=f[(kind, key)]) for r, f in feats if f[(kind, key)] is not None]
        outl = [r for r in known if r["outlier"]]
        normal = [r for r in known if not r["outlier"]]
        if not outl:
            continue   # nothing to contrast yet
        for value in sorted({r["v"] for r in known}):
            carriers = [r for r in known if r["v"] == value]
            out.append(_pattern(kind, key, "caption", value, outl, normal, carriers, compare=bool(normal)))
    return out


def spoken_patterns(rows: list[dict]) -> list[dict]:
    out = []
    for field, kind in SPOKEN_FIELDS.items():
        tagged = [dict(r, v=r["values"][field]) for r in rows if r["values"][field]]
        outl = [r for r in tagged if r["outlier"]]
        if not outl:
            continue
        owners = {r["owner"] for r in outl}
        normal = [r for r in tagged if not r["outlier"] and r["owner"] in owners]
        compare = len(normal) >= COMPARE_MIN_M
        for value in sorted({r["v"] for r in outl} | ({r["v"] for r in normal} if compare else set())):
            carriers = [r for r in outl + (normal if compare else []) if r["v"] == value]
            labels = "accepted" if all(r["status"][field] == "accepted" for r in carriers) else "suggested"
            out.append(_pattern(kind, field, "spoken", value, outl, normal if compare else [], carriers,
                                compare=compare, labels=labels))
    return out


def mark_same_reels(patterns: list[dict]) -> None:
    """Two caption-level patterns carried by exactly the same reels are one signal (a caption whose
    line 1 is a keyword gate is also a keyword-gate CTA). The later one points at the first.
    Spoken tags are left alone: while few reels are tagged, every tag shares the same reels."""
    first = {}
    for p in patterns:
        key = (p["contrast"]["level"], tuple(p.pop("_carriers", ())))
        if key[0] != "caption" or len(key[1]) < 3:
            continue
        if key in first:
            p["same_reels_as"] = first[key]
        else:
            first[key] = p["id"]


def his_uses() -> dict[str, list[str]]:
    """Pattern id -> his draft ids (status "draft"; examples don't count as his uses)."""
    uses = defaultdict(list)
    if store.DRAFTS.is_dir():
        for p in sorted(store.DRAFTS.glob("*.json")):
            d = store.load_json(p) or {}
            if isinstance(d, dict) and d.get("status") == "draft":
                for pid in d.get("pattern_ids") or []:
                    uses[str(pid)].append(str(d.get("id") or p.stem))
    return uses


def check_patterns(patterns: list[dict]) -> None:
    """Every line shows its contrast and passes the shared rule checks (dashboard/render.py)."""
    r = render()
    texts = []
    for p in patterns:
        try:
            r.check_pattern_line(p["line"])
        except r.RenderError as e:
            raise PatternError(f"{p['id']}: {e}")
        texts += [(f"{p['id']}.line", p["line"]), (f"{p['id']}.label", p["label"]),
                  (f"{p['id']}.slot", p["slot"]), (f"{p['id']}.family", p["family"])]
    try:
        r.check_authored(texts)
    except r.RenderError as e:
        raise PatternError(str(e))


def build(write: bool = True) -> dict:
    reels = {r["shortcode"]: r for r in store.list_reels()}
    cap_rows, cap_left = caption_population(reels)
    sp_rows, sp_left = spoken_population(reels)
    patterns = caption_patterns(cap_rows) + spoken_patterns(sp_rows)
    old = {p.get("id"): p for p in (store.load_json(store.patterns_path(), {}) or {}).get("patterns") or []}
    uses = his_uses()
    now = store.now_iso()
    for p in patterns:
        p["his_uses"] = uses.get(p["id"], [])
        p["added_at"] = (old.get(p["id"]) or {}).get("added_at") or now
    order = {k: i for i, k in enumerate(KIND_ORDER)}
    patterns.sort(key=lambda p: (order[p["kind"]], LEVELS.index(p["contrast"]["level"]), p["label"]))
    mark_same_reels(patterns)
    check_patterns(patterns)
    counts = defaultdict(lambda: {"outliers": 0, "normal": 0})
    for r in cap_rows:
        counts[r["owner"]]["outliers" if r["outlier"] else "normal"] += 1
    doc = {
        "updated_at": now,
        "patterns": patterns,
        "population": {
            "caption": {"creators": dict(sorted(counts.items())),
                        "outliers": sum(c["outliers"] for c in counts.values()),
                        "normal": sum(c["normal"] for c in counts.values()),
                        "borderline": sorted(r["shortcode"] for r in cap_rows if isinstance(r.get("x"), (int, float))
                                             and BORDERLINE[0] <= r["x"] < BORDERLINE[1]),
                        "left_out": {k: sorted(set(v)) for k, v in cap_left.items()},
                        "source": "swipe/creators/private/<handle>.items.json (each creator's public pull)"},
            "spoken": {"outliers": sorted(r["shortcode"] for r in sp_rows if r["outlier"]),
                       "normal": sorted(r["shortcode"] for r in sp_rows if not r["outlier"]),
                       "left_out": {k: sorted(set(v)) for k, v in sp_left.items()},
                       "compare_from": f"{COMPARE_MIN_M} tagged normal reels of the same creators",
                       "source": "swipe/reels/<sc>/reel.json shape (suggested or accepted labels)"},
        },
        "rules": ("Outlier = 2x or more the creator's own median plays, each reel against the median of the "
                  "creator's other baseline reels (this reel left out). Pattern counts are reel counts. "
                  "Each line shows outliers k/n vs normal k/m, or says outliers only, no comparison yet. "
                  "Spoken level: only reels with a re-checked reels-only baseline. "
                  "TRIBE output is never read here."),
    }
    if write:
        with store.locked():
            store.save_json(store.patterns_path(), doc)
    return doc


def cmd_build(args) -> int:
    doc = build(write=not args.dry_run)
    pats = doc["patterns"]
    pop = doc["population"]
    print(f"{len(pats)} patterns ({'not written, dry run' if args.dry_run else store.patterns_path()})")
    c = pop["caption"]
    print(f"caption level: {c['outliers']} outliers vs {c['normal']} normal reels from "
          f"{', '.join('@' + h for h in c['creators']) or 'no creators'}; left out "
          + (", ".join(f"{k} {len(v)}" for k, v in c["left_out"].items() if v) or "none"))
    s = pop["spoken"]
    print(f"spoken level: {len(s['outliers'])} tagged outliers, {len(s['normal'])} tagged normal; left out "
          + (", ".join(f"{k} {len(v)}" for k, v in s["left_out"].items() if v) or "none"))
    for p in pats:
        print("  " + p["line"])
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strategist.patterns", description="Swipe file patterns")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build", help="rebuild swipe/patterns.json from the swipe file")
    p.add_argument("--dry-run", action="store_true", help="print, don't write")
    args = ap.parse_args(argv)
    try:
        return cmd_build(args)
    except (PatternError, StoreError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
