"""Tests for the 6-word copy check. Run: python strategist/test_copycheck.py

Synthetic tests point the store at temp folders (a fake swipe file, outputs and
VAULT). The real-data tests read the Demo TRIBE job's events.json and the real
corpus read-only, and skip when those files aren't on this machine. Nothing is
written outside temp folders; no network."""

import contextlib
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
from strategist import copycheck, store  # noqa: E402

DEMO_JOB = "20260101-000000-demo0000"
REAL_EVENTS = PROJECT_ROOT / "outputs" / DEMO_JOB / "events.json"
JOB = "20261001-120000-0123abcd"
TRANSCRIPT = "Purple otters quietly audit every spreadsheet before lunch on Tuesdays"
EVENT_WORDS = "Seven copper kettles whistle louder than any marching band could manage today"
VAULT = ("# vault\n\n```text\nNobody reads the onboarding manual until the server melts down\n```\n\n"
         "1. `Ship the tiny fix before the giant rewrite eats the quarter` (shape)\n")
OWN_POST = "My own sentence about invoices and calendars that nobody else wrote at all"
CLEAN = "I checked the booking sheet by hand on Monday and found two rows missing."


def words_items(text, start=0.0):
    return [{"text": w, "start": start + i * 0.3, "stop": start + i * 0.3 + 0.25} for i, w in enumerate(text.split())]


