"""Local tests for the swipe pages (board and reel cards). Run: python strategist/test_render_swipe.py
Synthetic data (creator "testcreator", shortcodes like "TESTREEL01") in temp folders, plus one
read-only pass over the real swipe file that writes its pages to a temp folder. No Apify, no
Modal, no network: any HTTP call fails the test. The real swipe/, outputs/, reports/ and VAULT
are never written."""

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
from strategist import render as srender, store  # noqa: E402

R = srender.R
sys.path.insert(0, str(PROJECT_ROOT / "dashboard"))
import test_render as dash  # noqa: E402  the dashboard's synthetic report and notes builders

JOB = "20261001-120000-0123abcd"
JPEG = b"\xff\xd8\xff\xe0synthetic-jpeg\xff\xd9"
CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"
# A reel card shows the private stills by file path (the page holds no copy), so it also allows file: images.
CSP_CARD = CSP.replace("img-src data:;", "img-src data: file:;")
ALLOWED_SORT_FIELDS = {"x", "plays", "posted", "duration", "handle"}
VIDEO_RE = re.compile(r"\.(?:mp4|mov|m4v|webm|mkv|avi|wav|m4a|mp3)\b", re.IGNORECASE)


def no_network(*a, **k):
    raise AssertionError("unexpected network call in a test")


def page_data(path: Path) -> dict:
    html = Path(path).read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="data-page">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


def check_static(test: unittest.TestCase, path: Path) -> str:
    """Every page: CSP, licence footer, no network loads, no video paths."""
    html = Path(path).read_text(encoding="utf-8")
    csp = CSP_CARD if Path(path).parent.name == "reels" else CSP
    test.assertIn(f'content="{csp}"', html, path)
    for needle in ("CC BY-NC 4.0", "Built with Llama", "Llama 3.2 Community License", "Not a view forecast."):
        test.assertIn(needle, html, f"{path}: licence footer missing {needle!r}")
    test.assertNotRegex(html, r"<script[^>]+src=|<link[^>]+rel=.?stylesheet|@import|url\(\s*['\"]?https?:", path)
    test.assertIsNone(VIDEO_RE.search(html), f"{path}: video path on the page")
    return html


def check_card(test: unittest.TestCase, card: dict) -> None:
    """The card contract, and the counts strip never inside a card line."""
    R.validate_card(card)
    for ln in card["lines"]:
        text = R.card_line_text(ln)
        test.assertIsNone(R.COUNT_TERMS_RE.search(text), f"counts in a card line: {text!r}")
    if card.get("counts"):
        test.assertIsNone(R.BRAIN_TERMS_RE.search(card["counts"]["text"]), card["counts"])


