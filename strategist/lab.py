"""Script lab: drafts for his future account, built from pattern slots and checked before he reads them.

Usage (from the Tribe folder):
    python -m strategist.lab new <slug> [--pattern <id>]... [--from <sc>] [--target 30] [--example] [--force]
    python -m strategist.lab check <draft_id|slug> [--no-vault] [--json] [--dry-run]
    python -m strategist.lab list

new writes drafts/<yyyymmdd>-<slug>.json (gitignored): a skeleton of beats with the
pattern slots to fill. A slug "from-<shortcode>" (the board's Recreate command) or
--from <sc> seeds the beats from that reel's tagged shape: kinds and shape names
only, never its words. The script coach (strategist/coach.md) fills the skeleton.

check runs every check and writes the results back into the draft:
  copycheck     6-word copy check (strategist/copycheck.py) against the swipe file,
                linked TRIBE job words and the VAULT corpus; em dashes
  voice_check   VAULT linkedin/voice/VOICE.md rules that apply to a spoken script:
                no em dashes or emojis, the never-words, mostly 5 to 15 words a
                sentence (warnings), questions to the viewer (warnings), and numbers:
                only ones found in a usable VAULT linkedin/PROOF.md row (proof_rows
                records the rows)
  rules_check   the Tribe rules (dashboard/render.py): every margin note starts
                "Test:" and passes the banned-word, wall, cause-word and pronoun
                checks; script lines pass the banned-word and wall checks; no
                creator framing (@handles); known pattern ids and hook shapes
  est_s         estimated length read aloud at 2.5 words a second, per beat too
Notes are renumbered 1..n across the draft. Warnings never fail a check.

Off-camera lines start "(off camera)": they count toward the length, but they are
not his voice, so the voice rules skip them.

Exit codes: 0 every check passed, 1 a check failed (the draft says which), 2 refused
(bad slug or id, unknown pattern). Standard library only. VAULT is only read
(linkedin/PROOF.md and the copy-check corpus), never written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import copycheck, shapes, store
from .store import StoreError

R = store.rules()   # dashboard/render.py: the shared rule checks

WORDS_PER_S = 2.5
TARGET_S = 30
TARGET_RANGE = (10, 60)          # CLAUDE.md "Inputs": 10 to 60 s clips
LENGTH_TOL_S, LENGTH_TOL_FRAC = 2.0, 0.10
OFF_CAMERA = "(off camera)"
STATUSES = ("draft", "example")
DEFAULT_KINDS = ("hook", "setup", "proof", "payoff")
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{1,60}$")
ID_RE = re.compile(r"^\d{8}-[A-Za-z0-9][A-Za-z0-9-]{1,60}$")
FROM_RE = re.compile(r"^from-([A-Za-z0-9_-]{5,40})$")
HANDLE_MENTION_RE = re.compile(r"(?<![\w.])@[A-Za-z0-9._]{2,30}")

# ---------------------------------------------------------------- VOICE.md rules (VAULT linkedin/voice/VOICE.md, read-only)
# Ported, not imported. "Words I never use" (lines 78-95) are errors; spoken fillers
# (rule 9, line 142) are warnings. Sentence length: rule 1 (line 134) and line 20.
VOICE_NEVER = (
    # A5 AI-tell list (lines 79-81)
    r"delv(?:e|es|ed|ing)", r"game[\s-]?changers?", r"unlock(?:s|ed|ing)?", r"unleash(?:es|ed|ing)?",
    r"elevat(?:e|es|ed|ing)", r"supercharg(?:e|es|ed|ing)", r"harness(?:es|ed|ing)?", r"seamless(?:ly)?",
    r"robust", r"cutting[\s-]edge", r"revolutioni[sz](?:e|es|ed|ing)", r"landscapes?", r"navigat(?:e|es|ed|ing)",
    r"realms?",
    # stock phrases (line 84)
    r"here['’]s the thing", r"let that sink in", r"in today['’]s fast[\s-]paced world", r"in this day and age",
    # corporate jargon (line 85)
    r"leverag(?:e|es|ed|ing)", r"synerg(?:y|ies)", r"utili[sz](?:e|es|ed|ing)", r"solutions?", r"stakeholders?",
    r"best[\s-]in[\s-]class", r"scalable", r"empower(?:s|ed|ing)?", r"streamlin(?:e|es|ed|ing)",
    r"transform(?:s|ed|ing)?", r"ecosystems?",
    # polished transitions, hype, AI buzzwords (lines 86-88)
    r"furthermore", r"moreover", r"additionally", r"insane(?:ly)?", r"crazy", r"mind[\s-]blowing", r"massive(?:ly)?",
    r"agentic", r"ai[\s-]powered", r"autonomous agents?",
    # (lines 91-95)
    r"i['’]d be happy to", r"please find attached", r"dog ass", r"crap", r"ffs", r"shit",
)
VOICE_NEVER_RE = re.compile(r"(?<![A-Za-z])(?:" + "|".join(VOICE_NEVER) + r")(?![A-Za-z])", re.IGNORECASE)
FILLERS_RE = re.compile(r"(?<![A-Za-z])(?:as you can see|over here|so yeah|you know|blah blah)(?![A-Za-z])",
                        re.IGNORECASE)
HONESTY_RE = re.compile(r"(?<![A-Za-z])(?:i['’]ll be honest|to be honest|i can['’]t lie|that['’]s the catch"
                        r"|a bit buggy)(?![A-Za-z])", re.IGNORECASE)
PROBLEM_TURN_RE = re.compile(r"now here['’]s the problem", re.IGNORECASE)
CAPS_RUN_RE = re.compile(r"\b[A-Z]{3,}[!.]?(?:\s+[A-Z]{3,}[!.]?)+")
CAPS_OK = {"TRIBE", "FAIR", "META", "CRM", "API", "MCP", "CLI", "SEO", "DTC", "UTM"}
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")
SENTENCE_MIN, SENTENCE_MAX, SENTENCE_LONG = 5, 15, 25
SENTENCE_SHARE = 0.6     # "most sentences" between 5 and 15 words
WORD_RE = re.compile(r"[A-Za-z0-9$£€₹%]+(?:['’][A-Za-z]+)?")

# ---------------------------------------------------------------- numbers (VOICE.md rule 8: every figure traces to PROOF.md)
NUMBER_RE = re.compile(r"(?<![\w.])[$£€₹]?\d[\d,]*(?:\.\d+)?(?:%|\+)?")
NUMBER_WORDS_RE = re.compile(
    r"(?<![A-Za-z])(?:ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty"
    r"|forty|fifty|sixty|seventy|eighty|ninety|hundreds?|thousands?|millions?|billions?|dozens?)(?![A-Za-z])",
    re.IGNORECASE)
PROOF_ROW_RE = re.compile(r"^[A-Z]\d{1,3}$")


class LabError(Exception):
    """A lab command was refused. The message says why."""


# ---------------------------------------------------------------- small helpers

def drafts_dir() -> Path:
    return store.DRAFTS


def proof_path() -> Path:
    return store.VAULT / "linkedin" / "PROOF.md"


def check_slug(slug: str) -> str:
    if not SLUG_RE.match(slug or ""):
        raise LabError(f"not a draft slug: {slug!r} (letters, digits and hyphens, 2 to 61 characters)")
    return slug


def draft_path(draft_id: str) -> Path:
    if not ID_RE.match(draft_id or ""):
        raise LabError(f"not a draft id: {draft_id!r}")
    return drafts_dir() / f"{draft_id}.json"


def resolve(ref: str) -> Path:
    """drafts/<id>.json for a draft id, or for a slug when exactly one draft has it."""
    ref = (ref or "").strip()
    if ID_RE.match(ref) and draft_path(ref).is_file():
        return draft_path(ref)
    if SLUG_RE.match(ref):
        found = sorted(drafts_dir().glob(f"[0-9]*-{ref}.json")) if drafts_dir().is_dir() else []
        found = [p for p in found if ID_RE.match(p.stem) and p.stem.split("-", 1)[1] == ref]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise LabError(f"slug {ref!r} matches {len(found)} drafts: use the id ({', '.join(p.stem for p in found)})")
    raise LabError(f"no draft {ref!r} in drafts/ (python -m strategist.lab list)")


def load_draft(ref: str) -> dict:
    path = resolve(ref)
    try:
        draft = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise LabError(f"{path.name} is not valid JSON: {e}") from None
    if not isinstance(draft, dict):
        raise LabError(f"{path.name} is not a JSON object")
    return draft


def list_drafts() -> list[dict]:
    out = []
    for p in sorted(drafts_dir().glob("*.json")) if drafts_dir().is_dir() else []:
        if not ID_RE.match(p.stem):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def load_patterns() -> dict[str, dict]:
    doc = store.load_json(store.patterns_path(), {}) or {}
    return {p["id"]: p for p in doc.get("patterns") or [] if isinstance(p, dict) and p.get("id")}


def is_off_camera(sentence: str) -> bool:
    return sentence.strip().lower().startswith(OFF_CAMERA)


def strip_marker(text: str) -> str:
    return re.sub(re.escape(OFF_CAMERA), " ", text or "", flags=re.IGNORECASE)


def word_count(text: str) -> int:
    return len(WORD_RE.findall(strip_marker(text)))


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", (text or "").strip())
    return [s.strip() for s in parts if s and s.strip()]


def content_sig(draft: dict) -> str:
    """A fingerprint of what the checks read, so a page can tell when a check is out of date."""
    keep = {k: draft.get(k) for k in ("target_s", "pattern_ids", "variants")}
    keep["beats"] = [{k: b.get(k) for k in ("name", "kind", "say", "on_screen")} | {
        "notes": [n.get("text") for n in b.get("notes") or [] if isinstance(n, dict)]}
        for b in draft.get("beats") or [] if isinstance(b, dict)]
    keep["proof_rows"] = sorted(declared_rows(draft))
    raw = json.dumps(keep, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def declared_rows(draft: dict) -> list[str]:
    out = []
    for r in draft.get("proof_rows") or []:
        rid = r.get("row") if isinstance(r, dict) else r
        if isinstance(rid, str) and rid.strip() and rid.strip() not in out:
            out.append(rid.strip())
    return out


# ---------------------------------------------------------------- new

def slot_of(kind: str, pats: list[dict]) -> str:
    for p in pats:
        if p["kind"] == "hook" and kind == "hook":
            return p.get("slot") or ""
        if p["kind"] == "cta" and kind == "cta":
            return p.get("slot") or ""
    return f"[{kind}: {shapes.BEAT_KINDS.get(kind, 'your own beat')}]"


def beats_skeleton(kinds, pats: list[dict], names=None) -> list[dict]:
    out = []
    for i, k in enumerate(kinds):
        out.append({"name": (names[i] if names and i < len(names) else k), "kind": k, "slot": slot_of(k, pats),
                    "est_start": 0.0, "est_end": 0.0, "say": "", "on_screen": "", "notes": []})
    return out


def kinds_for(pats: list[dict]) -> list[str]:
    struct = next((p for p in pats if p["kind"] == "structure"), None)
    if struct:
        return struct["id"].split(".", 2)[2].split("-")
    kinds = list(DEFAULT_KINDS)
    if any(p["kind"] == "cta" and not p["id"].endswith(".none") for p in pats):
        kinds.append("cta")
    return kinds


def from_reel(sc: str, known: dict[str, dict]) -> tuple[list[dict], list[str]]:
    """Beats and pattern ids seeded from one swipe reel's tagged shape (kinds and shape names, never words)."""
    reel = store.load_reel(store.check_shortcode(sc))
    shape = reel.get("shape") or {}
    beats = [b for b in shape.get("beats") or [] if isinstance(b, dict) and b.get("status") in R.SHAPE_SHOWN
             and b.get("kind")]
    pids = [pid for pid, p in known.items() if sc in (p.get("reels") or [])]
    pats = [known[p] for p in pids]
    hook = shape.get("hook_shape") or {}
    if hook.get("status") in R.SHAPE_SHOWN and hook.get("id") in shapes.HOOK_SHAPES:
        pats.append({"kind": "hook", "id": "", "slot": shapes.HOOK_SHAPES[hook["id"]][1]})
    if beats:
        kinds = [str(b["kind"]) for b in beats]
        names = [str(b.get("name") or b["kind"]) for b in beats]
    else:
        kinds, names = kinds_for(pats), None
    return beats_skeleton(kinds, pats, names), pids


