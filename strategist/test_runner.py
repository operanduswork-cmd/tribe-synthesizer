"""Tests for the laptop runner and its job checks. Run: python strategist/test_runner.py

Covers strategist/jobs.py (argument fuzzing, every D26 limit, stage gating, Pause, the
caps, the job states, leases and retries) and strategist/runner.py (the job loop over an
in-memory queue that mirrors the SQL in strategist/db.py, the executors against a temp
swipe store, Upstash over a fake opener, child processes, the instance lock, the Task
Scheduler entry). No database, no Upstash, no Apify, no Modal, no network: every HTTP
call goes to a fake opener and a stray urlopen fails the test. The real .env is never
read, and swipe/, drafts/ and VAULT are never written (temp folders only). The only real
processes are local Python children for the kill-tree test."""

import contextlib
import datetime as dt
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
# Run as a script, this folder is sys.path[0]; drop it so "render" can only mean dashboard/render.py.
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
sys.path.insert(0, str(PROJECT_ROOT))
from strategist import db, jobs, reel, runner, store  # noqa: E402

R = store.rules()
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 15, 6, 30, tzinfo=UTC)
FAKE_TOKEN = "SYNTHETIC_upstash_token_never_print_0123456789"
FAKE_APIFY = "apify_api_SYNTHETIC_TOKEN_never_print_0123456789"
UPSTASH = "https://demo-runner-test.upstash.io"

# One valid value for every argument of every kind (all properties, optional ones too).
VALID = {
    "reel.accept": {"sc": "DEMO0000001", "field": "beats.1"},
    "reel.reject": {"sc": "DEMO0000001", "field": "hook_shape"},
    "reel.discount": {"sc": "DEMO0000001", "reason": "It's a paid collab, #ad in the caption"},
    "patterns.build": {},
    "lab.check": {"draft_id": "20261009-my-draft"},
    "sync.push": {},
    "coach.new_draft": {"slug": "my-hook", "from_sc": "DEMO0000002", "pattern_id": "hook.spoken.question-first",
                        "brief": "Shorter hook.\nEnd on the proof line!"},
    "coach.this_but": {"draft_id": "20261009-my-draft", "variant_id": "v_2", "text": "This but punchier"},
    "coach.replace": {"draft_id": "20261009-my-draft", "replace": "the old opener", "with": "a sharper question"},
    "coach.tag_shapes": {"sc": "DEMO0000003"},
    "reel.add_link": {"sc": "DEMO0000004"},
    "reel.add_handle": {"handle": "@demo_creator_a"},
    "tribe.lanes": {"sc": "DEMO0000005"},
}

# Refused in every string argument, identifiers and free text alike.
FUZZ_EVERYWHERE = [
    # shell metacharacters
    "DEMO0;rm -rf x", "DEMO0|calc", "DEMO0&&calc", "$(calc)", "`calc`", "DEMO0>out", "%PATH%", "DEMO0^x",
    "a & b", "x;y", "DEMO0 < in",
    # quotes
    '"DEMO00001"', "\u201cDEMO00001\u201d", 'say "hi"',
    # newlines and control characters
    "DEMO00001\r\n", "DEMO0\r0001", "DEMO\x0000001", "DEMO0\t0001", "\x1b[31mDEMO", "DEMO\x7f0001",
    # Unicode lookalikes and invisible characters
    "\uff24\uff25\uff2d\uff2f00001", "D\u0415MO00001", "DEMO\u200b00001", "DEMO\u202e00001", "DEMO\u00a000001",
    "DEMO\ufeff00001", "\u0391\u0392C00001",
    # path traversal
    "../../.env", "..\\..\\x", "C:\\Windows", "/etc/passwd", "~/x", "a/../b", "..", "swipe/reels/x",
    # very long
    "A" * 10_000, "a b " * 400,
    # flags and dash lookalikes
    "-Precision", "--yes", "-h", "-Precision fp32", "\u2013Precision", "\u2014yes", "\u2212x", "\u2010x", "\uff0dx",
    # empty and padding
    "", " ", " DEMO00001", "DEMO00001 ",
]
# Refused in identifiers; plain text may hold them (an apostrophe, a long word, Arabic digits).
FUZZ_IDS_ONLY = ["'DEMO00001'", "A" * 200, "\u0662\u0660\u0662\u0666\u0661\u0660\u0660\u0669-x1",
                 "DEMO00001\n", "DEMO\n00001", "DEMO 00001", "DEMO=00001", "DEMO@0001"]
# Refused in one-line text (a discount reason); multi-line coach text takes them.
FUZZ_ONE_LINE = ["DEMO00001\n", "DEMO\n00001", "line one\nline two"]


def uid() -> str:
    return str(uuid.uuid4())


def no_network(*a, **k):
    raise AssertionError("unexpected network call in a test")


def enabled_kinds(*names):
    """jobs.kinds() with these kinds switched on (the paid ones are off in stage 1)."""
    real = jobs.kinds()
    out = {k: dict(v) for k, v in real.items()}
    for n in names:
        out[n]["enabled"] = True
    return mock.patch.object(jobs, "kinds", return_value=out)


# ---------------------------------------------------------------- an in-memory jobs table

class UniqueViolation(Exception):
    sqlstate = db.UNIQUE_VIOLATION


class MemoryQueue:
    """The jobs, job_events and settings tables in memory, with the semantics of the SQL in
    strategist/db.py and web/db/migrations/0000_init.sql: claim order, no claim while
    paused, one running paid job, the live idem_key index, leases, finish rules."""

    def __init__(self, clock):
        self.clock = clock
        self.rows: dict[str, dict] = {}
        self.events: list[tuple[str, str]] = []
        self.paused = False
        self.writes = 0
        self.resets = 0
        self.seq = 0

    # -- the site's side
    def insert(self, kind, args=None, estimate_usd=0.0, idem_key=None, confirmed=True, confirmed_at=None,
               cancel_requested=False):
        if idem_key is not None:
            if not jobs.IDEM_RE.match(idem_key):
                raise ValueError("idem_key CHECK")
            if any(r["idem_key"] == idem_key and r["status"] in db.LIVE for r in self.rows.values()):
                raise UniqueViolation("jobs_idem_live")
        self.seq += 1
        job_id = uid()
        now = self.clock()
        self.rows[job_id] = {
            "id": job_id, "kind": kind, "args": dict(args if args is not None else VALID[kind]),
            "estimate_usd": float(estimate_usd), "idem_key": idem_key,
            # queued a little before now, so a confirm at now is a later click (as on the site)
            "created_at": now - dt.timedelta(seconds=10) + dt.timedelta(microseconds=self.seq),
            "confirmed_at": confirmed_at if confirmed_at is not None else (now if confirmed else None),
            "cancel_requested": cancel_requested, "status": "queued", "lease_until": None, "started_at": None,
            "finished_at": None, "result": None, "error_code": None, "refusal": None}
        return job_id

    def _job(self, r):
        return {k: r[k] for k in db.JOB_COLS}

    def _set(self, r, status):
        jobs.check_transition(r["status"], status)
        r["status"] = status
        self.writes += 1

    # -- the runner's side (DbQueue's methods)
    def claim(self):
        if self.paused:
            return None
        paid = jobs.paid_kinds()
        busy = any(r["status"] == "running" and r["kind"] in paid for r in self.rows.values())
        todo = sorted((r for r in self.rows.values() if r["status"] == "queued" and r["confirmed_at"] is not None
                       and not r["cancel_requested"] and not (busy and r["kind"] in paid)),
                      key=lambda r: (r["created_at"], r["id"]))
        if not todo:
            return None
        r = todo[0]
        self._set(r, "running")
        r["started_at"] = self.clock()
        r["lease_until"] = self.clock() + dt.timedelta(seconds=db.LEASE_S)
        return self._job(r)

    def heartbeat(self, job_id):
        r = self.rows.get(job_id)
        if not r or r["status"] != "running":
            return None
        r["lease_until"] = self.clock() + dt.timedelta(seconds=db.LEASE_S)
        return {"cancel_requested": r["cancel_requested"]}

    def finish(self, job_id, status, result=None, error_code=None, refusal=None):
        if status not in db.FINAL:
            raise db.DbError(status)
        if status == "failed" and not error_code:
            raise db.DbError("a failed job needs an error_code")
        if status == "refused" and not refusal:
            raise db.DbError("a refused job needs a refusal line")
        if error_code is not None and not db.ERROR_CODE_RE.match(error_code):
            raise db.DbError(error_code)
        if refusal is not None:
            db.clean_line(refusal, "refusal")
        if result is not None:
            db.canonical_json(result)
        r = self.rows[db.check_job_id(job_id)]
        if r["status"] not in db.LIVE:
            return False
        self._set(r, status)
        r.update(finished_at=self.clock(), lease_until=None, result=result, error_code=error_code, refusal=refusal)
        return True

    def add_event(self, job_id, key, **params):
        line = db.event_line(key, **params)
        self.events.append((db.check_job_id(job_id), line))
        self.writes += 1
        return line

    def interrupt_stale(self):
        out = []
        for r in self.rows.values():
            if r["status"] == "running" and jobs.lease_expired(r["lease_until"], self.clock()):
                self._set(r, "interrupted")
                r.update(finished_at=self.clock(), lease_until=None, error_code="lease_expired")
                out.append(r["id"])
        return out

    def cancel_queued(self):
        out = []
        for r in self.rows.values():
            if r["status"] == "queued" and r["cancel_requested"]:
                self._set(r, "cancelled")
                r["finished_at"] = self.clock()
                out.append(r["id"])
        return out

    def is_paused(self):
        return self.paused

    def paid_stats(self, job_id, day, month):
        paid = jobs.paid_kinds()
        rows = [r for r in self.rows.values() if r["id"] != job_id and r["status"] in
                ("running", "done", "failed", "interrupted")]
        today = [r for r in rows if r["kind"] in paid and r["started_at"] and r["started_at"] >= day]
        return {"running_other": sum(1 for r in rows if r["status"] == "running" and r["kind"] in paid),
                "today_n": len(today), "today_usd": sum(r["estimate_usd"] for r in today),
                "tribe_month_n": sum(1 for r in rows if r["kind"] == "tribe.lanes" and r["started_at"]
                                     and r["started_at"] >= month)}

    def retry_interrupted(self, job_id):
        r = self.rows[job_id]
        if r["status"] != "interrupted" or not jobs.should_retry(r["kind"], r["idem_key"], r["cancel_requested"]):
            return None
        try:
            return self.insert(r["kind"], r["args"], r["estimate_usd"], jobs.retry_key(job_id))
        except UniqueViolation:
            return None

    def list_queued(self, limit=20):
        rows = sorted((r for r in self.rows.values() if r["status"] == "queued" and not r["cancel_requested"]),
                      key=lambda r: (r["created_at"], r["id"]))
        return [self._job(r) for r in rows[:limit]]

    def reset(self):
        self.resets += 1

    # -- helpers for the tests
    def lines(self, job_id):
        return [line for j, line in self.events if j == job_id]


