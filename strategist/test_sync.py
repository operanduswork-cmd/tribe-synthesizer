"""Tests for strategist/sync.py (export, push, audit). Run: python -m strategist.test_sync

A synthetic swipe file in a temp folder (strategist/test_render_swipe.py SwipeCase) and a fake
database connection that understands the statements strategist/db.py sends (pages, images,
brain assets, one transaction). The brain cases add synthetic preds and a synthetic atlas, masks
and mesh (strategist/test_brain_assets.py). No network, no psycopg, no .env: the CLI tests
replace db.load_env and db.connect. The real swipe/, drafts/, outputs/ and reports/ are never
written.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
sys.path.insert(0, str(PROJECT_ROOT))
from strategist import brain_assets as B, db, hosted, store, sync  # noqa: E402
from strategist import test_brain_assets as tba  # noqa: E402
from strategist import test_render_swipe as trs  # noqa: E402

dash = trs.dash
JOB = trs.JOB
TRANSCRIPT = "Grab the blue folder before lunch. Then label every tab twice."
RUN = "grab the blue folder"


class FakeCursor:
    def __init__(self, rows=(), rowcount=0):
        self.rows, self.rowcount = list(rows), rowcount

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeDb:
    """The pages, images and brain_assets tables in memory, for the statements strategist/db.py sends."""

    def __init__(self, fail_on: str | None = None):
        self.pages: dict[tuple[str, str], dict] = {}
        self.images: dict[str, dict] = {}
        self.assets: dict[str, dict] = {}
        self.sql: list[str] = []
        self.fail_on = fail_on
        self.closed = False
        self.transactions = 0

    @contextlib.contextmanager
    def transaction(self):
        self.transactions += 1
        saved = copy.deepcopy((self.pages, self.images, self.assets))
        try:
            yield
        except BaseException:
            self.pages, self.images, self.assets = saved
            raise

    def close(self):
        self.closed = True

    def execute(self, sql, params=()):
        self.sql.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("synthetic database failure")
        if sql == db.UPSERT_PAGE:
            kind, key, v, body, digest = params
            old = self.pages.get((kind, key))
            if old and old["hash"] == digest:
                return FakeCursor(rowcount=0)
            self.pages[(kind, key)] = {"v": v, "json": json.loads(body), "hash": digest}
            return FakeCursor(rowcount=1)
        if sql.startswith("DELETE FROM pages WHERE kind = %s AND NOT (key = ANY(%s))"):
            kind, keep = params
            gone = sorted(k for (kd, k) in self.pages if kd == kind and k not in keep)
            for k in gone:
                del self.pages[(kind, k)]
            return FakeCursor([(k,) for k in gone], len(gone))
        if sql == db.UPSERT_IMAGE:
            key, data, digest = params
            old = self.images.get(key)
            if old and old["hash"] == digest:
                return FakeCursor(rowcount=0)
            self.images[key] = {"mime": "image/png", "bytes": bytes(data), "hash": digest}
            return FakeCursor(rowcount=1)
        if sql.startswith("DELETE FROM images WHERE NOT (key = ANY(%s))"):
            keep, = params
            gone = sorted(k for k in self.images if k not in keep)
            for k in gone:
                del self.images[k]
            return FakeCursor([(k,) for k in gone], len(gone))
        if sql.startswith("SELECT kind, key, v, json, hash FROM pages"):
            rows = [(k, key, r["v"], copy.deepcopy(r["json"]), r["hash"]) for (k, key), r in sorted(self.pages.items())
                    if not params or k == params[0]]
            return FakeCursor(rows, len(rows))
        if sql.startswith("SELECT key, mime, bytes, hash FROM images"):
            rows = [(k, r["mime"], memoryview(r["bytes"]), r["hash"]) for k, r in sorted(self.images.items())]
            return FakeCursor(rows, len(rows))
        if sql == db.UPSERT_BRAIN_ASSET:
            key, kind, mime, data, raw_bytes, digest = params
            old = self.assets.get(key)
            if old and old["hash"] == digest:
                return FakeCursor(rowcount=0)
            self.assets[key] = {"kind": kind, "mime": mime, "encoding": "gzip", "bytes": bytes(data),
                                "raw_bytes": raw_bytes, "hash": digest}
            return FakeCursor(rowcount=1)
        if sql.startswith("SELECT key, hash FROM brain_assets"):
            rows = [(k, r["hash"]) for k, r in sorted(self.assets.items())]
            return FakeCursor(rows, len(rows))
        if sql.startswith("DELETE FROM brain_assets WHERE NOT (key = ANY(%s))"):
            keep, = params
            gone = sorted(k for k in self.assets if k not in keep)
            for k in gone:
                del self.assets[k]
            return FakeCursor([(k,) for k in gone], len(gone))
        if sql.startswith("SELECT key, kind, mime, encoding, bytes, raw_bytes, hash FROM brain_assets"):
            rows = [(k, r["kind"], r["mime"], r["encoding"], memoryview(r["bytes"]), r["raw_bytes"], r["hash"])
                    for k, r in sorted(self.assets.items())]
            return FakeCursor(rows, len(rows))
        raise AssertionError(f"unexpected SQL: {sql}")


class SyncCase(trs.SwipeCase):
    def setUp(self):
        super().setUp()
        self.creator()
        self.reel(tribe=self.tribe_job(), shape=self.shape(), transcript=TRANSCRIPT)
        (store.OUTPUTS / JOB / "peak.png").write_bytes(dash._tiny_png())
        self.reel(sc="TESTREEL02", plays=900, shape=self.shape(), transcript="Another synthetic line, nothing else.")

    def bundle(self):
        return sync.build()


class TestPush(SyncCase):
    def test_push_upserts_with_hashes_then_leaves_unchanged_pages(self):
        bundle, private = self.bundle()
        conn = FakeDb()
        done = sync.push(conn, bundle, private)
        keys = sorted(f"{k}/{key}" for k, key, _ in bundle["pages"])
        self.assertEqual(sorted(done["changed"]), keys)
        self.assertEqual(conn.transactions, 1)
        for kind, key, page in bundle["pages"]:
            row = conn.pages[(kind, key)]
            self.assertEqual(row["json"], page)
            self.assertEqual(row["hash"], db.page_hash(page))
            self.assertEqual(row["v"], 1)
        self.assertEqual(sorted(conn.images), [f"tribe/{JOB}/peak.png"])
        self.assertEqual(done["images"], [f"tribe/{JOB}/peak.png"])
        again = sync.push(conn, bundle, private)
        self.assertEqual((again["changed"], again["same"], again["images"]), ([], len(keys), []))
        self.assertEqual(sync.audit(conn, private), [])

    def test_push_removes_pages_whose_source_is_gone(self):
        bundle, private = self.bundle()
        conn = FakeDb()
        sync.push(conn, bundle, private)
        conn.pages[("lab", "20260101-old-draft")] = {"v": 1, "json": {"v": 1}, "hash": "0" * 64}
        conn.images["tribe/20260101-000000-00000000/peak.png"] = {"mime": "image/png", "bytes": b"", "hash": "x"}
        shutil.rmtree(store.reel_dir("TESTREEL02"))
        bundle, private = self.bundle()
        done = sync.push(conn, bundle, private)
        self.assertEqual(sorted(done["removed"]), ["lab/20260101-old-draft", "reel/TESTREEL02"])
        self.assertEqual(done["images_removed"], ["tribe/20260101-000000-00000000/peak.png"])
        self.assertNotIn(("reel", "TESTREEL02"), conn.pages)
        self.assertIn("board/index", done["changed"])          # the board lost a reel

    def test_push_keeps_reel_pages_when_the_laptop_has_none(self):
        bundle, private = self.bundle()
        conn = FakeDb()
        sync.push(conn, bundle, private)
        empty = {"pages": [p for p in bundle["pages"] if p[0] != "reel"], "images": bundle["images"]}
        log = []
        done = sync.push(conn, empty, private, log=log.append)
        self.assertIn(("reel", "TESTREEL01"), conn.pages)
        self.assertEqual(done["kept"], ["reel"])
        self.assertIn("--allow-empty", log[0])
        done = sync.push(conn, empty, private, allow_empty=True)
        self.assertNotIn(("reel", "TESTREEL01"), conn.pages)
        self.assertEqual(sorted(done["removed"]), ["reel/TESTREEL01", "reel/TESTREEL02"])

    def test_push_refuses_a_leak_and_sends_nothing(self):
        bundle, private = self.bundle()
        bad = copy.deepcopy(bundle)
        for kind, key, page in bad["pages"]:
            if kind == "reel":
                page["beats"][0]["name"] = f"{RUN} again"
                break
        conn = FakeDb()
        with self.assertRaises(sync.SyncError) as cm:
            sync.push(conn, bad, private)
        self.assertIn("privacy scan refused", str(cm.exception))
        self.assertIn("/beats/0/name", str(cm.exception))
        self.assertNotIn(RUN, str(cm.exception).lower())
        self.assertEqual(conn.sql, [])
        for mutate in (lambda b: b["pages"].append(("reel", "TESTREEL09", {"v": 1})),
                       lambda b: b["images"].update({f"tribe/{JOB}/peak.png": dash._tiny_png()[:20]}),
                       lambda b: b["pages"][0][2].update(stamp=["C:\\Users\\x", "counts"])):
            bad = copy.deepcopy(bundle)
            mutate(bad)
            with self.assertRaises(sync.SyncError):
                sync.push(conn, bad, private)
            self.assertEqual(conn.sql, [])

    def test_a_database_failure_rolls_back(self):
        bundle, private = self.bundle()
        conn = FakeDb(fail_on="DELETE FROM images")
        with self.assertRaises(RuntimeError):
            sync.push(conn, bundle, private)
        self.assertEqual((conn.pages, conn.images), ({}, {}))
        conn = FakeDb()
        with mock.patch.object(db, "upsert_image", side_effect=db.DbError("tribe/x: not a PNG")):
            with self.assertRaises(sync.SyncError) as cm:
                sync.push(conn, bundle, private)
        self.assertIn("nothing was saved", str(cm.exception))
        self.assertEqual(conn.pages, {})

    def test_build_refuses_when_the_laptop_data_leaks(self):
        self.reel(sc="TESTREEL03", shape=self.shape(beat_name=f"{RUN} demo"), transcript=TRANSCRIPT)
        with self.assertRaises(sync.SyncError) as cm:
            sync.build()
        self.assertIn("reel/TESTREEL03", str(cm.exception))
        self.assertNotIn(RUN, str(cm.exception).lower())


class TestAudit(SyncCase):
    def pushed(self):
        bundle, private = self.bundle()
        conn = FakeDb()
        sync.push(conn, bundle, private)
        return conn, private

    def test_clean_rows_pass(self):
        conn, private = self.pushed()
        self.assertEqual(sync.audit(conn, private), [])

    def test_audit_finds_leaks_and_broken_rows(self):
        conn, private = self.pushed()
        reel = conn.pages[("reel", "TESTREEL01")]
        reel["json"]["beats"][0]["name"] = f"{RUN} demo"            # a private run, hash left stale
        board = conn.pages[("board", "index")]
        board["json"]["stamp"][0] = "3 creators, see C:/Users/x"
        board["hash"] = db.page_hash(board["json"])
        conn.pages[("lab", "20261009-x")] = {"v": 1, "json": {"v": 1, "id": "20261009-x"}, "hash": "0" * 64}
        meta = conn.pages[("meta", "index")]
        conn.pages[("meta", "other")] = copy.deepcopy(meta)
        conn.images[f"tribe/{JOB}/peak.png"]["bytes"] = b"\xff\xd8jpeg"
        conn.images["tribe/20260101-000000-00000000/peak.png"] = {"mime": "image/jpeg", "bytes": b"x", "hash": "x"}
        problems = sync.audit(conn, private)
        text = "\n".join(problems)
        for must in ("reel/TESTREEL01: hash does not match", "reel/TESTREEL01 /beats/0/name: 1 4-word run",
                     "board/index", "lab/20261009-x", "meta/other: stored under the wrong key",
                     f"image tribe/{JOB}/peak.png", "not image/png"):
            self.assertIn(must, text)
        self.assertNotIn(RUN, text.lower())

    def test_audit_spots_a_missing_peak_picture(self):
        conn, private = self.pushed()
        del conn.images[f"tribe/{JOB}/peak.png"]
        self.assertEqual(sync.audit(conn, private), [f"tribe/{JOB}: its peak picture tribe/{JOB}/peak.png is not in images"])


class BrainCase(SyncCase):
    """TESTREEL01's TRIBE job with synthetic preds (and a synthetic atlas, masks and mesh): a brain
    page and three assets."""

    def setUp(self):
        super().setUp()
        self.docs = tba.install_synthetic(self, self.tmp / "brain-masks")
        tba.write_preds(store.OUTPUTS / JOB, self.docs["masks"], tba.synthetic_preds(30, seed=2))

    def frames(self):
        return f"tribe/{JOB}/frames.i8"


class TestBrainPush(BrainCase):
    SHARED = ["shared/atlas-v1.bin", "shared/fsaverage5-inflated-v1.bin"]

    def test_push_uploads_assets_once_then_skips_unchanged(self):
        bundle, private = self.bundle()
        self.assertIn(("brain", JOB), [(k, key) for k, key, _ in bundle["pages"]])
        conn = FakeDb()
        done = sync.push(conn, bundle, private)
        self.assertEqual(sorted(done["assets"]), self.SHARED + [self.frames()])
        self.assertIn(f"brain/{JOB}", done["changed"])
        self.assertEqual(conn.transactions, 1)
        for key, a in bundle["assets"].items():
            row = conn.assets[key]
            self.assertEqual((row["kind"], row["mime"], row["bytes"], row["raw_bytes"], row["hash"]),
                             (a.kind, "application/octet-stream", a.data, a.raw_bytes, a.hash))
        self.assertEqual(conn.pages[("brain", JOB)]["json"]["frames"]["sha256"], bundle["assets"][self.frames()].hash)
        before = len(conn.sql)
        again = sync.push(conn, bundle, private)
        self.assertEqual((again["assets"], again["assets_same"], again["assets_removed"]), ([], 3, []))
        self.assertNotIn(db.UPSERT_BRAIN_ASSET, conn.sql[before:])     # unchanged: no bytes sent again
        self.assertEqual(sync.audit(conn, private), [])
        # a rebuilt bundle is byte-identical, so nothing is re-sent either
        rebuilt, _ = self.bundle()
        self.assertEqual({k: a.hash for k, a in rebuilt["assets"].items()},
                         {k: a.hash for k, a in bundle["assets"].items()})

    def test_changed_preds_resend_only_the_frames(self):
        bundle, private = self.bundle()
        conn = FakeDb()
        sync.push(conn, bundle, private)
        tba.write_preds(store.OUTPUTS / JOB, self.docs["masks"], tba.synthetic_preds(30, seed=7))
        bundle, private = self.bundle()
        done = sync.push(conn, bundle, private)
        self.assertEqual((done["assets"], done["assets_same"]), ([self.frames()], 2))
        self.assertEqual(sync.audit(conn, private), [])

    def test_orphans_go_and_the_brain_follows_its_source(self):
        bundle, private = self.bundle()
        conn = FakeDb()
        sync.push(conn, bundle, private)
        old = bundle["assets"][self.frames()]
        conn.assets["tribe/20260101-000000-00000000/frames.i8"] = dict(conn.assets[self.frames()])
        done = sync.push(conn, bundle, private)
        self.assertEqual(done["assets_removed"], ["tribe/20260101-000000-00000000/frames.i8"])
        # preds.npy gone: the brain page, its frames and (no other brain page) the shared assets go
        (store.OUTPUTS / JOB / "preds.npy").unlink()
        bundle, private = self.bundle()
        self.assertNotIn("brain", [k for k, _, _ in bundle["pages"]])
        self.assertEqual(bundle["assets"], {})
        done = sync.push(conn, bundle, private)
        self.assertIn(f"brain/{JOB}", done["removed"])
        self.assertEqual(sorted(done["assets_removed"]), self.SHARED + [self.frames()])
        self.assertEqual(conn.assets, {})
        self.assertIn(("tribe", JOB), conn.pages)                         # the tribe page stays
        self.assertEqual(sync.audit(conn, private), [])
        self.assertTrue(old.data)

    def test_a_missing_atlas_or_mesh_refuses_and_sends_nothing(self):
        bundle, private = self.bundle()
        conn = FakeDb()
        sync.push(conn, bundle, private)
        before = (copy.deepcopy(conn.pages), copy.deepcopy(conn.assets))
        for name in ("ATLAS_JSON", "MESH_NPZ"):
            with mock.patch.object(B, name, self.tmp / "gone" / "x"):
                with self.assertRaises(sync.SyncError) as cm:
                    sync.build()
            self.assertIn("brain: could not build", str(cm.exception))
            self.assertIn("nothing leaves the laptop", str(cm.exception))
        with mock.patch.object(B, "ATLAS_JSON", self.tmp / "gone" / "atlas-v1.json"):
            self.assertIn("run scoring/build_atlas.py", str(self._refusal()))
        self.assertEqual((conn.pages, conn.assets), before)                # never a silent wipe

    def _refusal(self):
        with self.assertRaises(sync.SyncError) as cm:
            sync.build()
        return cm.exception

    def test_push_refuses_bad_assets_and_sends_nothing(self):
        bundle, private = self.bundle()
        frames = bundle["assets"][self.frames()]
        cases = [
            ("wrong mime", lambda b: b["assets"].update({frames.key: frames._replace(mime="text/csv")}), "text/csv"),
            ("short frames", lambda b: b["assets"].update({frames.key: B.pack(
                "frames", frames.key, B.header("frames", 29, 20484, 127) + frames.raw[16:-20484])}),
             "the page has 30 seconds"),
            ("cut frames", lambda b: b["assets"].update({frames.key: B.Asset(
                frames.key, "frames", frames.mime, frames.raw[:-20484], B.gz(frames.raw[:-20484]),
                hashlib.sha256(B.gz(frames.raw[:-20484])).hexdigest())}), "expected exactly"),
            ("orphan", lambda b: b["assets"].update({"shared/atlas-v2.bin": b["assets"]["shared/atlas-v1.bin"]._replace(
                key="shared/atlas-v2.bin")}), "no brain page uses it"),
            ("missing", lambda b: b["assets"].pop("shared/atlas-v1.bin"), "is not stored"),
            ("stale hash", lambda b: b["assets"].update({frames.key: frames._replace(hash="0" * 64)}), "hash does not match"),
            ("no tribe page", lambda b: b.update(pages=[x for x in b["pages"] if x[0] != "tribe"]), "no tribe page"),
        ]
        for name, mutate, must in cases:
            bad = {"pages": list(bundle["pages"]), "images": dict(bundle["images"]), "assets": dict(bundle["assets"])}
            mutate(bad)
            conn = FakeDb()
            with self.assertRaises(sync.SyncError, msg=name) as cm:
                sync.push(conn, bad, private)
            self.assertIn(must, str(cm.exception), name)
            self.assertEqual(conn.sql, [], name)

    def test_a_failure_mid_push_rolls_back_the_assets(self):
        bundle, private = self.bundle()
        conn = FakeDb(fail_on="DELETE FROM brain_assets")
        with self.assertRaises(RuntimeError):
            sync.push(conn, bundle, private)
        self.assertEqual((conn.pages, conn.images, conn.assets), ({}, {}, {}))


class TestBrainAudit(BrainCase):
    def pushed(self):
        bundle, private = self.bundle()
        conn = FakeDb()
        sync.push(conn, bundle, private)
        return conn, private

    def test_audit_finds_broken_assets(self):
        conn, private = self.pushed()
        fr = conn.assets[self.frames()]
        atl = conn.assets["shared/atlas-v1.bin"]
        mesh = conn.assets["shared/fsaverage5-inflated-v1.bin"]
        fr["bytes"] = fr["bytes"][:100] + bytes([fr["bytes"][100] ^ 0xFF]) + fr["bytes"][101:]   # stale hash, bad gzip
        atl["mime"] = "text/plain"
        mesh["raw_bytes"] += 1
        mesh["hash"] = "f" * 64
        conn.assets["tribe/20260101-000000-00000000/frames.i8"] = dict(mesh, kind="frames")
        problems = sync.audit(conn, private)
        text = "\n".join(problems)
        for must in (f"asset {self.frames()}: hash does not match", "asset shared/atlas-v1.bin: stored as 'text/plain'",
                     "raw_bytes says", "tribe/20260101-000000-00000000/frames.i8: no brain page uses it",
                     "damaged gzip data",
                     f"brain/{JOB} /mesh: asset shared/fsaverage5-inflated-v1.bin is stored with another hash"):
            self.assertIn(must, text)

    def test_audit_ties_brain_pages_to_tribe_pages_and_assets(self):
        conn, private = self.pushed()
        del conn.assets["shared/atlas-v1.bin"]
        page = conn.pages[("brain", JOB)]
        page["json"]["time_s"] = page["json"]["time_s"][:-1]
        page["hash"] = db.page_hash(page["json"])
        problems = sync.audit(conn, private)
        text = "\n".join(problems)
        self.assertIn(f"brain/{JOB} /atlas: asset shared/atlas-v1.bin is not stored", text)
        self.assertIn(f"brain/{JOB}: its seconds differ from the tribe page's", text)
        del conn.pages[("tribe", JOB)]
        self.assertIn(f"brain/{JOB}: no tribe page for this job", "\n".join(sync.audit(conn, private)))

    def test_audit_never_quotes_a_private_run_planted_in_a_brain_label(self):
        conn, private = self.pushed()
        page = conn.pages[("brain", JOB)]
        page["json"]["atlas"]["hcp"]["labels"][0] = f"{RUN} demo"
        page["hash"] = db.page_hash(page["json"])
        problems = sync.audit(conn, private)
        self.assertTrue(any(f"brain/{JOB}" in p and "not one of" in p for p in problems), problems)
        self.assertNotIn(RUN, "\n".join(problems).lower())


class TestExportAndCli(SyncCase):
    def test_export_writes_payloads_pictures_and_a_manifest(self):
        bundle, _ = self.bundle()
        out = self.tmp / "export"
        (out / "reel").mkdir(parents=True)
        (out / "reel" / "STALE00001.json").write_text("{}", encoding="utf-8")
        sync.export(bundle, out)
        self.assertFalse((out / "reel" / "STALE00001.json").exists())
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["pages"]), len(bundle["pages"]))
        for row in manifest["pages"]:
            page = json.loads((out / row["kind"] / f"{row['key']}.json").read_text(encoding="utf-8"))
            self.assertEqual(db.page_hash(page), row["hash"])
            self.assertEqual(hosted.size_of(page), row["bytes"])
        self.assertEqual((out / "images" / "tribe" / JOB / "peak.png").read_bytes(), dash._tiny_png())
        with self.assertRaises(sync.SyncError):
            sync.export(bundle, PROJECT_ROOT / "web" / "export")
        self.assertFalse((PROJECT_ROOT / "web" / "export").exists())

    def test_cli(self):
        out = self.tmp / "cli-export"
        self.assertEqual(sync.main(["export", "--out", str(out)]), 0)
        self.assertTrue((out / "reel" / "TESTREEL01.json").is_file())
        conn = FakeDb()
        with mock.patch.object(db, "load_env", return_value=[]), mock.patch.object(db, "connect", return_value=conn):
            self.assertEqual(sync.main(["push"]), 0)
            self.assertTrue(conn.closed)
            self.assertIn(("reel", "TESTREEL01"), conn.pages)
            self.assertEqual(sync.main(["audit"]), 0)
            conn.pages[("reel", "TESTREEL01")]["hash"] = "0" * 64
            self.assertEqual(sync.main(["audit"]), 1)
        url = "postgresql://tribe_runner:s3cret-pw@example.invalid/db"
        with mock.patch.object(db, "load_env", return_value=[]), \
                mock.patch.object(db, "connect", return_value=FakeDb(fail_on="INSERT INTO pages")), \
                mock.patch.dict("os.environ", {db.DSN_ENV: url}), \
                mock.patch.object(FakeDb, "execute", side_effect=RuntimeError(f"bad thing near {url}")), \
                mock.patch("sys.stderr") as err:
            self.assertEqual(sync.main(["push"]), 2)
        said = "".join(str(c.args[0]) for c in err.write.call_args_list if c.args)
        self.assertIn("Refused: push failed", said)
        self.assertNotIn("s3cret-pw", said)
        with mock.patch.object(db, "load_env", return_value=[]), mock.patch.dict("os.environ", {db.DSN_ENV: ""}):
            self.assertEqual(sync.main(["audit"]), 2)      # no URL: refused before any connection

    def test_export_writes_brain_assets_unpacked(self):
        tba.install_synthetic(self, self.tmp / "brain-masks")
        docs = json.loads(B.MASKS_JSON.read_text(encoding="utf-8"))
        tba.write_preds(store.OUTPUTS / JOB, docs, tba.synthetic_preds(30, seed=4))
        bundle, _ = self.bundle()
        out = self.tmp / "export-brain"
        (out / "assets" / "tribe" / "20260101-000000-00000000").mkdir(parents=True)
        (out / "assets" / "tribe" / "20260101-000000-00000000" / "frames.i8").write_bytes(b"stale")
        sync.export(bundle, out)
        self.assertFalse((out / "assets" / "tribe" / "20260101-000000-00000000" / "frames.i8").exists())
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(a["key"] for a in manifest["assets"]), sorted(bundle["assets"]))
        for row in manifest["assets"]:
            a = bundle["assets"][row["key"]]
            self.assertEqual((out / "assets" / row["key"]).read_bytes(), a.raw)
            self.assertEqual((row["kind"], row["bytes"], row["raw_bytes"], row["hash"]),
                             (a.kind, len(a.data), a.raw_bytes, a.hash))
        self.assertTrue((out / "brain" / f"{JOB}.json").is_file())
        self.assertEqual(manifest["total_bytes"], sum(r["bytes"] for r in manifest["pages"])
                         + sum(i["bytes"] for i in manifest["images"]) + sum(a["bytes"] for a in manifest["assets"]))
        names = [n for n, _ in sync.sizes(bundle)]
        self.assertIn(f"brain/{JOB}", names)
        self.assertTrue(any(n.startswith(f"tribe/{JOB}/frames.i8 (gzip") for n in names))

    def test_cli_refuses_a_leaky_laptop(self):
        self.reel(sc="TESTREEL03", shape=self.shape(beat_name=f"{RUN} demo"), transcript=TRANSCRIPT)
        conn = FakeDb()
        out = self.tmp / "leaky"
        with mock.patch.object(db, "load_env", return_value=[]), mock.patch.object(db, "connect", return_value=conn):
            self.assertEqual(sync.main(["push"]), 2)
            self.assertEqual(sync.main(["export", "--out", str(out)]), 2)
        self.assertEqual(conn.sql, [])
        self.assertFalse(out.exists())


class TestSpend(unittest.TestCase):
    def test_spend_page_fits_its_schema_and_is_not_synced(self):
        import datetime as dt
        from strategist import contract
        now = dt.datetime(2026, 10, 9, 10, 15, tzinfo=dt.timezone.utc)
        page = hosted.spend_page(0.42, None, now)
        contract.check_page("spend", page)
        self.assertEqual((page["month"], page["modal_cap_usd"], page["apify_usd"], page["apify_cap_usd"]),
                         ("2026-10", 30.0, None, 4.5))
        self.assertEqual(hosted.page_problems("spend", page), [])
        self.assertNotIn("spend", hosted.SYNC_KINDS)   # the runner's page: a push never overwrites or removes it
        self.assertIn("brain", hosted.SYNC_KINDS)


class TestDbReads(unittest.TestCase):
    def test_list_pages_and_images(self):
        conn = FakeDb()
        conn.pages[("reel", "TESTREEL01")] = {"v": 1, "json": {"v": 1, "shortcode": "TESTREEL01"}, "hash": "h"}
        conn.pages[("board", "index")] = {"v": 1, "json": json.dumps({"v": 1}), "hash": "h2"}
        conn.images["tribe/x/peak.png"] = {"mime": "image/png", "bytes": b"\x89PNG", "hash": "h3"}
        rows = db.list_pages(conn)
        self.assertEqual([(r["kind"], r["key"]) for r in rows], [("board", "index"), ("reel", "TESTREEL01")])
        self.assertEqual(rows[0]["page"], {"v": 1})                 # a JSON string is parsed
        self.assertEqual([r["key"] for r in db.list_pages(conn, "reel")], ["TESTREEL01"])
        with self.assertRaises(db.DbError):
            db.list_pages(conn, "nope")
        self.assertEqual(db.list_images(conn), [{"key": "tribe/x/peak.png", "mime": "image/png", "bytes": b"\x89PNG",
                                                 "hash": "h3"}])
        conn.assets["shared/atlas-v1.bin"] = {"kind": "atlas", "mime": "application/octet-stream", "encoding": "gzip",
                                              "bytes": b"\x1f\x8b", "raw_bytes": 16, "hash": "h4"}
        self.assertEqual(db.list_brain_assets(conn), [{"key": "shared/atlas-v1.bin", "kind": "atlas",
                                                       "mime": "application/octet-stream", "encoding": "gzip",
                                                       "bytes": b"\x1f\x8b", "raw_bytes": 16, "hash": "h4"}])
        self.assertEqual(db.brain_asset_hashes(conn), {"shared/atlas-v1.bin": "h4"})


class TestArchivedReels(SyncCase):
    """D31: sync takes down only the hosted pages of an archived reel; the files stay."""

    def test_push_removes_the_archived_reels_page_and_nothing_else(self):
        bundle, private = self.bundle()
        conn = FakeDb()
        sync.push(conn, bundle, private)
        doc = store.load_reel("TESTREEL02")
        doc["archived"] = True
        store.save_reel(doc)
        bundle, private = self.bundle()
        self.assertNotIn(("reel", "TESTREEL02"), {(k, key) for k, key, _ in bundle["pages"]})
        done = sync.push(conn, bundle, private)
        self.assertEqual(done["removed"], ["reel/TESTREEL02"])
        self.assertTrue(store.reel_path("TESTREEL02").is_file())
        self.assertIn(("reel", "TESTREEL01"), conn.pages)
        self.assertEqual(sync.audit(conn, private), [])

    def test_unarchive_brings_the_page_back(self):
        doc = store.load_reel("TESTREEL02")
        doc["archived"] = True
        store.save_reel(doc)
        bundle, private = self.bundle()
        conn = FakeDb()
        sync.push(conn, bundle, private)
        self.assertNotIn(("reel", "TESTREEL02"), conn.pages)
        doc["archived"] = False
        store.save_reel(doc)
        bundle, private = self.bundle()
        done = sync.push(conn, bundle, private)
        self.assertIn("reel/TESTREEL02", done["changed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