def new_draft(slug: str, pattern_ids=(), from_sc: str | None = None, target_s=TARGET_S, status="draft",
              today: str | None = None, force: bool = False) -> tuple[Path, dict]:
    check_slug(slug)
    if status not in STATUSES:
        raise LabError(f"status must be one of {STATUSES}")
    if not (isinstance(target_s, (int, float)) and TARGET_RANGE[0] <= target_s <= TARGET_RANGE[1]):
        raise LabError(f"target must be {TARGET_RANGE[0]} to {TARGET_RANGE[1]} s (CLAUDE.md inputs)")
    known = load_patterns()
    unknown = [p for p in pattern_ids if p not in known]
    if unknown:
        raise LabError(f"unknown pattern id(s) {unknown}: see swipe/patterns.json (python -m strategist.patterns build)")
    m = FROM_RE.match(slug)
    from_sc = from_sc or (m.group(1) if m else None)
    pids = list(dict.fromkeys(pattern_ids))
    if from_sc:
        try:
            beats, seeded = from_reel(from_sc, known)
        except StoreError as e:
            raise LabError(str(e)) from None
        pids += [p for p in seeded if p not in pids]
    else:
        pats = [known[p] for p in pids]
        beats = beats_skeleton(kinds_for(pats), pats)
    day = (today or store.now_iso()[:10]).replace("-", "")
    draft_id = f"{day}-{slug}"
    path = draft_path(draft_id)
    if path.exists() and not force:
        raise LabError(f"{path.name} already exists (use another slug, or --force to start it again)")
    draft = {
        "id": draft_id, "slug": slug, "status": status, "target_s": target_s, "est_s": 0.0,
        "words_per_s": WORDS_PER_S, "pattern_ids": pids, "from_reel": from_sc,
        "beats": beats, "variants": [], "proof_rows": [],
        "copycheck": None, "voice_check": None, "rules_check": None, "length": None,
        "checked_sig": None, "checked_at": None, "updated_at": store.now_iso(),
    }
    store.save_json(path, draft)
    return path, draft