class Clock:
    def __init__(self, at=NOW):
        self.at = at

    def __call__(self):
        return self.at

    def advance(self, **kw):
        self.at += dt.timedelta(**kw)


class FakeExec:
    """An executor that records its calls, writes raw output to the job log and returns rc."""

    def __init__(self, rc=0, say="raw output line", boom=None):
        self.rc, self.say, self.boom, self.calls = rc, say, boom, []

    def __call__(self, kind, args, out):
        self.calls.append((kind, dict(args)))
        out.write(self.say + "\n")
        if self.boom:
            raise self.boom
        return self.rc


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="runner-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(store, "SWIPE", self.tmp / "swipe")   # the swipe lock lives in a temp folder
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch("urllib.request.urlopen", side_effect=no_network)
        p.start()
        self.addCleanup(p.stop)
        self.clock = Clock()
        self.q = MemoryQueue(self.clock)
        self.sync_calls = 0
        self.sync_rc = 0

    def fake_sync(self, out):
        self.sync_calls += 1
        out.write("sync output\n")
        return self.sync_rc

    def make_runner(self, executors=None, sync="fake", **kw):
        execs = executors if executors is not None else {k: FakeExec() for k in runner.STAGE1 if k != "sync.push"}
        return runner.Runner(self.q, None, executors=execs, sync=self.fake_sync if sync == "fake" else sync,
                             log_dir=self.tmp / "logs", clock=self.clock,
                             apify_usd=kw.pop("apify_usd", lambda: 0.0),
                             modal_usd=kw.pop("modal_usd", lambda now: 0.0), lease_s=kw.pop("lease_s", 30), **kw)

    def log_text(self, job_id):
        return (self.tmp / "logs" / f"{job_id}.log").read_text(encoding="utf-8")


# ---------------------------------------------------------------- argument fuzzing

class ArgumentTests(unittest.TestCase):
    def test_valid_arguments_pass_for_every_kind(self):
        self.assertEqual(set(VALID), set(jobs.kinds()))
        for kind, args in VALID.items():
            with self.subTest(kind=kind):
                self.assertEqual(jobs.validate(kind, args), args)

    def string_props(self):
        for kind, spec in jobs.kinds().items():
            for name in spec["args"]["properties"]:
                yield kind, name

    def test_every_string_argument_is_text_or_has_a_pattern(self):
        for kind, name in self.string_props():
            prop = jobs.kinds()[kind]["args"]["properties"][name]
            with self.subTest(kind=kind, name=name):
                self.assertEqual(prop["type"], "string")
                self.assertTrue(name in jobs.FREE_TEXT or "pattern" in prop or "enum" in prop)

    def test_fuzzed_values_are_refused_everywhere(self):
        n = 0
        for kind, name in self.string_props():
            text = name in jobs.FREE_TEXT
            fuzz = FUZZ_EVERYWHERE + ([] if text else FUZZ_IDS_ONLY)
            if text and not jobs.FREE_TEXT[name]:
                fuzz = fuzz + FUZZ_ONE_LINE
            for bad in fuzz:
                args = dict(VALID[kind], **{name: bad})
                with self.subTest(kind=kind, name=name, value=bad[:40]):
                    with self.assertRaises(jobs.Refusal) as cm:
                        jobs.validate(kind, args)
                    self.assertEqual(cm.exception.code, "bad_args")
                    n += 1
        self.assertGreater(n, 500)

    def test_free_text_takes_plain_sentences(self):
        for text in ("It's a paid collab, #ad in the caption", "Partner hashtag (not tagged)!",
                     "Creator\u2019s pinned reel", "Recheck: 2 reels, 48 h old", "Collab with @demo_creator_b",
                     "R\u00e9sum\u00e9 shown on screen", "\u0939\u093f\u0902\u0926\u0940 \u0915\u0948\u092a\u094d\u0936\u0928"):
            with self.subTest(text=text):
                self.assertEqual(jobs.validate("reel.discount", {"sc": "DEMO0000001", "reason": text})["reason"], text)
        self.assertEqual(jobs.validate("coach.this_but", VALID["coach.this_but"] | {"text": "Line one\nLine two"})
                         ["text"], "Line one\nLine two")

    def test_reason_must_be_display_text(self):
        for bad in ("see notes.json", "copy in transcript.txt", "OneDrive copy", "AppData copy", "clip.mp4 is gone",
                    "said: \u201chi"):
            with self.subTest(bad=bad):
                with self.assertRaises(jobs.Refusal):
                    jobs.validate("reel.discount", {"sc": "DEMO0000001", "reason": bad})

    def test_wrong_shapes_are_refused(self):
        cases = [("reel.accept", {"sc": "DEMO0000001", "field": "all", "cmd": "calc"}),   # extra field
                 ("reel.accept", {"sc": "DEMO0000001"}),                                     # missing field
                 ("reel.accept", {"sc": 12345678, "field": "all"}),
                 ("reel.accept", {"sc": ["DEMO0000001"], "field": "all"}),
                 ("reel.accept", {"sc": None, "field": "all"}),
                 ("reel.accept", {"sc": True, "field": "all"}),
                 ("reel.accept", {"sc": {"x": 1}, "field": "all"}),
                 ("reel.accept", ["DEMO0000001", "all"]),
                 ("reel.accept", "accept DEMO0000001 all"),
                 ("reel.accept", None),
                 ("reel.reject", {"sc": "DEMO0000001", "field": "all"}),                     # reject takes no all
                 ("patterns.build", {"dry_run": "1"}),
                 ("sync.push", {"--dry": ""})]
        for kind, args in cases:
            with self.subTest(kind=kind, args=str(args)[:50]):
                with self.assertRaises(jobs.Refusal) as cm:
                    jobs.validate(kind, args)
                self.assertEqual(cm.exception.code, "bad_args")

    def test_unknown_kinds_are_refused(self):
        for kind in ("reel.add", "shell", "reel.accept ", "REEL.ACCEPT", "", None, 7, "tribe.lanes;calc"):
            with self.subTest(kind=kind):
                with self.assertRaises(jobs.Refusal) as cm:
                    jobs.validate(kind, {})
                self.assertEqual(cm.exception.code, "unknown_kind")

    def test_patterns_are_full_matches(self):
        rx = jobs._full("^[A-Za-z0-9_-]{5,20}$")
        self.assertIsNotNone(rx.fullmatch("DEMO00001"))
        for bad in ("DEMO00001\n", "xDEMO00001!", "DEMO١٢٣٤", "ＤEMO00001"):
            self.assertIsNone(rx.fullmatch(bad))
        self.assertIsNone(jobs._full("^(all|cta)$").fullmatch("allcta"))

    def test_contract_gaps_are_closed_here(self):
        """contract.validate (re.search) and store.check_shortcode (re.match) take a trailing
        newline; the contract's shortcode pattern takes a leading dash. The runner doesn't."""
        from strategist import contract
        contract.check_job_args("reel.accept", {"sc": "DEMO00001\n", "field": "all"})
        contract.check_job_args("reel.accept", {"sc": "-Precision", "field": "all"})
        for sc in ("DEMO00001\n", "-Precision", "--yes-done"):
            with self.assertRaises(jobs.Refusal):
                jobs.validate("reel.accept", {"sc": sc, "field": "all"})

    def test_parsed_arguments_match_exactly(self):
        """What argparse hands to the CLI command is exactly the checked value: no flag confusion."""
        cases = [("reel.accept", {"sc": "A_b-c1D", "field": "all"}),
                 ("reel.accept", {"sc": "DEMO0000001", "field": "beats.12"}),
                 ("reel.reject", {"sc": "Dd2FOEVxaap", "field": "cta"}),
                 ("reel.discount", {"sc": "DEMO0000001", "reason": "It's paid, tagged --reason=x? no: #ad"}),
                 ("reel.discount", {"sc": "DEMO0000001", "reason": "Recheck = later"})]
        for kind, args in cases:
            clean = jobs.validate(kind, args)
            module, argv = runner.cli_argv(kind, clean)
            self.assertEqual(module, "reel")
            ns = reel.build_parser().parse_args(argv)
            self.assertEqual(ns.sc, args["sc"])
            if "field" in args:
                self.assertEqual(ns.field, args["field"])
            else:
                self.assertEqual(ns.reason, args["reason"])
                self.assertFalse(ns.clear)
            self.assertFalse([a for a in argv[1:] if a.startswith("-") and not a.startswith("--reason=")])

    def test_cli_argv_for_every_stage1_kind(self):
        self.assertEqual(runner.cli_argv("patterns.build", {}), ("patterns", ["build"]))
        self.assertEqual(runner.cli_argv("lab.check", {"draft_id": "20261009-x1"}), ("lab", ["check", "20261009-x1"]))
        self.assertEqual(runner.cli_argv("sync.push", {}), ("sync", ["push"]))
        for kind in jobs.kinds():
            if kind not in runner.STAGE1:
                with self.assertRaises(runner.RunnerError):
                    runner.cli_argv(kind, VALID[kind])


# ---------------------------------------------------------------- the D26 limits

def job(kind, **kw):
    j = {"id": uid(), "kind": kind, "args": dict(VALID[kind]), "estimate_usd": jobs.estimate(kind, VALID[kind]),
         "idem_key": None, "created_at": NOW - dt.timedelta(minutes=2), "confirmed_at": NOW - dt.timedelta(minutes=1)}
    j.update(kw)
    return j


def facts(**kw):
    base = dict(now=NOW, paused=False, modal_usd=0.0, apify_usd=0.0)
    base.update(kw)
    return jobs.Facts(**base)


ALL_KINDS = tuple(VALID)


