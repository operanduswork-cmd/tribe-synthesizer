"""Tests for the script lab, its checks and the patterns and lab pages. Run: python strategist/test_lab.py

Synthetic tests point the store at temp folders (a fake swipe file, drafts, outputs and an
VAULT tree holding a small PROOF.md). The real-data tests only read: the example draft is
checked in memory (never written), and the real pages are rendered into a temp folder.
No Apify, no Modal, no network: any HTTP call fails the test. VAULT is never written."""

import contextlib
import copy
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
# Run as a script, this folder is sys.path[0]; drop it so "render" can only mean dashboard/render.py.
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
sys.path.insert(0, str(PROJECT_ROOT))
from strategist import lab, patterns, render as srender, store  # noqa: E402

R = srender.R
CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"
CSP_CARD = CSP.replace("img-src data:;", "img-src data: file:;")   # reel cards link the private stills by path
TODAY = "2026-10-08"
TRANSCRIPT = "Velvet otters quietly audit every spreadsheet before lunch on rainy Tuesdays"
PROOF_MD = """# Proof bank

## Tier A: real outcomes

| # | System (plain name) | What it does | Result number | Source file | Name OK? | Caveat |
|---|---|---|---|---|---|---|
| A1 | Parcel hub | Pulls records into one place | 715 parcels in the live database | x/todo.md | ASK | NOT FOR POSTS (reads as fluff) |
| A2 | Booking audit | Read a booking setup for a week | 24 booked calls in 7 days | y/baseline.md | ASK | Never say 45 bookings |

## Tier E: external facts

| # | Fact | Source | Caveat |
|---|---|---|---|
| E2 | Trained on about 450 hours of scans from 25 people | paper 2026 | Never say 720 people |
| E5 | A tool with 24 settings | docs | none |

## Do not use (numbers that failed verification)

- "3,000 emails for zero rupees": test sends only
"""
CLEAN_SAY = [
    "(off camera) How many people helped build the model? 25. (off camera) And then what?",
    "So the model is basically a way to guess a reaction. You give it a short clip.",
    "About 450 hours went into it. That part took a while to read through.",
    "I'll be honest, it is not a mind reader. It learned from scans, not from my feed.",
]


def no_network(*a, **k):
    raise AssertionError("unexpected network call in a test")


def page_data(path: Path) -> dict:
    html = Path(path).read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="data-page">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


def check_static(test, path: Path) -> str:
    html = Path(path).read_text(encoding="utf-8")
    test.assertIn(f'content="{CSP_CARD if Path(path).parent.name == "reels" else CSP}"', html, path)
    for needle in ("CC BY-NC 4.0", "Built with Llama", "Llama 3.2 Community License", "Not a view forecast."):
        test.assertIn(needle, html, f"{path}: licence footer missing {needle!r}")
    test.assertNotRegex(html, r"<script[^>]+src=|<link[^>]+rel=.?stylesheet|@import|url\(\s*['\"]?https?:", path)
    test.assertNotRegex(html, r"\.(?:mp4|mov|wav|m4a|mp3)\b", path)
    return html


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def pattern(pid, kind, label, slot, k=1, n=2, j=None, m=None, reels=(), added="2026-10-08T10:00:00+00:00",
            uses=(), level=None, few=True):
    level = level or pid.split(".")[1]
    p = {"id": pid, "family": "Test family", "kind": kind, "slot": slot, "label": label,
         "level_tag": "caption" if level == "caption" else "spoken, tagged", "reels": list(reels),
         "contrast": {"outliers": {"k": k, "n": n}, "normal": {"k": j, "m": m}, "level": level},
         "by_creator": {"test.creator": {"outliers": {"k": k, "n": n}, "normal": {"k": j, "m": m}}},
         "few_reels": few, "first_seen": "2026-09-01", "last_seen": "2026-09-20", "his_uses": list(uses),
         "added_at": added}
    if level == "spoken":
        p["labels"] = "suggested"
    p["line"] = patterns.pattern_line(p)
    return p


