"""Tests for strategist/brain_assets.py (the brain view's page and binary assets, D28).
Run: python -m strategist.test_brain_assets

Two parts:
  - Synthetic: a temp outputs folder and a synthetic atlas, masks and mesh (made-up geometry,
    real HCP codes): the layouts and headers, one colour scale per reel, dequantisation error,
    area means against plain numpy, the fixed area order, byte-identical rebuilds, and every
    refusal (NaN, wrong width, rows, raw_z, masks version, over 90 s, missing atlas or mesh).
  - RealData: the three TRIBE jobs on this laptop, in memory only (skipped with a message when
    scoring/masks/atlas-v1.json, the mesh or outputs/ is missing): size caps, the atlas lookup
    reproduces masks-v1 and the Yeo cross-check masks, raw_z and time_s match each report.
Nothing is written outside temp folders; no network, no database.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
sys.path.insert(0, str(PROJECT_ROOT))
from strategist import brain_assets as B, contract, store  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "dashboard"))
import test_render as dash  # noqa: E402  the dashboard's synthetic report builder

JOB = "20261001-120000-0123abcd"
REAL_LINKED = "20260101-000000-demo0000"
REAL_JOBS = ("20261008-130514-b670602f", "20260101-000000-demo0000", "20261008-225213-68b712e3")


# ---------------------------------------------------------------- synthetic helpers (also used by
# strategist/test_sync.py and strategist/test_hosted_privacy.py)

def install_synthetic(case: unittest.TestCase, folder: Path) -> dict:
    """Write a synthetic atlas, masks and mesh into folder and point brain_assets at them for the
    rest of the test. Returns the atlas and masks documents."""
    folder.mkdir(parents=True, exist_ok=True)
    atlas = B.synthetic_atlas()
    masks = B.synthetic_masks(atlas)
    (folder / "atlas-v1.json").write_text(json.dumps(atlas), encoding="utf-8")
    (folder / "masks-v1.json").write_text(json.dumps(masks), encoding="utf-8")
    np.savez(folder / "mesh.npz", **B.synthetic_mesh())
    for name, path in (("ATLAS_JSON", folder / "atlas-v1.json"), ("MASKS_JSON", folder / "masks-v1.json"),
                       ("MESH_NPZ", folder / "mesh.npz")):
        p = mock.patch.object(B, name, path)
        p.start()
        case.addCleanup(p.stop)
    return {"atlas": atlas, "masks": masks}


def synthetic_preds(rows: int, seed: int = 0, scale: float = 0.2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(rows)[:, None]
    return (scale * rng.standard_normal((rows, B.N_V)) + 0.05 * np.sin(0.3 * t)).astype(np.float32)


def write_preds(job_dir: Path, masks: dict, P: np.ndarray) -> None:
    """preds.npy plus a report.json whose time_s, rows and raw_z belong to these preds (as
    scoring/score.py would write them)."""
    job_dir = Path(job_dir)
    np.save(job_dir / "preds.npy", P)
    rep = json.loads((job_dir / "report.json").read_text(encoding="utf-8"))
    rows = P.shape[0]
    s = B.scoring()
    X = P.astype(np.float64)
    rep["time_s"] = [float(t) for t in range(rows)]
    rep["per_second"] = [{"t": t, "black": False, "silent": False, "edge": t < 2 or t >= rows - 2, "hook": t < 3}
                         for t in range(rows)]
    rep["clip"]["rows"], rep["clip"]["seconds"] = rows, float(rows) - 0.4
    rep["masks_version"], rep["job_id"] = masks["version"], job_dir.name
    for k in B.LINE_KEYS:
        z = s.zscore(X[:, np.asarray(masks["lines"][k]["vertices"])].mean(axis=1))
        line = rep["lines"][k]
        line["raw_z"] = [s._r(v) for v in z.tolist()]
        for f in ("display_z", "shape_z"):
            line[f] = (line[f] * (rows // len(line[f]) + 1))[:rows]
    rep["combined"]["shape_z"] = (rep["combined"]["shape_z"] * (rows // len(rep["combined"]["shape_z"]) + 1))[:rows]
    (job_dir / "report.json").write_text(json.dumps(rep), encoding="utf-8")


def make_job(outputs: Path, masks: dict, rows: int = 12, job: str = JOB, seed: int = 0, sc: str = "TESTREEL01"):
    """A whole synthetic job folder: report.json, predict_meta.json and preds.npy."""
    d = Path(outputs) / job
    d.mkdir(parents=True, exist_ok=True)
    rep = dash.make_report(job_id=job)
    rep["source"]["source_url"] = f"https://www.instagram.com/reel/{sc}/"
    (d / "report.json").write_text(json.dumps(rep), encoding="utf-8")
    (d / "predict_meta.json").write_text(json.dumps({"mock": False, "precision": "bf16"}), encoding="utf-8")
    P = synthetic_preds(rows, seed)
    write_preds(d, masks, P)
    return d, P


class SynthCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="brain-assets-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(store, "OUTPUTS", self.tmp / "outputs")
        p.start()
        self.addCleanup(p.stop)
        self.docs = install_synthetic(self, self.tmp / "masks")
        self.masks = self.docs["masks"]

    def job(self, rows=12, **kw):
        return make_job(store.OUTPUTS, self.masks, rows, **kw)

    def refused(self, must: str, job: str = JOB):
        with self.assertRaises(B.BrainError) as cm:
            B.build(job)
        self.assertIn(must, str(cm.exception))
        return str(cm.exception)


# ---------------------------------------------------------------- synthetic

class TestLayouts(SynthCase):
    def test_headers_lengths_and_page(self):
        d, P = self.job(12)
        page, assets = B.build(JOB, {"shortcode": "TESTREEL01"})
        contract.check_page("brain", page)
        self.assertEqual(B.page_problems(page), [])
        self.assertEqual(sorted(assets), ["shared/atlas-v1.bin", "shared/fsaverage5-inflated-v1.bin",
                                          f"tribe/{JOB}/frames.i8"])
        fr = assets[f"tribe/{JOB}/frames.i8"]
        self.assertEqual(struct.unpack("<4sIII", fr.raw[:16]), (b"TBF1", 12, 20484, 127))
        self.assertEqual(len(fr.raw), 16 + 12 * 20484)
        mesh = assets["shared/fsaverage5-inflated-v1.bin"]
        self.assertEqual(struct.unpack("<4sIII", mesh.raw[:16]), (b"TBM1", 10242, 20480, 1))
        self.assertEqual(len(mesh.raw), 573520)
        atl = assets["shared/atlas-v1.bin"]
        self.assertEqual(struct.unpack("<4sIII", atl.raw[:16]), (b"TBA1", 20484, 180, 7))
        self.assertEqual(len(atl.raw), 40984)
        for a in assets.values():
            self.assertEqual(a.mime, "application/octet-stream")
            self.assertEqual(a.data[:2], b"\x1f\x8b")
            self.assertEqual(gzip.decompress(a.data), a.raw)
            self.assertEqual(a.hash, hashlib.sha256(a.data).hexdigest())
            self.assertEqual(B.check_asset(a.kind, a.raw)["vertices" if a.kind != "mesh" else "vertices_per_side"],
                             20484 if a.kind != "mesh" else 10242)
        for name in ("frames", "mesh", "atlas"):
            ref = page[name]
            self.assertEqual(assets[ref["key"]].hash, ref["sha256"])
            self.assertEqual(assets[ref["key"]].raw_bytes, ref["bytes"])
        self.assertEqual(page["shortcode"], "TESTREEL01")
        self.assertEqual(page["precision"], "bf16")
        self.assertEqual(page["framing"], "predicted average-brain response")
        self.assertEqual(page["scale"]["label"], "one colour scale for this whole reel")
        self.assertEqual(page["time_s"], [float(t) for t in range(12)])
        atlas = B.load_atlas()
        # the atlas binary is the lookup, byte for byte
        self.assertEqual(np.frombuffer(atl.raw[16:16 + 20484], dtype=np.uint8).tolist(), atlas["hcp_lookup"].tolist())
        self.assertEqual(np.frombuffer(atl.raw[16 + 20484:], dtype=np.uint8).tolist(), atlas["yeo_lookup"].tolist())
        # mesh sections in order: coords L, coords R, faces L, faces R, sulc L, sulc R
        m = B.synthetic_mesh()
        body = mesh.raw[16:]
        coords = np.frombuffer(body, dtype="<f4", count=2 * 10242 * 3).reshape(2, 10242, 3)
        self.assertTrue(np.array_equal(coords[0], m["infl_left"]))
        sulc = np.frombuffer(body, dtype="<f4", offset=2 * 10242 * 12 + 2 * 20480 * 6).reshape(2, 10242)
        self.assertTrue(np.array_equal(sulc[1], m["sulc_right"]))

    def test_one_scale_and_dequantisation(self):
        _, P = self.job(12, seed=3)
        page, assets = B.build(JOB)
        X = P.astype(np.float64)
        cortex = B.load_atlas()["hcp_lookup"] != 0
        vmax = page["scale"]["vmax"]
        self.assertEqual(vmax, round(float(np.percentile(np.abs(X[:, cortex]), 99)), 6))
        self.assertEqual(set(page["scale"]), {"mode", "label", "vmax", "percentile", "pooled", "levels", "colormap",
                                              "grey_below", "full_at", "clipped_share"})   # no per-row scale
        q = np.frombuffer(assets[page["frames"]["key"]].raw[16:], dtype=np.int8).reshape(12, -1)
        self.assertGreaterEqual(int(q.min()), -127)
        self.assertLessEqual(int(q.max()), 127)
        inside = np.abs(X) <= vmax
        self.assertLessEqual(float(np.abs(q / 127 * vmax - X)[inside].max()), vmax / 254 + 1e-9)
        self.assertTrue(np.all(np.abs(q[~inside]) == 127))
        self.assertAlmostEqual(page["scale"]["clipped_share"], 0.01, delta=0.003)
        # the same rows in a reel with a louder second keep one scale for every second
        louder = P.copy()
        louder[5] *= 3
        write_preds(store.OUTPUTS / JOB, self.masks, louder)
        page2, _ = B.build(JOB)
        self.assertNotEqual(page2["scale"]["vmax"], vmax)

    def test_area_means_are_numpy_means(self):
        _, P = self.job(12, seed=5)
        page, _ = B.build(JOB)
        atlas = B.load_atlas()
        X = P.astype(np.float64)
        hcp, yeo = atlas["hcp_lookup"], atlas["yeo_lookup"]
        left, right = np.arange(20484) < 10242, np.arange(20484) >= 10242
        for k in (1, 2, 90, 180):
            for side, mask in (("hcp_left", left), ("hcp_right", right)):
                want = np.round(X[:, (hcp == k) & mask].mean(axis=1), 4)
                self.assertTrue(np.allclose(page["areas"][side][k - 1], want, atol=1e-4), (side, k))
        for k in range(1, 8):
            want = np.round(X[:, yeo == k].mean(axis=1), 4)
            self.assertTrue(np.allclose(page["areas"]["yeo"][k - 1], want, atol=1e-4), k)
        for line in B.LINE_KEYS:
            want = X[:, np.asarray(self.masks["lines"][line]["vertices"])].mean(axis=1)
            self.assertTrue(np.allclose(page["areas"]["lines"][line], want, atol=1e-4), line)
        for name in ("hcp_left", "hcp_right"):
            self.assertEqual(len(page["areas"][name]), 180)
            self.assertTrue(all(len(r) == 12 for r in page["areas"][name]))

    def test_order_is_fixed_by_the_atlas_not_the_values(self):
        self.job(12, seed=1)
        page, _ = B.build(JOB)
        order, network = page["atlas"]["order"], page["atlas"]["hcp"]["network"]
        self.assertEqual(order, sorted(range(180), key=lambda i: (network[i], i)))
        self.assertEqual([network[i] for i in order], sorted(network))
        write_preds(store.OUTPUTS / JOB, self.masks, synthetic_preds(12, seed=99)[::-1].copy())
        again, _ = B.build(JOB)
        self.assertEqual(again["atlas"]["order"], order)
        self.assertNotEqual(again["areas"], page["areas"])

    def test_two_builds_are_byte_identical(self):
        self.job(12)
        p1, a1 = B.build(JOB)
        B._shared_cached.cache_clear()
        B._atlas_cached.cache_clear()
        p2, a2 = B.build(JOB)
        self.assertEqual(p1, p2)
        self.assertEqual({k: v.data for k, v in a1.items()}, {k: v.data for k, v in a2.items()})
        self.assertEqual(B.gz(b"x" * 100), B.gz(b"x" * 100))
        self.assertEqual(B.gz(b"abc")[4:8], b"\x00\x00\x00\x00")   # mtime 0

    def test_refusals(self):
        d, P = self.job(12)
        bad = P.copy()
        bad[3, 7] = np.nan
        np.save(d / "preds.npy", bad)
        self.refused("NaN")
        np.save(d / "preds.npy", P[:, :20000])
        self.refused("expected (rows, 20484)")
        np.save(d / "preds.npy", P[:11])
        self.refused("11 preds rows for 12 seconds")
        write_preds(d, self.masks, P)
        rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
        rep["lines"]["hearing"]["raw_z"][4] += 0.01
        (d / "report.json").write_text(json.dumps(rep), encoding="utf-8")
        self.refused("hearing line's within-reel z differs")
        write_preds(d, self.masks, P)
        rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
        rep["masks_version"] = "masks-v2"
        (d / "report.json").write_text(json.dumps(rep), encoding="utf-8")
        self.refused("masks version")
        write_preds(d, self.masks, synthetic_preds(91))
        self.refused("over the 90 s")
        write_preds(d, self.masks, P)
        rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
        rep["job_id"] = "20261001-120000-ffffffff"
        (d / "report.json").write_text(json.dumps(rep), encoding="utf-8")
        self.refused("names another job")
        write_preds(d, self.masks, P)
        (d / "predict_meta.json").write_text(json.dumps({"mock": True}), encoding="utf-8")
        self.refused("mock")
        (d / "predict_meta.json").write_text(json.dumps({"mock": False}), encoding="utf-8")
        for job in ("latest", "../x", JOB + "\n", "20261001-120000-0123ABCD"):
            with self.assertRaises(B.BrainError):
                B.build(job)
        (d / "preds.npy").unlink()
        self.refused("preds.npy not found")
        np.save(d / "preds.npy", P)
        self.assertEqual(B.build(JOB)[0]["precision"], None)

    def test_missing_atlas_or_mesh_refuses(self):
        self.job(12)
        with mock.patch.object(B, "ATLAS_JSON", self.tmp / "nope" / "atlas-v1.json"):
            self.assertIn("run scoring/build_atlas.py", self.refused("atlas-v1.json not found"))
        with mock.patch.object(B, "MESH_NPZ", self.tmp / "nope" / "mesh.npz"):
            self.refused("mesh.npz not found")

    def test_check_asset_refuses_broken_files(self):
        self.job(12)
        _, assets = B.build(JOB)
        fr = assets[f"tribe/{JOB}/frames.i8"].raw
        atl = assets["shared/atlas-v1.bin"].raw
        mesh = assets["shared/fsaverage5-inflated-v1.bin"].raw
        cases = [("frames", b"TBX1" + fr[4:], "magic"), ("frames", fr[:-1], "expected exactly"),
                 ("frames", fr[:16] + b"\x80" + fr[17:], "below -127"), ("atlas", atl[:16] + b"\xb5" + atl[17:], "0..180"),
                 ("mesh", mesh[:16 + 2 * 10242 * 12] + b"\xff\xff" + mesh[16 + 2 * 10242 * 12 + 2:], "face index"),
                 ("frames", B.header("frames", 91, 20484, 127) + bytes(91 * 20484), "1 to 90"),
                 ("atlas", b"TBA1", "header"), ("nope", fr, "not a brain asset kind")]
        for kind, raw, must in cases:
            with self.assertRaises(B.BrainError) as cm:
                B.check_asset(kind, raw)
            self.assertIn(must, str(cm.exception), kind)
        with self.assertRaisesRegex(B.BrainError, "11 rows, the page has 12|12 rows, the page has 11"):
            B.check_asset("frames", fr, rows=11)
        with self.assertRaises(B.BrainError):
            B.pack("frames", "shared/atlas-v1.bin", fr)          # a key of another kind
        with self.assertRaises(B.BrainError):
            B.pack("frames", f"tribe/{JOB}/numbers.csv", fr)     # never a stored CSV

    def test_gunzip_and_stored_problems(self):
        raw = B.header("atlas", 20484, 180, 7) + bytes(2 * 20484)
        a = B.pack("atlas", "shared/atlas-v1.bin", raw)
        self.assertEqual(B.stored_problems(a.key, a.kind, a.mime, a.data, a.raw_bytes, a.hash), ([], raw))
        with self.assertRaisesRegex(B.BrainError, "not gzip"):
            B.gunzip(b"PK\x03\x04")
        with self.assertRaisesRegex(B.BrainError, "over 100 bytes"):
            B.gunzip(B.gz(bytes(10000)), limit=100)
        with self.assertRaisesRegex(B.BrainError, "trailing"):
            B.gunzip(a.data + b"extra")
        probs = B.stored_problems(a.key, "mesh", "text/plain", a.data, a.raw_bytes + 1, "0" * 64)[0]
        text = " ".join(probs)
        for must in ("its key says 'atlas'", "'text/plain'", "hash does not match", "raw_bytes says"):
            self.assertIn(must, text)
        self.assertIn("not a brain asset key", " ".join(B.stored_problems("tribe/x/numbers.csv", "frames", a.mime,
                                                                          a.data, a.raw_bytes, a.hash)[0]))

    def test_page_problems_catch_structure(self):
        self.job(12)
        page, _ = B.build(JOB)
        cases = []
        p = json.loads(json.dumps(page))
        p["areas"]["hcp_left"][3] = p["areas"]["hcp_left"][3][:-1]
        cases.append((p, "/areas/hcp_left: 1 row(s)"))
        p = json.loads(json.dumps(page))
        p["areas"]["lines"]["seeing"].append(0.1)
        cases.append((p, "/areas/lines/seeing"))
        p = json.loads(json.dumps(page))
        p["frames"]["key"] = "tribe/20261002-120000-0123abcd/frames.i8"
        cases.append((p, "nothing spans two jobs"))
        p = json.loads(json.dumps(page))
        p["frames"]["bytes"] -= 20484
        cases.append((p, "/frames/bytes"))
        p = json.loads(json.dumps(page))
        p["atlas"]["order"] = list(reversed(p["atlas"]["order"]))
        cases.append((p, "/atlas/order: differs"))
        p = json.loads(json.dumps(page))
        p["atlas"]["hcp"]["labels"][0], p["atlas"]["hcp"]["labels"][1] = p["atlas"]["hcp"]["labels"][1], \
            p["atlas"]["hcp"]["labels"][0]
        cases.append((p, "/atlas/hcp: differs"))
        for p, must in cases:
            found = B.page_problems(p)
            self.assertTrue(any(must in f for f in found), (must, found))

    def test_synthetic_page_and_fixture_text(self):
        page = B.synthetic_page(list(range(9)))
        contract.check_page("brain", page)
        self.assertEqual(len(page["areas"]["yeo"][0]), 9)
        self.assertEqual(page["frames"]["bytes"], 16 + 9 * 20484)
        self.assertEqual(json.loads(B.fixture_text(page)), page)
        self.assertEqual(B.synthetic_page(list(range(9))), page)
        # every vertex of an area holds its wave, so the area mean is the wave itself
        self.assertNotEqual(page["areas"]["hcp_left"][0], page["areas"]["hcp_right"][0])

    def test_vertices_stays_off_web(self):
        self.job(6)
        for bad in (B.WEB, B.WEB / "public", B.WEB / "fixtures" / "x"):
            with self.assertRaisesRegex(B.BrainError, "web/"):
                B.vertices(JOB, bad, log=lambda *_: None)
        path = B.vertices(JOB, self.tmp / "laptop", log=lambda *_: None)
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], f"# {B.FOOTER_12E}")
        header = next(ln for ln in lines if not ln.startswith("#"))
        self.assertEqual(header, "vertex,hemisphere,area,network,feeds_line,s0,s1,s2,s3,s4,s5")
        self.assertEqual(len([ln for ln in lines if not ln.startswith("#")]), 1 + 20484)
        self.assertEqual(B.main(["vertices", JOB, "--out", str(B.WEB / "out")]), 2)
        self.assertFalse((B.WEB / "out").exists())

    def test_show_prints_sizes_not_values(self):
        _, P = self.job(6)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(B.main(["show", JOB]), 0)
        text = out.getvalue()
        self.assertIn("6 rows", text)
        self.assertIn("frames", text)
        self.assertNotIn(str(round(float(P[0, 0]), 4)), text)
        self.assertEqual(B.main(["show", "not-a-job"]), 2)


class TestContractFile(unittest.TestCase):
    def test_contract_and_footer(self):
        c = B.contract()
        self.assertEqual(B.raw_size("frames", 54), 1106152)
        self.assertEqual(B.raw_size("mesh"), c["kinds"]["mesh"]["raw_bytes"])
        self.assertEqual(B.raw_size("atlas"), c["kinds"]["atlas"]["raw_bytes"])
        self.assertLessEqual(B.raw_size("frames", c["rows_max"]), c["raw_bytes"]["max"])
        good = {f"tribe/{JOB}/frames.i8": "frames", "shared/fsaverage5-inflated-v1.bin": "mesh",
                "shared/atlas-v1.bin": "atlas", "shared/atlas-v12.bin": "atlas"}
        for key, kind in good.items():
            self.assertEqual(B.kind_of(key), kind)
        for key in (f"tribe/{JOB}/numbers.csv", f"tribe/{JOB}/peak.png", "shared/atlas-v1.bin\n",
                    "shared/atlas-v1000.bin", "tribe/20261001-120000-0123ABCD/frames.i8", "../shared/atlas-v1.bin",
                    "shared/fsaverage5-pial-v1.bin", f"tribe/{JOB}/{JOB}/frames.i8"):
            self.assertIsNone(B.kind_of(key), key)
        licence = (PROJECT_ROOT / "docs" / "LICENCE.md").read_text(encoding="utf-8")
        section = licence[licence.index("### E. Report footer"):]
        self.assertEqual(B.FOOTER_12E, section.split("```")[1].strip())

    def test_schema_codes_are_the_atlas_codes(self):
        codes, yeo = B.schema_codes()
        self.assertEqual(len(codes), 180)
        self.assertEqual(len(yeo), 7)
        if not B.ATLAS_JSON.is_file():
            self.skipTest("scoring/masks/atlas-v1.json missing: run scoring/build_atlas.py")
        atlas = B.load_atlas()
        self.assertEqual(atlas["labels"], codes)
        self.assertEqual(atlas["yeo_labels"], yeo)


# ---------------------------------------------------------------- real data (read-only, in memory)

class RealData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [p.name for p in (B.ATLAS_JSON, B.MESH_NPZ, B.MASKS_JSON) if not p.is_file()]
        jobs = [j for j in REAL_JOBS if (store.OUTPUTS / j / "preds.npy").is_file()]
        if missing or not jobs:
            raise unittest.SkipTest(f"real brain data not on this machine (missing: {missing or 'outputs'})")
        cls.jobs = jobs
        cls.built = {j: B.build(j) for j in jobs}

    def test_sizes_and_rows(self):
        for job, (page, assets) in self.built.items():
            body = json.dumps(page, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            self.assertLessEqual(len(body), 256 * 1024, job)
            fr = assets[page["frames"]["key"]]
            self.assertLess(len(fr.data), 2 * 1024 * 1024, job)
            rep = json.loads((store.OUTPUTS / job / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(page["time_s"], rep["time_s"], job)
            self.assertEqual(B.check_asset("frames", fr.raw)["rows"], len(rep["time_s"]))
            self.assertEqual(B.page_problems(page), [], job)
            contract.check_page("brain", page)
            self.assertTrue(0 < page["scale"]["vmax"] < 10)
            self.assertLessEqual(page["scale"]["clipped_share"], 0.02)

    def test_atlas_reproduces_masks_v1_and_yeo_crosscheck(self):
        atlas = B.load_atlas()
        masks = json.loads(B.MASKS_JSON.read_text(encoding="utf-8"))
        hcp, yeo = atlas["hcp_lookup"], atlas["yeo_lookup"]
        for line, spec in masks["lines"].items():
            ks = [i + 1 for i, ln in enumerate(atlas["line"]) if ln == line]
            self.assertEqual(sorted(atlas["labels"][k - 1] for k in ks), sorted(spec["parcels"]), line)
            self.assertEqual(np.nonzero(np.isin(hcp, ks))[0].tolist(), spec["vertices"], line)
        self.assertEqual(np.nonzero(yeo == 1)[0].tolist(), masks["crosscheck"]["yeo_visual"]["vertices"])
        self.assertEqual(np.nonzero(np.isin(yeo, (3, 4)))[0].tolist(),
                         masks["crosscheck"]["yeo_dorsal_ventral_attention"]["vertices"])
        self.assertEqual((int((hcp[:10242] == 0).sum()), int((hcp[10242:] == 0).sum())), (868, 874))
        self.assertEqual((int((yeo[:10242] == 0).sum()), int((yeo[10242:] == 0).sum())), (888, 881))
        doc = json.loads(B.ATLAS_JSON.read_text(encoding="utf-8"))
        self.assertEqual(doc["masks_version"], masks["version"])
        for name, digest in doc["sha256"].items():
            self.assertEqual(digest, {**masks["atlas"]["hcp_mmp1"]["sha256"], **masks["atlas"]["yeo7"]["sha256"]}[name])

    def test_raw_z_matches_each_report(self):
        s = B.scoring()
        masks = s.load_masks(B.MASKS_JSON)
        for job in self.jobs:
            P = np.load(store.OUTPUTS / job / "preds.npy").astype(np.float64)
            rep = json.loads((store.OUTPUTS / job / "report.json").read_text(encoding="utf-8"))
            for k in B.LINE_KEYS:
                z = s.zscore(P[:, masks["lines"][k]].mean(axis=1))
                self.assertLessEqual(float(np.max(np.abs(z - np.asarray(rep["lines"][k]["raw_z"])))), 2e-3, (job, k))
            page = self.built[job][0]
            for k in B.LINE_KEYS:
                self.assertTrue(np.allclose(page["areas"]["lines"][k], P[:, masks["lines"][k]].mean(axis=1),
                                            atol=1e-4), (job, k))

    def test_only_the_linked_job_is_hosted(self):
        linked = {(r.get("tribe") or {}).get("job_id") for r in store.list_reels() if r.get("tribe")}
        self.assertIn(REAL_LINKED, linked)
        self.assertNotIn("20261008-225213-68b712e3", linked)   # the unlinked bf16 rerun never leaves
        self.assertNotIn("20261008-130514-b670602f", linked)   # Sintel: read-only tests only


if __name__ == "__main__":
    unittest.main(verbosity=2)
