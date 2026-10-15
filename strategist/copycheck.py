"""6-word copy check: a draft may borrow a reel's shape, never its words.

Usage (from the Tribe folder):
    python -m strategist.copycheck <file> [--no-vault] [--json]

<file> is a draft (drafts/<id>.json: every say, on_screen, note, variant line and
why is checked, each with where it sits) or any text file (.md, .txt, a
suggestions.json). Exit 0 when clean, 1 when a copied 6-word run or an em dash
is found, 2 when the file can't be read. Hits print the shared words and where
they came from, never a whole transcript.

Ported from VAULT linkedin/tools/copycheck.py (6-word runs against the vault's
example posts, em dashes) and corpuscheck.py (6-word runs against every scraped
creator post and repurpose caption/transcript, own posts left out). Read for
logic, never imported. Changes: runs are normalised harder (case, punctuation,
curly vs straight apostrophes, "1,000" vs "1000"), and the corpus adds the
swipe file and linked TRIBE jobs:

    swipe/reels/<sc>/private/{transcript.txt, words.json, caption.txt}
    swipe/creators/private/<handle>.items.json      captions of each creator pull
    outputs/<job>/events.json                       words of TRIBE jobs linked to a swipe reel
    VAULT research/repurpose/media/<sc>/*.txt, *.srt  (read-only)
    VAULT research/repurpose/data/*.json              caption + transcript (corpuscheck.py)
    VAULT research/raw/post*.json                     LinkedIn posts, his own left out (corpuscheck.py)
    VAULT research/raw/ig-*.json                      captions of the Instagram creator pulls
    VAULT linkedin/COPY-VAULT.md                      the example posts (copycheck.py)

VAULT is only read, through the exact paths above (never its .env or .mcp.json).
The draft's grams are made first and each corpus text is intersected with
them, so nothing large is held in memory.

Result (also the drafts contract's copycheck field): {ok, hits:[...], em_dashes}
    hit = {"kind": "copy", "run": "six shared words", "source": "...", "where": "beats[0].say"}
        | {"kind": "em_dash", "count": n, "where": "..."}

Standard library only.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

from . import store

N = 6
EM_DASH = "—"
SELF = "your-linkedin-id"   # his LinkedIn id in VAULT research/raw (corpuscheck.py SELF)
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")
_WORD_RE = re.compile(r"[a-z0-9$%]+")
_SRT_TIME_RE = re.compile(r"^\s*\d+:\d+:\d+[,.]\d+\s*-->\s*\d+:\d+:\d+[,.]\d+\s*$")
_FENCE = "`" * 3
_VAULT_FENCED_RE = re.compile(_FENCE + r"text\n(.*?)" + _FENCE, re.S)
_VAULT_NUMBERED_RE = re.compile(r"^\d+\. `(.*?)` \(", re.M)
DRAFT_TEXT_KEYS = ("say", "on_screen", "line", "why", "text")


class CopyCheckError(Exception):
    """The file could not be checked. The message says why."""


# ---------------------------------------------------------------- normalising

def words(text: str) -> list[str]:
    """Lower case, apostrophes dropped (don't = dont), thousands commas dropped, punctuation stripped."""
    t = (text or "").lower().translate(_APOSTROPHES).replace("'", "")
    return _WORD_RE.findall(_THOUSANDS_RE.sub("", t))


def runs(ws: list[str], n: int = N) -> set[str]:
    return {" ".join(ws[i:i + n]) for i in range(len(ws) - n + 1)}


# ---------------------------------------------------------------- the corpus (label, text) pairs

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


def _word_list_text(items) -> str:
    return " ".join(str(w.get("text") or "") for w in items or [] if isinstance(w, dict))


def srt_text(raw: str) -> str:
    """Subtitle text only: no cue numbers, no timings, cues joined so runs across cues count."""
    keep = [ln.strip() for ln in raw.splitlines()
            if ln.strip() and not ln.strip().isdigit() and not _SRT_TIME_RE.match(ln)]
    return " ".join(keep)


def swipe_sources():
    for p in sorted((store.SWIPE / "reels").glob("*/reel.json")):
        reel = _json(p) or {}
        sc, owner = p.parent.name, reel.get("owner") or "?"
        priv = p.parent / "private"
        yield f"@{owner} {sc} timed words", _word_list_text(_json(priv / "words.json"))
        yield f"@{owner} {sc} transcript", _read(priv / "transcript.txt")
        yield f"@{owner} {sc} caption", _read(priv / "caption.txt")
        job = (reel.get("tribe") or {}).get("job_id")
        if job and re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{8}", str(job)):
            events = _json(store.OUTPUTS / job / "events.json") or {}
            items = events.get("words") if isinstance(events, dict) else events
            yield f"TRIBE job {job} words (@{owner} {sc})", _word_list_text(items)
    for p in sorted((store.SWIPE / "creators" / "private").glob("*.items.json")):
        handle = p.name[:-len(".items.json")]
        for it in _json(p) or []:
            if isinstance(it, dict) and it.get("caption"):
                yield f"@{handle} {it.get('shortCode', '?')} caption", it["caption"]


def vault_sources():
    vault = store.VAULT
    if not vault.is_dir():
        return
    media = vault / "research" / "repurpose" / "media"
    for p in sorted(media.glob("*/*.txt")):
        yield f"VAULT repurpose/media/{p.parent.name}/{p.name}", _read(p)
    for p in sorted(media.glob("*/*.srt")):
        yield f"VAULT repurpose/media/{p.parent.name}/{p.name}", srt_text(_read(p))
    for p in sorted((vault / "research" / "repurpose" / "data").glob("*.json")):
        r = _json(p) or {}
        who = f"{r.get('platform') or '?'}:@{r.get('owner') or '?'} {p.stem}"
        yield f"VAULT repurpose {who} caption", r.get("caption") or ""
        yield f"VAULT repurpose {who} transcript", r.get("transcript") or ""
    for f in sorted(glob.glob(str(vault / "research" / "raw" / "post*.json"))):
        for post in _json(Path(f)) or []:
            if not isinstance(post, dict):
                continue
            a = post.get("author") or {}
            who = a.get("publicIdentifier") or a.get("name") or "?"
            text = post.get("content") or (post.get("post") or {}).get("text") or ""
            if who != SELF and text:
                yield f"VAULT LinkedIn @{who}", text
    for f in sorted(glob.glob(str(vault / "research" / "raw" / "ig-*.json"))):
        for it in _json(Path(f)) or []:
            if isinstance(it, dict) and it.get("caption"):
                yield f"VAULT IG @{it.get('ownerUsername') or '?'} {it.get('shortCode', '?')} caption", it["caption"]
    vault = _read(vault / "linkedin" / "COPY-VAULT.md")
    for i, ref in enumerate(_VAULT_FENCED_RE.findall(vault) + _VAULT_NUMBERED_RE.findall(vault)):
        yield f"VAULT COPY-VAULT.md example {i + 1}", ref


def corpus(include_vault: bool = True):
    yield from swipe_sources()
    if include_vault:
        yield from vault_sources()


# ---------------------------------------------------------------- checking

def check_texts(items, include_vault: bool = True, sources=None) -> dict:
    """Check (where, text) pairs. Each shared 6-word run is reported once, with the
    first place it sits in the draft and the first corpus source that has it."""
    items = [(w, t) for w, t in items if isinstance(t, str)]
    where_of: dict[str, str] = {}
    for where, text in items:
        for g in sorted(runs(words(text))):
            where_of.setdefault(g, where)
    found: dict[str, str] = {}
    if where_of:
        for label, text in (sources if sources is not None else corpus(include_vault)):
            if not text:
                continue
            for g in runs(words(text)) & where_of.keys():
                found.setdefault(g, label)
            if len(found) == len(where_of):
                break
    hits = [{"kind": "copy", "run": g, "source": found[g], "where": where_of[g]} for g in sorted(found)]
    dashes = 0
    for where, text in items:
        n = text.count(EM_DASH)
        if n:
            dashes += n
            hits.append({"kind": "em_dash", "count": n, "where": where})
    return {"ok": not hits, "hits": hits, "em_dashes": dashes}


def check_text(text: str, include_vault: bool = True, where: str = "text", sources=None) -> dict:
    return check_texts([(where, text)], include_vault, sources)


def draft_texts(draft: dict) -> list[tuple[str, str]]:
    """Every piece of text in a drafts/<id>.json that could end up said, shown or read."""
    out = []

    def walk(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("copycheck", "voice_check"):
                    continue
                p = f"{path}.{k}" if path else k
                if isinstance(v, str) and k in DRAFT_TEXT_KEYS:
                    out.append((p, v))
                else:
                    walk(v, p)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
    walk(draft, "")
    return out


def file_texts(path: Path) -> list[tuple[str, str]]:
    path = Path(path)
    if not path.is_file():
        raise CopyCheckError(f"no such file: {path}")
    raw = _read(path)
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise CopyCheckError(f"{path} is not valid JSON: {e}") from None
        if isinstance(data, dict) and ("beats" in data or "variants" in data):
            return draft_texts(data)
        return json_strings(data, path.name)
    return [(path.name, raw)]


def json_strings(obj, path: str = "") -> list[tuple[str, str]]:
    """Every string value in a JSON document, with its path (for files that aren't drafts)."""
    if isinstance(obj, str):
        return [(path, obj)]
    if isinstance(obj, dict):
        return [x for k, v in obj.items() for x in json_strings(v, f"{path}.{k}" if path else k)]
    if isinstance(obj, list):
        return [x for i, v in enumerate(obj) for x in json_strings(v, f"{path}[{i}]")]
    return []


def check_file(path: Path, include_vault: bool = True) -> dict:
    return check_texts(file_texts(path), include_vault)


def report_lines(result: dict) -> list[str]:
    copies = [h for h in result["hits"] if h["kind"] == "copy"]
    lines = [f"copied 6-word runs: {len(copies)}"]
    lines += [f"  - \"{h['run']}\"  in {h['where']}  (shared with {h['source']})" for h in copies]
    lines.append(f"em dashes: {result['em_dashes']}")
    lines += [f"  - {h['count']} in {h['where']}" for h in result["hits"] if h["kind"] == "em_dash"]
    lines.append("PASS" if result["ok"] else "FAIL: rewrite the lines above in your own words (shape only, never theirs)")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strategist.copycheck", description="6-word copy check")
    ap.add_argument("file")
    ap.add_argument("--no-vault", action="store_true", help="check against the swipe file and TRIBE jobs only")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args(argv)
    try:
        result = check_file(Path(args.file), include_vault=not args.no_vault)
    except CopyCheckError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print("\n".join(report_lines(result)))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