# ---------------------------------------------------------------- PROOF.md

def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def norm_number(raw: str) -> str | None:
    s = re.sub(r"[$£€₹,%+]", "", raw or "")
    try:
        return format(Decimal(s).normalize(), "f")
    except (InvalidOperation, ValueError):
        return None


def numbers_in(text: str) -> list[tuple[str, str]]:
    """(as written, normalised) for each digit number in the text."""
    out = []
    for m in NUMBER_RE.finditer(text or ""):
        n = norm_number(m.group(0))
        if n is not None:
            out.append((m.group(0), n))
    return out


def first_sentence(text: str, limit: int = 220) -> str:
    s = re.split(r"(?<=[.!?])\s+", (text or "").strip())[0] if text else ""
    return s if len(s) <= limit else s[:limit].rstrip() + "…"


def parse_proof(text: str) -> dict:
    """Rows of VAULT linkedin/PROOF.md: {id: {id, section, fact, caveat, source, numbers, blocked}},
    plus the numbers on its "Do not use" and "Warnings" lists."""
    rows, blocked_numbers = {}, set()
    header, section, bullets_blocked = None, "", False
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("#"):
            section = s.lstrip("#").strip()
            bullets_blocked = section.lower().startswith("do not use")
            header = None
            continue
        if s.startswith("**Warnings"):
            bullets_blocked = True
            continue
        if bullets_blocked and s.startswith("- "):
            blocked_numbers.update(n for _, n in numbers_in(s))
            continue
        if not s.startswith("|"):
            header = None
            continue
        cells = _cells(s)
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if re.match(r"^\|[\s:|-]+\|$", nxt) and not PROOF_ROW_RE.match(cells[0]):
            header = [c.lower() for c in cells]
            continue
        if not header or not PROOF_ROW_RE.match(cells[0]):
            continue
        col = dict(zip(header, cells))
        system = col.get("system (plain name)") or col.get("system") or ""
        result = col.get("result number") or col.get("fact") or ""
        fact = f"{system}: {result}" if system and result else (result or system)
        caveat = col.get("caveat") or col.get("post-safe?") or ""
        source = col.get("source file") or col.get("source") or col.get("source section") or ""
        # Numbers count from what the row claims, never from its caveat ("Never say 45+") or source path.
        number_text = " ".join(v for k, v in col.items()
                               if not k.startswith("source") and k not in ("#", "caveat", "post-safe?", "name ok?"))
        rows[cells[0]] = {"id": cells[0], "section": section, "fact": fact, "caveat": caveat, "source": source,
                          "numbers": {n for _, n in numbers_in(number_text)},
                          "blocked": "NOT FOR POSTS" in s}
    return {"rows": rows, "blocked_numbers": blocked_numbers}


