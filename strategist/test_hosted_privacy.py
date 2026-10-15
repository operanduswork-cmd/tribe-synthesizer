"""Privacy tests for the hosted copy (strategist/hosted.py, D25). Run: python -m strategist.test_hosted_privacy

Two parts:
  - RealData: builds the real hosted payloads from swipe/, drafts/ and outputs/ (read-only, in
    memory; nothing is written or sent) and checks them against the schemas, an independent
    4-word-run scan of every private transcript, caption, words.json and TRIBE job words, and
    a path scan. Then plants leaks (a transcript run in a beat name and in a card TRY line) in
    copies of the real payloads and checks the scan catches them. Failures name the page and
    field, never the private words.
  - Synthetic: a temp swipe file (strategist/test_render_swipe.py SwipeCase) for the whole
    pipeline: a planted run in a beat name refuses the bundle, a planted run or quote in a TRIBE
    note drops the note and the card falls back to fact_ideas, the HIGH quote stays on the
    laptop, copy-check hits are spans only and a live shared run (swipe or VAULT) refuses the
    bundle, file paths and peak.png text chunks never leave. Brain pages (D28): built only for a
    linked job with preds.npy, exact fields, atlas labels only, and the planted leaks (a private
    4-word run in a label, a laptop path, a "words" field, the label "Amygdala", a per-row vmax,
    a wrong frames length, a wrong mime) are caught without the message quoting them.
No network, no database.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import re
import struct
import sys
import unittest
import zlib
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
sys.path.insert(0, str(PROJECT_ROOT))
from strategist import brain_assets as B, contract, hosted, lab, render, store  # noqa: E402
from strategist import test_brain_assets as tba  # noqa: E402
from strategist import test_render_swipe as trs  # noqa: E402

R = render.R
dash = trs.dash
JOB = trs.JOB
# The strings the task names, plus the other laptop and secret markers.
LEAK_STRINGS = ("C:\\", "C:/", "/Users/", "OneDrive", "AppData", "private/", ".env", ".npy", "data:image", "file:/")
BRAIN_FIELDS = {"v", "job_id", "shortcode", "framing", "masks_version", "precision", "time_s", "scale", "frames", "mesh",
                "atlas", "areas"}


def brain_leak_cases(page: dict, run: str) -> list[tuple[str, dict, str]]:
    """(name, planted copy of a brain page, text a problem must hold) for the leaks D28 names."""
    t = len(page["time_s"])
    cases = []

    def plant(name, change, must):
        bad = copy.deepcopy(page)
        change(bad)
        cases.append((name, bad, must))
    plant("private run in a label", lambda p: p["atlas"]["hcp"]["labels"].__setitem__(0, run), "/atlas/hcp/labels/0")
    plant("private run as a network name", lambda p: p["atlas"]["yeo"]["labels"].__setitem__(4, f"Yeo network 5: {run}"),
          "/atlas/yeo/labels/4")
    plant("laptop path", lambda p: p["frames"].__setitem__("key", "C:\\Users\\someone\\OneDrive\\frames.i8"),
          "/frames/key")
    plant("words field", lambda p: p.__setitem__("words", [{"text": run, "start": 0.0}]), "unexpected field 'words'")
    plant("feeling label", lambda p: p["atlas"]["hcp"]["labels"].__setitem__(1, "Amygdala"), "/atlas/hcp/labels/1")
    plant("per-row vmax", lambda p: p["scale"].__setitem__("vmax", [p["scale"]["vmax"]] * t), "/scale/vmax")
    plant("per-row vmax field", lambda p: p["scale"].__setitem__("vmax_by_second", [p["scale"]["vmax"]] * t),
          "unexpected field 'vmax_by_second'")
    plant("wrong frames length", lambda p: p["frames"].__setitem__("bytes", p["frames"]["bytes"] - 20484), "/frames/bytes")
    plant("an area row too short", lambda p: p["areas"]["hcp_right"].__setitem__(7, p["areas"]["hcp_right"][7][:-1]),
          "/areas/hcp_right")
    plant("another job's frames", lambda p: p["frames"].__setitem__("key", "tribe/20990101-000000-00000000/frames.i8"),
          "nothing spans two jobs")
    plant("a stored numbers file", lambda p: p["mesh"].__setitem__("key", f"tribe/{p['job_id']}/numbers.csv"), "/mesh/key")
    return cases


# ---------------------------------------------------------------- an independent scan

def norm_words(text) -> list[str]:
    """Lower case, apostrophes dropped, every other non-alphanumeric a break (independent of copycheck)."""
    t = str(text or "").lower()
    for a in ("'", "’", "‘", "ʼ", "`"):
        t = t.replace(a, "")
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)
    return re.findall(r"[a-z0-9$%]+", t)


def grams(text, n: int = 4) -> set[str]:
    w = norm_words(text)
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def _json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def private_grams() -> dict[str, str]:
    """4-word runs of every private text on the laptop -> a label (never the words)."""
    out = {}

    def add(label, text):
        for part in str(text or "").split(" | "):
            for g in grams(part):
                out.setdefault(g, label)
    for d in sorted((store.SWIPE / "reels").glob("*/private")):
        sc = d.parent.name
        for p in sorted(d.glob("*.txt")):
            add(f"{sc} {p.name}", p.read_text(encoding="utf-8-sig"))
        words = _json(d / "words.json") or []
        add(f"{sc} words.json", " ".join(str(w.get("text") or "") for w in words if isinstance(w, dict)))
    for p in sorted((store.SWIPE / "creators" / "private").glob("*.items.json")):
        for it in _json(p) or []:
            if isinstance(it, dict):
                add(f"{p.name} caption", it.get("caption"))
    for d in sorted(store.OUTPUTS.glob("*")) if store.OUTPUTS.is_dir() else []:
        rep = _json(d / "report.json") or {}
        if isinstance(rep, dict):
            add(f"{d.name} report words", " ".join(str(w.get("text") or "") for w in rep.get("words") or []
                                                   if isinstance(w, dict)))
            for h in rep.get("word_hits") or []:
                if isinstance(h, dict):
                    add(f"{d.name} word hit", h.get("phrase"))
        ev = _json(d / "events.json")
        items = ev.get("words") if isinstance(ev, dict) else ev
        add(f"{d.name} events words", " ".join(str(w.get("text") or "") for w in items or [] if isinstance(w, dict)))
        for w in items or []:
            if isinstance(w, dict):
                add(f"{d.name} events sentence", w.get("sentence"))
        tsv = (d / "clip.tsv")
        if tsv.is_file():
            for row in csv.DictReader(io.StringIO(tsv.read_text(encoding="utf-8")), delimiter="\t"):
                add(f"{d.name} clip.tsv", row.get("sentence"))
    return out


def strings(obj, path=""):
    if isinstance(obj, str):
        yield path or "/", obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from strings(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from strings(v, f"{path}/{i}")


def leaks(page) -> list[str]:
    """(path: problem) for private runs (not in our own source text) and laptop markers in a payload."""
    priv = private_grams()
    own = hosted.own_runs()
    out = []
    for path, s in strings(page):
        hit = (grams(s) & priv.keys()) - own
        if hit:
            out.append(f"{path}: {len(hit)} run(s) from {sorted({priv[g] for g in hit})}")
        for m in LEAK_STRINGS:
            if m.lower() in s.lower():
                out.append(f"{path}: {m!r}")
    return out


def run_from(text: str) -> str | None:
    """Four consecutive words of a private text, chosen without printing them."""
    w = norm_words(text)
    for i in range(len(w) - 3):
        g = " ".join(w[i:i + 4])
        if g not in hosted.own_runs() and len(set(w[i:i + 4])) == 4:
            return g
    return None


# ---------------------------------------------------------------- the real data

class RealData(unittest.TestCase):
    """The real payloads, built read-only from the laptop's data."""

    @classmethod
    def setUpClass(cls):
        cls.private = hosted.private_runs()      # VAULT is read (read-only) for the copy-check runs
        cls.bundle = hosted.build_all(private=cls.private)
        cls.pages = {(k, key): p for k, key, p in cls.bundle["pages"]}

    def test_every_payload_fits_its_schema(self):
        reels = store.list_reels()
        kinds = [k for k, _, _ in self.bundle["pages"]]
        self.assertEqual(kinds.count("board"), 1)
        self.assertEqual(kinds.count("patterns"), 1)
        self.assertEqual(kinds.count("meta"), 1)
        self.assertEqual(kinds.count("reel"), len(reels))
        self.assertEqual(kinds.count("lab"), len(lab.list_drafts()))
        linked = {(r.get("tribe") or {}).get("job_id") for r in reels if r.get("tribe")}
        self.assertEqual(kinds.count("tribe"), sum(1 for j in linked if (store.OUTPUTS / j / "report.json").is_file()))
        self.assertEqual(kinds.count("brain"), sum(1 for j in linked if (store.OUTPUTS / j / "report.json").is_file()
                                                   and (store.OUTPUTS / j / "preds.npy").is_file()))
        self.assertEqual({key for k, key, _ in self.bundle["pages"] if k == "brain"},
                         {key for k, key, _ in self.bundle["pages"] if k == "tribe"} & {
                             j for j in linked if (store.OUTPUTS / j / "preds.npy").is_file()})
        for kind, key, page in self.bundle["pages"]:
            contract.check_page(kind, page)
            self.assertEqual(contract.page_key(kind, page), key)
            self.assertEqual(page["v"], 1)
        self.assertEqual(hosted.bundle_problems(self.bundle, self.private), [])

    def test_the_scan_holds_the_copy_check_corpus(self):
        self.assertTrue(self.private.copied, "no copy-check corpus: VAULT shared runs would go unseen")
        if store.VAULT.is_dir():
            self.assertTrue(any(v.startswith("VAULT ") for v in self.private.copied.values()))

    def test_no_private_run_anywhere(self):
        self.assertTrue(private_grams(), "no private text found: the scan would prove nothing")
        found = [f"{k}/{key} {x}" for k, key, page in self.bundle["pages"] for x in leaks(page)]
        self.assertEqual(found, [])

    def test_no_paths_or_inlined_images(self):
        for kind, key, page in self.bundle["pages"]:
            text = json.dumps(page, ensure_ascii=False)
            for m in LEAK_STRINGS:
                self.assertNotIn(m.lower(), text.lower(), f"{kind}/{key}")
            self.assertNotRegex(text, r"\.(?:mp4|mov|wav|m4a|mp3|jpe?g|txt|jsonl?)\b", f"{kind}/{key}")
        for key, a in self.bundle["assets"].items():   # numbers only: checked by structure, never byte-scanned
            self.assertEqual(B.check_asset(a.kind, a.raw)["vertices" if a.kind != "mesh" else "vertices_per_side"],
                             20484 if a.kind != "mesh" else 10242, key)
            self.assertEqual(B.gunzip(a.data), a.raw, key)
            self.assertEqual(a.mime, "application/octet-stream")
            self.assertIsNotNone(B.kind_of(key), key)
        for key, png in self.bundle["images"].items():
            self.assertTrue(png.startswith(hosted.PNG_MAGIC))
            self.assertLessEqual(len(png), hosted.IMAGE_MAX)
            for chunk in (b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"tIME"):
                self.assertNotIn(chunk, png, key)
            for m in LEAK_STRINGS:
                self.assertNotIn(m.encode(), png, key)

    def test_what_stays_on_the_laptop(self):
        for (kind, key), page in self.pages.items():
            text = json.dumps(page, ensure_ascii=False)
            self.assertNotIn('said: "', text)
            for field in ("transcript", "stills", "lanes", "local_path", "video_uri", "href", "source", "run",
                          "word_hits", "words", "phrase", "caption", "about", "nav", "fetch"):
                self.assertNotIn(f'"{field}":', text, f"{kind}/{key} has a {field} field")
        for (kind, key), page in self.pages.items():
            if kind == "tribe":   # lines, moments and the scale only: no peak values, no words
                self.assertEqual(page["framing"], "predicted average-brain response")
                self.assertEqual(set(page["lines"]), {"seeing", "hearing", "language", "attention", "combined"})
                for p in page["peaks"]:
                    self.assertEqual(set(p), {"t", "driving_lines", "edge"})
                for f in page["flat_stretches"]:
                    self.assertEqual(set(f), {"start", "end", "driving_lines", "edge"})
            if kind == "brain":   # one scale, atlas codes and names, area means: no words, no per-vertex floats
                self.assertEqual(set(page), BRAIN_FIELDS)
                self.assertEqual(page["framing"], "predicted average-brain response")
                self.assertEqual(page["scale"]["label"], "one colour scale for this whole reel")
                self.assertNotIsInstance(page["scale"]["vmax"], list)
                self.assertEqual(set(page["frames"]), {"key", "sha256", "bytes"})
                atlas = B.load_atlas()
                self.assertEqual(page["atlas"]["hcp"]["labels"], atlas["labels"])
                self.assertEqual(page["atlas"]["yeo"]["labels"], atlas["yeo_labels"])
                allow = set(atlas["labels"]) | set(atlas["yeo_labels"]) | {
                    page["atlas"]["hcp"]["name"], page["atlas"]["yeo"]["name"]}
                shown = contract.layer_strings(page, contract.load_schema("brain"))
                for path, layer, text in shown:
                    if "/atlas/" in path:
                        self.assertIn(text, allow, path)
                self.assertNotIn("Amygdala", json.dumps(page))
                t = len(page["time_s"])
                for name in ("hcp_left", "hcp_right", "yeo"):
                    self.assertTrue(all(len(row) == t for row in page["areas"][name]), name)
                tribe = self.pages[("tribe", key)]
                self.assertEqual(page["time_s"], tribe["time_s"])
                self.assertEqual(page["shortcode"], tribe["shortcode"])

    def test_hosted_card_drops_notes_with_quotes_or_runs(self):
        for reel in store.list_reels():
            job = (reel.get("tribe") or {}).get("job_id")
            notes = _json(store.OUTPUTS / str(job) / "notes.json") if job else None
            if not notes:
                continue
            mine = hosted.reel_runs(reel["shortcode"])
            dropped = [n for n in notes["notes"] if not hosted.note_ok(n, mine)]
            card = self.pages[("reel", reel["shortcode"])]["card"]
            tries = [ln["text"] for ln in card["lines"] if ln["tag"] == "TRY"]
            for n in dropped:
                self.assertNotIn(str(n.get("idea_to_test") or "").strip(), tries)
            for n in notes["notes"]:
                if hosted.QUOTE_RE.search(str(n.get("text") or "")):
                    self.assertFalse(hosted.note_ok(n, mine))

    def _a_reel_with_words(self):
        for reel in store.list_reels():
            sc = reel["shortcode"]
            text = " ".join(t for _, t in hosted.reel_sources(sc, reel.get("owner") or "?"))
            run = run_from(text)
            if run and self.pages[("reel", sc)]["beats"]:
                return sc, run
        self.skipTest("no reel with beats and a transcript")

    def test_planted_run_in_a_beat_name_is_caught(self):
        sc, run = self._a_reel_with_words()
        page = copy.deepcopy(self.pages[("reel", sc)])
        page["beats"][0]["name"] = f"demo: {run.upper()}!"
        problems = hosted.page_problems("reel", page, self.private)
        self.assertTrue(any("/beats/0/name" in p and "4-word run" in p for p in problems), problems)
        self.assertFalse(any(run in p.lower() for p in problems), "a problem quotes the private words")
        self.assertTrue(leaks(page))
        with self.assertRaises(hosted.HostedError):
            hosted.check_payload("reel", page, self.private)

    def test_planted_leaks_in_a_brain_page_are_caught(self):
        brains = [(key, p) for (k, key), p in self.pages.items() if k == "brain"]
        if not brains:
            self.skipTest("no brain page on this laptop (no linked job with preds.npy)")
        key, page = brains[0]
        _, run = self._a_reel_with_words()
        self.assertEqual(hosted.page_problems("brain", page, self.private), [])
        for name, bad, must in brain_leak_cases(page, run):
            problems = hosted.page_problems("brain", bad, self.private)
            text = " | ".join(problems)
            self.assertTrue(problems, name)
            self.assertIn(must, text, name)
            self.assertNotIn(run, text.lower(), f"{name}: a problem quotes the private words")
            for quoted in ("Amygdala", "someone", "OneDrive"):
                self.assertNotIn(quoted, text, name)
            with self.assertRaises(hosted.HostedError):
                hosted.check_payload("brain", bad, self.private)
            bundle = {"pages": [(k, kk, bad if (k, kk) == ("brain", key) else p) for k, kk, p in self.bundle["pages"]],
                      "images": self.bundle["images"], "assets": self.bundle["assets"]}
            self.assertTrue(hosted.bundle_problems(bundle, self.private), name)

    def test_planted_asset_problems_are_caught(self):
        if not self.bundle["assets"]:
            self.skipTest("no brain assets on this laptop")
        assets = self.bundle["assets"]
        frames = next(a for a in assets.values() if a.kind == "frames")
        cases = [("wrong mime", {frames.key: frames._replace(mime="text/plain")}, "'text/plain'"),
                 ("wrong frames length", {frames.key: B.pack("frames", frames.key, B.header(
                     "frames", B.check_asset("frames", frames.raw)["rows"] - 1, 20484, 127) + frames.raw[16:-20484])},
                  "the page has"),
                 ("stale hash", {frames.key: frames._replace(hash="0" * 64)}, "hash does not match")]
        for name, change, must in cases:
            bundle = dict(self.bundle, assets={**assets, **change})
            problems = hosted.bundle_problems(bundle, self.private)
            self.assertTrue(any(must in p for p in problems), (name, problems))
        # an asset is numbers: a byte pattern that happens to spell a path is not a leak (no byte scan)
        body = bytearray(frames.raw)
        spelled = "C:/Users/someone/OneDrive/.env".encode("ascii")
        body[16:16 + len(spelled)] = spelled
        noisy = B.pack("frames", frames.key, bytes(body))
        self.assertEqual(B.stored_problems(noisy.key, noisy.kind, noisy.mime, noisy.data, noisy.raw_bytes,
                                           noisy.hash)[0], [])

    def test_planted_run_in_a_note_is_caught(self):
        sc, run = self._a_reel_with_words()
        page = copy.deepcopy(self.pages[("reel", sc)])
        page["card"]["lines"][3]["text"] = f"Test: in your draft, say {run}."
        problems = hosted.page_problems("reel", page, self.private)
        self.assertTrue(any("/card/lines/3/text" in p for p in problems), problems)
        note = {"id": "n9", "kind": "word", "text": "0:01: a line.", "idea_to_test": f"Test: in your draft, say {run}."}
        self.assertFalse(hosted.note_ok(note, hosted.reel_runs(sc)))
        self.assertTrue(hosted.note_ok(dict(note, idea_to_test="Test: in your draft, cut the intro."),
                                       hosted.reel_runs(sc)))