class LimitTests(unittest.TestCase):
    def refused(self, code, j, f, built=ALL_KINDS):
        with self.assertRaises(jobs.Refusal) as cm:
            jobs.admit(j, f, built=built)
        self.assertEqual(cm.exception.code, code)
        return cm.exception

    def test_limits_are_the_d26_numbers(self):
        L = jobs.LIMITS
        self.assertEqual((L["paid_running_max"], L["paid_usd_per_day"], L["paid_jobs_per_day"],
                          L["tribe_reads_per_month"], L["confirm_expires_min"], L["modal_cap_usd"],
                          L["apify_cap_usd"]), (1, 1.0, 10, 4, 30, 30.0, 4.5))
        self.assertEqual(jobs.PLATFORM, "instagram")

    def test_runner_estimates_match_the_contract(self):
        for kind, spec in jobs.kinds().items():
            with self.subTest(kind=kind):
                self.assertAlmostEqual(jobs.estimate(kind, VALID[kind]), float(spec["estimate_usd"]), places=6)

    def test_free_stage1_jobs_pass(self):
        for kind in runner.STAGE1:
            with self.subTest(kind=kind):
                self.assertEqual(jobs.admit(job(kind), facts(), built=runner.STAGE1), VALID[kind])

    def test_free_jobs_do_not_expire(self):
        old = job("reel.accept", confirmed_at=NOW - dt.timedelta(days=3))
        self.assertTrue(jobs.admit(old, facts(), built=runner.STAGE1))

    def test_disabled_kinds_are_refused(self):
        for kind, spec in jobs.kinds().items():
            if not spec["enabled"]:
                with self.subTest(kind=kind):
                    self.refused("kind_disabled", job(kind), facts())
        self.assertEqual(sorted(k for k, s in jobs.kinds().items() if s["enabled"]), sorted(runner.STAGE1))

    def test_enabled_but_not_built_is_refused(self):
        with enabled_kinds("tribe.lanes"):
            self.refused("kind_not_built", job("tribe.lanes"), facts(), built=runner.STAGE1)

    def test_pause(self):
        for kind in ("reel.accept", "sync.push", "tribe.lanes"):
            with self.subTest(kind=kind):
                self.refused("paused", job(kind), facts(paused=True))

    def test_unconfirmed(self):
        self.refused("not_confirmed", job("reel.accept", confirmed_at=None), facts())
        with enabled_kinds("tribe.lanes"):
            self.refused("not_confirmed", job("tribe.lanes", confirmed_at=None), facts())

    def test_confirm_expires_after_30_minutes(self):
        with enabled_kinds("tribe.lanes"):
            queued = NOW - dt.timedelta(minutes=40)
            self.assertTrue(jobs.admit(job("tribe.lanes", created_at=queued, confirmed_at=NOW - dt.timedelta(minutes=29)),
                                       facts(), built=ALL_KINDS))
            self.refused("confirm_expired", job("tribe.lanes", created_at=queued,
                                                confirmed_at=NOW - dt.timedelta(minutes=31)), facts())

    def test_confirm_dated_ahead_never_dodges_the_expiry(self):
        with enabled_kinds("tribe.lanes"):
            for ahead in (dt.timedelta(minutes=3), dt.timedelta(days=365 * 70)):
                with self.subTest(ahead=ahead):
                    self.refused("confirm_bad_time", job("tribe.lanes", confirmed_at=NOW + ahead), facts())
            # a laptop clock a little behind the database clock is fine
            self.assertTrue(jobs.admit(job("tribe.lanes", created_at=NOW - dt.timedelta(minutes=1),
                                           confirmed_at=NOW + dt.timedelta(seconds=90)), facts(), built=ALL_KINDS))
        # free jobs only need a confirm time
        self.assertTrue(jobs.admit(job("reel.accept", confirmed_at=NOW + dt.timedelta(days=1)), facts(),
                                   built=runner.STAGE1))

    def test_paid_confirm_must_come_after_the_insert(self):
        with enabled_kinds("tribe.lanes"):
            for created in (NOW - dt.timedelta(minutes=1), NOW - dt.timedelta(seconds=30), None, "2026-10-15"):
                with self.subTest(created=created):
                    self.refused("confirm_bad_time", job("tribe.lanes", created_at=created,
                                                         confirmed_at=NOW - dt.timedelta(minutes=1)), facts())
        self.assertTrue(jobs.admit(job("reel.accept", created_at=NOW, confirmed_at=NOW), facts(), built=runner.STAGE1))

    def test_higher_re_estimate_is_refused(self):
        with enabled_kinds("tribe.lanes", "reel.add_handle"):
            self.refused("estimate_higher", job("tribe.lanes", estimate_usd=0.05), facts())
            self.refused("estimate_higher", job("reel.add_handle", estimate_usd=0.08), facts())
            self.refused("estimate_higher", job("tribe.lanes", estimate_usd=None), facts())
            self.refused("estimate_higher", job("tribe.lanes", estimate_usd=float("nan")), facts())
            self.assertTrue(jobs.admit(job("tribe.lanes", estimate_usd=0.10), facts(), built=ALL_KINDS))
            self.assertTrue(jobs.admit(job("tribe.lanes", estimate_usd="0.1000"), facts(), built=ALL_KINDS))

    def test_one_paid_job_at_a_time(self):
        with enabled_kinds("reel.add_link"):
            self.refused("paid_busy", job("reel.add_link"), facts(paid_running_other=1))

    def test_daily_dollar_and_job_limits(self):
        with enabled_kinds("tribe.lanes"):
            self.refused("daily_usd_cap", job("tribe.lanes"), facts(paid_today_usd=0.95))
            self.assertTrue(jobs.admit(job("tribe.lanes"), facts(paid_today_usd=0.90), built=ALL_KINDS))
            self.refused("daily_job_cap", job("tribe.lanes"), facts(paid_today_n=10))
            self.assertTrue(jobs.admit(job("tribe.lanes"), facts(paid_today_n=9), built=ALL_KINDS))

    def test_four_deep_reads_a_month(self):
        with enabled_kinds("tribe.lanes", "reel.add_link"):
            self.refused("tribe_month_cap", job("tribe.lanes"), facts(tribe_month_n=4))
            self.assertTrue(jobs.admit(job("tribe.lanes"), facts(tribe_month_n=3), built=ALL_KINDS))
            self.assertTrue(jobs.admit(job("reel.add_link"), facts(tribe_month_n=4), built=ALL_KINDS))

    def test_modal_cap_and_unknown_spend(self):
        with enabled_kinds("tribe.lanes"):
            self.refused("modal_cap", job("tribe.lanes"), facts(modal_usd=29.95))
            self.assertTrue(jobs.admit(job("tribe.lanes"), facts(modal_usd=29.90), built=ALL_KINDS))
            self.refused("modal_spend_unknown", job("tribe.lanes"), facts(modal_usd=None))
            self.refused("modal_spend_unknown", job("tribe.lanes"), facts(modal_usd=float("inf")))

            def broken():
                raise jobs.UsageError("no local copy of the Modal ledger yet")
            self.refused("modal_spend_unknown", job("tribe.lanes"), facts(modal_usd=broken))

    def test_apify_cap_and_unknown_usage(self):
        with enabled_kinds("reel.add_link", "reel.add_handle"):
            self.refused("apify_cap", job("reel.add_handle"), facts(apify_usd=4.45))
            self.assertTrue(jobs.admit(job("reel.add_handle"), facts(apify_usd=4.40), built=ALL_KINDS))
            self.refused("apify_cap", job("reel.add_link"), facts(apify_usd=4.4999))
            self.refused("apify_usage_unknown", job("reel.add_link"), facts(apify_usd=None))
            self.refused("apify_usage_unknown", job("reel.add_link"), facts(apify_usd=-1.0))

            def broken():
                raise jobs.UsageError("Apify refused the usage request (HTTP 401)")
            self.refused("apify_usage_unknown", job("reel.add_link"), facts(apify_usd=broken))

    def test_each_cap_is_read_only_for_its_own_billing(self):
        def never():
            raise AssertionError("read when it should not be")
        with enabled_kinds("tribe.lanes", "reel.add_link"):
            self.assertTrue(jobs.admit(job("tribe.lanes"), facts(apify_usd=never), built=ALL_KINDS))
            self.assertTrue(jobs.admit(job("reel.add_link"), facts(modal_usd=never), built=ALL_KINDS))
            # a cheaper refusal comes first, so the network is never asked
            self.refused("daily_job_cap", job("reel.add_link"), facts(paid_today_n=10, apify_usd=never))
        self.refused("kind_disabled", job("tribe.lanes"), facts(apify_usd=never))   # still off; reel.add_* are on (D31)

    def test_refusal_lines_are_fixed_and_pass_the_rules(self):
        for code, line in jobs.REFUSALS.items():
            with self.subTest(code=code):
                self.assertRegex(code, db.ERROR_CODE_RE)
                self.assertEqual(db.event_line("refused", code=code), f"Refused: {code}.")
                self.assertEqual(db.clean_line(line, "refusal"), line)
                self.assertNotIn("\u2014", line)
                R.check_authored([(code, line)])
                self.assertEqual(R.find_banned(line), [])
        with self.assertRaises(ValueError):
            jobs.Refusal("made_up_code")

    def test_detail_never_reaches_the_line(self):
        r = self.refused("bad_args", job("reel.accept", args={"sc": "DEMO0;secret", "field": "all"}), facts())
        self.assertIn("secret", r.detail)
        self.assertNotIn("secret", r.line)


# ---------------------------------------------------------------- spend readers