def load_proof() -> dict | None:
    p = proof_path()
    try:
        return parse_proof(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------- the checks

def script_items(draft: dict) -> list[tuple[str, str, str]]:
    """(where, text, kind) for every line he would say ("spoken") or show ("screen")."""
    out = []
    for i, b in enumerate(draft.get("beats") or []):
        if not isinstance(b, dict):
            continue
        if isinstance(b.get("say"), str):
            out.append((f"beats[{i}].say", b["say"], "spoken"))
        if isinstance(b.get("on_screen"), str):
            out.append((f"beats[{i}].on_screen", b["on_screen"], "screen"))
    for i, v in enumerate(draft.get("variants") or []):
        if isinstance(v, dict) and isinstance(v.get("line"), str):
            out.append((f"variants[{i}].line", v["line"], "variant"))
    return out


def note_items(draft: dict) -> list[tuple[str, str]]:
    out = []
    for i, b in enumerate(draft.get("beats") or []):
        for j, n in enumerate((b or {}).get("notes") or []):
            if isinstance(n, dict):
                out.append((f"beats[{i}].notes[{j}]", str(n.get("text") or "")))
    return out


def issue(level: str, kind: str, where: str, message: str) -> dict:
    return {"level": level, "kind": kind, "where": where, "message": message}


def check_numbers(draft: dict, proof: dict | None, issues: list) -> list[dict]:
    """Every digit number he says or shows must be in a usable PROOF.md row. Returns proof_rows."""
    declared = declared_rows(draft)
    rows = (proof or {}).get("rows") or {}
    used: dict[str, list[str]] = {r: [] for r in declared}
    for rid in declared:
        if proof is not None and rid not in rows:
            issues.append(issue("error", "proof", "proof_rows", f"{rid} is not a row in VAULT linkedin/PROOF.md"))
        elif rows.get(rid, {}).get("blocked"):
            issues.append(issue("error", "proof", "proof_rows", f"{rid} is marked NOT FOR POSTS in PROOF.md"))
    for where, text, _ in script_items(draft):
        for m in NUMBER_WORDS_RE.finditer(strip_marker(text)):
            issues.append(issue("error", "number_word", where,
                                f"'{m.group(0)}': write numbers as digits so they can be checked against PROOF.md"))
        for raw, n in numbers_in(strip_marker(text)):
            if proof is None:
                issues.append(issue("error", "number", where,
                                    f"{raw}: VAULT linkedin/PROOF.md not found, so no number can be checked"))
                continue
            found = [r for r in rows.values() if n in r["numbers"] and not r["blocked"]]
            mine = [r for r in found if r["id"] in declared]
            if not found:
                why = ("it is only in a PROOF.md row marked NOT FOR POSTS" if any(n in r["numbers"] for r in rows.values())
                       else "it is on the PROOF.md Do not use list" if n in proof["blocked_numbers"]
                       else "it is not in any PROOF.md row")
                issues.append(issue("error", "number", where, f"{raw}: {why}. Cut it, or add a verified row first"))
            elif declared and not mine:
                issues.append(issue("error", "number", where, f"{raw} is in PROOF row {', '.join(r['id'] for r in found)}, "
                                    f"not in the rows this draft names ({', '.join(declared)})"))
            else:
                pick = mine or found
                if not declared and len(found) > 1:
                    issues.append(issue("warning", "number", where, f"{raw} is in PROOF rows "
                                        f"{', '.join(r['id'] for r in found)}: name the one you mean in proof_rows"))
                for r in pick:
                    if raw not in used.setdefault(r["id"], []):
                        used[r["id"]].append(raw)
    out = []
    for rid, nums in used.items():
        r = rows.get(rid) or {}
        out.append({"row": rid, "numbers": nums, "fact": first_sentence(r.get("fact", "")),
                    "caveat": first_sentence(r.get("caveat", ""), 260), "source": "VAULT linkedin/PROOF.md"})
    return out


def voice_check(draft: dict, proof: dict | None) -> tuple[dict, list[dict]]:
    issues: list[dict] = []
    spoken_sentences: list[tuple[str, str]] = []
    honesty = problem_turns = 0
    for where, text, kind in script_items(draft):
        if "—" in text:
            issues.append(issue("error", "em_dash", where, "em dash: VOICE.md rule 10 (use a full stop or a comma)"))
        if EMOJI_RE.search(text):
            issues.append(issue("error", "emoji", where, "emoji: VOICE.md rule 10"))
        own = " ".join(s for s in sentences(text) if not is_off_camera(s))
        for m in VOICE_NEVER_RE.finditer(own):
            issues.append(issue("error", "never_word", where, f"'{m.group(0)}' is on the VOICE.md never list"))
        for m in FILLERS_RE.finditer(own):
            issues.append(issue("warning", "filler", where, f"'{m.group(0)}' is a spoken filler (VOICE.md rule 9)"))
        for m in CAPS_RUN_RE.finditer(own):
            if not set(re.findall(r"[A-Z]{3,}", m.group(0))) <= CAPS_OK:
                issues.append(issue("warning", "caps", where, f"'{m.group(0)}': no caps shouting (VOICE.md line 94)"))
        if kind == "screen":
            continue
        for s in sentences(text):
            if is_off_camera(s):
                continue
            if s.rstrip().endswith("?"):
                issues.append(issue("warning", "question", where, f"'{s}': a question to the viewer? VOICE.md says no "
                                    f"rhetorical questions. Fine if it is a real off-camera voice: start it '{OFF_CAMERA}'"))
            if kind == "spoken":
                spoken_sentences.append((where, s))
            elif word_count(s) > SENTENCE_MAX:
                issues.append(issue("warning", "sentence_length", where, f"{word_count(s)} words: hooks land faster under "
                                    f"{SENTENCE_MAX + 1}"))
        if kind == "spoken":
            honesty += len(HONESTY_RE.findall(own))
            problem_turns += len(PROBLEM_TURN_RE.findall(own))
    long_ones = [(w, s) for w, s in spoken_sentences if word_count(s) > SENTENCE_LONG]
    for w, s in spoken_sentences:
        n = word_count(s)
        if n > SENTENCE_MAX:
            issues.append(issue("warning", "sentence_length", w, f"{n} words: VOICE.md keeps most sentences at "
                                f"{SENTENCE_MIN} to {SENTENCE_MAX}"))
    if len(long_ones) > 1:
        issues.append(issue("error", "sentence_length", "beats", f"{len(long_ones)} sentences over {SENTENCE_LONG} words: "
                            "VOICE.md rule 1 allows at most one"))
    if spoken_sentences:
        inside = sum(1 for _, s in spoken_sentences if SENTENCE_MIN <= word_count(s) <= SENTENCE_MAX)
        if inside / len(spoken_sentences) < SENTENCE_SHARE:
            issues.append(issue("warning", "sentence_length", "beats", f"{inside} of {len(spoken_sentences)} sentences "
                                f"are {SENTENCE_MIN} to {SENTENCE_MAX} words: VOICE.md keeps most of them there"))
    if honesty > 1:
        issues.append(issue("warning", "honesty", "beats", f"{honesty} honesty markers: VOICE.md rule 6 uses one per piece"))
    if problem_turns > 1:
        issues.append(issue("warning", "problem_turn", "beats", "'Now here's the problem.' more than once (VOICE.md line 40)"))
    proof_rows = check_numbers(draft, proof, issues)
    ok = not any(i["level"] == "error" for i in issues)
    return {"ok": ok, "issues": issues, "source": "VAULT linkedin/voice/VOICE.md, linkedin/PROOF.md"}, proof_rows


def _rule(fn, items, kind: str, where: str, issues: list) -> None:
    try:
        fn(items)
    except R.RenderError as e:
        issues.append(issue("error", kind, where, str(e)))


def creator_handles() -> set[str]:
    """Swipe creators whose bare handle can't be an ordinary word or a brand name (it has a dot,
    an underscore or a digit). Any @handle is caught by HANDLE_MENTION_RE."""
    return {p.stem.lower() for p in (store.SWIPE / "creators").glob("*.json") if re.search(r"[._\d]", p.stem)}


def rules_check(draft: dict) -> dict:
    issues: list[dict] = []
    if draft.get("status") not in STATUSES:
        issues.append(issue("error", "status", "status", f"status must be one of {STATUSES}"))
    t = draft.get("target_s")
    if not (R._finite(t) and TARGET_RANGE[0] <= t <= TARGET_RANGE[1]):
        issues.append(issue("warning", "target", "target_s", f"target {t!r}: clips are {TARGET_RANGE[0]} to "
                            f"{TARGET_RANGE[1]} s for now (CLAUDE.md inputs)"))
    beats = [b for b in draft.get("beats") or [] if isinstance(b, dict)]
    if not beats:
        issues.append(issue("error", "beats", "beats", "no beats yet"))
    for i, b in enumerate(beats):
        if not str(b.get("say") or "").strip():
            issues.append(issue("warning", "empty", f"beats[{i}].say", "nothing to say in this beat yet"))
    for where, text in note_items(draft):
        if not text.strip().startswith("Test:"):
            issues.append(issue("error", "note", where, "a margin note starts 'Test:': a thing to test, not a fix"))
        if R.idea_needs_one_scale(text):
            issues.append(issue("error", "note", where, "compares predicted lines across reels or versions without "
                                "'on one scale'"))
        _rule(R.check_authored, [(where, text)], "rule", where, issues)
    for i, v in enumerate(draft.get("variants") or []):
        where = f"variants[{i}]"
        if not isinstance(v, dict):
            issues.append(issue("error", "variant", where, "not an object"))
            continue
        if v.get("shape") not in shapes.HOOK_SHAPES:
            issues.append(issue("warning", "variant", where, f"hook shape {v.get('shape')!r} is not in strategist/shapes.py"))
        if not str(v.get("why") or "").strip():
            issues.append(issue("error", "variant", where, "every variant needs a one-line why"))
        _rule(R.check_authored, [(f"{where}.why", str(v.get("why") or ""))], "rule", f"{where}.why", issues)
    ids = [v.get("id") for v in draft.get("variants") or [] if isinstance(v, dict)]
    if len(ids) != len(set(ids)) or not all(isinstance(i, str) and i for i in ids):
        issues.append(issue("error", "variant", "variants", "each variant needs its own id"))
    for where, text, _ in script_items(draft):
        # His own speech: banned words and the wall, but feeling words are his to use.
        _rule(lambda t: R.check_banned(t, emotions=False), [(where, text)], "rule", where, issues)
        _rule(R.check_mixed_layers, [(where, text)], "rule", where, issues)
    handles = creator_handles()
    texts = [(w, t) for w, t, _ in script_items(draft)] + note_items(draft) + [
        (f"variants[{i}].why", str(v.get("why") or "")) for i, v in enumerate(draft.get("variants") or [])
        if isinstance(v, dict)]
    for where, text in texts:
        named = HANDLE_MENTION_RE.findall(text) + [h for h in handles if re.search(
            r"(?<![\w.])" + re.escape(h) + r"(?![\w])", text, re.IGNORECASE)]
        if named:
            issues.append(issue("error", "creator", where, f"names a creator ({', '.join(sorted(set(named)))}): never frame "
                                "a draft against another creator"))
    known = load_patterns()
    for pid in draft.get("pattern_ids") or []:
        if pid not in known:
            issues.append(issue("warning", "pattern", "pattern_ids", f"{pid} is not in swipe/patterns.json"))
    for i, v in enumerate(draft.get("variants") or []):
        pid = (v or {}).get("pattern_id") if isinstance(v, dict) else None
        if pid and pid not in known:
            issues.append(issue("warning", "pattern", f"variants[{i}].pattern_id", f"{pid} is not in swipe/patterns.json"))
    return {"ok": not any(i["level"] == "error" for i in issues), "issues": issues,
            "source": "dashboard/render.py rule checks, strategist/coach.md"}


def estimate(draft: dict) -> float:
    """Per-beat est_start / est_end at 2.5 words a second, read aloud; returns the total."""
    t = 0.0
    for b in draft.get("beats") or []:
        if not isinstance(b, dict):
            continue
        n = word_count(str(b.get("say") or ""))
        b["est_start"] = round(t, 1)
        t += n / WORDS_PER_S
        b["est_end"] = round(t, 1)
    return round(t, 1)


def length_check(est_s: float, target_s) -> dict:
    if not R._finite(target_s):
        return {"est_s": est_s, "target_s": target_s, "status": "no target", "summary": f"about {round(est_s)} s"}
    tol = max(LENGTH_TOL_S, LENGTH_TOL_FRAC * target_s)
    status = "over" if est_s > target_s + tol else "under" if est_s < target_s - tol else "ok"
    words = {"ok": f"within {round(tol)} s of the target", "over": f"{round(est_s - target_s)} s over the target",
             "under": f"{round(target_s - est_s)} s under the target"}[status]
    return {"est_s": est_s, "target_s": target_s, "tolerance_s": round(tol, 1), "status": status,
            "summary": f"about {round(est_s)} s read aloud at {WORDS_PER_S} words a second, {words}"}


def renumber(draft: dict) -> None:
    n = 0
    for b in draft.get("beats") or []:
        for note in (b or {}).get("notes") or []:
            if isinstance(note, dict):
                n += 1
                note["n"] = n


def check(draft: dict, include_vault: bool = True) -> dict:
    """Run every check on a draft (in place) and return it with the results filled in."""
    draft["words_per_s"] = WORDS_PER_S
    renumber(draft)
    est = estimate(draft)
    draft["est_s"] = est
    draft["length"] = length_check(est, draft.get("target_s"))
    cc = copycheck.check_texts(copycheck.draft_texts(draft), include_vault=include_vault)
    cc["corpus"] = "swipe file, linked TRIBE job words" + (", VAULT corpus" if include_vault else " (VAULT skipped)")
    draft["copycheck"] = cc
    draft["voice_check"], draft["proof_rows"] = voice_check(draft, load_proof())
    draft["rules_check"] = rules_check(draft)
    draft["checked_sig"] = content_sig(draft)
    draft["checked_at"] = draft["updated_at"] = store.now_iso()
    return draft


def passed(draft: dict) -> bool:
    return all((draft.get(k) or {}).get("ok") for k in ("copycheck", "voice_check", "rules_check"))


def summary_lines(draft: dict) -> list[str]:
    cc, vc, rc = draft["copycheck"], draft["voice_check"], draft["rules_check"]
    out = [f"draft {draft['id']} ({draft.get('status')})", f"length: {draft['length']['summary']}"]
    out += copycheck.report_lines(cc)
    for name, res in (("voice", vc), ("rules", rc)):
        errs = [i for i in res["issues"] if i["level"] == "error"]
        warns = [i for i in res["issues"] if i["level"] == "warning"]
        out.append(f"{name}: {'ok' if res['ok'] else 'FAIL'} ({len(errs)} problems, {len(warns)} to look at)")
        out += [f"  - {i['level']}: {i['where']}: {i['message']}" for i in errs + warns]
    rows = ", ".join(f"{r['row']} ({', '.join(r['numbers']) or 'no numbers'})" for r in draft["proof_rows"]) or "none"
    out.append(f"PROOF rows: {rows}")
    out.append("PASS" if passed(draft) else "FAIL: fix the problems above, then check again")
    return out


# ---------------------------------------------------------------- CLI

def cmd_new(args) -> int:
    path, draft = new_draft(args.slug, args.pattern or [], args.from_sc, args.target,
                            "example" if args.example else "draft", force=args.force)
    print(path)
    print(f"{len(draft['beats'])} beats: " + " → ".join(b["kind"] for b in draft["beats"]))
    print(f"patterns: {', '.join(draft['pattern_ids']) or 'none'}")
    print(f"next: fill it with the script coach (strategist/coach.md), then python -m strategist.lab check {draft['id']}")
    return 0


def cmd_check(args) -> int:
    path = resolve(args.draft)
    draft = check(load_draft(args.draft), include_vault=not args.no_vault)
    if not args.dry_run:
        store.save_json(path, draft)
    if args.json:
        print(json.dumps({k: draft[k] for k in ("id", "est_s", "length", "copycheck", "voice_check", "rules_check",
                                                "proof_rows")}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(summary_lines(draft)))
    return 0 if passed(draft) else 1


def cmd_list(args) -> int:
    drafts = list_drafts()
    if not drafts:
        print("no drafts yet (python -m strategist.lab new <slug>)")
    for d in drafts:
        state = "not checked" if not d.get("checked_at") else "pass" if passed(d) else "fail"
        print(f"{d.get('id')}  {d.get('status')}  about {round(d.get('est_s') or 0)} s of {d.get('target_s')} s  {state}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strategist.lab", description="Script lab drafts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new", help="start drafts/<id>.json from pattern slots")
    p.add_argument("slug")
    p.add_argument("--pattern", action="append", help="pattern id from swipe/patterns.json (repeatable)")
    p.add_argument("--from", dest="from_sc", help="seed the beats from this swipe reel's tagged shape")
    p.add_argument("--target", type=float, default=TARGET_S, help=f"target length in seconds (default {TARGET_S})")
    p.add_argument("--example", action="store_true", help="status 'example' (never counted as his use of a pattern)")
    p.add_argument("--force", action="store_true", help="overwrite a draft with the same id")
    p = sub.add_parser("check", help="run every check and write the results into the draft")
    p.add_argument("draft", help="draft id or slug")
    p.add_argument("--no-vault", action="store_true", help="copy check against the swipe file only")
    p.add_argument("--json", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="print, don't write")
    sub.add_parser("list", help="list drafts")
    args = ap.parse_args(argv)
    try:
        return {"new": cmd_new, "check": cmd_check, "list": cmd_list}[args.cmd](args)
    except (LabError, StoreError, copycheck.CopyCheckError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
