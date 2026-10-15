"""Local tests for the swipe store and the reel CLI. Run: python strategist/test_reel.py
Everything here is synthetic (creator "testcreator", shortcodes like "TESTREEL01"). No Apify,
no Modal, no network: every HTTP call is mocked and a stray one fails the test. Writes only
to temp folders; the real swipe/, outputs/ and VAULT are never touched."""

import contextlib
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from strategist import reel, store, transcribe  # noqa: E402

FAKE_TOKEN = "apify_api_SYNTHETIC_TOKEN_never_print_0123456789"
PULL = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.timezone.utc)
JOB = "20261001-120000-0123abcd"
JPEG = b"\xff\xd8\xff\xe0synthetic-jpeg\xff\xd9"


def item(sc, plays, *, likes=100, comments=10, kind="clips", days_ago=10, pinned=False, paid=False,
         owner="testcreator", caption="Synthetic caption line\nsecond line"):
    posted = (PULL - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    d = {"shortCode": sc, "url": f"https://www.instagram.com/p/{sc}/", "ownerUsername": owner, "timestamp": posted,
         "type": "Video" if kind == "clips" else "Sidecar", "productType": kind, "paidPartnership": paid,
         "likesCount": likes, "commentsCount": comments, "caption": caption,
         "latestComments": [{"text": "nice"}]}
    if kind == "clips":
        d.update({"videoPlayCount": plays, "videoDuration": 30.0, "videoUrl": "https://cdn.example.test/v.mp4"})
    if pinned:
        d["isPinned"] = True
    return d


def normal_items(n, start=1000, owner="testcreator"):
    return [item(f"NORMAL{i:04d}", start + 10 * i, owner=owner, days_ago=5 + i) for i in range(n)]


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def no_network(*a, **k):
    raise AssertionError("unexpected network call in a test")


class TempStore(unittest.TestCase):
    """Points the store at a temp folder and blocks the network."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="strategist-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, sub in (("SWIPE", "swipe"), ("DRAFTS", "drafts"), ("OUTPUTS", "outputs"), ("VAULT", "vault")):
            p = mock.patch.object(store, name, self.tmp / sub)
            p.start()
            self.addCleanup(p.stop)
        for target, value in ((reel, "ENV_FILE"), ):
            p = mock.patch.object(target, value, self.tmp / "no.env")
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("urllib.request.urlopen", side_effect=no_network)
        self.urlopen = p.start()
        self.addCleanup(p.stop)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = reel.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def creator(self, median_plays=200, n=25, thin=False, handle="testcreator"):
        c = {"handle": handle, "platform": "instagram", "baseline": {
            "n": n, "kind": "reels only", "window": None, "median": {"plays": median_plays, "likes": 50, "comments": 5},
            "excluded": {k: [] for k in store.EXCLUDED_KEYS}, "source": "test", "pulled_at": None,
            "pulled_at_note": "test", "thin": thin}}
        store.save_creator(c)
        return c

    def reel_record(self, sc="TESTREEL01", plays=500, owner="testcreator", duration=30.0, cta=None):
        r = reel.new_reel(sc, owner, "2026-09-01T10:00:00.000Z",
                          reel.make_counts(plays, 120, 30, "2026-09-20T10:00:00+00:00", "test"), False,
                          {"duration_s": duration, "first_word_s": 0.4, "words_per_s": 2.5, "text_on_screen_0s": None,
                           "cta": cta, "source": {}}, "test")
        store.save_reel(store.derive(r, store.load_creator(owner)))
        return r


# ---------------------------------------------------------------- baseline, x, outlier

class BaselineTests(TempStore):
    def test_exclusions_reels_only(self):
        items = [item("KEEP000001", 100), item("KEEP000002", 200), item("KEEP000003", 300),
                 item("PINNED0001", 5000, pinned=True), item("PAID000001", 4000, paid=True),
                 item("FRESH00001", 3000, days_ago=1), item("TARGET0001", 9000),
                 item("CAROUSEL01", None, kind="carousel_container"), item("IMAGE00001", None, kind="feed")]
        b = store.compute_baseline(items, pulled_at=PULL.isoformat(), pulled_at_note="test", source="test",
                                   targets={"TARGET0001"})
        self.assertEqual(b["n"], 3)
        self.assertEqual(b["kind"], "reels only")
        self.assertEqual(b["median"], {"plays": 200, "likes": 100, "comments": 10})
        self.assertEqual(b["excluded"], {"pinned": ["PINNED0001"], "paid": ["PAID000001"], "fresh": ["FRESH00001"],
                                         "target": ["TARGET0001"], "not_reel": ["CAROUSEL01", "IMAGE00001"]})
        self.assertTrue(b["thin"])
        self.assertEqual(b["window"], {"from": "2026-09-21", "to": "2026-09-21"})

    def test_thin_flag(self):
        kw = dict(pulled_at=PULL.isoformat(), pulled_at_note="t", source="t")
        self.assertTrue(store.compute_baseline(normal_items(19), **kw)["thin"])
        self.assertFalse(store.compute_baseline(normal_items(20), **kw)["thin"])

    def test_fresh_needs_a_pull_time(self):
        b = store.compute_baseline([item("FRESH00001", 3000, days_ago=1)], pulled_at=None, pulled_at_note="?",
                                   source="t")
        self.assertEqual(b["n"], 1)

    def test_median(self):
        self.assertEqual(store.med([1, 2, 3, 4]), 2.5)
        self.assertEqual(store.med([3, None, 1, 2]), 2)
        self.assertIsNone(store.med([None]))

    def test_x_and_outlier(self):
        self.creator(median_plays=200)
        r = self.reel_record(plays=500)
        self.assertEqual(r["x"]["plays"], 2.5)
        self.assertTrue(r["outlier"])
        self.assertFalse(r["flags"]["under_2x"])
        self.assertIn("own median of 25 reels", r["x"]["vs"])
        r = self.reel_record(sc="TESTREEL02", plays=300)
        self.assertEqual(r["x"]["plays"], 1.5)
        self.assertFalse(r["outlier"])
        self.assertTrue(r["flags"]["under_2x"])

    def test_discount_cancels_outlier(self):
        self.creator(median_plays=200)
        self.reel_record(plays=500)
        rc, out, _ = self.run_cli("discount", "TESTREEL01", "--reason", "giveaway reel")
        self.assertEqual(rc, 0)
        r = store.load_reel("TESTREEL01")
        self.assertFalse(r["outlier"])
        self.assertEqual(r["discount"]["by"], "user")
        self.assertEqual(r["discount"]["reason"], "giveaway reel")
        self.run_cli("discount", "TESTREEL01", "--clear")
        self.assertTrue(store.load_reel("TESTREEL01")["outlier"])

    def test_flags(self):
        self.creator(median_plays=200, thin=True)
        r = self.reel_record(plays=500, duration=72.4, cta={"type": "comment-keyword", "t": 50.1})
        self.assertTrue(r["flags"]["thin_baseline"])
        self.assertTrue(r["flags"]["gated_cta"])
        self.assertTrue(r["flags"]["over_60s"])
        self.assertFalse(r["flags"]["fresh"])

    def test_no_baseline_means_no_x(self):
        r = self.reel_record(owner="nobaseline")
        self.assertIsNone(r["x"]["plays"])
        self.assertFalse(r["outlier"])
        self.assertFalse(r["flags"]["under_2x"])

    def test_trim_keeps_no_media_urls_or_comment_text(self):
        it = item("KEEP000001", 100)
        it["latestComments"] = [{"text": "Guide"}, {"text": "guide!"}, {"text": "Guide"}, {"text": "a real sentence"}]
        t = store.trim_item(it)
        self.assertNotIn("videoUrl", t)
        self.assertNotIn("latestComments", t)
        self.assertEqual(t["topCommentRepeat"], 3)

    def test_atomic_save_leaves_no_temp_files(self):
        store.save_json(store.SWIPE / "a.json", {"a": 1})
        store.save_json(store.SWIPE / "a.json", {"a": 2})
        self.assertEqual([p.name for p in store.SWIPE.iterdir()], ["a.json"])
        self.assertEqual(store.load_json(store.SWIPE / "a.json"), {"a": 2})


# ---------------------------------------------------------------- facts

class FactsTests(unittest.TestCase):
    WORDS = [{"text": t, "start": i * 0.5, "stop": i * 0.5 + 0.4} for i, t in enumerate(
        "this is a synthetic test line , comment word and I'll share the checklist".split())]

    def test_spoken_comment_gate_is_timed(self):
        cta, src = reel.find_cta(self.WORDS, "", 'Comment "word" and I\'ll send it', [])
        self.assertEqual(cta["type"], "comment-keyword")
        self.assertEqual(cta["t"], 3.5)
        self.assertIn("spoken at 0:03", src)
        self.assertIn("caption", src)

    def test_cta_time_from_subtitle_segment(self):
        segs = [{"start": 51.44, "end": 53.34, "text": "for the full checklist, comment word and I'll share it."}]
        cta, src = reel.find_cta([{"text": "up,", "start": 51.5, "stop": 51.6}], "", "", [], segs)
        self.assertEqual(cta["type"], "comment-keyword")
        self.assertTrue(51.44 < cta["t"] < 53.34)
        self.assertIn("estimated", src)

    def test_read_srt(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.srt"
            p.write_text("1\n00:00:00,480 --> 00:00:02,880\nFirst line\n\n2\n00:01:03,040 --> 00:01:06,800\n"
                         "second\nline\n", encoding="utf-8")
            self.assertEqual(reel.read_srt(p), [{"start": 0.48, "end": 2.88, "text": "First line"},
                                                {"start": 63.04, "end": 66.8, "text": "second line"}])

    def test_link_in_caption(self):
        cta, src = reel.find_cta([], "", "Try it free at example.com/tool", [])
        self.assertEqual(cta, {"type": "link", "t": None})
        self.assertIn("caption", src)

    def test_comment_below_is_not_a_gate(self):
        cta, _ = reel.find_cta([], "comment below what you think", "", [])
        self.assertEqual(cta["type"], "comment")
        self.assertNotIn(cta["type"], store.GATED_CTAS)

    def test_repeated_comments_suggest_a_gate(self):
        cta, src = reel.find_cta([], "no ask here", "Topic only", ["Guide", "guide!", "Guide", "nice one"])
        self.assertEqual(cta, {"type": "comment-keyword", "t": None})
        self.assertIn("inferred", src)

    def test_facts(self):
        f = reel.build_facts(self.WORDS, 30.0, "test", "test words", "", "", [])
        self.assertEqual(f["first_word_s"], 0.0)
        spoken = [w for w in self.WORDS if w["text"] != ","]   # a lone "," is no word
        self.assertEqual(f["words_per_s"], round(len(spoken) / (spoken[-1]["stop"] - spoken[0]["start"]), 2))
        self.assertIsNone(f["text_on_screen_0s"])

    def test_punctuation_tokens_are_not_words(self):
        from strategist import transcribe
        self.assertFalse(transcribe.is_word("."))
        self.assertTrue(transcribe.is_word("I'll"))
        words = [{"text": "one", "start": 0.0, "stop": 0.4}, {"text": "two", "start": 0.5, "stop": 1.0},
                 {"text": ".", "start": 1.0, "stop": 2.0}]
        f = reel.build_facts(words, 3.0, "test", "test words", "", "", [])
        self.assertEqual(f["words_per_s"], 2.0)   # 2 words over 0.0-1.0 s, the "." left out

    def test_words_from_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "events.json"
            p.write_text(json.dumps({"words": [{"text": "Hi,", "start": 0.39, "duration": 0.26, "stop": 0.65},
                                               {"text": " ", "start": 1.0, "stop": 1.1}]}), encoding="utf-8")
            self.assertEqual(transcribe.words_from_events(p), [{"text": "Hi,", "start": 0.39, "stop": 0.65}])

    def test_missing_faster_whisper_is_a_clear_refusal(self):
        with mock.patch.dict(sys.modules, {"faster_whisper": None}):
            with self.assertRaises(transcribe.TranscribeError) as ctx:
                transcribe._model("small.en")
        self.assertIn("pip install faster-whisper", str(ctx.exception))
        err = io.StringIO()
        with mock.patch.dict(sys.modules, {"faster_whisper": None}), contextlib.redirect_stderr(err), \
                tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.wav").write_bytes(b"RIFF")
            self.assertEqual(transcribe.main([str(Path(tmp) / "a.wav")]), 2)
        self.assertIn("refused", err.getvalue())

    def test_compare(self):
        c = transcribe.compare([{"text": "a", "start": 11.72, "stop": 12}],
                               [{"text": "a", "start": 12.23, "stop": 12.3}])
        self.assertEqual(c["first_word_diff_s"], -0.51)
        self.assertEqual(c["word_count_diff"], 0)


# ---------------------------------------------------------------- import-vault

class ImportVaultTests(TempStore):
    def setUp(self):
        super().setUp()
        vault = store.VAULT
        raw = vault / "research" / "raw"
        data = vault / "research" / "repurpose" / "data"
        media = vault / "research" / "repurpose" / "media" / "TESTREEL01"
        for d in (raw, data, media):
            d.mkdir(parents=True)
        items = normal_items(22) + [item("TESTREEL01", 90000), item("CAROUSEL01", None, kind="carousel_container")]
        (raw / "ig-testcreator.json").write_text(json.dumps(items), encoding="utf-8")
        rec = {"shortcode": "TESTREEL01", "url": "https://www.instagram.com/p/TESTREEL01/", "owner": "testcreator",
               "date": "2026-09-20T10:00:00.000Z", "type": "Video", "product_type": "clips",
               "caption": 'Comment "word" and I\'ll send the guide\nSecond caption line stays out',
               "likes": 900, "comments": 700, "views": 90000, "paid_partnership": False,
               "baseline_posts": 23, "median_views": 1100, "x_views": 81.8, "duration_s": 31.5,
               "transcript": "synthetic transcript text, comment word and I'll send it", "top_comments": ["word"]}
        (data / "TESTREEL01.json").write_text(json.dumps(rec), encoding="utf-8")
        other = dict(rec, shortcode="OTHERREEL1", owner="otherbrand", views=50000, baseline_posts=11,
                     median_views=10000.5, median_likes=100, median_comments=5, transcript=None)
        (data / "OTHERREEL1.json").write_text(json.dumps(other), encoding="utf-8")
        carousel = dict(rec, shortcode="CAROUSEL02", owner="otherbrand", type="Sidecar",
                        product_type="carousel_container", views=None)
        (data / "CAROUSEL02.json").write_text(json.dumps(carousel), encoding="utf-8")
        for i, t in enumerate((0.5, 6.0, 12.0, 18.0, 24.0, 30.0), 1):
            (media / f"frame-{i:02d}-{t:05.1f}s.jpg").write_bytes(JPEG)
        (media / "video.mp4").write_bytes(b"not a real video")
        (media / "video.transcript.txt").write_text("synthetic", encoding="utf-8")
        job = store.OUTPUTS / JOB
        job.mkdir(parents=True)
        (job / "report.json").write_text(json.dumps({"mock": False, "peaks": [{"t": 17, "value": 1.2}]}),
                                         encoding="utf-8")
        (job / "events.json").write_text(json.dumps({"words": [
            {"text": "Synthetic", "start": 0.4, "stop": 0.8}, {"text": "comment", "start": 25.0, "stop": 25.3},
            {"text": "word", "start": 25.3, "stop": 25.6}, {"text": "and", "start": 25.6, "stop": 25.7},
            {"text": "I'll", "start": 25.7, "stop": 25.9}, {"text": "send", "start": 25.9, "stop": 26.1}]}),
            encoding="utf-8")
        (job / "source.json").write_text(json.dumps({"source_url": "https://www.instagram.com/reel/TESTREEL01/"}),
                                         encoding="utf-8")
        p = mock.patch.dict(reel.AUTO_LINK, {"TESTREEL01": JOB}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def vault_state(self):
        return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in store.VAULT.rglob("*"))

    def test_import(self):
        before = self.vault_state()
        rc, out, err = self.run_cli("import-vault", "--no-transcribe")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.vault_state(), before, "VAULT must not change")
        # reels only
        self.assertTrue(store.reel_path("TESTREEL01").is_file())
        self.assertTrue(store.reel_path("OTHERREEL1").is_file())
        self.assertFalse(store.reel_dir("CAROUSEL02").exists())
        self.assertIn("skipped CAROUSEL02", out)
        # baseline: 22 normal reels; the target and the carousel left out
        c = store.load_creator("testcreator")
        self.assertEqual(c["baseline"]["n"], 22)
        self.assertEqual(c["baseline"]["excluded"]["target"], ["TESTREEL01"])
        self.assertEqual(c["baseline"]["excluded"]["not_reel"], ["CAROUSEL01"])
        self.assertEqual(c["baseline"]["pulled_at_note"], "pull date unknown (file date)")
        self.assertFalse(c["baseline"]["thin"])
        # a creator with no raw cache carries VAULT's numbers, marked
        o = store.load_creator("otherbrand")
        self.assertEqual(o["baseline"]["source"], "VAULT repurpose record, not re-checked")
        self.assertTrue(o["baseline"]["thin"])
        self.assertEqual(store.load_reel("OTHERREEL1")["x"]["plays"], round(50000 / 10000.5, 2))
        # the target reel
        r = store.load_reel("TESTREEL01")
        self.assertTrue(r["outlier"])
        self.assertEqual(r["tribe"], {"job_id": JOB, "run_date": "2026-10-01", "scale": "within-reel"})
        self.assertEqual(r["facts"]["first_word_s"], 0.4)
        self.assertEqual(r["facts"]["cta"], {"type": "comment-keyword", "t": 25.0})
        self.assertTrue(r["flags"]["gated_cta"])
        self.assertEqual(r["counts"]["source_field"]["plays"], "videoPlayCount")
        priv = store.private_dir("TESTREEL01")
        self.assertEqual(len(json.loads((priv / "words.json").read_text(encoding="utf-8"))), 6)
        self.assertEqual((priv / "caption.txt").read_text(encoding="utf-8").strip(),
                         'Comment "word" and I\'ll send the guide')
        stills = sorted(p.name for p in (priv / "stills").iterdir())
        self.assertLessEqual(len(stills), 4)
        self.assertTrue(all(s.endswith(".jpg") for s in stills))
        self.assertTrue(stills[0].startswith("1-open-0.5s"))
        # no video anywhere under swipe/, and the import is logged at $0
        self.assertFalse([p for p in store.SWIPE.rglob("*") if p.suffix.lower() in reel.VIDEO_EXTS])
        rows = [json.loads(ln) for ln in store.fetch_log_path().read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["est_usd"], 0.0)
        self.assertEqual(set(rows[0]), {"at", "what", "items", "est_usd", "actor", "ok"})
        self.assertNotIn("views", out.lower())

    def test_import_transcribes_without_a_tribe_job(self):
        seen = []

        def fake(path, model):
            seen.append(Path(path))
            return [{"text": "Synthetic", "start": 0.6, "stop": 0.9}, {"text": "words", "start": 0.9, "stop": 1.2}]
        before = self.vault_state()
        with mock.patch.dict(reel.AUTO_LINK, {}, clear=True), \
                mock.patch.object(transcribe, "transcribe_media", side_effect=fake):
            rc, _, err = self.run_cli("import-vault")
        self.assertEqual(rc, 0, err)
        self.assertEqual(seen, [store.VAULT / "research" / "repurpose" / "media" / "TESTREEL01" / "video.mp4"])
        self.assertEqual(self.vault_state(), before)
        r = store.load_reel("TESTREEL01")
        self.assertIsNone(r["tribe"])
        self.assertEqual(r["facts"]["first_word_s"], 0.6)
        self.assertIn("faster-whisper", r["facts"]["source"]["words"])
        self.assertFalse([p for p in store.SWIPE.rglob("*") if p.suffix.lower() in reel.VIDEO_EXTS])

    def test_reimport_keeps_his_decisions(self):
        self.run_cli("import-vault", "--no-transcribe")
        tag = self.tmp / "tag.json"
        tag.write_text(json.dumps({"hook_shape": "question-then-number"}), encoding="utf-8")
        self.run_cli("tag", "TESTREEL01", "--from", str(tag))
        self.run_cli("accept", "TESTREEL01", "hook_shape")
        self.run_cli("discount", "TESTREEL01", "--reason", "keyword gate")
        rc, _, err = self.run_cli("import-vault", "--no-transcribe")
        self.assertEqual(rc, 0, err)
        r = store.load_reel("TESTREEL01")
        self.assertEqual(r["shape"]["hook_shape"], {"id": "question-then-number", "status": "accepted"})
        self.assertEqual(r["discount"]["reason"], "keyword gate")
        self.assertFalse(r["outlier"])

    def test_baseline_reels_for_patterns(self):
        self.run_cli("import-vault", "--no-transcribe")
        rows = store.baseline_reels("testcreator")
        self.assertEqual(len(rows), 22)
        self.assertNotIn("TESTREEL01", {r["shortcode"] for r in rows})
        self.assertTrue(all("caption" in r and "outlier" in r for r in rows))


# ---------------------------------------------------------------- add (Apify, mocked)

class AddTests(TempStore):
    URL = "https://www.instagram.com/reel/TESTREEL09/"

    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {"APIFY_TOKEN": FAKE_TOKEN})
        p.start()
        self.addCleanup(p.stop)
        self.seen_videos = []

    def fake_urlopen(self, items):
        calls = []

        def opener(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            calls.append(req)
            if url.startswith("https://api.apify.com/"):
                self.assertEqual(req.get_header("Authorization"), f"Bearer {FAKE_TOKEN}")
                return FakeResponse(json.dumps(items).encode())
            if url.startswith("https://cdn.example.test/"):
                return FakeResponse(b"\x00\x00\x00\x18ftypmp42 synthetic video bytes")
            raise AssertionError(f"unexpected URL {url}")
        self.urlopen.side_effect = opener
        return calls

    def fake_transcribe(self, path, model):
        self.seen_videos.append(Path(path))
        self.assertTrue(Path(path).is_file())
        self.assertNotIn(str(store.SWIPE.resolve()), str(Path(path).resolve()))
        return [{"text": "synthetic", "start": 0.3, "stop": 0.7}, {"text": "words", "start": 0.7, "stop": 1.1}]

    def fake_still(self, video, t, out):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(JPEG)
        return True

    def media_mocks(self):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(transcribe, "transcribe_media", side_effect=self.fake_transcribe))
        stack.enter_context(mock.patch.object(reel, "probe_duration", return_value=30.0))
        stack.enter_context(mock.patch.object(reel, "grab_still", side_effect=self.fake_still))
        return stack

    def test_add_url_refuses_without_yes(self):
        rc, out, _ = self.run_cli("add", self.URL)
        self.assertEqual(rc, 2)
        self.assertIn("$0.003", out)
        self.assertIn("--yes", out)
        self.urlopen.assert_not_called()
        self.assertFalse(store.fetch_log_path().exists())

    def test_add_handle_refuses_without_yes(self):
        rc, out, _ = self.run_cli("add", "@testcreator")
        self.assertEqual(rc, 2)
        self.assertIn("$0.081", out)
        self.urlopen.assert_not_called()
        self.assertFalse(store.SWIPE.exists())

    def test_add_url_with_mock(self):
        self.creator(median_plays=1000)
        store.save_json(store.creator_items_path("testcreator"), normal_items(21) + [item("TESTREEL09", 5000)])
        store.save_creator(reel.rebuild_creator(store.load_creator("testcreator")))
        calls = self.fake_urlopen([item("TESTREEL09", 5000, caption="Link in bio for the guide")])
        with self.media_mocks():
            rc, out, err = self.run_cli("add", self.URL, "--yes")
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(calls), 2)
        self.assertNotIn(FAKE_TOKEN, out + err)
        r = store.load_reel("TESTREEL09")
        self.assertEqual(r["counts"]["plays"], 5000)
        self.assertEqual(r["imported_from"], "Apify reel link")
        self.assertIn("this reel left out", r["x"]["vs"])
        self.assertEqual(r["facts"]["cta"]["type"], "link-in-bio")
        self.assertEqual(store.load_creator("testcreator")["baseline"]["excluded"]["target"], ["TESTREEL09"])
        # the temp video is gone, and no video ever reached swipe/
        self.assertTrue(self.seen_videos)
        self.assertFalse(any(p.exists() for p in self.seen_videos))
        self.assertFalse(self.seen_videos[0].parent.exists())
        self.assertFalse([p for p in store.SWIPE.rglob("*") if p.suffix.lower() in reel.VIDEO_EXTS])
        self.assertLessEqual(len(list((store.private_dir("TESTREEL09") / "stills").iterdir())), 4)
        rows = [json.loads(ln) for ln in store.fetch_log_path().read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[-1]["est_usd"], 0.003)
        self.assertEqual(rows[-1]["actor"], "apify~instagram-scraper")
        self.assertTrue(rows[-1]["ok"])

    def test_add_url_error_never_prints_token(self):
        def boom(req, timeout=None):
            raise urllib.error.URLError(f"proxy said no to {FAKE_TOKEN}")
        self.urlopen.side_effect = boom
        rc, out, err = self.run_cli("add", self.URL, "--yes")
        self.assertEqual(rc, 2)
        self.assertNotIn(FAKE_TOKEN, out + err)
        self.assertIn("refused", err)
        rows = [json.loads(ln) for ln in store.fetch_log_path().read_text(encoding="utf-8").splitlines()]
        self.assertFalse(rows[-1]["ok"])

    def test_add_url_refuses_non_reel(self):
        self.fake_urlopen([item("TESTREEL09", None, kind="carousel_container")])
        rc, _, err = self.run_cli("add", self.URL, "--yes")
        self.assertEqual(rc, 2)
        self.assertIn("not a reel", err)
        self.assertFalse(store.reel_dir("TESTREEL09").exists())

    def test_add_url_needs_token(self):
        with mock.patch.dict(os.environ, {"APIFY_TOKEN": ""}):
            rc, _, err = self.run_cli("add", self.URL, "--yes")
        self.assertEqual(rc, 2)
        self.assertIn("APIFY_TOKEN", err)
        self.urlopen.assert_not_called()

    def test_add_handle_with_mock(self):
        items = normal_items(24) + [item("OUTLIER001", 9000, days_ago=3), item("PINNED0001", 99999, pinned=True),
                                    item("CAROUSEL01", None, kind="carousel_container")]
        self.fake_urlopen(items)
        with self.media_mocks():
            rc, out, err = self.run_cli("add", "@testcreator", "--yes")
        self.assertEqual(rc, 0, err)
        self.assertNotIn(FAKE_TOKEN, out + err)
        c = store.load_creator("testcreator")
        self.assertEqual(c["baseline"]["n"], 25)
        self.assertEqual(c["baseline"]["excluded"]["pinned"], ["PINNED0001"])
        self.assertFalse(c["baseline"]["thin"])
        self.assertTrue(store.creator_items_path("testcreator").is_file())
        r = store.load_reel("OUTLIER001")
        self.assertTrue(r["outlier"])
        self.assertEqual(r["imported_from"], "Apify @testcreator pull")
        self.assertIn("this reel included", r["x"]["vs"])
        self.assertFalse(store.reel_dir("PINNED0001").exists())
        rows = [json.loads(ln) for ln in store.fetch_log_path().read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[-1]["est_usd"], 0.081)
        self.assertEqual(rows[-1]["items"], len(items))
        self.assertFalse([p for p in store.SWIPE.rglob("*") if p.suffix.lower() in reel.VIDEO_EXTS])


# ---------------------------------------------------------------- shape, link-tribe, list

class ShapeTests(TempStore):
    def setUp(self):
        super().setUp()
        self.creator(median_plays=200)
        self.reel_record(plays=500)

    def tag(self, data, *extra):
        p = self.tmp / "tag.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return self.run_cli("tag", "TESTREEL01", "--from", str(p), *extra)

    def test_tag_accept_reject(self):
        rc, _, err = self.tag({"hook_shape": "question-then-number", "format": "talking head + screen",
                               "cta": "comment keyword", "beats": [
                                   {"start": 0, "end": 3, "kind": "hook", "name": "off-camera question"},
                                   {"start": 3, "end": 25, "kind": "demo", "name": "tool walkthrough"}]})
        self.assertEqual(rc, 0, err)
        s = store.load_reel("TESTREEL01")["shape"]
        self.assertEqual(s["hook_shape"], {"id": "question-then-number", "status": "suggested"})
        self.assertEqual({b["status"] for b in s["beats"]}, {"suggested"})
        self.assertEqual(self.run_cli("accept", "TESTREEL01", "hook_shape")[0], 0)
        self.assertEqual(self.run_cli("reject", "TESTREEL01", "cta")[0], 0)
        self.assertEqual(self.run_cli("accept", "TESTREEL01", "beats.1")[0], 0)
        s = store.load_reel("TESTREEL01")["shape"]
        self.assertEqual(s["hook_shape"]["status"], "accepted")
        self.assertEqual(s["cta"]["status"], "rejected")
        self.assertEqual([b["status"] for b in s["beats"]], ["suggested", "accepted"])
        # a new suggestion never overwrites an accepted label unless forced
        self.tag({"hook_shape": "bold-claim"})
        self.assertEqual(store.load_reel("TESTREEL01")["shape"]["hook_shape"]["id"], "question-then-number")
        self.tag({"hook_shape": "bold-claim"}, "--force")
        self.assertEqual(store.load_reel("TESTREEL01")["shape"]["hook_shape"],
                         {"id": "bold-claim", "status": "suggested"})
        self.assertEqual(self.run_cli("accept", "TESTREEL01", "all")[0], 0)
        self.assertEqual(self.run_cli("reject", "TESTREEL01", "all")[0], 2)
        self.assertEqual(self.run_cli("accept", "TESTREEL01", "nonsense")[0], 2)

    def test_tag_refuses_rule_breaks(self):
        for bad in ({"hook_shape": "viral opener"}, {"format": "best hook format"},
                    {"cta": "her keyword ask"}, {"hook_shape": "17x opener"},
                    {"beats": [{"start": 0, "end": 3, "kind": "hook", "name": "works because of the number"}]},
                    {"beats": [{"start": 5, "end": 3, "kind": "hook", "name": "backwards"}]},
                    {"mood": "anything"}):
            rc, _, err = self.tag(bad)
            self.assertEqual(rc, 2, f"{bad} should be refused")
        self.assertIsNone(store.load_reel("TESTREEL01")["shape"]["hook_shape"])

    def test_link_tribe(self):
        job = store.OUTPUTS / JOB
        job.mkdir(parents=True)
        (job / "report.json").write_text(json.dumps({"mock": False, "peaks": []}), encoding="utf-8")
        (job / "events.json").write_text(json.dumps({"words": [{"text": "Hi", "start": 0.5, "stop": 0.7}]}),
                                         encoding="utf-8")
        (job / "source.json").write_text(json.dumps({"source_url": "https://www.instagram.com/reel/OTHERREEL1/"}),
                                         encoding="utf-8")
        rc, _, err = self.run_cli("link-tribe", "TESTREEL01", JOB)
        self.assertEqual(rc, 2)
        self.assertIn("not this reel", err)
        (job / "source.json").write_text(json.dumps({"source_url": "https://www.instagram.com/reel/TESTREEL01/"}),
                                         encoding="utf-8")
        self.assertEqual(self.run_cli("link-tribe", "TESTREEL01", JOB)[0], 0)
        r = store.load_reel("TESTREEL01")
        self.assertEqual(r["tribe"]["job_id"], JOB)
        self.assertEqual(r["facts"]["first_word_s"], 0.5)
        (job / "report.json").write_text(json.dumps({"mock": True}), encoding="utf-8")
        self.assertEqual(self.run_cli("link-tribe", "TESTREEL01", JOB)[0], 2)

    def test_list(self):
        rc, out, _ = self.run_cli("list")
        self.assertEqual(rc, 0)
        self.assertIn("TESTREEL01", out)
        self.assertIn("plays", out)
        self.assertNotIn("views", out.lower())
        for line in out.splitlines():
            if "plays" in line:
                self.assertNotIn("TRIBE", line)

    def test_discount_reason_is_checked(self):
        rc, _, err = self.run_cli("discount", "TESTREEL01", "--reason", "her views were bought")
        self.assertEqual(rc, 2)
        self.assertIsNone(store.load_reel("TESTREEL01")["discount"])


class ArchiveTests(TempStore):
    """D31: archived reels are hidden by default and nothing is deleted."""

    def setUp(self):
        super().setUp()
        self.creator(handle="alpha")
        self.creator(handle="beta")
        self.creator(handle="gamma")
        for sc, owner in (("ALPHAREEL1", "alpha"), ("ALPHAREEL2", "alpha"), ("BETAREEL01", "beta"),
                          ("GAMMAREEL1", "gamma")):
            self.reel_record(sc, owner=owner)
            store.private_dir(sc).mkdir(parents=True, exist_ok=True)
            (store.private_dir(sc) / "caption.txt").write_text("synthetic\n", encoding="utf-8")

    def shown(self, **kw):
        return sorted(r["shortcode"] for r in store.list_reels(**kw))

    def test_archive_one_hides_it_by_default_and_keeps_files(self):
        rc, out, _ = self.run_cli("archive", "ALPHAREEL1")
        self.assertEqual(rc, 0)
        self.assertIn("archived ALPHAREEL1", out)
        self.assertTrue(store.load_reel("ALPHAREEL1")["archived"])
        self.assertEqual(self.shown(), ["ALPHAREEL2", "BETAREEL01", "GAMMAREEL1"])
        self.assertEqual(len(self.shown(include_archived=True)), 4)
        self.assertTrue((store.private_dir("ALPHAREEL1") / "caption.txt").is_file())

    def test_archive_is_idempotent_and_says_what_changed(self):
        self.run_cli("archive", "ALPHAREEL1")
        rc, out, _ = self.run_cli("archive", "ALPHAREEL1")
        self.assertEqual(rc, 0)
        self.assertNotIn("archived ALPHAREEL1", out)
        self.assertIn("0 archived, 1 already were", out)

    def test_unarchive_restores_the_reel(self):
        self.run_cli("archive", "ALPHAREEL1", "BETAREEL01")
        rc, out, _ = self.run_cli("unarchive", "ALPHAREEL1")
        self.assertEqual(rc, 0)
        self.assertIn("unarchived ALPHAREEL1", out)
        self.assertEqual(self.shown(), ["ALPHAREEL1", "ALPHAREEL2", "GAMMAREEL1"])
        self.assertFalse(store.load_reel("ALPHAREEL1")["archived"])

    def test_archive_owners_takes_every_reel_of_those_creators(self):
        rc, out, _ = self.run_cli("archive", "--owners", "alpha,beta")
        self.assertEqual(rc, 0)
        self.assertEqual(self.shown(), ["GAMMAREEL1"])
        for sc in ("ALPHAREEL1", "ALPHAREEL2", "BETAREEL01"):
            self.assertIn(f"archived {sc}", out)

    def test_archive_all_except_owner_keeps_only_the_named_creators(self):
        rc, out, _ = self.run_cli("archive", "--all-except-owner", "gamma")
        self.assertEqual(rc, 0)
        self.assertEqual(self.shown(), ["GAMMAREEL1"])
        self.assertIn("3 archived", out)

    def test_archive_needs_exactly_one_way_to_pick(self):
        for argv in (["archive"], ["archive", "ALPHAREEL1", "--owners", "beta"]):
            rc, _, err = self.run_cli(*argv)
            self.assertEqual(rc, 2)
            self.assertIn("refused", err)
        rc, _, err = self.run_cli("archive", "--owners", "bad handle!")
        self.assertEqual(rc, 2)
        self.assertEqual(self.shown(), ["ALPHAREEL1", "ALPHAREEL2", "BETAREEL01", "GAMMAREEL1"])

    def test_archive_of_a_missing_reel_is_refused(self):
        rc, _, err = self.run_cli("archive", "NOSUCHREEL")
        self.assertEqual(rc, 2)
        self.assertIn("no reel NOSUCHREEL", err)

    def test_list_hides_archived_and_says_how_many(self):
        self.run_cli("archive", "ALPHAREEL1")
        rc, out, _ = self.run_cli("list")
        self.assertEqual(rc, 0)
        self.assertNotIn("ALPHAREEL1", out)
        self.assertIn("1 archived, not shown", out)

    def test_refresh_owner_still_updates_archived_reels(self):
        self.run_cli("archive", "ALPHAREEL1")
        c = store.load_creator("alpha")
        c["baseline"]["median"]["plays"] = 100
        store.save_creator(c)
        reel.refresh_owner("alpha")
        self.assertEqual(store.load_reel("ALPHAREEL1")["x"]["plays"], 5.0)
        self.assertTrue(store.load_reel("ALPHAREEL1")["archived"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