class SwipeCase(unittest.TestCase):
    """Points the store at a temp folder and blocks the network."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="swipe-render-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, sub in (("SWIPE", "swipe"), ("DRAFTS", "drafts"), ("OUTPUTS", "outputs"), ("VAULT", "vault")):
            p = mock.patch.object(store, name, self.tmp / sub)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("urllib.request.urlopen", side_effect=no_network)
        p.start()
        self.addCleanup(p.stop)
        self.reports = self.tmp / "reports"
        self.log = []

    # ---- fixtures

    def creator(self, handle="testcreator", n=25, median=1000, kind="reels only", items=True):
        c = {"handle": handle, "platform": "instagram", "baseline": {
            "n": n, "kind": kind, "window": {"from": "2026-08-01", "to": "2026-09-20"},
            "median": {"plays": median, "likes": 50, "comments": 5},
            "excluded": {k: [] for k in store.EXCLUDED_KEYS}, "source": "synthetic test pull",
            "pulled_at": "2026-10-01T12:00:00+00:00", "pulled_at_note": "Apify pull", "thin": n < 20}}
        store.save_creator(c)
        if items:
            store.save_json(store.creator_items_path(handle), [
                {"shortCode": f"NORMAL{i:04d}", "productType": "clips", "videoPlayCount": 800 + 20 * i,
                 "likesCount": 40, "commentsCount": 4, "timestamp": "2026-09-01T10:00:00.000Z", "videoDuration": 30.0}
                for i in range(n)])
        return c

    def reel(self, sc="TESTREEL01", plays=5000, owner="testcreator", tribe=None, shape=None, facts=None,
             discount=None, stills=3, transcript="Synthetic opening line. Second line here. Third line."):
        facts = facts if facts is not None else {
            "duration_s": 29.6, "first_word_s": 0.4, "words_per_s": 2.7, "text_on_screen_0s": True,
            "cta": {"type": "comment-keyword", "t": 26.0},
            "source": {"duration_s": "synthetic", "words": "synthetic words", "cta": "synthetic"}}
        r = {"shortcode": sc, "url": f"https://www.instagram.com/reel/{sc}/", "owner": owner,
             "posted": "2026-09-20T10:00:00.000Z", "type": "reel",
             "counts": {"plays": plays, "likes": 300, "comments": 40, "as_of": "2026-10-01T12:00:00+00:00",
                        "as_of_note": "Apify pull", "source_field": dict(store.SOURCE_FIELD)},
             "x": {}, "outlier": False, "flags": {"paid": False}, "discount": discount, "facts": facts,
             "shape": shape or store.empty_shape(), "tribe": tribe, "imported_from": "synthetic",
             "added_at": "2026-10-01T12:00:00+00:00"}
        store.save_reel(store.derive(r, store.load_creator(owner)))
        priv = store.private_dir(sc)
        if transcript:
            store.save_text(priv / "transcript.txt", transcript + "\n")
        for i in range(stills):
            t = [0.5, 2.0, 26.0, 12.5, 20.0][i]
            role = ["open", "early", "cta", "peak", "mid"][i]
            (priv / "stills").mkdir(parents=True, exist_ok=True)
            (priv / "stills" / f"{i + 1}-{role}-{t:.1f}s.jpg").write_bytes(JPEG)
        return r

    def tribe_job(self, sc="TESTREEL01", job=JOB, mock_flag=False, notes=True):
        d = store.OUTPUTS / job
        d.mkdir(parents=True, exist_ok=True)
        rep = dash.make_report(job_id=job, mock=mock_flag)
        rep["source"]["source_url"] = f"https://www.instagram.com/reel/{sc}/"
        (d / "report.json").write_text(json.dumps(rep), encoding="utf-8")
        (d / "predict_meta.json").write_text(json.dumps({"mock": mock_flag}), encoding="utf-8")
        (d / "events.json").write_text(json.dumps({"words": [{"text": "hello", "start": 0.4, "stop": 0.8}]}),
                                       encoding="utf-8")
        if notes:
            (d / "notes.json").write_text(json.dumps(dash.make_notes(job_id=job)), encoding="utf-8")
        return {"job_id": job, "run_date": "2026-10-01", "scale": "within-reel"}

    def shape(self, hook="question-then-number-answer", cta="comment-keyword", beat_name="demo"):
        return {"hook_shape": {"id": hook, "status": "accepted"},
                "format": {"value": "talking-head", "status": "suggested"},
                "cta": {"value": cta, "status": "suggested"},
                "beats": [{"start": 0, "end": 3, "kind": "hook", "name": "question", "status": "accepted"},
                          {"start": 3, "end": 20, "kind": "demo", "name": beat_name, "status": "suggested"},
                          {"start": 20, "end": 25, "kind": "aside", "name": "dropped idea", "status": "rejected"}]}

    def render_reel(self, sc="TESTREEL01"):
        return srender.render_reel(sc, self.reports, log=self.log.append)

    def render_board(self):
        return srender.render_board(self.reports, log=self.log.append)

    def refused(self, fn, must=None):
        with self.assertRaises(R.RenderError) as cm:
            fn()
        if must:
            self.assertIn(must, str(cm.exception))
        return str(cm.exception)


class TestReelCard(SwipeCase):
    def test_facts_card_without_tribe(self):
        self.creator()
        self.reel(shape=self.shape())
        out = self.render_reel()
        self.assertEqual(out, self.reports / "swipe" / "reels" / "TESTREEL01.html")
        check_static(self, out)
        d = page_data(out)
        card = d["card"]
        check_card(self, card)
        self.assertEqual([ln["tag"] for ln in card["lines"]], ["HOOK", "BEATS", "PACE", "TRY", "TRY"])
        self.assertIsNone(card["footnote"])
        self.assertIn("question then number answer", card["lines"][0]["text"])
        self.assertEqual(card["lines"][1]["text"], "question → demo (suggested)")  # the rejected beat is left out
        self.assertEqual(card["lines"][2]["time"], "0:26")
        self.assertTrue(card["lines"][3]["text"].startswith("Test: open your draft with the same hook shape"))
        self.assertEqual([b["name"] for b in d["beats"]], ["question", "demo"])
        # No TRIBE read: no word hits, and the private transcript is never copied into the page.
        self.assertEqual((d["transcript"]["mode"], d["transcript"]["items"]), ("hits", []))
        self.assertIn("stays private", d["transcript"]["empty"])
        self.assertNotIn("Synthetic opening line", out.read_text(encoding="utf-8"))
        self.assertIn("no TRIBE run", d["about"]["stamps"])
        self.assertIn("accepted by you: 2 of 6 labels", d["about"]["stamps"])
        self.assertIsNone(d["about"]["framing"])
        self.assertEqual(d["recreate"], "/script new from-TESTREEL01")

    def test_tribe_card_uses_report_and_notes(self):
        self.creator()
        self.reel(tribe=self.tribe_job(), shape=self.shape())
        d = page_data(self.render_reel())
        card = d["card"]
        check_card(self, card)
        self.assertEqual([ln["tag"] for ln in card["lines"]], ["HOOK", "HIGH", "FLAT", "TRY", "TRY"])
        self.assertEqual(card["footnote"], R.CARD_FOOTNOTE)
        self.assertEqual(card["lines"][1]["time"], "0:12")
        self.assertEqual(card["lines"][2]["time"], "0:20-0:24")
        self.assertEqual(card["lines"][3]["text"], "Test: in your draft, hold the main shot a beat longer in one cut "
                                                   "and compare retention.")
        self.assertEqual(d["transcript"]["mode"], "hits")
        # the creator's words are exempt from the banned list ("POST" in a word hit)
        self.assertEqual([h["text"] for h in d["transcript"]["items"]], ["post it POST", "today"])
        self.assertIn("not rendered yet", d["lanes"]["text"])
        self.assertIn("TRIBE run 2026-10-01", d["about"]["stamps"])
        self.assertIn("average brain", d["about"]["framing"])
        self.assertEqual(sum(t.count(R.WALL_SENTENCE) for t in d["about"]["lines"]), 1)

    def test_tribe_card_links_the_report_page(self):
        self.creator()
        self.reel(tribe=self.tribe_job())
        page = self.reports / "2026-10-01-synthetic-test" / "report.html"
        page.parent.mkdir(parents=True)
        page.write_text(f'<script type="application/json">{{"job_id":"{JOB}"}}</script>', encoding="utf-8")
        d = page_data(self.render_reel())
        self.assertEqual(d["lanes"]["href"], "../../2026-10-01-synthetic-test/report.html")

    def test_tribe_card_without_notes_uses_fact_ideas(self):
        self.creator()
        self.reel(tribe=self.tribe_job(notes=False))
        card = page_data(self.render_reel())["card"]
        self.assertEqual(card["mode"], "tribe")
        self.assertTrue(all("your draft" in ln["text"] for ln in card["lines"][3:]))

    def test_missing_tribe_folder_falls_back_to_facts(self):
        self.creator()
        self.reel(tribe={"job_id": JOB, "run_date": "2026-10-01", "scale": "within-reel"})
        d = page_data(self.render_reel())
        self.assertEqual(d["card"]["mode"], "facts")
        self.assertIn("not on this laptop", d["lanes"]["text"])

    def test_mock_tribe_output_refused(self):
        self.creator()
        self.reel(tribe=self.tribe_job(mock_flag=True))
        self.refused(self.render_reel, "mock")

    def test_counts_strip_apart_from_the_card(self):
        self.creator(n=14, median=1000)
        self.reel(plays=17800, tribe=self.tribe_job())
        out = self.render_reel()
        d = page_data(out)
        strip = d["card"]["counts"]["text"]
        self.assertIn("17,800 plays", strip)
        self.assertIn("17.8x own median (14 reels)", strip)
        self.assertIn("thin baseline", strip)
        check_card(self, d["card"])
        html = out.read_text(encoding="utf-8")
        body = html[html.index("<body>"):]
        self.assertLess(body.index('id="counts"'), body.index('id="snippet"'))
        snippet = body[body.index('id="snippet"'):body.index("</section>", body.index('id="snippet"'))]
        self.assertNotIn('id="counts"', snippet)

    def test_baseline_of_other_post_types_is_not_called_reels(self):
        self.creator(n=11, kind="all post types (VAULT record), not reels only", items=False)
        self.reel()
        d = page_data(self.render_reel())
        self.assertIn("(11 posts, all types)", d["card"]["counts"]["text"])
        self.assertNotIn("reels)", d["card"]["counts"]["text"])

    def test_one_x_for_every_page(self):
        # 312,098 / 17,385.5 = 17.9516: stored as 17.95 (17.9x when rounded twice); the exact value prints 18.0x.
        self.creator(n=14, median=17385.5)
        self.reel(plays=312098)
        stored = store.load_reel("TESTREEL01")
        self.assertEqual(stored["x"]["plays"], 17.95)
        strip = page_data(self.render_reel())["card"]["counts"]["text"]
        self.assertIn("18.0x own median (14 reels)", strip)
        self.assertEqual(R.counts_strip(dict(stored, _baseline=store.load_creator("testcreator")["baseline"]))["text"],
                         strip)
        r = page_data(self.render_board())["reels"][0]
        self.assertTrue(r["counts"].startswith("312,098 plays · 18.0x own median"), r["counts"])

    def test_strip_carries_every_counts_flag(self):
        self.creator(n=25, median=10000)
        facts = {"duration_s": 29.0, "first_word_s": 0.0, "words_per_s": 3.5, "text_on_screen_0s": None,
                 "cta": {"type": "comment-keyword", "t": None},
                 "source": {"cta": "inferred: 6 of the top comments are one repeated word"}}
        r = self.reel(plays=7500, facts=facts)
        r = store.load_reel("TESTREEL01")
        r["counts"]["as_of"], r["posted"] = "2026-09-21T09:00:00+00:00", "2026-09-20T10:00:00.000Z"
        r["counts"]["as_of_note"] = "pull date unknown (file date); counts from VAULT's repurpose record"
        store.save_reel(store.derive(r, store.load_creator("testcreator")))
        d = page_data(self.render_reel())
        strip = d["card"]["counts"]["text"]
        for want in ("fresh when pulled, counts not settled", "under 2x: taste, not proof",
                     "gated call to action, guessed from comments", "file date 2026-09-21 (pull date unknown)"):
            self.assertIn(want, strip)
        pace = d["card"]["lines"][2]
        self.assertEqual(pace["tag"], "PACE")
        self.assertIn("comment keyword, guessed: not seen or heard", pace["text"])
        board = page_data(self.render_board())["reels"][0]
        self.assertIn("gated CTA, guessed from comments", [b["label"] for b in board["badges"]])
        self.assertEqual(board["as_of"], "file date 2026-09-21 (pull date unknown)")

    def test_stills_capped_and_chips_open_the_nearest(self):
        self.creator()
        self.reel(tribe=self.tribe_job(), stills=5)
        out = self.render_reel()
        d = page_data(out)
        self.assertEqual(len(d["stills"]), 4)
        # Linked by file path from the private folder, never embedded: the page alone carries no frame.
        self.assertNotIn("data:image", out.read_text(encoding="utf-8"))
        for s in d["stills"]:
            self.assertTrue((out.parent / s["src"]).resolve().is_file(), s["src"])
            self.assertIn("/private/stills/", s["src"])
        self.assertEqual([s["chip"] for s in d["stills"]], ["0:00", "0:02", "0:12", "0:26"])  # time order
        by_tag = {ln["tag"]: ln for ln in d["card"]["lines"]}
        self.assertEqual(d["stills"][by_tag["HOOK"]["still"]]["chip"], "0:00")
        self.assertEqual(d["stills"][by_tag["HIGH"]["still"]]["chip"], "0:12")
        self.assertEqual(d["stills"][by_tag["FLAT"]["still"]]["chip"], "0:26")  # 0:20-0:24: the 0:26 still is 1 s past it

    def test_cta_none_and_generic_fallbacks(self):
        self.creator()
        self.reel(shape=self.shape(cta="none"))
        ideas = srender.fact_ideas(store.load_reel("TESTREEL01"))
        self.assertIn("Test: try your draft both with no call to action and with one short one at the end.", ideas)
        self.assertFalse(any("(none)" in i for i in ideas))
        bare = {"facts": {}, "shape": {}}
        self.assertEqual(srender.fact_ideas(bare), list(srender.GENERIC_IDEAS))
        self.creator(handle="bare")
        self.reel(sc="TESTREEL09", owner="bare", facts={}, transcript=None, stills=0)
        card = page_data(self.render_reel("TESTREEL09"))["card"]
        self.assertEqual([ln["text"] for ln in card["lines"][3:]], list(srender.GENERIC_IDEAS))

    def test_authored_text_violations_refused(self):
        self.creator()
        cases = {
            "cause": dict(discount={"reason": "giveaway, because the counts jumped", "by": "user", "at": "2026-10-02"}),
            "pronoun": dict(discount={"reason": "her giveaway reel", "by": "user", "at": "2026-10-02"}),
            "banned": dict(shape=self.shape(beat_name="viral demo")),
            "wall": dict(shape=self.shape(beat_name="17.8x peak")),
        }
        for what, kw in cases.items():
            with self.subTest(what):
                self.reel(**kw)
                self.refused(self.render_reel)
        self.reel(shape=self.shape(hook="performance-hook"))
        self.refused(self.render_reel, "HOOK")

    def test_video_path_refused(self):
        self.creator()
        facts = {"duration_s": 29.6, "first_word_s": 0.4, "words_per_s": 2.7, "text_on_screen_0s": None, "cta": None,
                 "source": {"duration_s": "ffprobe of C:/temp/clip.mp4"}}
        self.reel(facts=facts)
        self.refused(self.render_reel, "video")

    def test_transcript_never_copied_into_the_card(self):
        self.creator()
        self.reel(transcript="This went viral because of one trick. She said it twice.")
        html = self.render_reel().read_text(encoding="utf-8")   # the creator's words aren't checked: they aren't there
        self.assertNotIn("viral because", html)

    def test_cards_differ_without_a_tribe_read(self):
        self.creator()
        self.reel(shape=self.shape())
        one = page_data(self.render_reel())["card"]["lines"][4]["text"]
        self.assertEqual(one, "Test: in your draft, give the demo beat about 17 seconds, like this reel's demo.")
        self.reel(sc="TESTREEL02", shape=dict(self.shape(), beats=[
            {"start": 0, "end": 4, "kind": "hook", "name": "cold open", "status": "suggested"},
            {"start": 4, "end": 15, "kind": "proof", "name": "screen proof", "status": "suggested"}]))
        two = page_data(self.render_reel("TESTREEL02"))["card"]["lines"][4]["text"]
        self.assertNotEqual(one, two)


class TestBoard(SwipeCase):
    def make_three(self):
        self.creator(n=25, median=1000)
        self.creator(handle="other.creator", n=11, median=2000, kind="all post types (VAULT record), not reels only",
                     items=False)
        self.reel("TESTREEL01", plays=5000, tribe=self.tribe_job(), shape=self.shape())
        self.reel("TESTREEL02", plays=1500, discount={"reason": "giveaway reel", "by": "user", "at": "2026-10-02"})
        self.reel("TESTREEL03", plays=60000, owner="other.creator")
        store.log_fetch("@testcreator last 30 posts", 30, 0.081, "apify~instagram-scraper", True)

    def test_board_renders(self):
        self.make_three()
        out = self.render_board()
        self.assertEqual(out, self.reports / "swipe" / "index.html")
        check_static(self, out)
        d = page_data(out)
        self.assertEqual(d["header"], "Swipe file")
        self.assertEqual(d["stamp"], ["2 creators · 3 reels", "counts as of 2026-10-01, refreshed by hand"])
        self.assertEqual(d["nav"][0], {"text": "Patterns", "href": "patterns.html"})
        self.assertTrue(any("python -m strategist.reel add @handle" in t for t in d["about"]))
        self.assertEqual([r["sc"] for r in d["reels"]], ["TESTREEL03", "TESTREEL01", "TESTREEL02"])  # x, largest first
        r1 = next(r for r in d["reels"] if r["sc"] == "TESTREEL01")
        self.assertEqual(r1["counts"], "5,000 plays · 5.0x own median (25 reels)")
        self.assertEqual(r1["tribe"], "TRIBE read 2026-10-01")
        self.assertEqual(r1["href"], "reels/TESTREEL01.html")
        self.assertEqual(len(r1["peer"]["ticks"]), 25)
        self.assertTrue(0 <= r1["peer"]["me"] <= 1 and 0 <= r1["peer"]["median"] <= 1)
        r2 = next(r for r in d["reels"] if r["sc"] == "TESTREEL02")
        self.assertEqual({b["key"] for b in r2["badges"]}, {"gated_cta", "discounted", "under_2x"})
        self.assertIn("under 2x · taste, not proof", [b["label"] for b in r2["badges"]])
        self.assertFalse(r2["filter"]["two_x"])
        self.assertEqual(r1["recreate"], "/script new from-TESTREEL01")
        r3 = next(r for r in d["reels"] if r["sc"] == "TESTREEL03")
        self.assertIn("(11 posts, all types)", r3["counts"])
        self.assertIn("thin_baseline", r3["filter"]["flags"])
        self.assertEqual(len(d["fetch"]), 1)
        self.assertIn("$0.081", d["fetch_total"])
        self.assertEqual(sum(t.count(R.WALL_SENTENCE) for t in d["about"]), 1)
        self.assertEqual({c["handle"] for c in d["creators"]}, {"@testcreator", "@other.creator"})

    def test_sort_keys_guarded(self):
        self.make_three()
        d = page_data(self.render_board())
        self.assertEqual({s["field"] for s in d["sorts"]}, ALLOWED_SORT_FIELDS)
        self.assertEqual(d["default_sort"], "-x")
        for r in d["reels"]:
            self.assertEqual(set(r["sort"]), ALLOWED_SORT_FIELDS)  # nothing from TRIBE to sort on
        for bad in ("-tribe.job_id", "tribe", "peak", "-hook_0_3s.language", "flat_stretches", "attention", "views"):
            with self.subTest(bad):
                with mock.patch.object(srender, "SORTS", srender.SORTS + ((bad, "bad"),)):
                    self.refused(self.render_board)
        with mock.patch.object(srender, "DEFAULT_SORT", "-tribe.run_date"):
            self.refused(self.render_board, "TRIBE")

    def test_no_rank_numbers(self):
        self.make_three()
        html = self.render_board().read_text(encoding="utf-8")
        template = (srender.TEMPLATES / "board.html").read_text(encoding="utf-8")
        self.assertNotIn("<ol", template)
        for rx in (r"\b(?:i|idx|index|n)\s*\+\s*1\b", r"(?i)\brank"):  # no list position written anywhere
            m = re.search(rx, template)
            self.assertIsNone(m, m and template[max(0, m.start() - 60):m.end() + 20])
        for r in page_data(Path(self.reports / "swipe" / "index.html"))["reels"]:
            for text in (r["counts"], r["meta"], r["shape"]):
                self.assertNotRegex(text, r"^\s*#?\d+[.)]\s", text)
        self.assertNotRegex(re.sub(r"<style>.*?</style>", "", html, flags=re.S), r"(?<![\w&])#\d+")

    def test_board_has_no_brain_output(self):
        self.make_three()
        d = page_data(self.render_board())
        for r in d["reels"]:
            blob = json.dumps({k: v for k, v in r.items() if k not in ("sc", "href", "url", "recreate")})
            self.assertNotRegex(blob.lower(), r"\b(?:peaks?|flat|high|low|seeing|hearing|attention|response)\b", r["sc"])

    def test_board_text_violation_refused(self):
        self.make_three()
        reel = store.load_reel("TESTREEL02")
        reel["discount"]["reason"] = "outlier from a giveaway, which is why the peak looks big"
        store.save_reel(reel)
        self.refused(self.render_board)

    def test_empty_swipe_file(self):
        d = page_data(self.render_board())
        self.assertEqual(d["reels"], [])
        self.assertEqual(d["stamp"][0], "0 creators · 0 reels")

    def test_board_links_patterns_and_drafts(self):
        self.make_three()
        store.save_json(store.DRAFTS / "20261001-try-one.json", {"id": "20261001-try-one", "slug": "try-one",
                                                                  "status": "draft", "beats": []})
        d = page_data(self.render_board())
        self.assertIn({"text": "Draft: try one", "href": "lab/20261001-try-one.html"}, d["nav"])


class TestTemplatesAndCli(SwipeCase):
    def test_templates_pass_the_rule_checks(self):
        for name in ("board.html", "card.html"):
            text = (srender.TEMPLATES / name).read_text(encoding="utf-8")
            R.check_authored([(name, text)])
            self.assertEqual(text.count(srender.SLOT), 1)
            self.assertIn(f'content="{CSP_CARD if name == "card.html" else CSP}"', text)

    def test_page_js_syntax(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        for name in ("board.html", "card.html"):
            text = (srender.TEMPLATES / name).read_text(encoding="utf-8")
            scripts = re.findall(r"<script>(.*?)</script>", text, re.S)
            self.assertEqual(len(scripts), 1, name)
            js = self.tmp / f"{name}.js"
            js.write_text(scripts[0], encoding="utf-8")
            r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{name}: {r.stderr}")

    def test_cli(self):
        self.creator()
        self.reel()
        run = lambda *a: srender.main([*a, "--reports-dir", str(self.reports)])  # noqa: E731
        with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            self.assertEqual(run("reel"), 2)              # needs a shortcode
            self.assertEqual(run("lab"), 2)               # needs a draft id
            self.assertEqual(run("reel", "NOPE01"), 2)    # not in the swipe file
            self.assertEqual(run("reel", "../x"), 2)      # not a shortcode
            self.assertEqual(run("patterns"), 0)
            self.assertEqual(run("all"), 0)
        self.assertTrue((self.reports / "swipe" / "index.html").is_file())
        self.assertTrue((self.reports / "swipe" / "reels" / "TESTREEL01.html").is_file())


class TestRealSwipeFile(unittest.TestCase):
    """Every reel already in the real swipe file renders cleanly (read-only; pages go to a temp folder)."""

    def test_real_pages(self):
        reels = store.list_reels()
        if not reels:
            self.skipTest("no reels in the real swipe file yet")
        with mock.patch("urllib.request.urlopen", side_effect=no_network), \
                tempfile.TemporaryDirectory(prefix="swipe-real-") as tmp:
            paths = srender.render_all(tmp, log=lambda *a: None)
            # board, one card per reel, the patterns page, one script lab page per draft
            self.assertEqual(len(paths), len(reels) + 2 + len(srender._drafts()))
            for p in paths:
                check_static(self, p)
            for r in reels:
                page = Path(tmp) / "swipe" / "reels" / f"{r['shortcode']}.html"
                d = page_data(page)
                check_card(self, d["card"])
                self.assertNotIn("data:image", page.read_text(encoding="utf-8"))   # no still inside the page
                self.assertLessEqual(len(d["stills"]), 4)
                chips = [c for ln in d["card"]["lines"] for c in R.CHIP_RE.findall(R.card_line_text(ln))]
                self.assertEqual(len(chips), len(set(chips)), chips)
            board = page_data(Path(tmp) / "swipe" / "index.html")
            self.assertEqual(len(board["reels"]), len(reels))
            for r in board["reels"]:
                self.assertEqual(set(r["sort"]), ALLOWED_SORT_FIELDS)


if __name__ == "__main__":
    unittest.main(verbosity=1)