# ---------------------------------------------------------------- synthetic, end to end

TRANSCRIPT = "Grab the blue folder before lunch. Then label every tab twice."
RUN = "grab the blue folder"


def png_with_text(text: bytes = b"Software\x00C:\\Users\\someone\\plot.py") -> bytes:
    png = dash._tiny_png()

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return png[:33] + chunk(b"tEXt", text) + png[33:]


class Synthetic(trs.SwipeCase):

    def job(self, notes=None, words=None, png=None):
        link = self.tribe_job()
        d = store.OUTPUTS / JOB
        rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
        rep["source"]["local_path"] = r"C:\Users\someone\OneDrive\clip.mp4"
        if words is not None:
            rep["words"] = words
        (d / "report.json").write_text(json.dumps(rep), encoding="utf-8")
        if notes is not None:
            (d / "notes.json").write_text(json.dumps(notes), encoding="utf-8")
        (d / "peak.png").write_bytes(png if png is not None else png_with_text())
        return link

    def build(self):
        return {(k, key): p for k, key, p in hosted.build_all()["pages"]}

    def refused(self, must=()):
        with self.assertRaises(hosted.HostedError) as cm:
            hosted.build_all()
        msg = str(cm.exception)
        for m in must:
            self.assertIn(m, msg)
        self.assertNotIn(RUN, msg.lower(), "the refusal quotes the private words")
        return msg

    def test_clean_bundle(self):
        self.creator()
        self.reel(tribe=self.job(), shape=self.shape(), transcript=TRANSCRIPT,
                  facts={"duration_s": 29.6, "first_word_s": 0.4, "words_per_s": 2.7, "text_on_screen_0s": True,
                         "cta": {"type": "comment-keyword", "t": 26.0},
                         "source": {"duration_s": r"C:\Users\someone\clip.json (ffprobe)", "cta": "private/caption.txt"}})
        bundle = hosted.build_all()
        pages = {(k, key): p for k, key, p in bundle["pages"]}
        self.assertEqual(sorted(k for k, _ in pages), ["board", "meta", "patterns", "reel", "tribe"])
        reel = pages[("reel", "TESTREEL01")]
        self.assertEqual(reel["facts"][0], {"label": "Length", "value": "0:29"})
        self.assertEqual(reel["tribe"], {"job_id": JOB, "run_date": "2026-10-01", "missing": False})
        self.assertEqual(reel["local_cmd"], "python -m strategist.render reel TESTREEL01 --open")
        tribe = pages[("tribe", JOB)]
        self.assertEqual(tribe["shortcode"], "TESTREEL01")
        self.assertEqual(tribe["peak_image"], {"key": f"tribe/{JOB}/peak.png", "t": 12})
        self.assertNotIn("value", json.dumps(tribe["peaks"]))
        png = bundle["images"][f"tribe/{JOB}/peak.png"]
        self.assertNotIn(b"tEXt", png)                       # the text chunk (a laptop path) never leaves
        self.assertEqual(png, dash._tiny_png())
        for (kind, key), page in pages.items():
            self.assertEqual(leaks(page), [], f"{kind}/{key}")

    def test_planted_run_in_a_beat_name_refuses_the_bundle(self):
        self.creator()
        self.reel(shape=self.shape(beat_name=f"{RUN} demo"), transcript=TRANSCRIPT)
        msg = self.refused(["reel/TESTREEL01", "/beats/1/name", "4-word run", "TESTREEL01 transcript"])
        self.assertIn("nothing leaves the laptop", msg)

    def test_planted_run_in_a_caption_of_a_creator_pull(self):
        self.creator()
        items = store.load_json(store.creator_items_path("testcreator"))
        items[0]["caption"] = "Grab the blue folder, everyone."
        store.save_json(store.creator_items_path("testcreator"), items)
        self.reel(shape=self.shape(beat_name=f"{RUN} demo"), transcript="")
        self.refused(["/beats/1/name", "@testcreator captions"])

    def test_planted_note_is_dropped_and_the_card_falls_back(self):
        notes = dash.make_notes(job_id=JOB)
        notes["notes"][2]["idea_to_test"] = f"Test: in your draft, {RUN} first."          # peak note: the top TRY
        notes["notes"][1]["text"] += ' The creator says "a quoted line" here.'           # hook note: a quote
        self.creator()
        self.reel(tribe=self.job(notes=notes), shape=self.shape(), transcript=TRANSCRIPT)
        offline = srender_card(self)
        self.assertIn(f"{RUN} first", offline[3]["text"].lower())                          # the laptop page keeps it
        card = self.build()[("reel", "TESTREEL01")]["card"]
        tries = [ln["text"] for ln in card["lines"][3:]]
        self.assertFalse(any(RUN in t.lower() for t in tries))
        self.assertNotIn("Test: in your draft, say the first line of speech a second earlier.", tries)   # quoted
        self.assertEqual(tries[0], "Test: in your draft, tighten any long stretch with no new picture.")
        self.assertIn(tries[1], render.fact_ideas(store.load_reel("TESTREEL01")))         # fell back
        # Forced through, the same note is a leak the scan refuses.
        page, _ = render.build_reel_page("TESTREEL01", hosted=True, keep_note=lambda n: True)
        problems = hosted.page_problems("reel", hosted.project_reel(page), hosted.PrivateRuns(hosted.private_sources()))
        self.assertTrue(any("/card/lines/3/text" in p and "4-word run" in p for p in problems), problems)

    def test_high_quote_stays_on_the_laptop(self):
        words = [{"text": w, "start": 12.0 + i * 0.2, "stop": 12.15 + i * 0.2, "rows": [12], "lang_z": 1.2,
                  "ghost": False, "stretched": False} for i, w in enumerate(("three", "easy", "steps"))]
        self.creator()
        self.reel(tribe=self.job(words=words), shape=self.shape(), transcript=TRANSCRIPT)
        offline = srender_card(self)
        self.assertIn('said: "…three easy steps…"', offline[1]["text"])
        high = self.build()[("reel", "TESTREEL01")]["card"]["lines"][1]
        self.assertEqual(high["text"], "seeing and attention lines high for this reel · quote stays on the laptop")
        self.assertEqual(high["time"], "0:12")

    def test_lab_hits_are_spans_and_proof_has_no_file(self):
        self.creator()
        self.reel(shape=self.shape(), transcript=TRANSCRIPT)
        say = "Here is the thing: nobody reads the second tab. Ever."
        draft = {"id": "20261009-span-test", "slug": "span-test", "status": "draft", "target_s": 30, "est_s": 8.0,
                 "updated_at": "2026-10-09T10:00:00+00:00", "checked_at": "2026-10-09T10:00:00+00:00",
                 "pattern_ids": ["hook.caption.not-a-pattern"], "proof_rows": [{"row": "A1", "numbers": [],
                                                                                "fact": "", "caveat": None,
                                                                                "source": "VAULT linkedin/PROOF.md"}],
                 "beats": [{"kind": "hook", "name": "cold open", "est_start": 0, "est_end": 4, "say": say,
                            "on_screen": "", "slot": "", "notes": []}],
                 "variants": [{"id": "v1", "shape": "", "pattern_id": "hook.caption.not-a-pattern",
                               "line": "Nobody reads the second tab.", "why": "A blunt open to test."}],
                 "copycheck": {"ok": False, "em_dashes": 1, "hits": [
                     {"kind": "copy", "run": "nobody reads the second tab ever", "source": "VAULT LinkedIn @someone",
                      "where": "beats[0].say"},
                     {"kind": "em_dash", "count": 1, "where": "variants[0].why"}]}}
        draft["checked_sig"] = lab.content_sig(draft)
        store.save_json(store.DRAFTS / f"{draft['id']}.json", draft)
        built, _ = render.build_lab_page(draft["id"], hosted=True)
        page = hosted.project_lab(built)
        a, b = page["hits"][0]["span"]
        self.assertEqual(say[a:b], "nobody reads the second tab. Ever")
        self.assertEqual(page["hits"], [{"kind": "copy", "where": "beats[0].say", "span": [a, b], "count": None},
                                        {"kind": "em_dash", "where": "variants[0].why", "span": None, "count": 1}])
        self.assertNotIn("@someone", json.dumps(page))
        # A span over a run that is still in his line would mark a creator's words: it never leaves (D25).
        msg = self.refused(["lab/20261009-span-test", "/hits/0", "still in the draft"])
        self.assertNotIn("nobody reads", msg.lower())
        self.assertNotIn("@someone", msg)
        # Rewritten, the stored hit is stale and has no span: the page leaves.
        draft["beats"][0]["say"] = "Here is the thing: most people skip the second tab. Ever."
        store.save_json(store.DRAFTS / f"{draft['id']}.json", draft)
        page = self.build()[("lab", "20261009-span-test")]
        self.assertEqual(page["hits"][0], {"kind": "copy", "where": "beats[0].say", "span": None, "count": None})
        self.assertEqual(page["proof"][0]["fact"], "(see the row in the proof bank on the laptop)")
        self.assertEqual(page["patterns"][0], {"id": "hook.caption.not-a-pattern", "kind": "Pattern",
                                               "line": "hook.caption.not-a-pattern: not in the swipe patterns yet",
                                               "known": False})
        self.assertIsNone(page["variants"][0]["pattern_id"])
        self.assertNotIn("@someone", json.dumps(page))
        # His draft repeating a creator's run: the scan refuses the bundle (he rewrites, then pushes).
        draft["beats"][0]["say"] = f"So {RUN} and go."
        store.save_json(store.DRAFTS / f"{draft['id']}.json", draft)
        self.refused(["lab/20261009-span-test", "/beats/0/say"])

    def test_vault_shared_run_in_a_draft_refuses_the_bundle(self):
        """A draft line that repeats 6 words from what the copy check reads in VAULT (here a LinkedIn
        post by someone else) never leaves, checked or not."""
        post = "Most founders never write down the one number that matters each week."
        raw = store.VAULT / "research" / "raw"
        raw.mkdir(parents=True)
        (raw / "posts-test.json").write_text(json.dumps([{"author": {"publicIdentifier": "someone-else"},
                                                           "content": post}]), encoding="utf-8")
        self.creator()
        self.reel(shape=self.shape(), transcript=TRANSCRIPT)
        draft = {"id": "20261009-vault-test", "slug": "vault-test", "status": "draft", "target_s": 30, "est_s": 8.0,
                 "updated_at": "2026-10-09T10:00:00+00:00", "pattern_ids": [], "proof_rows": [],
                 "beats": [{"kind": "hook", "name": "cold open", "est_start": 0, "est_end": 4,
                            "say": "Okay so: never write down the one number that matters. Then fix it.",
                            "on_screen": "", "slot": "", "notes": []}],
                 "variants": []}
        store.save_json(store.DRAFTS / f"{draft['id']}.json", draft)
        msg = self.refused(["lab/20261009-vault-test", "/beats/0/say", "6-word run", "VAULT LinkedIn @someone-else"])
        self.assertNotIn("one number that matters", msg.lower())
        # The 4-word scan alone (swipe and TRIBE texts) would have let it through.
        alone = hosted.PrivateRuns(hosted.private_sources())
        self.assertEqual([k for k, _, _ in hosted.build_all(private=alone)["pages"]].count("lab"), 1)
        # Rewritten: it leaves.
        draft["beats"][0]["say"] = "Okay so: pick the one weekly figure you actually check. Then fix it."
        store.save_json(store.DRAFTS / f"{draft['id']}.json", draft)
        self.assertIn(("lab", "20261009-vault-test"), self.build())

    def test_bad_peak_pictures_are_refused(self):
        self.creator()
        self.reel(tribe=self.job(png=b"\xff\xd8not a png"), shape=self.shape(), transcript=TRANSCRIPT)
        self.refused(["tribe", "not a PNG"])
        big = dash._tiny_png()
        big = big[:33] + struct.pack(">I", 1100000) + b"IDAT" + b"\0" * 1100000 + struct.pack(
            ">I", zlib.crc32(b"IDAT" + b"\0" * 1100000) & 0xFFFFFFFF) + big[33:]
        (store.OUTPUTS / JOB / "peak.png").write_bytes(big)
        self.refused(["over the 1048576 byte limit"])

    def test_brain_page_and_assets_leave_clean(self):
        docs = tba.install_synthetic(self, self.tmp / "brain-masks")
        self.creator()
        self.reel(tribe=self.job(), shape=self.shape(), transcript=TRANSCRIPT)
        tba.write_preds(store.OUTPUTS / JOB, docs["masks"], tba.synthetic_preds(30, seed=1))
        bundle = hosted.build_all()
        pages = {(k, key): p for k, key, p in bundle["pages"]}
        brain = pages[("brain", JOB)]
        self.assertEqual(set(brain), BRAIN_FIELDS)
        self.assertEqual(brain["shortcode"], "TESTREEL01")
        self.assertEqual(brain["time_s"], pages[("tribe", JOB)]["time_s"])
        self.assertEqual(sorted(bundle["assets"]), ["shared/atlas-v1.bin", "shared/fsaverage5-inflated-v1.bin",
                                                    f"tribe/{JOB}/frames.i8"])
        self.assertEqual(hosted.bundle_problems(bundle), [])
        self.assertEqual(leaks(brain), [])
        private = hosted.private_runs()
        for name, bad, must in brain_leak_cases(brain, RUN):
            problems = hosted.page_problems("brain", bad, private)
            self.assertIn(must, " | ".join(problems), name)
            self.assertNotIn(RUN, " | ".join(problems).lower(), name)
        # the transcript run planted in a label: the schema refuses it, quietly
        bad = copy.deepcopy(brain)
        bad["atlas"]["hcp"]["labels"][0] = f"{RUN} demo"
        msg = " ".join(hosted.page_problems("brain", bad, private))
        self.assertIn("not one of the 180 allowed values", msg)
        self.assertNotIn(RUN, msg.lower())

    def test_no_preds_no_brain_page_and_a_missing_atlas_refuses(self):
        docs = tba.install_synthetic(self, self.tmp / "brain-masks")
        self.creator()
        self.reel(tribe=self.job(), shape=self.shape(), transcript=TRANSCRIPT)
        bundle = hosted.build_all()
        self.assertNotIn("brain", [k for k, _, _ in bundle["pages"]])
        self.assertEqual(bundle["assets"], {})
        tba.write_preds(store.OUTPUTS / JOB, docs["masks"], tba.synthetic_preds(30))
        with mock.patch.object(B, "ATLAS_JSON", self.tmp / "nowhere" / "atlas-v1.json"):
            msg = self.refused(["brain: could not build", "run scoring/build_atlas.py", "nothing leaves the laptop"])
        self.assertNotIn(RUN, msg.lower())
        # an unlinked job's folder (a rerun) never gets a brain page
        tba.make_job(store.OUTPUTS, docs["masks"], 30, job="20261001-120000-ffffffff")
        jobs = [key for k, key, _ in hosted.build_all()["pages"] if k == "brain"]
        self.assertEqual(jobs, [JOB])

    def test_strip_paths(self):
        self.assertEqual(render.strip_paths("VAULT research/raw/ig-x.ai.json (apify~instagram-scraper)"),
                         "VAULT (apify~instagram-scraper)")
        self.assertEqual(render.strip_paths(r"C:\Users\a\b.txt, then words.json"), "then")
        self.assertEqual(render.strip_paths("VAULT repurpose record, not re-checked"),
                         "VAULT repurpose record, not re-checked")

    def test_schema_refusal_fails_closed(self):
        self.creator()
        self.reel(shape=self.shape(), transcript=TRANSCRIPT)
        page = self.build()[("reel", "TESTREEL01")]
        bad = dict(page, transcript="anything")
        self.assertTrue(hosted.page_problems("reel", bad))
        with self.assertRaises(hosted.HostedError):
            hosted.check_payload("reel", bad)
        bad = copy.deepcopy(page)
        bad["stamps"]["page"] = r"page made on C:\dev\project"
        self.assertTrue(hosted.page_problems("reel", bad))


def srender_card(case) -> list[dict]:
    """The offline card lines, from the page render.render_reel writes in the test's temp folder."""
    return trs.page_data(case.render_reel())["card"]["lines"]


if __name__ == "__main__":
    unittest.main(verbosity=2)