class FakeHTTP(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class SpendTests(unittest.TestCase):
    def test_apify_usage_read(self):
        seen = []

        def opener(req, timeout):
            seen.append(req)
            return FakeHTTP(json.dumps({"data": {"current": {"monthlyUsageUsd": 3.34},
                                                 "limits": {"maxMonthlyUsageUsd": 5}}}).encode())
        self.assertEqual(jobs.apify_month_usd(FAKE_APIFY, opener=opener), 3.34)
        self.assertEqual(seen[0].full_url, jobs.APIFY_LIMITS_URL)
        self.assertEqual(seen[0].get_method(), "GET")
        self.assertEqual(seen[0].get_header("Authorization"), f"Bearer {FAKE_APIFY}")

    def test_apify_failures_never_show_the_token(self):
        def http_401(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

        def down(req, timeout):
            raise urllib.error.URLError(f"refused for {FAKE_APIFY}")
        for opener in (http_401, down, lambda r, timeout: FakeHTTP(b"{}"),
                       lambda r, timeout: FakeHTTP(b'{"data":{"current":{"monthlyUsageUsd":"lots"}}}'),
                       lambda r, timeout: FakeHTTP(b"not json")):
            with self.assertRaises(jobs.UsageError) as cm:
                jobs.apify_month_usd(FAKE_APIFY, opener=opener)
            self.assertNotIn(FAKE_APIFY, str(cm.exception))
        with self.assertRaisesRegex(jobs.UsageError, "APIFY_TOKEN"):
            jobs.apify_month_usd("", opener=no_network)

    def test_apify_token_comes_from_the_reel_env_helper(self):
        with mock.patch.object(reel, "env_value", return_value=FAKE_APIFY) as env:
            jobs.apify_month_usd(opener=lambda r, timeout: FakeHTTP(
                b'{"data":{"current":{"monthlyUsageUsd":1}}}'))
        env.assert_called_once_with("APIFY_TOKEN")

    def test_modal_month_from_a_ledger_copy(self):
        tmp = Path(tempfile.mkdtemp(prefix="ledger-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        with self.assertRaises(jobs.UsageError):
            jobs.modal_month_usd(tmp / "missing", NOW)
        month = tmp / "2026-10"
        month.mkdir()
        rows = [{"event": "started", "run_id": "a", "worst_case_usd": 1.5, "created_at": NOW.isoformat()},
                {"event": "finished", "run_id": "a", "estimated_usd": 0.10},
                {"event": "started", "run_id": "b", "worst_case_usd": 0.75, "created_at": NOW.isoformat()}]
        for i, row in enumerate(rows):
            (month / f"{i}.json").write_text(json.dumps(row), encoding="utf-8")
        self.assertAlmostEqual(jobs.modal_month_usd(tmp, NOW), 0.85)   # b has no finished row: worst case
        self.assertEqual(jobs.modal_month_usd(tmp, NOW.replace(month=11)), 0.0)

    def test_ledger_mirror_command_is_an_argument_list(self):
        argv = jobs.ledger_mirror_argv("2026-10", Path("C:/x/ledger"))
        self.assertEqual(argv[:6], ["modal", "volume", "get", "--force", "tribe-runs", "ledger/2026-10"])
        for bad in ("2026-13", "2026-10; calc", "../x", ""):
            with self.assertRaises(ValueError):
                jobs.ledger_mirror_argv(bad, Path("x"))


# ---------------------------------------------------------------- job states, leases, retries

class StateTests(unittest.TestCase):
    def test_transitions(self):
        ok = [("queued", "running"), ("queued", "cancelled"), ("queued", "refused"), ("running", "done"),
              ("running", "failed"), ("running", "interrupted"), ("running", "refused"), ("running", "cancelled")]
        for old, new in ok:
            self.assertEqual(jobs.check_transition(old, new), new)
        for old in jobs.STATUSES:
            for new in jobs.STATUSES:
                if (old, new) not in ok:
                    with self.subTest(old=old, new=new):
                        with self.assertRaises(ValueError):
                            jobs.check_transition(old, new)
        self.assertEqual(set(jobs.STATUSES), set(db.STATUSES))
        self.assertEqual(set(jobs.FINAL), set(db.FINAL))

    def test_lease_and_retry_rules(self):
        self.assertTrue(jobs.lease_expired(NOW - dt.timedelta(seconds=1), NOW))
        self.assertTrue(jobs.lease_expired(None, NOW))
        self.assertFalse(jobs.lease_expired(NOW + dt.timedelta(seconds=1), NOW))
        self.assertTrue(jobs.should_retry("reel.accept", None))
        self.assertTrue(jobs.should_retry("reel.accept", "click:abc12345"))
        self.assertFalse(jobs.should_retry("reel.accept", "retry:" + uid()))
        self.assertFalse(jobs.should_retry("reel.accept", None, cancel_requested=True))
        for paid in jobs.paid_kinds():
            self.assertFalse(jobs.should_retry(paid, None))
        self.assertFalse(jobs.should_retry("not.a.kind", None))
        self.assertRegex(jobs.retry_key(uid()), jobs.IDEM_RE)

    def test_calendar_is_laptop_time(self):
        d, m = jobs.day_start(NOW), jobs.month_start(NOW)
        self.assertEqual((d.hour, d.minute, m.day), (0, 0, 1))
        self.assertLessEqual(d, jobs.local(NOW))
        self.assertLessEqual(m, d)


class RunnerFlowTests(RunnerCase):
    def test_free_job_runs_syncs_and_closes(self):
        r = self.make_runner()
        jid = self.q.insert("reel.accept")
        self.assertEqual(r.round(), 1)
        row = self.q.rows[jid]
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["result"], {"rc": 0, "synced": True})
        self.assertEqual(self.q.lines(jid), ["Started.", "Step 1 of 2.", "Step 2 of 2.",
                                             "Pushing pages to the dashboard.", "Done."])
        self.assertEqual(r.executors["reel.accept"].calls, [("reel.accept", VALID["reel.accept"])])
        self.assertEqual(self.sync_calls, 1)
        self.assertIn("raw output line", self.log_text(jid))
        self.assertIsNone(row["lease_until"])

    def test_raw_output_stays_in_the_laptop_log(self):
        secret = "SYNTHETIC transcript words that must stay local"
        r = self.make_runner({"reel.discount": FakeExec(say=secret)})
        jid = self.q.insert("reel.discount")
        r.round()
        self.assertIn(secret, self.log_text(jid))
        self.assertNotIn(secret, json.dumps(self.q.events) + json.dumps(self.q.rows[jid], default=str))
        for _, line in self.q.events:
            self.assertIn(line, [db.EVENT_LINES[k] for k in db.EVENT_LINES] + [
                "Step 1 of 2.", "Step 2 of 2."])

    def test_cli_refusal_fails_without_sync(self):
        r = self.make_runner({"reel.accept": FakeExec(rc=2)})
        jid = self.q.insert("reel.accept")
        r.round()
        self.assertEqual((self.q.rows[jid]["status"], self.q.rows[jid]["error_code"]), ("failed", "cli_refused"))
        self.assertEqual(self.q.lines(jid)[-1], "Failed: cli_refused.")
        self.assertEqual(self.sync_calls, 0)

    def test_lab_check_with_a_failed_check_is_done(self):
        r = self.make_runner({"lab.check": FakeExec(rc=1)})
        jid = self.q.insert("lab.check")
        r.round()
        self.assertEqual(self.q.rows[jid]["status"], "done")
        self.assertIn("Checking the draft.", self.q.lines(jid))

    def test_crash_is_logged_locally(self):
        r = self.make_runner({"patterns.build": FakeExec(boom=RuntimeError("SYNTHETIC boom"))})
        jid = self.q.insert("patterns.build")
        r.round()
        self.assertEqual((self.q.rows[jid]["status"], self.q.rows[jid]["error_code"]), ("failed", "crashed"))
        self.assertIn("SYNTHETIC boom", self.log_text(jid))
        self.assertNotIn("SYNTHETIC boom", json.dumps(self.q.events))

    def test_missing_sync_keeps_the_change_and_says_so(self):
        r = self.make_runner(sync=None)
        jid = self.q.insert("reel.reject")
        r.round()
        self.assertEqual(self.q.rows[jid]["status"], "done")
        self.assertEqual(self.q.rows[jid]["result"], {"rc": 0, "synced": False})
        self.assertIn("Failed: sync_missing.", self.q.lines(jid))
        self.sync_rc = 1
        r = self.make_runner()
        jid = self.q.insert("reel.reject")
        r.round()
        self.assertIn("Failed: sync_failed.", self.q.lines(jid))

    def test_sync_push_job(self):
        r = self.make_runner()
        jid = self.q.insert("sync.push")
        r.round()
        self.assertEqual(self.q.rows[jid]["status"], "done")
        self.assertEqual(self.sync_calls, 1)
        self.assertEqual(self.q.lines(jid), ["Started.", "Pushing pages to the dashboard.", "Done."])
        r = self.make_runner(sync=None)
        jid = self.q.insert("sync.push")
        r.round()
        self.assertEqual(self.q.rows[jid]["status"], "refused")
        self.assertEqual(self.q.rows[jid]["error_code"], "kind_not_built")

    def test_disabled_kind_is_refused_and_never_runs(self):
        execs = {k: FakeExec() for k in jobs.kinds()}
        r = self.make_runner(execs)
        jids = {k: self.q.insert(k, estimate_usd=jobs.estimate(k, VALID[k])) for k in jobs.kinds()
                if not jobs.kinds()[k]["enabled"]}
        r.round()
        for kind, jid in jids.items():
            with self.subTest(kind=kind):
                row = self.q.rows[jid]
                self.assertEqual((row["status"], row["error_code"]), ("refused", "kind_disabled"))
                self.assertEqual(row["refusal"], jobs.REFUSALS["kind_disabled"])
                self.assertEqual(self.q.lines(jid), ["Started.", "Refused: kind_disabled."])
                self.assertEqual(execs[kind].calls, [])

    def test_stage1_runner_only_runs_stage1_kinds(self):
        self.assertEqual(set(runner.EXECUTORS) | {"sync.push"}, set(runner.STAGE1))
        r = runner.Runner(self.q, None, clock=self.clock, log_dir=self.tmp / "logs", sync=self.fake_sync)
        with enabled_kinds("tribe.lanes"):
            jid = self.q.insert("tribe.lanes", estimate_usd=0.1)
            r.round()
        self.assertEqual(self.q.rows[jid]["error_code"], "kind_not_built")

    def test_bad_arguments_are_refused_before_running(self):
        ex = FakeExec()
        r = self.make_runner({"reel.accept": ex})
        jid = self.q.insert("reel.accept", {"sc": "-Precision", "field": "all"})
        r.round()
        self.assertEqual((self.q.rows[jid]["status"], self.q.rows[jid]["error_code"]), ("refused", "bad_args"))
        self.assertEqual(ex.calls, [])
        self.assertIn("may not start with a dash", self.log_text(jid))
        self.assertNotIn("Precision", json.dumps(self.q.rows[jid], default=str).replace(
            json.dumps(self.q.rows[jid]["args"]), ""))

    def test_pause_stops_claims_and_refuses_a_claimed_job(self):
        r = self.make_runner()
        jid = self.q.insert("reel.accept")
        self.q.paused = True
        self.assertEqual(r.round(), 0)
        self.assertEqual(self.q.rows[jid]["status"], "queued")
        self.q.paused = False
        claimed = self.q.claim()
        self.q.paused = True   # paused between the claim and the start
        self.assertEqual(r.run_job(claimed), "refused")
        self.assertEqual(self.q.rows[jid]["error_code"], "paused")

    def test_jobs_run_in_order(self):
        order = []

        class Rec(FakeExec):
            def __call__(self, kind, args, out):
                order.append(kind)
                return 0
        r = self.make_runner({k: Rec() for k in ("reel.accept", "patterns.build", "lab.check")})
        for k in ("patterns.build", "reel.accept", "lab.check"):
            self.q.insert(k)
        self.assertEqual(r.round(), 3)
        self.assertEqual(order, ["patterns.build", "reel.accept", "lab.check"])

    def test_unconfirmed_jobs_wait(self):
        r = self.make_runner()
        jid = self.q.insert("reel.accept", confirmed=False)
        self.assertEqual(r.round(), 0)
        self.assertEqual(self.q.rows[jid]["status"], "queued")

    def test_swipe_lock_is_held_during_the_job_and_released(self):
        held = []

        class LockCheck(FakeExec):
            def __call__(self, kind, args, out):
                held.append(bool(store._LOCKS))
                return 0
        r = self.make_runner({"reel.accept": LockCheck()})
        self.q.insert("reel.accept")
        r.round()
        self.assertEqual(held, [True])
        self.assertFalse(store._LOCKS)

    def test_busy_swipe_lock_fails_the_job(self):
        r = self.make_runner()
        jid = self.q.insert("reel.accept")
        with mock.patch.object(store, "locked", side_effect=store.LockTimeout("swipe/ is busy")):
            r.round()
        self.assertEqual(self.q.rows[jid]["error_code"], "lock_busy")

    def test_a_dropped_connection_is_retried_once(self):
        r = self.make_runner()
        jid = self.q.insert("reel.accept")
        real = self.q.claim
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise ConnectionError("server closed the connection")
            return real()
        self.q.claim = flaky
        with self.assertLogs("tribe.runner", "WARNING") as logs:
            self.assertEqual(r.safe_round(), 1)
        self.assertIn("reconnecting", logs.output[0])
        self.assertEqual(self.q.resets, 1)
        self.assertEqual(self.q.rows[jid]["status"], "done")

    def test_dry_run_writes_nothing(self):
        r = self.make_runner()
        good = self.q.insert("reel.accept")
        bad = self.q.insert("reel.accept", {"sc": "../../x", "field": "all"})
        off = self.q.insert("tribe.lanes", estimate_usd=0.1)
        out = []
        self.assertEqual(r.dry(out.append), 0)
        text = "\n".join(out)
        self.assertIn(f"{good}  reel.accept  would run", text)
        self.assertIn(f"{bad}  reel.accept  would refuse: bad_args", text)
        self.assertIn(f"{off}  tribe.lanes  would refuse: kind_disabled", text)
        self.assertEqual(self.q.writes, 0)
        self.assertTrue(all(row["status"] == "queued" for row in self.q.rows.values()))


class LeaseTests(RunnerCase):
    def test_killed_runner_leaves_the_job_interrupted_and_a_free_job_retries_once(self):
        r = self.make_runner()
        jid = self.q.insert("reel.accept", idem_key="click:0001abcd")
        self.q.claim()                                   # a runner claimed it, then died
        self.clock.advance(seconds=db.LEASE_S - 1)
        r.housekeeping()
        self.assertEqual(self.q.rows[jid]["status"], "running")
        self.clock.advance(seconds=2)
        r.housekeeping()
        row = self.q.rows[jid]
        self.assertEqual((row["status"], row["error_code"]), ("interrupted", "lease_expired"))
        self.assertIn(db.EVENT_LINES["interrupted"], self.q.lines(jid))
        retries = [x for x in self.q.rows.values() if x["idem_key"] == f"retry:{jid}"]
        self.assertEqual(len(retries), 1)
        retry = retries[0]
        self.assertEqual((retry["status"], retry["kind"], retry["args"]), ("queued", "reel.accept",
                                                                         VALID["reel.accept"]))
        self.assertIsNotNone(retry["confirmed_at"])
        # the retry dies too: never retried again
        self.q.claim()
        self.clock.advance(seconds=db.LEASE_S + 1)
        r.housekeeping()
        self.assertEqual(retry["status"], "interrupted")
        self.assertEqual(sum(1 for x in self.q.rows.values() if x["status"] in db.LIVE), 0)

    def test_paid_jobs_never_retry(self):
        r = self.make_runner()
        with enabled_kinds("tribe.lanes"):
            jid = self.q.insert("tribe.lanes", estimate_usd=0.1)
            self.q.claim()
            self.clock.advance(seconds=db.LEASE_S + 1)
            r.housekeeping()
        self.assertEqual(self.q.rows[jid]["status"], "interrupted")
        self.assertEqual(len(self.q.rows), 1)

    def test_cancelled_interrupted_job_does_not_retry(self):
        r = self.make_runner()
        jid = self.q.insert("reel.accept")
        self.q.claim()
        self.q.rows[jid]["cancel_requested"] = True
        self.clock.advance(seconds=db.LEASE_S + 1)
        r.housekeeping()
        self.assertEqual(len(self.q.rows), 1)

    def test_heartbeat_renews_the_lease_and_sees_a_cancel(self):
        r = self.make_runner()
        jid = self.q.insert("reel.accept")
        self.q.claim()
        first = self.q.rows[jid]["lease_until"]
        self.clock.advance(seconds=60)
        with runner.Lease(r, jid, every_s=0.01) as lease:
            deadline = time.monotonic() + 5
            while self.q.rows[jid]["lease_until"] == first and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertGreater(self.q.rows[jid]["lease_until"], first)
            self.assertFalse(lease.should_stop())
            self.q.rows[jid]["cancel_requested"] = True
            while not lease.cancel.is_set() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(lease.cancel.is_set())
        lease2 = runner.Lease(r, jid)
        self.q.finish(jid, "done")
        lease2.renew()
        self.assertTrue(lease2.lost.is_set())

    def test_cancel_before_start(self):
        ex = FakeExec()
        r = self.make_runner({"reel.accept": ex})
        jid = self.q.insert("reel.accept")
        claimed = self.q.claim()
        self.q.rows[jid]["cancel_requested"] = True
        self.assertEqual(r.run_job(claimed), "cancelled")
        self.assertEqual(ex.calls, [])
        self.assertEqual(self.q.lines(jid)[-1], "Cancelled.")

    def test_cancelled_while_queued(self):
        r = self.make_runner()
        jid = self.q.insert("reel.accept", cancel_requested=True)
        self.assertEqual(r.round(), 0)
        self.assertEqual(self.q.rows[jid]["status"], "cancelled")
        self.assertEqual(self.q.lines(jid), ["Cancelled."])

    def test_idempotency_key(self):
        a = self.q.insert("reel.accept", idem_key="click:dup00001")
        with self.assertRaises(UniqueViolation):
            self.q.insert("reel.accept", idem_key="click:dup00001")
        self.make_runner().round()
        self.assertEqual(self.q.rows[a]["status"], "done")
        b = self.q.insert("reel.accept", idem_key="click:dup00001")   # closed jobs free the key
        self.assertNotEqual(a, b)
        # a retry key that is already live is not queued twice
        jid = self.q.insert("reel.reject")
        self.q.claim()
        self.q.insert("reel.reject", idem_key=jobs.retry_key(jid))
        self.clock.advance(seconds=db.LEASE_S + 1)
        self.q.interrupt_stale()
        self.assertIsNone(self.q.retry_interrupted(jid))

    def test_paid_limits_through_the_runner(self):
        execs = {k: FakeExec() for k in ("tribe.lanes", "reel.add_link")}
        modal_reads = []
        r = self.make_runner(execs, modal_usd=lambda now: modal_reads.append(now) or 0.0)
        awake = []

        @contextlib.contextmanager
        def fake_awake():
            awake.append("on")
            yield
        with enabled_kinds("tribe.lanes", "reel.add_link"), mock.patch.object(runner, "keep_awake", fake_awake):
            first = self.q.insert("tribe.lanes", estimate_usd=0.1)
            r.round()
            self.assertEqual(self.q.rows[first]["status"], "done")
            self.assertEqual(awake, ["on"])
            self.assertEqual(len(modal_reads), 1)
            # three more deep reads this month (earlier days), then the fifth is refused
            for days in (3, 4, 5):
                j = self.q.insert("tribe.lanes", estimate_usd=0.1)
                self.q.rows[j].update(status="done", started_at=self.clock() - dt.timedelta(days=days),
                                      finished_at=self.clock())
            fifth = self.q.insert("tribe.lanes", estimate_usd=0.1)
            r.round()
            self.assertEqual(self.q.rows[fifth]["error_code"], "tribe_month_cap")
            # nine more paid jobs today make ten: the next is refused
            for _ in range(9):
                j = self.q.insert("reel.add_link", estimate_usd=0.006)
                self.q.rows[j].update(status="done", started_at=self.clock(), finished_at=self.clock())
            eleventh = self.q.insert("reel.add_link", estimate_usd=0.006)
            r.round()
            self.assertEqual(self.q.rows[eleventh]["error_code"], "daily_job_cap")
            # an expired confirm and a low confirmed estimate
            old = self.q.insert("reel.add_link", estimate_usd=0.006,
                                confirmed_at=self.clock() - dt.timedelta(minutes=31))
            low = self.q.insert("reel.add_link", estimate_usd=0.001)
            ahead = self.q.insert("reel.add_link", estimate_usd=0.006,
                                  confirmed_at=self.clock() + dt.timedelta(days=365 * 70))
            r.round()
            self.assertEqual(self.q.rows[old]["error_code"], "confirm_expired")
            self.assertEqual(self.q.rows[low]["error_code"], "estimate_higher")
            self.assertEqual(self.q.rows[ahead]["error_code"], "confirm_bad_time")

    def test_one_paid_job_running_blocks_the_next_claim(self):
        with enabled_kinds("tribe.lanes", "reel.add_link"):
            a = self.q.insert("tribe.lanes", estimate_usd=0.1)
            b = self.q.insert("reel.add_link", estimate_usd=0.006)
            c = self.q.insert("reel.accept")
            self.assertEqual(self.q.claim()["id"], a)
            self.assertEqual(self.q.claim()["id"], c)     # free jobs pass a running paid one
            self.assertIsNone(self.q.claim())
            self.assertEqual(self.q.rows[b]["status"], "queued")
            self.assertEqual(self.q.paid_stats(b, jobs.day_start(NOW), jobs.month_start(NOW))["running_other"], 1)


# ---------------------------------------------------------------- the real CLIs in process

class ExecutorTests(RunnerCase):
    def setUp(self):
        super().setUp()
        for name, sub in (("DRAFTS", "drafts"), ("OUTPUTS", "outputs"), ("VAULT", "vault")):
            p = mock.patch.object(store, name, self.tmp / sub)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(reel, "ENV_FILE", self.tmp / "no.env")
        p.start()
        self.addCleanup(p.stop)
        r = reel.new_reel("DEMO0000001", "demo_creator_a", "2026-09-01T10:00:00.000Z",
                          reel.make_counts(500, 120, 30, "2026-09-20T10:00:00+00:00", "test"), False,
                          {"duration_s": 30.0, "first_word_s": 0.4, "words_per_s": 2.5, "text_on_screen_0s": None,
                           "cta": None, "source": {}}, "test")
        r["shape"] = {"hook_shape": {"id": "question-then-number", "status": "suggested"}, "format": None,
                      "cta": None, "beats": []}
        store.save_reel(store.derive(r, None))

    def test_accept_reject_and_discount_change_the_reel(self):
        out = io.StringIO()
        self.assertEqual(runner.run_cli("reel.accept", {"sc": "DEMO0000001", "field": "hook_shape"}, out), 0)
        self.assertEqual(store.load_reel("DEMO0000001")["shape"]["hook_shape"]["status"], "accepted")
        self.assertEqual(runner.run_cli("reel.reject", {"sc": "DEMO0000001", "field": "hook_shape"}, out), 0)
        self.assertEqual(store.load_reel("DEMO0000001")["shape"]["hook_shape"]["status"], "rejected")
        reason = "It's a paid collab, #ad in the caption"
        self.assertEqual(runner.run_cli("reel.discount", {"sc": "DEMO0000001", "reason": reason}, out), 0)
        self.assertEqual(store.load_reel("DEMO0000001")["discount"]["reason"], reason)
        self.assertIn("DEMO0000001: accepted hook_shape", out.getvalue())

    def test_cli_refusals_come_back_as_exit_2(self):
        out = io.StringIO()
        self.assertEqual(runner.run_cli("reel.accept", {"sc": "DEMO0000009", "field": "all"}, out), 2)
        self.assertEqual(runner.run_cli("reel.accept", {"sc": "DEMO0000001", "field": "cta"}, out), 2)
        self.assertEqual(runner.run_cli("lab.check", {"draft_id": "20261009-not-there"}, out), 2)
        self.assertIn("refused", out.getvalue())

    def test_patterns_build_runs_on_an_empty_store(self):
        out = io.StringIO()
        self.assertIn(runner.run_cli("patterns.build", {}, out), (0, 2))

    def test_whole_job_through_the_runner_with_the_real_cli(self):
        r = runner.Runner(self.q, None, sync=self.fake_sync, log_dir=self.tmp / "logs", clock=self.clock)
        jid = self.q.insert("reel.accept", {"sc": "DEMO0000001", "field": "all"})
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            r.round()
        self.assertEqual(self.q.rows[jid]["status"], "done")
        self.assertEqual(store.load_reel("DEMO0000001")["shape"]["hook_shape"]["status"], "accepted")
        self.assertEqual(stdout.getvalue(), "")             # CLI output went to the job log
        self.assertIn("accepted hook_shape", self.log_text(jid))

    def test_run_sync_without_the_module(self):
        with mock.patch("importlib.util.find_spec", return_value=None):
            self.assertIsNone(runner.run_sync(io.StringIO()))


# ---------------------------------------------------------------- Upstash

class FakeUpstash:
    def __init__(self, answers):
        self.answers, self.requests = list(answers), []

    def __call__(self, req, timeout):
        self.requests.append((req.full_url, json.loads(req.data), dict(req.header_items()), timeout))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return FakeHTTP(json.dumps(a).encode())


class WakeTests(unittest.TestCase):
    def wake(self, answers, **kw):
        op = FakeUpstash(answers)
        return runner.Wake(UPSTASH, FAKE_TOKEN, opener=op, **kw), op

    def test_env_and_url_checks(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(runner.Wake.from_env())
        env = {"KV_REST_API_URL": UPSTASH, "KV_REST_API_TOKEN": FAKE_TOKEN,
               "UPSTASH_REDIS_REST_URL": "https://other.upstash.io", "UPSTASH_REDIS_REST_TOKEN": "x" * 20}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(runner.Wake.from_env(opener=no_network).url, UPSTASH)
        for bad in ("http://demo.upstash.io", "https://evil.example.com", "https://upstash.io.evil.com",
                    "https://demo.upstash.io/x?y=1", "https://user:pw@demo.upstash.io", "demo.upstash.io", ""):
            with self.subTest(url=bad):
                with self.assertRaises(runner.WakeError) as cm:
                    runner.Wake(bad, FAKE_TOKEN, opener=no_network)
                self.assertNotIn(FAKE_TOKEN, str(cm.exception))
        self.assertEqual(set(runner.ENV_NAMES), {db.DSN_ENV, "KV_REST_API_URL", "KV_REST_API_TOKEN",
                                                "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"})

    def test_key_names_are_the_ones_the_site_reads(self):
        keys = json.loads((store.PROJECT_ROOT / "web" / "contracts" / "runner.json").read_text(encoding="utf-8"))
        self.assertEqual((runner.WAKE_KEY, runner.HEARTBEAT_KEY, runner.LAST_SEEN_KEY, runner.HEARTBEAT_TTL_S,
                          runner.WAIT_S),
                         (keys["wake_key"], keys["heartbeat_key"], keys["last_seen_key"], keys["heartbeat_ttl_s"],
                          keys["wait_s"]))
        redis_ts = (store.PROJECT_ROOT / "web" / "lib" / "redis.ts").read_text(encoding="utf-8")
        self.assertIn('from "@/contracts/runner.json"', redis_ts)
        for name in ("wake_key", "heartbeat_key", "last_seen_key"):
            self.assertIn(f"RUNNER.{name}", redis_ts)

    def test_heartbeat_expires_after_90_seconds(self):
        w, op = self.wake([[{"result": "OK"}, {"result": "OK"}]])
        w.beat("2026-10-15T06:30:00+00:00")
        url, body, headers, _ = op.requests[0]
        self.assertEqual(url, UPSTASH + "/pipeline")
        self.assertEqual(body, [["SET", runner.HEARTBEAT_KEY, "2026-10-15T06:30:00+00:00", "EX", "90"],
                                ["SET", runner.LAST_SEEN_KEY, "2026-10-15T06:30:00+00:00"]])
        self.assertEqual(headers["Authorization"], f"Bearer {FAKE_TOKEN}")
        w, _ = self.wake([[{"result": "OK"}, {"error": "ERR"}]])
        with self.assertRaises(runner.WakeError):
            w.beat("x")

    def test_blocking_pop_wakes_and_clears_the_list(self):
        w, op = self.wake([{"result": [runner.WAKE_KEY, "1"]}, {"result": 1}, {"result": None}])
        self.assertTrue(w.wait(50))
        self.assertEqual(op.requests[0][1], ["BLPOP", runner.WAKE_KEY, "50"])
        self.assertGreater(op.requests[0][3], 50)          # the HTTP timeout outlasts the pop
        self.assertEqual(op.requests[1][1], ["DEL", runner.WAKE_KEY])
        self.assertFalse(w.wait(50))
        self.assertTrue(w.blocking)

    def test_rest_without_blocking_pop_falls_back_to_polling(self):
        refused = urllib.error.HTTPError(UPSTASH, 400, "Bad Request", {},
                                         io.BytesIO(b'{"error":"ERR blocking commands are not supported"}'))
        t = [0.0]
        sleeps = []

        def sleep(s):
            sleeps.append(s)
            t[0] += s
        w, op = self.wake([refused, {"result": None}, {"result": "1"}, {"result": 1},
                           {"result": None}, {"result": None}, {"result": None}],
                          sleep=sleep, clock=lambda: t[0], poll_s=8)
        self.assertTrue(w.wait(50))
        self.assertFalse(w.blocking)
        self.assertEqual([r[1][0] for r in op.requests], ["BLPOP", "LPOP", "LPOP", "DEL"])
        self.assertEqual(sleeps, [8])
        t[0] = 0.0
        w.poll_s = 30
        self.assertFalse(w.wait(40))                       # no BLPOP again, polls until the time runs out
        self.assertEqual([r[1][0] for r in op.requests[4:]], ["LPOP", "LPOP", "LPOP"])   # at 0, 30 and 40 s

    def test_a_plain_client_error_on_blpop_also_falls_back(self):
        plain = urllib.error.HTTPError(UPSTASH, 400, "Bad Request", {}, io.BytesIO(b"not json"))
        w, op = self.wake([plain, {"result": "1"}, {"result": 1}], sleep=lambda s: None)
        self.assertTrue(w.wait(50))
        self.assertFalse(w.blocking)
        w, _ = self.wake([urllib.error.HTTPError(UPSTASH, 503, "Unavailable", {}, io.BytesIO(b""))])
        with self.assertRaises(runner.WakeError):
            w.wait(50)
        self.assertIsNone(w.blocking)                      # a server error is not "unsupported"

    def test_bad_token_is_an_error_without_the_token(self):
        w, _ = self.wake([urllib.error.HTTPError(UPSTASH, 401, "Unauthorized", {}, None)])
        with self.assertRaises(runner.WakeError) as cm:
            w.wait(50)
        self.assertIn("401", str(cm.exception))
        self.assertNotIn(FAKE_TOKEN, str(cm.exception))
        w, _ = self.wake([urllib.error.URLError(f"down {FAKE_TOKEN}")])
        with self.assertRaises(runner.WakeError) as cm:
            w.cmd("LPOP", runner.WAKE_KEY)
        self.assertNotIn(FAKE_TOKEN, str(cm.exception))


# ---------------------------------------------------------------- the database side (fake connection)

class FakeCursor:
    def __init__(self, one=None, rows=()):
        self.one, self.rows = one, list(rows)

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, answers):
        self.answers, self.calls, self.closed = list(answers), [], False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    def close(self):
        self.closed = True


class DbQueueTests(unittest.TestCase):
    def test_paid_stats_statement(self):
        jid = uid()
        conn = FakeConn([FakeCursor((1, 3, "0.2060", 2))])
        q = runner.DbQueue(connect=lambda: conn)
        day, month = jobs.day_start(NOW), jobs.month_start(NOW)
        self.assertEqual(q.paid_stats(jid, day, month),
                         {"running_other": 1, "today_n": 3, "today_usd": 0.206, "tribe_month_n": 2})
        sql, params = conn.calls[0]
        paid = jobs.paid_kinds()
        self.assertEqual(params, (paid, paid, day, paid, day, month, jid))
        self.assertIn("status IN ('running', 'done', 'failed', 'interrupted')", sql)
        with self.assertRaises(db.DbError):
            q.paid_stats("1; DROP TABLE jobs", day, month)

    def test_retry_statement(self):
        jid, new = uid(), uid()
        conn = FakeConn([FakeCursor(("reel.accept", None, False)), FakeCursor((new,))])
        q = runner.DbQueue(connect=lambda: conn)
        self.assertEqual(q.retry_interrupted(jid), new)
        self.assertEqual(conn.calls[1][1], (f"retry:{jid}", jid, f"retry:{jid}"))
        self.assertIn("NOT EXISTS", conn.calls[1][0])
        self.assertIn("status = 'interrupted' AND NOT cancel_requested", conn.calls[1][0])
        for row in (("tribe.lanes", None, False), ("reel.accept", f"retry:{uid()}", False),
                    ("reel.accept", None, True), None):
            conn = FakeConn([FakeCursor(row)])
            self.assertIsNone(runner.DbQueue(connect=lambda: conn).retry_interrupted(jid))
            self.assertEqual(len(conn.calls), 1)
        conn = FakeConn([FakeCursor(("reel.accept", None, False)), UniqueViolation("jobs_idem_live")])
        self.assertIsNone(runner.DbQueue(connect=lambda: conn).retry_interrupted(jid))

    def test_list_queued_and_reconnect(self):
        jid = uid()
        row = (jid, "reel.accept", json.dumps(VALID["reel.accept"]), "0", None, NOW, NOW)
        made = []

        def connect():
            made.append(FakeConn([FakeCursor(rows=[row])]))
            return made[-1]
        q = runner.DbQueue(connect=connect)
        self.assertEqual(q.list_queued()[0]["args"], VALID["reel.accept"])
        q.reset()
        self.assertTrue(made[0].closed)
        q.conn()
        self.assertEqual(len(made), 2)


# ---------------------------------------------------------------- processes, power, lock, task

class ProcessTests(unittest.TestCase):
    def test_commands_are_argument_lists_never_shells(self):
        for bad in ("python -c 1", ["cmd", "/c", "dir"], ["C:\\Windows\\System32\\cmd.exe", "/c"],
                    ["run.bat"], ["x.CMD", "a"], [], ["python", 1], ["python", "a\x00b"], ("command.com",)):
            with self.subTest(bad=bad):
                with self.assertRaises(runner.RunnerError):
                    runner.check_argv(bad)
        self.assertEqual(runner.check_argv(("powershell", "-NoProfile", "-File", "x.ps1")),
                         ["powershell", "-NoProfile", "-File", "x.ps1"])

    def test_popen_gets_shell_false(self):
        seen = {}

        class P:
            pid = 4242

            def __init__(self, argv, **kw):
                seen.update(argv=argv, **kw)

            def poll(self):
                return 0
        rc = runner.run_process(["python", "-c", "pass"], io.StringIO(), popen=P)
        self.assertEqual(rc, 0)
        self.assertIs(seen["shell"], False)
        self.assertEqual(seen["argv"], ["python", "-c", "pass"])

    def test_cancel_and_timeout_kill_the_tree(self):
        killed = []

        class P:
            pid = 4242

            def __init__(self, argv, **kw):
                pass

            def poll(self):
                return None

            def wait(self, t):
                return 1
        self.assertEqual(runner.run_process(["x"], io.StringIO(), should_cancel=lambda: True, popen=P,
                                            kill=killed.append), "cancelled")
        self.assertEqual(runner.run_process(["x"], io.StringIO(), timeout_s=0, poll_s=0.01, popen=P,
                                            kill=killed.append), "timeout")
        self.assertEqual(killed, [4242, 4242])

    def test_kill_tree_uses_taskkill_tree_force(self):
        calls = []
        with mock.patch.object(runner.os, "name", "nt"):
            runner.kill_tree(1234, run=lambda argv, **kw: calls.append(argv))
        self.assertEqual(calls, [["taskkill", "/T", "/F", "/PID", "1234"]])

    @unittest.skipUnless(os.name == "nt", "Windows process tree")
    def test_cancel_really_kills_child_and_grandchild(self):
        tmp = Path(tempfile.mkdtemp(prefix="runner-proc-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        pidfile = tmp / "grandchild.pid"
        child = ("import subprocess, sys, time\n"
                 "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                 f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
                 "time.sleep(120)\n")
        log = open(tmp / "job.log", "w", encoding="utf-8")
        self.addCleanup(log.close)
        started = time.monotonic()
        rc = runner.run_process([sys.executable, "-c", child], log, poll_s=0.1,
                                should_cancel=lambda: pidfile.is_file() and pidfile.read_text().strip() != "")
        self.assertEqual(rc, "cancelled")
        self.assertLess(time.monotonic() - started, 60)
        grandchild = int(pidfile.read_text())
        deadline = time.monotonic() + 10
        while alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse(alive(grandchild))

    def test_keep_awake_sets_and_clears(self):
        with runner.keep_awake():
            pass
        if os.name == "nt":
            import ctypes
            calls = []
            fake = mock.MagicMock(side_effect=lambda flags: calls.append(flags) or 1)
            with mock.patch.object(ctypes.windll.kernel32, "SetThreadExecutionState", fake):
                with runner.keep_awake():
                    self.assertEqual(calls, [runner.ES_CONTINUOUS | runner.ES_SYSTEM_REQUIRED])
            self.assertEqual(calls[-1], runner.ES_CONTINUOUS)


def alive(pid: int) -> bool:
    """Is a Windows process still running (GetExitCodeProcess == STILL_ACTIVE)?"""
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        return code.value == 259
    finally:
        k32.CloseHandle(h)


HOLDER = """
import sys
sys.path.insert(0, sys.argv[1])
from strategist import runner
from pathlib import Path
lock = runner.InstanceLock(Path(sys.argv[2]))
print("held" if lock.acquire() else "busy", flush=True)
sys.stdin.read()
"""


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="runner-entry-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, value in (("LOG_DIR", self.tmp / "logs"), ("LOCK_FILE", self.tmp / "runner.lock"),
                            ("APP_DIR", self.tmp)):
            p = mock.patch.object(runner, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(db, "load_env", side_effect=AssertionError("the real .env must not be read"))
        self.load_env = p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._drop_handlers)

    def _drop_handlers(self):
        root = runner.logging.getLogger("tribe")
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()

    def test_one_runner_at_a_time(self):
        proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(PROJECT_ROOT), str(self.tmp / "runner.lock")],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(), "held")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(runner.main([]), 3)
            self.assertIn("another runner is already running", out.getvalue())
            self.load_env.assert_not_called()
        finally:
            proc.stdin.close()
            proc.wait(10)
            proc.stdout.close()
        lock = runner.InstanceLock(self.tmp / "runner.lock")
        self.assertTrue(lock.acquire())
        self.assertFalse(runner.InstanceLock(self.tmp / "runner.lock").acquire())
        lock.release()

    def test_missing_database_url_is_refused(self):
        self.load_env.side_effect = None
        with mock.patch.dict(os.environ, {}, clear=True):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(runner.main(["--once"]), 2)
        self.assertIn(db.DSN_ENV, out.getvalue())
        self.assertEqual(self.load_env.call_args[0][0], runner.ENV_NAMES)
        lock = runner.InstanceLock(self.tmp / "runner.lock")
        self.assertTrue(lock.acquire())   # released on the way out
        lock.release()

    def test_task_xml(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(runner.main(["--print-task-xml"]), 0)
        text = out.getvalue()
        self.load_env.assert_not_called()
        self.assertFalse((self.tmp / "logs").exists())
        root = ET.fromstring(text.replace('encoding="UTF-16"', ""))
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(root.find("t:Actions/t:Exec/t:Arguments", ns).text, "-m strategist.runner")
        self.assertEqual(root.find("t:Actions/t:Exec/t:WorkingDirectory", ns).text, str(store.PROJECT_ROOT))
        cmd = root.find("t:Actions/t:Exec/t:Command", ns).text
        if (Path(sys.executable).with_name("pythonw.exe")).is_file():
            self.assertTrue(cmd.lower().endswith("pythonw.exe"))
        self.assertIsNotNone(root.find("t:Triggers/t:LogonTrigger", ns))
        self.assertEqual(root.find("t:Settings/t:MultipleInstancesPolicy", ns).text, "IgnoreNew")
        self.assertEqual(root.find("t:Settings/t:ExecutionTimeLimit", ns).text, "PT0S")
        x = runner.task_xml(python=Path("C:/P&Q/python.exe"), workdir=Path("C:/a<b"), user="D\\u")
        root = ET.fromstring(x.replace('encoding="UTF-16"', ""))
        self.assertEqual(root.find("t:Actions/t:Exec/t:WorkingDirectory", ns).text, str(Path("C:/a<b")))

# ---------------------------------------------------------------- the import executors (D31)

class FakeIO:
    """What run_import writes its raw output to."""

    def __init__(self):
        self.text = []

    def write(self, t):
        self.text.append(t)
        return len(t)

    def flush(self):
        pass

    def __str__(self):
        return "".join(self.text)


class ImportCase(RunnerCase):
    """run_import with reel, patterns and media mocked: no Apify, no ffmpeg, no network."""

    def setUp(self):
        super().setUp()
        self.calls = []
        self.events = []
        self.new_reels = []

    def add_reel(self, sc, owner="demo_creator_a"):
        store.save_reel({"shortcode": sc, "owner": owner, "counts": {}, "facts": {}})

    def fake_add(self, kind):
        def fn(target, ns):
            self.calls.append((kind, target, ns.yes, getattr(ns, "limit", None)))
            for sc in self.new_reels:
                self.add_reel(sc)
            store.log_fetch("test pull", 3, 0.003, "test", True)
            return 0
        return fn

    def fake_media(self, fail=()):
        def fn(sc, opts, out=print):
            self.calls.append(("media", sc, opts.allow_apify, opts.yes, opts.force, round(opts.max_usd, 4)))
            if sc in fail:
                raise runner.media.MediaError("no source worked")
            return {"sc": sc, "source": "yt-dlp"}
        return fn

    def patches(self, rc_patterns=0, fail=()):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(reel, "cmd_add_url", side_effect=self.fake_add("url")))
        stack.enter_context(mock.patch.object(reel, "cmd_add_handle", side_effect=self.fake_add("handle")))
        stack.enter_context(mock.patch.object(runner.patterns, "main",
                                              side_effect=lambda argv: self.calls.append(("patterns", tuple(argv))) or rc_patterns))
        stack.enter_context(mock.patch.object(runner.media, "fetch_one", side_effect=self.fake_media(fail)))
        return stack

    def ctx(self, stop=lambda: False):
        return runner.ImportContext(stop, lambda key, **p: self.events.append((key, p)))

    def test_link_runs_pull_patterns_then_video_with_the_cap(self):
        self.new_reels = ["DEMO0000004"]
        out = FakeIO()
        with self.patches():
            rc = runner.run_import("reel.add_link", {"sc": "DEMO0000004"}, out, self.ctx())
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls[0], ("url", "https://www.instagram.com/reel/DEMO0000004/", True, 30))
        self.assertEqual(self.calls[1], ("patterns", ("build",)))
        self.assertEqual(self.calls[2], ("media", "DEMO0000004", True, True, False, jobs.VIDEO_CAP_USD))
        self.assertEqual([k for k, _ in self.events], ["apify_done", "transcribing", "stills"])
        self.assertEqual(self.events[0][1], {"n": 3})
        self.assertNotIn("cancel_seen", [k for k, _ in self.events])

    def test_handle_uses_limit_30_and_videos_only_for_new_reels(self):
        self.add_reel("DEMOOLD0001")
        self.new_reels = ["DEMOOLD0001", "DEMONEW0001", "DEMONEW0002"]
        with self.patches():
            rc = runner.run_import("reel.add_handle", {"handle": "@demo_creator_a"}, FakeIO(), self.ctx())
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls[0], ("handle", "@demo_creator_a", True, 30))
        media_sc = [c[1] for c in self.calls if c[0] == "media"]
        self.assertEqual(media_sc, ["DEMONEW0001", "DEMONEW0002"])

    def test_the_apify_video_cap_counts_what_earlier_re_pulls_spent(self):
        store.log_fetch(f"{runner.media.LOG_WHAT} OLDREEL0001", 1, 0.003, "test", True)
        self.new_reels = ["DEMO0000004"]
        with self.patches():
            runner.run_import("reel.add_link", {"sc": "DEMO0000004"}, FakeIO(), self.ctx())
        cap = [c for c in self.calls if c[0] == "media"][0][5]
        self.assertAlmostEqual(cap, 0.003 + jobs.VIDEO_CAP_USD, places=4)

    def test_a_missing_video_does_not_fail_the_job(self):
        self.new_reels = ["DEMONEW0001", "DEMONEW0002"]
        out = FakeIO()
        with self.patches(fail=("DEMONEW0001",)):
            rc = runner.run_import("reel.add_handle", {"handle": "demo_creator_a"}, out, self.ctx())
        self.assertEqual(rc, 0)
        self.assertIn("DEMONEW0001: no video", str(out))
        self.assertIn("1 of 2 new reels have a video", str(out))

    def test_a_refused_pull_stops_before_patterns_and_video(self):
        out = FakeIO()
        with self.patches(), mock.patch.object(reel, "cmd_add_url", side_effect=reel.ReelError("no public post")):
            rc = runner.run_import("reel.add_link", {"sc": "DEMO0000004"}, out, self.ctx())
        self.assertEqual(rc, 2)
        self.assertEqual(self.calls, [])
        self.assertEqual([k for k, _ in self.events], ["apify_done"])

    def test_a_failed_patterns_build_skips_the_videos(self):
        self.new_reels = ["DEMO0000004"]
        with self.patches(rc_patterns=2):
            rc = runner.run_import("reel.add_link", {"sc": "DEMO0000004"}, FakeIO(), self.ctx())
        self.assertEqual(rc, 2)
        self.assertNotIn("media", [c[0] for c in self.calls])

    def test_running_the_same_link_twice_does_not_duplicate_or_redo_videos(self):
        self.new_reels = ["DEMO0000004"]
        with self.patches():
            runner.run_import("reel.add_link", {"sc": "DEMO0000004"}, FakeIO(), self.ctx())
            runner.run_import("reel.add_link", {"sc": "DEMO0000004"}, FakeIO(), self.ctx())
        self.assertEqual(len(store.list_reels()), 1)
        for c in (c for c in self.calls if c[0] == "media"):
            self.assertFalse(c[4], "force is never set, so media.fetch_one keeps a video already in media/")

    def test_arguments_are_rebuilt_not_passed_through(self):
        with self.assertRaises(store.StoreError):
            runner.import_target("reel.add_link", {"sc": "../evil"})
        with self.assertRaises(store.StoreError):
            runner.import_target("reel.add_handle", {"handle": "a b"})
        self.assertEqual(runner.import_target("reel.add_handle", {"handle": "@demo.x"}), ("@demo.x", "@demo.x"))
        with self.assertRaises(runner.RunnerError):
            runner.import_target("patterns.build", {})

    def test_cancel_between_steps_stops_the_job(self):
        self.new_reels = ["DEMO0000004"]
        seen = {"n": 0}

        def stop():
            seen["n"] += 1
            return seen["n"] >= 2    # after the pull
        with self.patches(), self.assertRaises(runner.Cancelled):
            runner.run_import("reel.add_link", {"sc": "DEMO0000004"}, FakeIO(), self.ctx(stop))
        self.assertNotIn("media", [c[0] for c in self.calls])
        self.assertEqual(self.events[-1][0], "cancel_seen")

    def test_media_run_tool_is_put_back_after_a_cancel(self):
        original = runner.media.run_tool
        self.new_reels = ["DEMO0000004"]
        seen = {"n": 0}

        def stop():
            seen["n"] += 1
            return seen["n"] >= 4    # at the first video
        with self.patches(), self.assertRaises(runner.Cancelled):
            runner.run_import("reel.add_link", {"sc": "DEMO0000004"}, FakeIO(), self.ctx(stop))
        self.assertIs(runner.media.run_tool, original)

    def test_cancel_kills_the_childs_whole_tree(self):
        killed = []

        class Child:
            pid = 4242

            def communicate(self, timeout=None):
                if not killed:
                    raise subprocess.TimeoutExpired("ffmpeg", timeout)
                return "", ""

        ctx = runner.ImportContext(lambda: True, lambda key, **p: self.events.append((key, p)), kill=killed.append)
        run_tool = runner.cancellable_run_tool(ctx, popen=lambda *a, **k: Child(), poll_s=0.01)
        with self.assertRaises(runner.Cancelled):
            run_tool(["ffmpeg", "-i", "x"])
        self.assertEqual(killed, [4242])
        self.assertEqual(self.events[-1][0], "cancel_seen")

    def test_a_tool_that_finishes_returns_its_output(self):
        class Child:
            pid, returncode = 1, 0

            def communicate(self, timeout=None):
                return "out", "err"
        run_tool = runner.cancellable_run_tool(self.ctx(), popen=lambda *a, **k: Child())
        got = run_tool(["ffprobe", "x"])
        self.assertEqual((got.returncode, got.stdout, got.stderr), (0, "out", "err"))
        with self.assertRaises(runner.RunnerError):
            run_tool(["cmd.exe", "/c", "dir"])     # never through cmd

    # -- through the runner: admit, events, sync, cancel, refusals

    def run_through(self, kind="reel.add_link", **insert):
        r = self.make_runner({kind: runner.run_import})
        jid = self.q.insert(kind, estimate_usd=jobs.estimate(kind, VALID[kind]), **insert)
        r.round()
        return jid

    def test_through_the_runner_events_sync_and_result(self):
        self.new_reels = ["DEMO0000004"]
        with self.patches():
            jid = self.run_through()
        row = self.q.rows[jid]
        self.assertEqual(row["status"], "done", row)
        self.assertEqual(self.q.lines(jid), [
            "Started.", "Apify run started.", "Step 1 of 2.", "Apify run finished: 3 items.",
            "Transcribing on the laptop.", "Taking stills on the laptop.", "Step 2 of 2.",
            "Pushing pages to the dashboard.", "Done."])
        self.assertEqual(self.sync_calls, 1)
        self.assertTrue(row["result"]["synced"])
        self.assertIn("new reels DEMO0000004", self.log_text(jid))

    def test_through_the_runner_cancel_is_seen_between_steps(self):
        self.new_reels = ["DEMO0000004"]
        r = self.make_runner({"reel.add_link": runner.run_import}, lease_s=0.01)
        jid = self.q.insert("reel.add_link", estimate_usd=0.006)

        def slow_add(target, ns):
            self.q.rows[jid]["cancel_requested"] = True
            time.sleep(0.4)    # the lease thread (every 0.01 s) sees the click
            return 0
        with self.patches(), mock.patch.object(reel, "cmd_add_url", side_effect=slow_add):
            r.round()
        row = self.q.rows[jid]
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(self.sync_calls, 0)
        self.assertEqual(self.q.lines(jid)[-1], "Cancelled.")
        self.assertNotIn("media", [c[0] for c in self.calls])

    def test_refused_at_the_apify_cap_before_anything_is_pulled(self):
        r = self.make_runner({"reel.add_link": runner.run_import, "reel.add_handle": runner.run_import},
                             apify_usd=lambda: 4.4999)
        link = self.q.insert("reel.add_link", estimate_usd=0.006)
        handle = self.q.insert("reel.add_handle", estimate_usd=0.10)
        with self.patches():
            r.round()
        for jid in (link, handle):
            self.assertEqual(self.q.rows[jid]["status"], "refused")
            self.assertEqual(self.q.rows[jid]["error_code"], "apify_cap")
        self.assertEqual(self.calls, [])

    def test_the_cap_reads_the_current_account_each_time(self):
        usage = iter([0.5, 4.4999])
        r = self.make_runner({"reel.add_link": runner.run_import}, apify_usd=lambda: next(usage))
        first = self.q.insert("reel.add_link", estimate_usd=0.006)
        second = self.q.insert("reel.add_link", estimate_usd=0.006)
        self.new_reels = ["DEMO0000004"]
        with self.patches():
            r.round()
        self.assertEqual(self.q.rows[first]["status"], "done")
        self.assertEqual(self.q.rows[second]["error_code"], "apify_cap")

    def test_refused_when_the_confirm_expired_or_the_estimate_is_low(self):
        r = self.make_runner({"reel.add_link": runner.run_import})
        old = self.q.insert("reel.add_link", estimate_usd=0.006, confirmed_at=self.clock() - dt.timedelta(minutes=31))
        low = self.q.insert("reel.add_handle", estimate_usd=0.081)
        with self.patches():
            r.round()
        self.assertEqual(self.q.rows[old]["error_code"], "confirm_expired")
        self.assertEqual(self.q.rows[low]["error_code"], "kind_not_built")
        r2 = self.make_runner({"reel.add_handle": runner.run_import})
        with self.patches():
            low2 = self.q.insert("reel.add_handle", estimate_usd=0.081)
            r2.round()
        self.assertEqual(self.q.rows[low2]["error_code"], "estimate_higher")
        self.assertEqual(self.calls, [])

    def test_estimates_and_kinds_are_pinned(self):
        self.assertEqual(jobs.estimate("reel.add_link", VALID["reel.add_link"]), 0.006)
        self.assertEqual(jobs.estimate("reel.add_handle", VALID["reel.add_handle"]), 0.10)
        self.assertEqual(jobs.VIDEO_CAP_USD, 0.02)
        for kind in runner.IMPORT_KINDS:
            spec = jobs.spec(kind)
            self.assertTrue(spec["enabled"] and spec["paid"], kind)
            self.assertEqual((spec["stage"], spec["billing"]), (1, "apify"), kind)
            self.assertEqual(spec["estimate_usd"], jobs.estimate(kind, VALID[kind]), kind)
            self.assertIn(kind, runner.STAGE1)
            self.assertIn(kind, runner.CHANGES_DATA)
            self.assertEqual(runner.KIND_EVENT[kind], "apify_started")
            self.assertIs(runner.EXECUTORS[kind], runner.run_import)
        self.assertEqual(jobs.LIMITS["apify_cap_usd"], 4.5)

    def test_every_event_line_the_imports_use_is_a_fixed_line(self):
        for key, params in (("apify_started", {}), ("apify_done", {"n": 3}), ("transcribing", {}), ("stills", {}),
                            ("cancel_seen", {})):
            self.assertTrue(db.event_line(key, **params))

    def test_usage_is_read_for_whatever_token_is_in_env(self):
        seen = []

        def opener(req, timeout=None):
            seen.append(req.get_header("Authorization"))
            return io.BytesIO(json.dumps({"data": {"current": {"monthlyUsageUsd": 0.12}}}).encode())
        with mock.patch.object(reel, "env_value", side_effect=["tok_one_SYNTH", "tok_two_SYNTH"]):
            self.assertEqual(jobs.apify_month_usd(opener=opener), 0.12)
            self.assertEqual(jobs.apify_month_usd(opener=opener), 0.12)
        self.assertEqual(seen, ["Bearer tok_one_SYNTH", "Bearer tok_two_SYNTH"])



if __name__ == "__main__":
    unittest.main(verbosity=1)