PATTERNS = [
    pattern("hook.spoken.off-camera-question-number-answer", "hook", "off camera question number answer",
            "[Off-camera voice asks a question] → [one number as the answer]", reels=["TESTREEL01"]),
    pattern("structure.spoken.hook-setup-proof-payoff", "structure", "hook → setup → proof → payoff",
            "[hook] → [setup] → [proof] → [payoff]"),
    pattern("cta.caption.comment-keyword", "cta", "comment keyword gate", "Comment [keyword] to get [asset]",
            k=2, n=4, j=11, m=28, reels=["TESTREEL01", "NORMAL0001"], added="2026-09-01T10:00:00+00:00"),
    pattern("cta.caption.none", "cta", "no ask", "No ask at the end", k=0, n=4, j=17, m=28),
]


class LabCase(unittest.TestCase):
    """A temp swipe file, drafts folder, outputs and VAULT (with PROOF.md); no network."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lab-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, sub in (("SWIPE", "swipe"), ("DRAFTS", "drafts"), ("OUTPUTS", "outputs"), ("VAULT", "vault")):
            p = mock.patch.object(store, name, self.tmp / sub)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("urllib.request.urlopen", side_effect=no_network)
        p.start()
        self.addCleanup(p.stop)
        store.save_text(store.VAULT / "linkedin" / "PROOF.md", PROOF_MD)
        store.save_json(store.patterns_path(), {"updated_at": TODAY, "patterns": PATTERNS})
        store.save_json(store.creator_path("test.creator"), {
            "handle": "test.creator", "platform": "instagram",
            "baseline": {"n": 14, "kind": "reels only", "median": {"plays": 1000, "likes": 50, "comments": 5},
                         "excluded": {k: [] for k in store.EXCLUDED_KEYS}, "thin": True}})
        store.save_json(store.creator_items_path("test.creator"), [
            {"shortCode": "NORMAL0001", "url": "https://www.instagram.com/p/NORMAL0001/", "productType": "clips",
             "videoPlayCount": 2500, "timestamp": "2026-09-01T10:00:00.000Z", "caption": "a caption"}])
        store.save_reel({"shortcode": "TESTREEL01", "url": "https://www.instagram.com/reel/TESTREEL01/",
                         "owner": "test.creator", "posted": "2026-09-20T10:00:00.000Z",
                         "counts": {"plays": 17800, "likes": 300, "comments": 40, "as_of": "2026-10-01"},
                         "x": {"plays": 17.8}, "outlier": True, "flags": {}, "discount": None,
                         "facts": {"duration_s": 30.0},
                         "shape": {"hook_shape": {"id": "off-camera-question-number-answer", "status": "suggested"},
                                   "format": None, "cta": {"value": "comment-keyword", "status": "accepted"},
                                   "beats": [{"start": 0, "end": 3, "kind": "hook", "name": "question then number",
                                              "status": "suggested"},
                                             {"start": 3, "end": 20, "kind": "demo", "name": "method steps",
                                              "status": "accepted"},
                                             {"start": 20, "end": 25, "kind": "aside", "name": "dropped",
                                              "status": "rejected"}]},
                         "tribe": None})
        store.save_text(store.private_dir("TESTREEL01") / "transcript.txt", TRANSCRIPT + ".\n")
        self.reports = self.tmp / "reports"

    # ---- helpers

    def new(self, slug="my-draft", pids=(PATTERNS[0]["id"],), **kw):
        path, draft = lab.new_draft(slug, list(pids), today=TODAY, **kw)
        return path, draft

    def filled(self, slug="my-draft", status="draft", say=None, notes=None, variants=None, proof=("E2",)):
        path, d = self.new(slug, status=status)
        for i, b in enumerate(d["beats"]):
            b["say"] = (say or CLEAN_SAY)[i] if i < len(say or CLEAN_SAY) else ""
            b["on_screen"] = "25 people" if i == 0 else ""
            b["notes"] = [{"n": 9, "text": t} for t in ((notes or {}).get(i) or ([f"Test: try beat {i} with one cut."]
                                                                                if i < 2 else []))]
        d["variants"] = variants if variants is not None else [
            {"id": "number", "shape": "off-camera-question-number-answer", "pattern_id": PATTERNS[0]["id"],
             "line": "(off camera) How many people helped build it? 25.", "why": "Tests a number answer up front."},
            {"id": "lab-first", "shape": "authority-drop", "pattern_id": None,
             "line": "A known lab put out a model for this.", "why": "Tests the lab's name before any number."}]
        d["proof_rows"] = list(proof)
        store.save_json(path, d)
        return path, d

    def checked(self, d):
        return lab.check(copy.deepcopy(d))

    def kinds(self, res, level="error"):
        return [i["kind"] for i in res["issues"] if i["level"] == level]

    def cli(self, mod, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = mod.main(list(args))
        return rc, out.getvalue(), err.getvalue()


class TestNew(LabCase):
    def test_skeleton_has_the_contract_fields(self):
        path, d = self.new()
        self.assertEqual(path, store.DRAFTS / "20261008-my-draft.json")
        for key in ("id", "slug", "status", "target_s", "est_s", "words_per_s", "pattern_ids", "beats", "variants",
                    "proof_rows", "copycheck", "voice_check", "updated_at"):
            self.assertIn(key, d)
        self.assertEqual((d["id"], d["slug"], d["status"], d["words_per_s"]), ("20261008-my-draft", "my-draft", "draft", 2.5))
        self.assertEqual([b["kind"] for b in d["beats"]], ["hook", "setup", "proof", "payoff"])
        self.assertEqual(d["beats"][0]["slot"], PATTERNS[0]["slot"])
        for b in d["beats"]:
            self.assertEqual(set(b) >= {"name", "est_start", "est_end", "say", "on_screen", "notes"}, True)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["id"], d["id"])

    def test_structure_and_cta_patterns_shape_the_beats(self):
        _, d = self.new("s1", [PATTERNS[1]["id"]])
        self.assertEqual([b["kind"] for b in d["beats"]], ["hook", "setup", "proof", "payoff"])
        _, d = self.new("s2", [PATTERNS[2]["id"]])
        self.assertEqual([b["kind"] for b in d["beats"]][-1], "cta")
        self.assertEqual(d["beats"][-1]["slot"], PATTERNS[2]["slot"])
        _, d = self.new("s3", [PATTERNS[3]["id"]])   # "no ask" adds no CTA beat
        self.assertNotIn("cta", [b["kind"] for b in d["beats"]])

    def test_from_reel_seeds_shape_never_words(self):
        path, d = lab.new_draft("from-TESTREEL01", today=TODAY)
        self.assertEqual(d["from_reel"], "TESTREEL01")
        self.assertEqual([(b["kind"], b["name"]) for b in d["beats"]],
                         [("hook", "question then number"), ("demo", "method steps")])   # rejected beat left out
        self.assertEqual(d["beats"][0]["slot"], PATTERNS[0]["slot"])
        self.assertEqual(set(d["pattern_ids"]), {PATTERNS[0]["id"], PATTERNS[2]["id"]})
        blob = path.read_text(encoding="utf-8").lower()
        for w in ("velvet", "otters", "spreadsheet"):
            self.assertNotIn(w, blob)

    def test_refusals(self):
        self.new()
        for kw, must in ((dict(slug="no spaces"), "slug"), (dict(slug="x"), "slug"),
                         (dict(slug="ok-slug", pids=["hook.nope"]), "unknown pattern"),
                         (dict(slug="my-draft"), "already exists"), (dict(slug="long", target_s=90), "target")):
            with self.subTest(must):
                with self.assertRaises(lab.LabError) as cm:
                    self.new(**kw)
                self.assertIn(must, str(cm.exception))
        self.new(force=True)   # --force starts it again
        with self.assertRaises(lab.LabError):
            lab.new_draft("from-NOPE000001", today=TODAY)


class TestCheck(LabCase):
    def test_clean_draft_passes_and_writes_back(self):
        path, _ = self.filled()
        rc, out, _ = self.cli(lab, "check", "my-draft")
        self.assertEqual(rc, 0, out)
        d = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(d["copycheck"]["ok"] and d["voice_check"]["ok"] and d["rules_check"]["ok"], out)
        words = sum(lab.word_count(s) for s in CLEAN_SAY)
        self.assertEqual(d["est_s"], round(words / 2.5, 1))
        self.assertEqual(d["beats"][0]["est_start"], 0.0)
        self.assertEqual(d["beats"][1]["est_start"], d["beats"][0]["est_end"])
        self.assertEqual(d["beats"][-1]["est_end"], d["est_s"])
        self.assertEqual([n["n"] for b in d["beats"] for n in b["notes"]], [1, 2])   # renumbered across the draft
        self.assertEqual(d["proof_rows"][0]["row"], "E2")
        self.assertEqual(d["proof_rows"][0]["numbers"], ["25", "450"])
        self.assertEqual(d["checked_sig"], lab.content_sig(d))
        self.assertIn(d["length"]["status"], ("ok", "under", "over"))
        self.assertIn("PASS", out)

    def test_copied_run_is_blocked(self):
        say = list(CLEAN_SAY)
        say[1] = "So here is the thing: velvet otters quietly audit every spreadsheet, in my view."
        path, _ = self.filled(say=say)
        rc, out, _ = self.cli(lab, "check", "my-draft")
        self.assertEqual(rc, 1)
        cc = json.loads(path.read_text(encoding="utf-8"))["copycheck"]
        self.assertFalse(cc["ok"])
        self.assertEqual(cc["hits"][0]["run"], "velvet otters quietly audit every spreadsheet")
        self.assertIn("TESTREEL01", cc["hits"][0]["source"])
        self.assertIn("beats[1].say", cc["hits"][0]["where"])

    def test_em_dash_fails_copy_and_voice(self):
        say = list(CLEAN_SAY)
        say[2] = "About 450 hours went into it — a long read."
        d = self.checked(self.filled(say=say)[1])
        self.assertFalse(d["copycheck"]["ok"])
        self.assertIn("em_dash", self.kinds(d["voice_check"]))

    def test_numbers_must_be_in_proof(self):
        cases = {
            "not anywhere": ("We did it in 9 days.", "not in any PROOF.md row"),
            "not for posts": ("It holds 715 parcels.", "NOT FOR POSTS"),
            "do not use": ("It sent 3,000 emails.", "Do not use"),
            "undeclared row": ("It booked 24 calls.", "not in the rows this draft names"),
        }
        for what, (line, must) in cases.items():
            with self.subTest(what):
                say = list(CLEAN_SAY)
                say[2] = line
                d = self.checked(self.filled(slug="n-" + what.replace(" ", "-"), say=say)[1])
                msgs = [i["message"] for i in d["voice_check"]["issues"] if i["kind"] == "number"]
                self.assertFalse(d["voice_check"]["ok"], msgs)
                self.assertTrue(any(must in m for m in msgs), msgs)
        say = list(CLEAN_SAY)
        say[2] = "It took twenty people."
        d = self.checked(self.filled(slug="words", say=say)[1])
        self.assertIn("number_word", self.kinds(d["voice_check"]))
        # declared row that names the number: fine; no declared rows and two rows match: a warning only
        say[2] = "It booked 24 calls."
        d = self.checked(self.filled(slug="declared", say=say, proof=("E2", "A2"))[1])
        self.assertTrue(d["voice_check"]["ok"], d["voice_check"]["issues"])
        self.assertEqual({r["row"]: r["numbers"] for r in d["proof_rows"]}["A2"], ["24"])
        d = self.checked(self.filled(slug="ambiguous", say=say, proof=())[1])
        self.assertTrue(d["voice_check"]["ok"])
        self.assertIn("number", self.kinds(d["voice_check"], "warning"))
        self.assertEqual({r["row"] for r in d["proof_rows"]}, {"A2", "E5", "E2"})
        # caveat numbers never count: "Never say 45 bookings"
        say[2] = "We got 45 bookings."
        d = self.checked(self.filled(slug="caveat", say=say)[1])
        self.assertFalse(d["voice_check"]["ok"])

    def test_no_proof_file_means_no_numbers(self):
        (store.VAULT / "linkedin" / "PROOF.md").unlink()
        d = self.checked(self.filled()[1])
        self.assertFalse(d["voice_check"]["ok"])
        self.assertTrue(any("PROOF.md not found" in i["message"] for i in d["voice_check"]["issues"]))

    def test_voice_warnings_and_errors(self):
        say = list(CLEAN_SAY)
        say[1] = ("So is this the model you want for your next clip? You know, it is pretty clean. I'll be honest, "
                  "it is a bit buggy.")
        say[3] = ("It took a long time and a lot of reading and a lot of small notes and a lot of late nights to get "
                  "the whole thing to a place where it made sense to anyone. It also took a long time and a lot of "
                  "reading and a lot of small notes and late nights to write this second very long sentence down.")
        d = self.checked(self.filled(say=say)[1])
        warns = self.kinds(d["voice_check"], "warning")
        for k in ("question", "filler", "sentence_length", "honesty"):
            self.assertIn(k, warns)
        self.assertIn("sentence_length", self.kinds(d["voice_check"]))   # two sentences over 25 words
        # an off-camera question is not a question to the viewer
        d = self.checked(self.filled(slug="clean2")[1])
        self.assertNotIn("question", self.kinds(d["voice_check"], "warning"))
        say = list(CLEAN_SAY)
        say[1] = "So the model gives you a seamless way to read a clip."
        d = self.checked(self.filled(slug="never", say=say)[1])
        self.assertIn("never_word", self.kinds(d["voice_check"]))

    def test_rules(self):
        cases = {
            "no Test:": dict(notes={0: ["Try one cut here."]}),
            "cause word": dict(notes={0: ["Test: one cut, because the hook drags."]}),
            "pronoun": dict(notes={0: ["Test: open the way her reel does."]}),
            "wall": dict(notes={0: ["Test: the 17.8x reel had a peak here."]}),
            "banned word in the script": dict(say=["(off camera) Is it viral? 25."] + CLEAN_SAY[1:]),
            "counts and brain in a script line": dict(say=CLEAN_SAY[:1] + ["The brain lines and the plays agree."]
                                                      + CLEAN_SAY[2:]),
            "@handle": dict(say=CLEAN_SAY[:1] + ["So @someone said this model reads minds."] + CLEAN_SAY[2:]),
            "bare handle": dict(notes={1: ["Test: the test.creator opening, in your words."]}),
            "variant with no why": dict(variants=[{"id": "a", "shape": "authority-drop", "line": "A lab put it out.",
                                                   "why": ""}]),
            "duplicate variant ids": dict(variants=[{"id": "a", "shape": "authority-drop", "line": "One.", "why": "x"},
                                                    {"id": "a", "shape": "authority-drop", "line": "Two.", "why": "y"}]),
        }
        for what, kw in cases.items():
            with self.subTest(what):
                d = self.checked(self.filled(slug="r-" + re.sub(r"[^a-z]+", "-", what.lower()).strip("-"), **kw)[1])
                self.assertFalse(d["rules_check"]["ok"] and d["voice_check"]["ok"], what)
        # his own speech may say "because": only notes and whys get the cause-word check
        say = list(CLEAN_SAY)
        say[1] = "So I built it because the old way was slow."
        d = self.checked(self.filled(slug="his-because", say=say)[1])
        self.assertTrue(d["rules_check"]["ok"], d["rules_check"]["issues"])
        _, dd = self.filled(slug="unknown-pattern")
        dd["pattern_ids"].append("hook.caption.nope")
        self.assertIn("pattern", self.kinds(self.checked(dd)["rules_check"], "warning"))

    def test_length_status(self):
        self.assertEqual(lab.length_check(31.0, 30)["status"], "ok")
        self.assertEqual(lab.length_check(36.0, 30)["status"], "over")
        self.assertEqual(lab.length_check(20.0, 30)["status"], "under")
        self.assertEqual(lab.word_count("(off camera) How are you? Fine."), 4)

    def test_cli_codes(self):
        self.assertEqual(self.cli(lab, "check", "nope")[0], 2)
        self.assertEqual(self.cli(lab, "new", "bad slug")[0], 2)
        self.assertEqual(self.cli(lab, "new", "fine-one", "--pattern", PATTERNS[0]["id"])[0], 0)
        rc, out, _ = self.cli(lab, "list")
        self.assertEqual(rc, 0)
        self.assertIn("fine-one", out)
        rc, out, _ = self.cli(lab, "check", "fine-one", "--dry-run", "--json")
        self.assertEqual(rc, 0)   # empty beats are warnings, not failures
        self.assertIn("rules_check", json.loads(out))


class TestLabPage(LabCase):
    def test_lab_page(self):
        path, _ = self.filled()
        self.cli(lab, "check", "my-draft")
        out = srender.render_lab("my-draft", self.reports, log=lambda *a: None)
        self.assertEqual(out, self.reports / "swipe" / "lab" / "20261008-my-draft.html")
        html = check_static(self, out)
        d = page_data(out)
        self.assertEqual(len(d["beats"]), 4)
        self.assertEqual([n["n"] for b in d["beats"] for n in b["notes"]], [1, 2])
        self.assertTrue(all(n["text"].startswith("Test:") for b in d["beats"] for n in b["notes"]))
        self.assertEqual([v["id"] for v in d["variants"]], ["number", "lab-first"])
        self.assertIn("1 of 2 tagged outliers", d["variants"][0]["pattern"])
        self.assertEqual(d["variants"][1]["pattern"], "not in the swipe patterns yet")
        self.assertEqual(d["variants"][0]["cmd"], "/script 20261008-my-draft variant number this but ")
        self.assertEqual(d["commands"]["this_but"], "/script 20261008-my-draft this but ")
        self.assertEqual([b["state"] for b in d["badges"]][:3], ["ok", "ok", "ok"])
        self.assertIsNone(d["stale"])
        pair = " ".join(d["hook_pair"])
        for must in ("D23", "$0.03 to $0.07", "average-brain response", "one scale", "not your audience"):
            self.assertIn(must, pair)
        self.assertEqual(d["proof"][0]["row"], "E2")
        # unordered: no numbered list of variants, no rank words
        template = (srender.TEMPLATES / "lab.html").read_text(encoding="utf-8")
        self.assertNotRegex(template, r'id="variants"[^>]*>\s*<ol')
        self.assertNotRegex(html.lower(), r"\b(?:best|ranked first|top pick)\b")
        R.check_mixed_layers([("page", s) for s in strings(d) if s not in (R.WALL_SENTENCE,)])

    def test_stale_and_unchecked(self):
        path, d = self.filled()
        p = page_data(srender.render_lab("my-draft", self.reports, log=lambda *a: None))
        self.assertIn("Not checked yet", p["stale"])
        self.assertEqual(p["badges"][0]["state"], "unchecked")
        self.cli(lab, "check", "my-draft")
        d = json.loads(path.read_text(encoding="utf-8"))
        d["beats"][1]["say"] += " One more line."
        store.save_json(path, d)
        p = page_data(srender.render_lab("my-draft", self.reports, log=lambda *a: None))
        self.assertIn("Changed since the last check", p["stale"])
        self.assertEqual(p["badges"][0]["state"], "stale")

    def test_lab_page_refuses_bad_text(self):
        for what, kw in (("banned word in a note", dict(notes={0: ["Test: the winning hook first."]})),
                         ("cause word in a why", dict(variants=[{"id": "a", "shape": "authority-drop", "line": "One.",
                                                                 "why": "It works because labs sound credible."}])),
                         ("banned word in the script", dict(say=["(off camera) Will it go viral? 25."] + CLEAN_SAY[1:]))):
            with self.subTest(what):
                self.filled(slug="bad-" + str(len(what)), **kw)
                with self.assertRaises(R.RenderError):
                    srender.render_lab("bad-" + str(len(what)), self.reports, log=lambda *a: None)
        with self.assertRaises(R.RenderError):
            srender.render_lab("no-such-draft", self.reports, log=lambda *a: None)


class TestPatternsPage(LabCase):
    def doc(self):
        return {"updated_at": TODAY, "patterns": copy.deepcopy(PATTERNS),
                "population": {"caption": {"creators": {"test.creator": {"outliers": 4, "normal": 28}}, "outliers": 4,
                                           "normal": 28, "left_out": {"paid": ["P1"], "fresh": []}},
                               "spoken": {"outliers": ["TESTREEL01"], "normal": [], "left_out": {},
                                          "compare_from": "3 tagged normal reels of the same creators"}}}

    def render(self, doc=None, today=None):
        import datetime as dt
        with mock.patch.object(patterns, "build", return_value=doc or self.doc()):
            return srender.render_patterns(self.reports, today=today or dt.date(2026, 10, 8), log=lambda *a: None)

    def test_patterns_page(self):
        doc = self.doc()
        doc["patterns"][2]["his_uses"] = ["20261008-my-draft"]
        self.filled()
        out = self.render(doc)
        self.assertEqual(out, self.reports / "swipe" / "patterns.html")
        check_static(self, out)
        d = page_data(out)
        self.assertEqual([t["key"] for t in d["tabs"]], ["hook", "structure", "cta", "format"])
        self.assertEqual({t["key"]: t["n"] for t in d["tabs"]}, {"hook": 1, "structure": 1, "cta": 2, "format": 0})
        by = {p["id"]: p for p in d["patterns"]}
        for p in d["patterns"]:
            R.check_pattern_line(p["contrast"])
            for line in p["by_creator"]:
                R.check_pattern_line(line)
            if p["zero"]:   # no counted outlier carries it: folded away, nothing to recreate
                self.assertIsNone(p["recreate"])
            else:
                self.assertTrue(p["recreate"].startswith("/script new try-") and p["recreate"].endswith(p["id"]))
        gate = by["cta.caption.comment-keyword"]
        self.assertEqual(gate["contrast"], "outliers 2/4 vs normal 11/28")
        self.assertEqual(gate["bars"], {"o": [2, 4], "m": [11, 28]})
        self.assertFalse(gate["new"])                   # first seen 2026-09-01, more than 7 days back
        self.assertEqual(gate["uses"], "you used it: 1 draft")
        self.assertEqual(gate["use_links"], [{"id": "20261008-my-draft", "href": "lab/20261008-my-draft.html"}])
        self.assertEqual([s["sc"] for s in gate["sources"]], ["TESTREEL01", "NORMAL0001"])
        self.assertEqual(gate["sources"][0]["href"], "reels/TESTREEL01.html")
        self.assertEqual(gate["sources"][0]["counts"], "17,800 plays · 17.8x own median (14 reels)")
        self.assertTrue(gate["sources"][1]["external"])
        self.assertEqual(gate["sources"][1]["counts"], "2,500 plays · 2.5x own median (14 reels)")
        hook = by["hook.spoken.off-camera-question-number-answer"]
        self.assertEqual(hook["contrast"], "1 of 2 tagged outliers · outliers only, no comparison yet")
        self.assertIsNone(hook["bars"])
        self.assertTrue(hook["new"] and hook["few"] and hook["suggested"])
        self.assertIn("completeness unknown", hook["completeness"])
        self.assertEqual(hook["uses"], "you used it: never")
        self.assertEqual(by["cta.caption.none"]["sources"], [])
        self.assertIn("Only normal reels", by["cta.caption.none"]["sources_empty"])
        self.assertTrue(by["cta.caption.none"]["zero"])
        self.assertFalse(gate["zero"])
        self.assertEqual(d["header"], "Patterns")
        self.assertTrue(d["stamp"].startswith("4 patterns · 3 new since 2026-10-01"), d["stamp"])
        # the short list on top: outlier share above the normal share, each line with its contrast
        self.assertEqual([l["text"] for l in d["lead"]], ["CTA: comment keyword gate (caption) · outliers 2/4 vs normal 11/28"])
        for l in d["lead"]:
            R.check_pattern_line(l["text"])
        # counts show only in the source lists; no brain words anywhere in the page data
        for p in d["patterns"]:
            rest = {k: v for k, v in p.items() if k != "sources"}
            self.assertNotRegex(json.dumps(rest), r"\bplays\b|\d+(?:\.\d+)?x own median")
        for s in strings(d):
            self.assertIsNone(R.BRAIN_TERMS_RE.search(s), s)

    def test_pattern_without_contrast_is_refused(self):
        doc = self.doc()
        doc["patterns"][2]["contrast"]["outliers"] = {"k": 5, "n": 4}   # impossible
        with self.assertRaises(R.RenderError):
            self.render(doc)

    def test_empty_swipe_file(self):
        shutil.rmtree(store.SWIPE)
        out = srender.render_patterns(self.reports, log=lambda *a: None)
        d = page_data(out)
        self.assertEqual(d["patterns"], [])
        self.assertTrue(d["stamp"].startswith("0 patterns"))

    def test_page_level_notes_and_hidden_uses(self):
        doc = self.doc()
        for p in doc["patterns"]:
            p["few_reels"], p["added_at"] = True, "2026-10-07T00:00:00+00:00"
        d = page_data(self.render(doc))   # no draft of his own in this temp folder
        self.assertTrue(all(not p["show_new"] and not p["show_few"] for p in d["patterns"]))
        self.assertTrue(any("few reels" in n for n in d["notes"]) and any("All 4 patterns are new" in n for n in d["notes"]))
        self.assertTrue(all(p["uses"] is None for p in d["patterns"]))   # "you used it: never" waits for his drafts

    def test_same_label_twice_names_its_level(self):
        doc = self.doc()
        twin = copy.deepcopy(doc["patterns"][2])
        twin.update(id="cta.spoken.comment-keyword", contrast={"outliers": {"k": 1, "n": 1}, "normal": {"k": None, "m": None},
                                                               "level": "spoken"}, by_creator={})
        doc["patterns"].append(twin)
        doc["patterns"][3]["same_reels_as"] = "cta.caption.comment-keyword"
        d = page_data(self.render(doc))
        by = {p["id"]: p for p in d["patterns"]}
        self.assertEqual(by["cta.caption.comment-keyword"]["label"], "comment keyword gate · caption")
        self.assertEqual(by["cta.spoken.comment-keyword"]["label"], "comment keyword gate · spoken")
        self.assertIn("Same reels as comment keyword gate", by["cta.caption.none"]["same"])

    def test_render_cli(self):
        self.filled()
        run = lambda *a: self.cli(srender, *a, "--reports-dir", str(self.reports))[0]  # noqa: E731
        with mock.patch.object(patterns, "build", return_value=self.doc()):
            self.assertEqual(run("patterns"), 0)
            self.assertEqual(run("lab", "my-draft"), 0)
            self.assertEqual(run("lab", "nope-nope"), 2)
        self.assertTrue((self.reports / "swipe" / "lab" / "20261008-my-draft.html").is_file())


class TestTemplates(unittest.TestCase):
    def test_templates_pass_the_rule_checks(self):
        for name in ("patterns.html", "lab.html"):
            text = (srender.TEMPLATES / name).read_text(encoding="utf-8")
            R.check_authored([(name, text)])
            self.assertEqual(text.count(srender.SLOT), 1)
            self.assertIn(f'content="{CSP}"', text)

    def test_page_js_syntax(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("patterns.html", "lab.html"):
                scripts = re.findall(r"<script>(.*?)</script>", (srender.TEMPLATES / name).read_text(encoding="utf-8"), re.S)
                self.assertEqual(len(scripts), 1, name)
                js = Path(tmp) / f"{name}.js"
                js.write_text(scripts[0], encoding="utf-8")
                r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{name}: {r.stderr}")

    def test_coach_rules_are_written_down(self):
        coach = (HERE / "coach.md").read_text(encoding="utf-8")
        for must in ("EXTRACT", "DRAFT", "Never reads", "PROOF.md", "VOICE.md", "unordered", "This but",
                     "python -m strategist.lab check", "No creator framing", "(off camera)"):
            self.assertIn(must, coach)
        self.assertNotIn("—", coach)


class TestRealData(unittest.TestCase):
    """Read-only: the example draft passes its check in memory, and the real pages render to a temp folder."""

    def test_example_draft_passes(self):
        examples = [d for d in lab.list_drafts() if d.get("status") == "example"]
        if not examples:
            self.skipTest("no example draft on this machine")
        with mock.patch("urllib.request.urlopen", side_effect=no_network):
            for ex in examples:
                d = lab.check(copy.deepcopy(ex), include_vault=store.VAULT.is_dir())
                self.assertTrue(lab.passed(d), lab.summary_lines(d))
                self.assertEqual(d["length"]["status"], "ok")
                self.assertGreaterEqual(len(d["variants"]), 3)
                self.assertTrue(all(n["text"].startswith("Test:") for b in d["beats"] for n in b["notes"]))
                self.assertTrue(25 <= d["est_s"] <= 35, d["est_s"])

    def test_real_pages(self):
        if not store.list_reels():
            self.skipTest("no swipe file on this machine")
        with mock.patch("urllib.request.urlopen", side_effect=no_network), \
                tempfile.TemporaryDirectory(prefix="lab-real-") as tmp:
            paths = srender.render_all(tmp, log=lambda *a: None)
            self.assertEqual(len(paths), len(store.list_reels()) + 2 + len(lab.list_drafts()))
            for p in paths:
                check_static(self, p)
            d = page_data(Path(tmp) / "swipe" / "patterns.html")
            for p in d["patterns"]:
                R.check_pattern_line(p["contrast"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