class TempCorpus(unittest.TestCase):
    """A fake swipe file, outputs folder and VAULT tree in a temp folder."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="copycheck-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, sub in (("SWIPE", "swipe"), ("DRAFTS", "drafts"), ("OUTPUTS", "outputs"), ("VAULT", "vault")):
            p = mock.patch.object(store, name, self.tmp / sub)
            p.start()
            self.addCleanup(p.stop)
        reel = {"shortcode": "TESTREEL01", "owner": "testcreator", "tribe": {"job_id": JOB}}
        store.save_json(store.reel_path("TESTREEL01"), reel)
        priv = store.private_dir("TESTREEL01")
        store.save_text(priv / "transcript.txt", TRANSCRIPT + ".\n")
        store.save_json(priv / "words.json", words_items(TRANSCRIPT))
        store.save_text(priv / "caption.txt", "A caption line about lighthouse keepers and their tidy logbooks\n")
        store.save_json(store.OUTPUTS / JOB / "events.json", {"words": words_items(EVENT_WORDS)})
        vault = store.VAULT
        store.save_text(vault / "linkedin" / "COPY-VAULT.md", VAULT)
        store.save_text(vault / "research" / "repurpose" / "media" / "ABCDE12345" / "video.transcript.srt",
                        "1\n00:00:00,000 --> 00:00:02,000\nGranite owls never blink during\n\n"
                        "2\n00:00:02,000 --> 00:00:04,000\nthe midnight inventory count\n")
        store.save_json(vault / "research" / "raw" / "posts-test.json", [
            {"author": {"publicIdentifier": copycheck.SELF}, "content": OWN_POST},
            {"author": {"publicIdentifier": "someone-else"}, "content": "Cold brew budgets explain nothing about hiring junior analysts"},
        ])
        store.save_json(vault / "research" / "repurpose" / "data" / "ABCDE12345.json",
                        {"platform": "instagram", "owner": "othercreator", "caption": "",
                         "transcript": "Velvet tractors plough the moon in silent rows"})

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = copycheck.main(list(args))
        return rc, out.getvalue(), err.getvalue()

    def draft_file(self, text, name="draft.md"):
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return p


class NormaliseTests(unittest.TestCase):
    def test_case_punctuation_apostrophes_thousands(self):
        self.assertEqual(copycheck.words("Don’t STOP, 1,000 times!"), ["dont", "stop", "1000", "times"])
        self.assertEqual(copycheck.words("don't stop 1000 times"), ["dont", "stop", "1000", "times"])

    def test_runs_are_six_words(self):
        r = copycheck.runs("a b c d e f g".split())
        self.assertEqual(r, {"a b c d e f", "b c d e f g"})
        self.assertEqual(copycheck.runs("a b c d e".split()), set())

    def test_srt_text_joins_cues(self):
        t = copycheck.srt_text("1\n00:00:00,000 --> 00:00:01,000\nhello there\n\n2\n00:00:01,000 --> 00:00:02,000\nfriend\n")
        self.assertEqual(t, "hello there friend")


class CorpusTests(TempCorpus):
    def test_seeded_tribe_events_run_is_blocked(self):
        seeded = "My draft opens here. " + " ".join(EVENT_WORDS.split()[2:8]) + " and then moves on."
        res = copycheck.check_text(seeded, include_vault=False)
        self.assertFalse(res["ok"])
        runs = {h["run"]: h for h in res["hits"] if h["kind"] == "copy"}
        run = " ".join(w.lower() for w in EVENT_WORDS.split()[2:8])
        self.assertIn(run, runs)
        self.assertIn(f"TRIBE job {JOB}", runs[run]["source"])

    def test_events_of_unlinked_jobs_are_not_read(self):
        store.save_json(store.reel_path("TESTREEL01"), {"shortcode": "TESTREEL01", "owner": "testcreator", "tribe": None})
        seeded = " ".join(EVENT_WORDS.split()[:7])
        self.assertTrue(copycheck.check_text(seeded, include_vault=False)["ok"])

    def test_swipe_transcript_and_case_insensitive(self):
        res = copycheck.check_text("PURPLE otters, quietly audit EVERY spreadsheet!", include_vault=False)
        self.assertFalse(res["ok"])
        self.assertEqual(res["hits"][0]["source"], "@testcreator TESTREEL01 timed words")

    def test_clean_draft_passes(self):
        res = copycheck.check_text(CLEAN)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["hits"], [])

    def test_em_dash_flagged(self):
        res = copycheck.check_text("A clean line — with a dash in it.")
        self.assertFalse(res["ok"])
        self.assertEqual(res["em_dashes"], 1)
        self.assertEqual(res["hits"], [{"kind": "em_dash", "count": 1, "where": "text"}])
        self.assertTrue(copycheck.check_text("An en dash – and a hyphen - are fine.")["ok"])

    def test_vault_vault_srt_data_and_raw_posts(self):
        for text, source in (("nobody reads the onboarding manual until the", "VAULT COPY-VAULT.md"),
                             ("ship the tiny fix before the giant", "VAULT COPY-VAULT.md"),
                             ("never blink during the midnight inventory", "VAULT repurpose/media/ABCDE12345"),
                             ("velvet tractors plough the moon in", "VAULT repurpose instagram:@othercreator"),
                             ("budgets explain nothing about hiring junior", "VAULT LinkedIn @someone-else")):
            res = copycheck.check_text(text)
            self.assertFalse(res["ok"], text)
            self.assertTrue(res["hits"][0]["source"].startswith(source), res["hits"][0])
        self.assertTrue(copycheck.check_text("never blink during the midnight inventory", include_vault=False)["ok"])

    def test_his_own_posts_are_not_in_the_corpus(self):
        self.assertTrue(copycheck.check_text(OWN_POST)["ok"])

    def test_draft_json_reports_where(self):
        draft = {"id": "d1", "status": "draft", "beats": [
            {"name": "hook", "say": CLEAN, "on_screen": "", "notes": [{"n": 1, "text": "Test: shorter"}]},
            {"name": "body", "say": "We " + " ".join(TRANSCRIPT.split()[:6]) + " now.", "on_screen": "tidy",
             "notes": []}],
            "variants": [{"id": "v1", "shape": "direct-question", "line": "Is your sheet — really done?", "why": "x"}],
            "copycheck": {"ok": False, "hits": [{"run": " ".join(TRANSCRIPT.split()[:6])}]}}
        p = self.tmp / "d1.json"
        p.write_text(json.dumps(draft), encoding="utf-8")
        res = copycheck.check_file(p, include_vault=False)
        copies = [h for h in res["hits"] if h["kind"] == "copy"]
        self.assertEqual([h["where"] for h in copies], ["beats[1].say"])
        self.assertEqual([h["where"] for h in res["hits"] if h["kind"] == "em_dash"], ["variants[0].line"])

    def test_cli_exit_codes_and_output(self):
        rc, out, _ = self.run_cli(str(self.draft_file(CLEAN)))
        self.assertEqual(rc, 0)
        self.assertIn("PASS", out)
        rc, out, _ = self.run_cli(str(self.draft_file("Then " + TRANSCRIPT + " again.")), "--no-vault")
        self.assertEqual(rc, 1)
        self.assertIn("FAIL", out)
        self.assertIn('"purple otters quietly audit every spreadsheet"', out)
        # Hits print shared 6-word runs, never the whole transcript.
        self.assertNotIn(TRANSCRIPT.lower(), out.lower())
        rc, out, _ = self.run_cli(str(self.draft_file("One — two")))
        self.assertEqual(rc, 1)
        self.assertIn("em dashes: 1", out)
        rc, _, err = self.run_cli(str(self.tmp / "missing.md"))
        self.assertEqual(rc, 2)
        self.assertIn("no such file", err)
        rc, out, _ = self.run_cli(str(self.draft_file(CLEAN)), "--json")
        self.assertEqual(json.loads(out), {"ok": True, "hits": [], "em_dashes": 0})


@unittest.skipUnless(REAL_EVENTS.is_file(), "Demo TRIBE job not on this machine")
class RealDemoTests(unittest.TestCase):
    """Read-only checks against the real Demo job words and the real corpus."""

    def real_words(self):
        events = json.loads(REAL_EVENTS.read_text(encoding="utf-8"))
        return [w["text"] for w in events["words"]]

    def test_seeded_run_from_demo_events_is_blocked(self):
        ws = self.real_words()
        run_words = ws[120:126]
        draft = "In my own reel I would say this instead: " + " ".join(run_words) + " and stop there."
        expected = copycheck.runs(copycheck.words(" ".join(run_words)))
        tmp = Path(tempfile.mkdtemp(prefix="copycheck-real-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        # Only the linked job's events.json in the corpus: a temp swipe file linking the real job.
        with mock.patch.object(store, "SWIPE", tmp / "swipe"):
            store.save_json(store.reel_path("DEMO0000001"),
                            {"shortcode": "DEMO0000001", "owner": "demo_creator_a", "tribe": {"job_id": DEMO_JOB}})
            res = copycheck.check_text(draft, include_vault=False)
        self.assertFalse(res["ok"])
        hits = {h["run"]: h["source"] for h in res["hits"] if h["kind"] == "copy"}
        self.assertTrue(expected and expected <= hits.keys(), (expected, hits))
        self.assertTrue(all(f"TRIBE job {DEMO_JOB}" in hits[r] for r in expected))

    def test_seeded_run_blocked_by_the_full_corpus(self):
        ws = self.real_words()
        res = copycheck.check_text("Here is my line: " + " ".join(ws[60:66]) + ".")
        self.assertFalse(res["ok"])

    def test_clean_draft_passes_the_full_corpus(self):
        res = copycheck.check_text(CLEAN + " The fix took one afternoon and a spare coffee.")
        self.assertTrue(res["ok"], res["hits"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
