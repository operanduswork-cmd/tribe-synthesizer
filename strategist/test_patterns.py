"""Tests for the shape vocabulary and the patterns build. Run: python strategist/test_patterns.py

Synthetic tests use creators "alpha" (with a post list) and "beta" (without) in a
temp swipe file. The real-data tests only read (build with write=False, copy
check of the vocabulary and the suggestion files) and skip when the data isn't
on this machine. No network, nothing written outside temp folders."""

import contextlib
import datetime as dt
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from strategist import copycheck, patterns, reel, shapes, store  # noqa: E402

render = store.rules()
PULL = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.timezone.utc)
GATE = "Comment GUIDE and I'll pass along my checklist.\nMore lines here about the topic and the steps."
QUESTION = "How do I fix my messy sheet?\nShort answer below."
STATEMENT = ("Tools change every week and the work stays the same, so here is a long caption that keeps going "
             "with plenty of words about process, notes, folders, checklists, calendars, invoices, reports, "
             "handovers, reviews and the small habits that keep a busy team calm on a Friday afternoon too.")
TEASE = "Ending is the best part"
REAL_SWIPE = PROJECT_ROOT / "swipe"


def item(sc, plays, caption, *, days_ago=10, pinned=False, paid=False, kind="clips", duration=40.0):
    posted = (PULL - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    d = {"shortCode": sc, "url": f"https://www.instagram.com/p/{sc}/", "ownerUsername": "alpha", "timestamp": posted,
         "productType": kind, "paidPartnership": paid, "likesCount": 10, "commentsCount": 1, "caption": caption}
    if kind == "clips":
        d.update({"videoPlayCount": plays, "videoDuration": duration})
    if pinned:
        d["isPinned"] = True
    return d


def shape(hook=None, fmt=None, cta=None, beats=()):
    return {"hook_shape": {"id": hook[0], "status": hook[1]} if hook else None,
            "format": {"value": fmt[0], "status": fmt[1]} if fmt else None,
            "cta": {"value": cta[0], "status": cta[1]} if cta else None,
            "beats": [{"start": i * 5.0, "end": i * 5.0 + 5, "kind": k, "name": f"beat {i}", "status": s}
                      for i, (k, s) in enumerate(beats)]}


def reel_doc(sc, owner, *, outlier, days_ago=10, fresh=False, discount=None, shp=None, tribe=None):
    posted = (PULL - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {"shortcode": sc, "owner": owner, "posted": posted, "outlier": outlier,
            "flags": {"fresh": fresh, "paid": False}, "discount": discount, "facts": {"duration_s": 40.0},
            "shape": shp or store.empty_shape(), "tribe": tribe}


class TempSwipe(unittest.TestCase):
    """alpha: 10 normal reels, 2 baseline outliers, 1 discounted outlier, a pinned, a paid and a
    carousel post, plus the target outlier ALPHAOUT01. beta: one outlier, no post list."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="patterns-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, sub in (("SWIPE", "swipe"), ("DRAFTS", "drafts"), ("OUTPUTS", "outputs"), ("VAULT", "vault")):
            p = mock.patch.object(store, name, self.tmp / sub)
            p.start()
            self.addCleanup(p.stop)
        items = [item(f"ALPHANORM{i}", 1000 + 10 * i, GATE if i < 4 else QUESTION if i < 7 else STATEMENT,
                      days_ago=10 + i) for i in range(10)]
        items += [item("ALPHAHIT01", 5000, GATE, days_ago=30, duration=25.0),
                  item("ALPHAHIT02", 5000, TEASE, days_ago=31, duration=70.0),
                  item("ALPHADISC1", 6000, TEASE, days_ago=32),
                  item("ALPHAPIN01", 90000, GATE, pinned=True, days_ago=200),
                  item("ALPHAPAID1", 9000, GATE, paid=True, days_ago=40),
                  item("ALPHACARO1", None, GATE, kind="carousel_container"),
                  item("ALPHAOUT01", 9000, GATE, days_ago=5)]
        baseline = store.compute_baseline(items, pulled_at=PULL.isoformat(), pulled_at_note="test pull",
                                          source="test", targets=("ALPHAOUT01",))
        store.save_creator({"handle": "alpha", "platform": "instagram", "baseline": baseline})
        store.save_json(store.creator_items_path("alpha"), items)
        store.save_creator({"handle": "beta", "platform": "instagram", "baseline": dict(baseline, n=11)})
        self.save(reel_doc("ALPHAOUT01", "alpha", outlier=True, days_ago=5, shp=shape(
            ("off-camera-question-number-answer", "suggested"), ("talking-head", "accepted"),
            ("comment-keyword", "rejected"),
            [("hook", "suggested"), ("setup", "suggested"), ("setup", "suggested"), ("cta", "suggested")]),
            tribe={"job_id": "20261001-120000-0123abcd", "run_date": "2026-10-01", "scale": "within-reel"}))
        self.save(reel_doc("BETAOUT001", "beta", outlier=True, days_ago=60, shp=shape(
            ("off-camera-question-number-answer", "accepted"), ("skit", "suggested"), ("end-card", "suggested"),
            [("hook", "accepted"), ("proof", "accepted"), ("cta", "accepted")])))
        self.save(reel_doc("ALPHAFRSH1", "alpha", outlier=False, days_ago=1, fresh=True,
                           shp=shape(("direct-question", "suggested"))))
        self.save(reel_doc("ALPHADISC1", "alpha", outlier=False, days_ago=32,
                           discount={"reason": "test", "by": "test", "at": PULL.isoformat()}))

    def save(self, doc):
        store.save_reel(doc)

    def built(self, write=True):
        return patterns.build(write=write)

    def by_id(self, doc):
        return {p["id"]: p for p in doc["patterns"]}

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = patterns.main(list(args))
        return rc, out.getvalue(), err.getvalue()


class CaptionLevelTests(TempSwipe):
    def test_contrast_is_outliers_vs_same_creators_normal(self):
        p = self.by_id(self.built())["hook.caption.keyword-gate-first"]
        self.assertEqual(p["contrast"], {"outliers": {"k": 2, "n": 3}, "normal": {"k": 4, "m": 10}, "level": "caption"})
        self.assertEqual(p["reels"], ["ALPHAHIT01", "ALPHAOUT01"])
        self.assertIn("outliers 2/3 vs normal 4/10", p["line"])
        self.assertTrue(p["few_reels"])
        self.assertEqual(p["by_creator"]["alpha"]["normal"], {"k": 4, "m": 10})
        self.assertEqual((p["first_seen"], p["last_seen"]), ("2026-09-01", "2026-09-26"))

    def test_left_out_reels_are_in_neither_group(self):
        doc = self.built()
        left = doc["population"]["caption"]["left_out"]
        self.assertEqual(left["pinned"], ["ALPHAPIN01"])
        self.assertEqual(left["paid"], ["ALPHAPAID1"])
        self.assertEqual(left["discounted"], ["ALPHADISC1"])
        self.assertEqual(left["fresh"], ["ALPHAFRSH1"])
        self.assertEqual(left["no_post_list"], ["BETAOUT001"])
        self.assertEqual(doc["population"]["caption"]["creators"], {"alpha": {"outliers": 3, "normal": 10}})
        tease = self.by_id(doc)["hook.caption.end-tease"]
        self.assertEqual(tease["contrast"]["outliers"], {"k": 1, "n": 3})   # the discounted tease is not counted

    def test_every_line_passes_the_shared_checks(self):
        doc = self.built()
        self.assertTrue(doc["patterns"])
        for p in doc["patterns"]:
            render.check_pattern_line(p["line"])
            render.check_authored([("line", p["line"]), ("slot", p["slot"]), ("label", p["label"])])
            self.assertNotRegex(p["line"], r"\d+\.\d+|plays|likes")

    def test_lengths_and_cta_features(self):
        ids = self.by_id(self.built())
        self.assertEqual(ids["format.caption.length-under-30s"]["contrast"]["outliers"], {"k": 1, "n": 3})
        self.assertEqual(ids["format.caption.length-over-60s"]["contrast"]["outliers"], {"k": 1, "n": 3})
        self.assertEqual(ids["cta.caption.comment-keyword"]["contrast"]["normal"], {"k": 4, "m": 10})
        self.assertEqual(ids["format.caption.caption-short"]["contrast"]["normal"], {"k": 3, "m": 10})
        self.assertEqual(ids["format.caption.caption-medium"]["contrast"]["normal"], {"k": 7, "m": 10})


class SpokenLevelTests(TempSwipe):
    def test_spoken_patterns_say_no_comparison_yet(self):
        ids = self.by_id(self.built())
        p = ids["hook.spoken.off-camera-question-number-answer"]
        self.assertEqual(p["contrast"], {"outliers": {"k": 2, "n": 2}, "normal": {"k": None, "m": None},
                                         "level": "spoken"})
        self.assertIn(render.PATTERN_NO_COMPARE, p["line"])
        self.assertEqual(p["labels"], "suggested")   # one of the two is still only suggested
        self.assertIn("(suggested)", p["line"])
        self.assertTrue(p["few_reels"])
        self.assertEqual(p["family"], "Big Number / Outcome")

    def test_rejected_labels_and_fresh_reels_are_skipped(self):
        doc = self.built()
        ids = self.by_id(doc)
        self.assertNotIn("cta.spoken.comment-keyword", ids)            # rejected on ALPHAOUT01
        self.assertEqual(ids["cta.spoken.end-card"]["contrast"]["outliers"], {"k": 1, "n": 1})
        self.assertNotIn("hook.spoken.direct-question", ids)           # only on the fresh reel
        self.assertEqual(doc["population"]["spoken"]["left_out"]["fresh"], ["ALPHAFRSH1"])

    def test_structures_merge_repeated_kinds(self):
        ids = self.by_id(self.built())
        self.assertIn("structure.spoken.hook-setup-cta", ids)
        self.assertIn("structure.spoken.hook-proof-cta", ids)
        self.assertEqual(ids["structure.spoken.hook-setup-cta"]["slot"], "[hook] → [setup] → [cta]")
        self.assertEqual(ids["structure.spoken.hook-proof-cta"]["labels"], "accepted")

    def test_comparison_once_enough_normal_reels_are_tagged(self):
        for i in range(3):
            self.save(reel_doc(f"ALPHATAG{i}", "alpha", outlier=False, days_ago=20 + i,
                               shp=shape(("direct-question" if i else "off-camera-question-number-answer", "accepted"))))
        ids = self.by_id(self.built())
        p = ids["hook.spoken.off-camera-question-number-answer"]
        self.assertEqual(p["contrast"]["normal"], {"k": 1, "m": 3})
        self.assertIn("outliers 2/2 vs normal 1/3", p["line"])
        self.assertIn("outliers 0/2 vs normal 2/3", ids["hook.spoken.direct-question"]["line"])
        for p in ids.values():
            render.check_pattern_line(p["line"])


class BuildTests(TempSwipe):
    def test_tribe_fields_are_never_read(self):
        def strip(doc):
            return [{k: v for k, v in p.items() if k != "added_at"} for p in doc["patterns"]]
        a = strip(self.built(write=False))
        r = store.load_reel("ALPHAOUT01")
        r["tribe"] = {"job_id": "20261002-120000-0123abcd", "run_date": "2026-10-02", "scale": "within-reel",
                      "peak": 99}
        self.save(r)
        self.assertEqual(a, strip(self.built(write=False)))

        def keys(o):
            if isinstance(o, dict):
                return set(o) | {k for v in o.values() for k in keys(v)}
            if isinstance(o, list):
                return {k for v in o for k in keys(v)}
            return set()
        self.assertNotIn("tribe", {k.lower() for k in keys(self.built(write=False))})

    def test_his_uses_count_drafts_not_examples(self):
        store.save_json(store.DRAFTS / "d1.json", {"id": "d1", "status": "draft",
                                                   "pattern_ids": ["hook.caption.keyword-gate-first"]})
        store.save_json(store.DRAFTS / "ex1.json", {"id": "ex1", "status": "example",
                                                    "pattern_ids": ["hook.caption.keyword-gate-first"]})
        ids = self.by_id(self.built())
        self.assertEqual(ids["hook.caption.keyword-gate-first"]["his_uses"], ["d1"])
        self.assertEqual(ids["hook.caption.end-tease"]["his_uses"], [])

    def test_added_at_kept_across_rebuilds(self):
        with mock.patch.object(store, "now_iso", return_value="2026-10-01T00:00:00+00:00"):
            self.built()
        with mock.patch.object(store, "now_iso", return_value="2026-10-05T00:00:00+00:00"):
            doc = self.built()
        self.assertEqual(doc["updated_at"], "2026-10-05T00:00:00+00:00")
        self.assertTrue(all(p["added_at"] == "2026-10-01T00:00:00+00:00" for p in doc["patterns"]))
        on_disk = store.load_json(store.patterns_path())
        self.assertEqual(on_disk["updated_at"], "2026-10-05T00:00:00+00:00")

    def test_refuses_a_line_without_contrast(self):
        with mock.patch.object(patterns, "pattern_line", return_value="Hook: keyword gate · outliers 2/3"):
            with self.assertRaises(patterns.PatternError):
                self.built(write=False)
        self.assertFalse(store.patterns_path().exists())

    def test_refuses_brain_words_next_to_outlier_counts(self):
        with mock.patch.dict(shapes.CAPTION_OPENERS, {"keyword-gate-first": ("peak keyword gate", "keyword-gate",
                                                                             "slot", "test")}):
            with self.assertRaises(patterns.PatternError):
                self.built(write=False)

    def test_no_outliers_means_no_caption_patterns(self):
        for sc in ("ALPHAOUT01", "BETAOUT001"):
            (store.reel_path(sc)).unlink()
        items = [it for it in store.load_json(store.creator_items_path("alpha"))
                 if it["shortCode"] not in ("ALPHAHIT01", "ALPHAHIT02", "ALPHADISC1", "ALPHAOUT01")]
        store.save_json(store.creator_items_path("alpha"), items)
        doc = self.built(write=False)
        self.assertEqual([p for p in doc["patterns"] if p["contrast"]["level"] == "caption"], [])

    def test_cli_build_and_dry_run(self):
        rc, out, _ = self.run_cli("build", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("dry run", out)
        self.assertFalse(store.patterns_path().exists())
        rc, out, _ = self.run_cli("build")
        self.assertEqual(rc, 0)
        self.assertTrue(store.patterns_path().exists())
        self.assertIn("outliers 2/3 vs normal 4/10", out)
        self.assertNotIn("views", out.lower())


class ConsistencyTests(TempSwipe):
    """One outlier rule everywhere, one cut-off, one signal counted once."""

    def gamma(self):
        # 2,100 plays: 1.94x a median that includes it (1,080), 2.02x the median of the other four (1,040).
        items = [item(f"GAMMA000{i}", p, STATEMENT, days_ago=10 + i) for i, p in enumerate((1000, 1000, 1080, 1080, 2100))]
        for it in items:
            it["ownerUsername"] = "gamma"
        baseline = store.compute_baseline(items, pulled_at=PULL.isoformat(), pulled_at_note="test pull", source="test")
        store.save_creator({"handle": "gamma", "platform": "instagram", "baseline": baseline})
        store.save_json(store.creator_items_path("gamma"), items)
        return baseline

    def test_baseline_reels_leave_themselves_out(self):
        self.assertEqual(self.gamma()["median"]["plays"], 1080)
        rows = {r["shortcode"]: r for r in store.baseline_reels("gamma")}
        self.assertTrue(rows["GAMMA0004"]["outlier"])            # 2100 / 1040, like a swipe reel's "this reel left out"
        self.assertEqual(rows["GAMMA0004"]["x_plays"], 2.02)
        self.assertFalse(rows["GAMMA0003"]["outlier"])
        doc = self.built(write=False)
        self.assertEqual(doc["population"]["caption"]["creators"]["gamma"], {"outliers": 1, "normal": 4})
        self.assertIn("GAMMA0004", doc["population"]["caption"]["borderline"])
        self.assertIn("other baseline reels (this reel left out)", doc["rules"])

    def test_spoken_level_skips_a_baseline_that_is_not_reels_only(self):
        store.save_creator({"handle": "delta", "platform": "instagram", "baseline": {
            "n": 11, "kind": "all post types (VAULT record), not reels only", "median": {"plays": 100},
            "source": "VAULT repurpose record, not re-checked", "excluded": {}}})
        self.save(reel_doc("DELTAOUT01", "delta", outlier=True, shp=shape(("cold-open-before-confession", "suggested"))))
        doc = self.built(write=False)
        self.assertEqual(doc["population"]["spoken"]["left_out"]["baseline_not_checked"], ["DELTAOUT01"])
        self.assertNotIn("DELTAOUT01", doc["population"]["spoken"]["outliers"])
        self.assertNotIn("hook.spoken.cold-open-before-confession", self.by_id(doc))

    def test_one_signal_listed_twice_is_marked(self):
        ids = self.by_id(self.built(write=False))
        # Every caption whose line 1 is the gate is also a keyword-gate CTA: the same reels, one signal.
        self.assertEqual(ids["cta.caption.comment-keyword"].get("same_reels_as"), "hook.caption.keyword-gate-first")
        self.assertNotIn("same_reels_as", ids["hook.caption.keyword-gate-first"])
        self.assertFalse(any(p.get("same_reels_as") for p in ids.values() if p["contrast"]["level"] == "spoken"))
        self.assertFalse(any("_carriers" in p for p in ids.values()))

    def test_one_over_60_cut_off(self):
        self.assertEqual(shapes.reel_length(store.OVER_S), "length-30-60s")
        self.assertEqual(shapes.reel_length(store.OVER_S + 0.3), "length-over-60s")
        r = store.derive({"shortcode": "ALPHAOUT01", "counts": {"plays": 1}, "facts": {"duration_s": store.OVER_S + 0.3}},
                         store.load_creator("alpha"))
        self.assertTrue(r["flags"]["over_60s"])


class ShapesTests(unittest.TestCase):
    def test_vocabulary_passes_the_shared_rule_checks(self):
        render.check_authored(shapes.all_texts())

    def test_vocabulary_has_no_predicted_response_words(self):
        # Pattern lines carry "outliers", so no label or slot may name the brain layer.
        hits = [(w, t) for w, t in shapes.all_texts() if render.BRAIN_TERMS_RE.search(t)]
        self.assertEqual(hits, [])

    def test_hook_ids_fit_the_card_hook_line(self):
        for i in shapes.HOOK_SHAPES:
            lab = shapes.label(i)
            self.assertIsNone(render._HOOK_FORBIDDEN_RE.search(lab), i)
            self.assertIsNone(render.COUNT_TERMS_RE.search(lab), i)
            self.assertLessEqual(len(lab), 45, i)
            self.assertEqual(lab, render._shape_label(i))

    def test_families_and_ids(self):
        for fam, _, _ in shapes.HOOK_SHAPES.values():
            self.assertIn(fam, shapes.FAMILIES)
        for _, fam, _, _ in shapes.CAPTION_OPENERS.values():
            self.assertIn(fam, shapes.FAMILIES)
        self.assertLessEqual({k for k, _ in reel.CTA_PATTERNS}, set(shapes.CTA_TYPES))
        self.assertEqual(set(shapes.BEAT_KINDS), {"hook", "setup", "proof", "demo", "payoff", "cta"})
        with self.assertRaises(ValueError):
            shapes.check_shape("hook_shape", "made-up-shape")
        shapes.check_shape("format", "skit")

    def test_caption_openers(self):
        cases = {
            'Comment "GUIDE" and I\'ll send it': "keyword-gate-first",
            "Comment GUIDE and I’ll pass it on": "keyword-gate-first",
            "Comment one thing you repeat each month and I will choose one": "comment-prompt-first",
            "Tool A vs Tool B, which one should I use?": "tool-versus-tool",
            "A big company just launched a new feature for teams": "news-just-shipped",
            "How do I stop running out of credits?": "question-first-person",
            "Should you build a product this year?": "question-to-viewer",
            "20 tasks this morning and nothing done": "number-first",
            "Most advice on sales is about convincing.": "most-people-claim",
            "How to connect a tool to your account": "how-to-title",
            "Ending is the best part": "end-tease",
            "Been building small tools all season and it adds up": "first-person-statement",
            "Build flows with a tool": "short-label",
            "Innovation is moving slower than it looks this year": "statement",
            "": "short-label",
        }
        for line, want in cases.items():
            self.assertEqual(shapes.caption_opener(line), want, line)

    def test_lengths_and_structure(self):
        self.assertEqual(shapes.caption_length("one two three"), "caption-short")
        self.assertEqual(shapes.caption_length(" ".join(["w"] * 61)), "caption-long")
        self.assertEqual(shapes.reel_length(29.9), "length-under-30s")
        self.assertEqual(shapes.reel_length(60), "length-30-60s")
        self.assertEqual(shapes.reel_length(60.2), "length-over-60s")   # one cut-off: store.OVER_S, more than 60 s
        self.assertEqual(shapes.reel_length(72), "length-over-60s")
        self.assertIsNone(shapes.reel_length(None))
        beats = [{"kind": "hook"}, {"kind": "setup"}, {"kind": "setup"}, {"kind": "cta"}]
        self.assertEqual(shapes.structure_id(beats), "hook-setup-cta")
        self.assertEqual(shapes.structure_slot(beats), "[hook] → [setup] → [cta]")


@unittest.skipUnless(store.VAULT.is_dir() and (REAL_SWIPE / "reels").is_dir(), "real corpus not on this machine")
class RealDataTests(unittest.TestCase):
    """Read-only: the vocabulary and the suggestion files are shape only, and a build of the real
    swipe file (not written) passes every check."""

    def test_vocabulary_is_shape_only(self):
        res = copycheck.check_texts(shapes.all_texts())
        self.assertTrue(res["ok"], res["hits"])

    def test_suggestion_files_are_shape_only(self):
        files = sorted((REAL_SWIPE / "reels").glob("*/suggestions.json"))
        if not files:
            self.skipTest("no suggestions.json yet")
        for f in files:
            d = json.loads(f.read_text(encoding="utf-8"))
            texts = [(k, v) for k, v in copycheck.json_strings(d) if not k.startswith("sources")]
            res = copycheck.check_texts(texts)
            self.assertTrue(res["ok"], (f, res["hits"]))
            render.check_authored([(k, v) for k, v in texts if k not in ("made_at", "shortcode")])
            s = d["shape"]
            self.assertLessEqual(set(s), set(store.SHAPE_FIELDS), f)
            # A reel with no spoken hook (text on screen only) may leave hook_shape out; `reel tag`
            # takes any subset of the fields. When it is there, it must be a known id.
            if s.get("hook_shape") is not None:
                shapes.check_shape("hook_shape", s["hook_shape"]["id"])
            shapes.check_shape("format", s["format"]["value"])
            shapes.check_shape("cta", s["cta"]["value"])
            self.assertTrue(all(b["kind"] in shapes.BEAT_KINDS for b in s["beats"]))

    def test_real_build_passes_checks(self):
        doc = patterns.build(write=False)
        for p in doc["patterns"]:
            render.check_pattern_line(p["line"])
            if p["contrast"]["level"] == "spoken" and p["contrast"]["normal"]["m"] is None:
                self.assertIn(render.PATTERN_NO_COMPARE, p["line"])


class ArchivedTests(TempSwipe):
    """D31: an archived reel, and a creator whose reels are all archived, feed no pattern."""

    def population(self):
        reels = {r["shortcode"]: r for r in store.list_reels()}
        return patterns.caption_population(reels)[0]

    def test_archived_reel_is_out_of_every_population(self):
        before = {r["shortcode"] for r in self.population()}
        self.assertIn("ALPHAOUT01", before)
        doc = store.load_reel("ALPHAOUT01")
        doc["archived"] = True
        store.save_reel(doc)
        after = {r["shortcode"] for r in self.population()}
        self.assertNotIn("ALPHAOUT01", after)
        self.assertIn("ALPHAHIT01", after)   # alpha still has active reels
        spoken = patterns.spoken_population({r["shortcode"]: r for r in store.list_reels()})[0]
        self.assertNotIn("ALPHAOUT01", {r["shortcode"] for r in spoken})

    def test_creator_with_only_archived_reels_feeds_nothing(self):
        for sc in ("ALPHAOUT01", "ALPHAFRSH1", "ALPHADISC1"):
            doc = store.load_reel(sc)
            doc["archived"] = True
            store.save_reel(doc)
        owners = {r["owner"] for r in self.population()}
        self.assertNotIn("alpha", owners)

    def test_build_ignores_archived_reels_and_unarchive_restores(self):
        full = self.by_id(self.built(write=False))
        doc = store.load_reel("BETAOUT001")
        doc["archived"] = True
        store.save_reel(doc)
        fewer = self.by_id(self.built(write=False))
        used = lambda doc: {sc for p in doc.values() for sc in p.get("reels", [])}   # noqa: E731
        self.assertIn("BETAOUT001", used(full))
        self.assertNotIn("BETAOUT001", used(fewer))
        doc["archived"] = False
        store.save_reel(doc)
        self.assertEqual(sorted(self.by_id(self.built(write=False))), sorted(full))


if __name__ == "__main__":
    unittest.main(verbosity=1)
