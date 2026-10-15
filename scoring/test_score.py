"""Local tests for scoring/score.py. Run: python scoring/test_score.py
No Modal, no network, no spend. Synthetic data only, except one optional check
against the two saved fixtures in outputs/ (skipped when they are absent)."""

import json
import math
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d

sys.path.insert(0, str(Path(__file__).parent))
import score  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KEYS = score.LINE_KEYS
CONTRACT_KEYS = {
    "framing", "scoring_version", "masks_version", "mock", "job_id", "label", "purpose", "source", "scale",
    "offset", "clip", "warnings", "time_s", "per_second", "lines", "combined", "calibration_only", "hook_0_3s",
    "peaks", "flat_stretches", "words", "word_hits", "stretched_words", "brain_picture", "crosscheck",
    "compare", "raw",
}


def _expect_refused(fn, needle=None):
    try:
        fn()
    except score.ScoreError as e:
        if needle:
            assert needle in str(e), f"expected {needle!r} in {e}"
        return str(e)
    raise AssertionError("expected ScoreError")


def _flat_shape(n, overrides=None):
    """shape_z dict with every line at 0, plus {line: {row: value}} overrides."""
    out = {k: np.zeros(n) for k in KEYS}
    for k, rows in (overrides or {}).items():
        for i, v in rows.items():
            out[k][i] = v
    return out


# ---------------------------------------------------------------- maths

def test_zscore_detrend_and_smoothing():
    x = np.array([1.0, 2.0, 3.0, 4.0, 10.0])
    z = score.zscore(x)
    assert abs(z.mean()) < 1e-12 and abs(z.std() - 1.0) < 1e-12
    assert np.all(score.zscore(np.full(7, 3.3)) == 0), "a constant line must give zeros, not NaN"
    t = np.arange(40.0)
    line = 0.3 * t - 2.0
    assert np.max(np.abs(score.detrend(line, t))) < 1e-9, "detrend removes a straight line exactly"
    wave = np.sin(t / 3.0)
    d = score.detrend(wave + 0.05 * t + 1.0, t)
    slope, _ = score.linear_fit(d, t)
    assert abs(slope) < 1e-9 and abs(d.mean()) < 1e-9
    # Uneven time axis: the fit uses the real start times, not the row number.
    tu = np.array([0.0, 1, 2, 3, 6, 7, 8, 9])
    assert np.max(np.abs(score.detrend(2.0 * tu + 5.0, tu))) < 1e-9
    # Smoothing = gaussian_filter1d(sigma=2, truncate=3, mode reflect): an impulse spreads +/- 6 rows only.
    imp = np.zeros(31)
    imp[15] = 1.0
    s = score.smooth(imp)
    assert np.allclose(s, gaussian_filter1d(imp, sigma=2, truncate=3, mode="reflect"))
    assert s[9] > 0 and s[21] > 0 and s[8] == 0 and s[22] == 0
    edge = np.zeros(20)
    edge[0] = 1.0
    assert np.allclose(score.smooth(edge), gaussian_filter1d(edge, 2, truncate=3, mode="reflect"))
    # shape_z of a ramp plus a bump: the ramp is gone, the bump is the maximum.
    P = np.zeros((40, score.N_VERTICES))
    bump = np.exp(-0.5 * ((t - 20) / 1.5) ** 2)
    P += (0.1 * t + bump)[:, None]
    masks = {k: np.arange(i * 10, i * 10 + 10) for i, k in enumerate(KEYS)}
    lines = score.build_lines(P, masks, t)
    for k in KEYS:
        L = lines[k]
        assert int(np.argmax(L["shape_z"])) == 20
        assert abs(L["shape_z"].mean()) < 1e-9 and abs(L["shape_z"].std() - 1) < 1e-9
        assert abs(L["display_z"].std() - 1) < 1e-9
        assert np.allclose(L["display_z"], score.zscore(score.smooth(L["raw"])))
        assert np.allclose(L["raw_z"], score.zscore(L["raw"]))
        assert L["trend"] == "rising" and L["trend_per_10s"] > 0.2


def test_trend_words():
    assert score.trend_word(0.2) == "flat" and score.trend_word(-0.2) == "flat"
    assert score.trend_word(0.21) == "rising" and score.trend_word(-0.21) == "falling"
    t = np.arange(30.0)
    slope10 = score.linear_fit(0.01 * t, t)[0] * 10
    assert abs(slope10 - 0.1) < 1e-12


def test_calibration_only_lines():
    P = np.zeros((3, score.N_VERTICES))
    P[0] = 2.0
    P[1, ::2] = 1.0
    P[1, 1::2] = -1.0
    P[2] = -P[1]
    rms = score.overall_rms(P)
    assert np.allclose(rms, [2.0, 1.0, 1.0])
    pc = score.pattern_change(P)
    assert pc[0] is None and pc[1] is None, "a constant row has no correlation"
    assert abs(pc[2] - 2.0) < 1e-12, "anti-correlated rows give 1 - (-1) = 2"


# ---------------------------------------------------------------- per-second flags

def test_black_silent_half_second_rule():
    t = np.arange(8.0)
    ranges = [[0.0, 0.5], [1.0, 1.49], [2.6, 3.2], [4.2, 4.5], [4.5, 4.75], [5.0, 5.4], [5.2, 5.45], [6.0, 9.0]]
    got = score.second_flags(t, ranges).tolist()
    assert got == [True, False, False, False, True, False, True, True], got
    assert score.second_flags(t, []).tolist() == [False] * 8
    assert score.second_flags(t, None).tolist() == [False] * 8


def test_edge_and_last_seconds():
    t = np.arange(10.0)
    assert score.edge_flags(t, 10.0).tolist() == [True, True] + [False] * 6 + [True, True]
    assert score.last_seconds(t, 10.0).tolist() == [False] * 8 + [True, True]


# ---------------------------------------------------------------- peaks

def test_peak_threshold_and_local_max():
    n = 30
    t = np.arange(float(n))
    black = np.zeros(n, bool)
    C = np.zeros(n)
    C[5] = 0.99
    C[12], C[13] = 1.0, 0.5
    C[20], C[21] = 1.5, 1.6        # 20 is not a local max (21 is higher)
    peaks = score.pick_peaks(C, t, black, _flat_shape(n), float(n))
    assert [p["t"] for p in peaks] == [21, 12], peaks
    assert peaks[0]["value"] == 1.6 and peaks[1]["value"] == 1.0


def test_peak_spacing_greedy():
    n = 40
    t = np.arange(float(n))
    C = np.zeros(n)
    C[10], C[12], C[14], C[20] = 2.0, 1.5, 1.4, 1.2
    peaks = score.pick_peaks(C, t, np.zeros(n, bool), _flat_shape(n), float(n))
    # 12 is only 2 s from the higher 10; 14 is exactly 4 s away (allowed); 20 is fine.
    assert [p["t"] for p in peaks] == [10, 14, 20], peaks
    C2 = np.zeros(n)
    C2[10], C2[13], C2[17] = 2.0, 1.5, 1.4   # 13 is 3 s from a higher peak: dropped
    p2 = score.pick_peaks(C2, t, np.zeros(n, bool), _flat_shape(n), float(n))
    assert [p["t"] for p in p2] == [10, 17], p2


def test_peak_black_and_last_two_seconds_excluded():
    n = 30
    t = np.arange(float(n))
    C = np.zeros(n)
    C[8] = 3.0      # black second: excluded
    C[28] = 2.5     # in the last 2 s: excluded
    C[29] = 2.0     # in the last 2 s: excluded
    C[24] = 1.1     # allowed (t_end - 3 is not in the last 2 s)
    black = np.zeros(n, bool)
    black[8] = True
    peaks = score.pick_peaks(C, t, black, _flat_shape(n), float(n))
    assert [p["t"] for p in peaks] == [24], peaks
    # The shoulder next to an excluded black maximum is not a local max (neighbours are compared as they are).
    C2 = np.zeros(n)
    C2[8], C2[9], C2[10] = 3.0, 1.5, 0.2
    p2 = score.pick_peaks(C2, t, black, _flat_shape(n), float(n))
    assert p2 == [], p2
    C3 = np.zeros(n)
    C3[6], C3[7], C3[8] = 0.2, 1.5, 3.0
    p3 = score.pick_peaks(C3, t, black, _flat_shape(n), float(n))
    assert p3 == [], p3


def test_peak_top3_edge_flag_and_driving_lines():
    n = 50
    t = np.arange(float(n))
    C = np.zeros(n)
    for i, v in [(1, 1.3), (10, 2.0), (20, 1.9), (30, 1.8), (40, 1.7)]:
        C[i] = v
    shape = _flat_shape(n, {"seeing": {10: 1.0, 1: 2.0}, "hearing": {10: 0.99}, "language": {10: 1.5}})
    peaks = score.pick_peaks(C, t, np.zeros(n, bool), shape, float(n))
    assert [p["t"] for p in peaks] == [10, 20, 30], "top 3 by value, highest first"
    assert peaks[0]["driving_lines"] == ["seeing", "language"]
    assert all(p["edge"] is False for p in peaks)
    C2 = np.zeros(n)
    C2[1], C2[2] = 1.3, 0.0
    C2[25] = 1.2
    p2 = score.pick_peaks(C2, t, np.zeros(n, bool), shape, float(n))
    assert [(p["t"], p["edge"]) for p in p2] == [(1, True), (25, False)]
    assert p2[0]["driving_lines"] == ["seeing"]


# ---------------------------------------------------------------- flat stretches

def test_flat_threshold_and_minimum_length():
    n = 40
    t = np.arange(float(n))
    C = np.zeros(n)
    C[5:8] = -1.5          # 3 s: too short
    C[12:16] = -1.0        # exactly 4 s at exactly -1.0: kept
    C[22:28] = -0.99       # not low enough
    flats = score.find_flats(C, t, np.zeros(n, bool), _flat_shape(n), float(n))
    assert [(f["start"], f["end"]) for f in flats] == [(12, 16)], flats
    f = flats[0]
    assert f["mean"] == -1.0 and f["strong"] is None and f["edge"] is False and f["overlaps_black"] is False


def test_flat_merge_gap():
    n = 40
    t = np.arange(float(n))
    C = np.zeros(n)
    C[10:12] = -2.0
    C[13:15] = -2.0        # gap of 1 s (row 12): merged into [10, 15)
    C[20:22] = -2.0
    C[24:26] = -2.0        # gap of 2 s: not merged, each too short
    flats = score.find_flats(C, t, np.zeros(n, bool), _flat_shape(n), float(n))
    assert [(f["start"], f["end"]) for f in flats] == [(10, 15)], flats
    assert abs(flats[0]["mean"] - (-8.0 / 5)) < 1e-9, "mean covers the merged gap second too"


def test_flat_edge_black_and_driving_lines():
    n = 30
    t = np.arange(float(n))
    C = np.zeros(n)
    C[1:5] = -1.2          # touches the first 2 s
    C[10:14] = -1.2        # middle, overlaps a black second
    C[24:28] = -1.2        # ends at 28 = t_end - 2: does not touch the last 2 s
    C2 = np.zeros(n)
    C2[25:29] = -1.2       # ends at 29: touches the last 2 s
    black = np.zeros(n, bool)
    black[12] = True
    shape = _flat_shape(n, {"hearing": {i: -1.5 for i in range(10, 14)},
                            "language": {10: -1.5, 11: -0.5, 12: -0.5, 13: -0.5}})
    flats = score.find_flats(C, t, black, shape, float(n))
    got = [(f["start"], f["end"], f["edge"], f["overlaps_black"]) for f in flats]
    assert got == [(1, 5, True, False), (10, 14, False, True), (24, 28, False, False)], got
    assert flats[1]["driving_lines"] == ["hearing"], flats[1]
    f2 = score.find_flats(C2, t, black, shape, float(n))
    assert [(f["start"], f["end"], f["edge"]) for f in f2] == [(25, 29, True)]


def test_flat_driving_line_mean_rule():
    n = 20
    t = np.arange(float(n))
    C = np.zeros(n)
    C[6:10] = -1.5
    shape = _flat_shape(n, {"seeing": {6: -2.0, 7: -1.0, 8: -0.5, 9: -0.5},     # mean -1.0: drives
                            "attention": {6: -2.0, 7: -1.0, 8: -0.5, 9: -0.4}})  # mean -0.975: does not
    flats = score.find_flats(C, t, np.zeros(n, bool), shape, float(n))
    assert flats[0]["driving_lines"] == ["seeing"], flats


# ---------------------------------------------------------------- words

def test_word_row_mapping():
    starts = np.arange(20.0)
    stops = starts + 1.0
    assert score.word_rows(12.8, 13.0, starts, stops) == [12], "ending on a row boundary stays in that row"
    assert score.word_rows(12.9, 13.2, starts, stops) == [12, 13]
    assert score.word_rows(13.0, 13.0, starts, stops) == [13], "zero-length word maps to the row holding its start"
    assert score.word_rows(4.5, 4.5, starts, stops) == [4]
    assert score.word_rows(25.0, 25.4, starts, stops) == [], "word after the last row maps to nothing"
    assert score.word_rows(3.2, 6.1, starts, stops) == [3, 4, 5, 6]


def test_ghost_and_stretched_rules():
    silent = score._merge_ranges([[10.0, 11.0]])
    assert score.is_ghost(10.5, 11.5, silent) is True, "exactly 50% inside silence is a ghost"
    assert score.is_ghost(10.6, 11.6, silent) is False, "40% inside is not"
    assert score.is_ghost(10.2, 10.2, silent) is True and score.is_ghost(12.0, 12.0, silent) is False
    assert score.is_stretched(1.0) and score.is_stretched(0.9999999999) and not score.is_stretched(0.99)


def _mapped(rows_z, word_specs, silent=None):
    """Build mapped words from (text, start, stop) specs against a 1-row-per-second language line."""
    n = len(rows_z)
    starts = np.arange(float(n))
    words = [{"text": a, "start": s, "stop": e, "duration": e - s} for a, s, e in word_specs]
    return score.map_words(words, starts, starts + 1.0, np.asarray(rows_z, float), silent or [])


def test_lang_z_is_max_over_rows():
    z = [0.0] * 10
    z[3], z[4] = 0.5, 1.7
    m = _mapped(z, [("a", 3.5, 4.2), ("b", 3.1, 3.4)])
    assert m[0]["rows"] == [3, 4] and m[0]["lang_z"] == 1.7
    assert m[1]["rows"] == [3] and m[1]["lang_z"] == 0.5


def test_phrase_joining_and_top5():
    z = [0.0] * 30
    for i in (5, 6, 8, 12, 15, 18, 21, 24, 27):
        z[i] = 1.0 + i / 100.0
    z[12] = 3.0
    m = _mapped(z, [
        ("one", 5.1, 5.3), ("two", 5.4, 5.6), ("three", 6.2, 6.4),   # rows 5, 5, 6: one phrase
        ("four", 8.1, 8.3),                                          # row 8 > 6 + 1: new phrase
        ("low", 9.1, 9.3),
        ("five", 12.1, 12.3),
        ("six", 15.1, 15.3), ("seven", 18.1, 18.3), ("eight", 21.1, 21.3), ("nine", 24.1, 24.3),
        ("ten", 27.1, 27.3),
    ])
    hits = score.word_hits(m)
    assert len(hits) == 5, "top 5 only"
    assert hits[0]["phrase"] == "five" and hits[0]["value"] == 3.0
    assert [h["phrase"] for h in hits[1:]] == ["ten", "nine", "eight", "seven"], hits
    assert all(h["ghost_flag"] is False for h in hits)
    all_hits = score.word_hits(m[:5])
    assert [h["phrase"] for h in all_hits] == ["four", "one two three"], all_hits
    one = [h for h in all_hits if h["phrase"] == "one two three"][0]
    assert one["start"] == 5.1 and one["end"] == 6.4 and one["value"] == 1.06


def test_non_candidate_word_breaks_a_phrase():
    z = [0.0] * 10
    z[3] = 2.0
    m = _mapped(z, [("a", 3.0, 3.2), ("stretchy", 3.2, 4.4), ("b", 3.5, 3.6)])
    assert m[1]["stretched"] is True
    hits = score.word_hits(m)
    assert sorted(h["phrase"] for h in hits) == ["a", "b"], "a phrase never skips a word"


def test_ghost_and_stretched_words_are_never_hits():
    z = [0.0] * 10
    z[2], z[5] = 2.5, 2.5
    m = _mapped(z, [("ghost", 2.1, 2.5), ("long", 5.0, 6.2), ("real", 5.3, 5.5)], silent=[[2.0, 3.0]])
    assert m[0]["ghost"] is True and m[1]["stretched"] is True
    hits = score.word_hits(m)
    assert [h["phrase"] for h in hits] == ["real"], hits


def test_low_words_are_not_hits():
    m = _mapped([0.99] * 5, [("a", 1.0, 1.2)])
    assert score.word_hits(m) == []


# ---------------------------------------------------------------- whole run on a synthetic folder

def _write_fixture(folder, *, rows=30, mock=False, preds=None, starts=None, analysed_s=None, words=None,
                   silent=None, black=None, flags_extra=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    if preds is None:
        t = np.arange(rows, dtype=float)
        base = np.exp(-0.5 * ((t - 15) / 1.2) ** 2) - 1.2 * ((t >= 21) & (t <= 26))
        preds = (rng.normal(0, 0.01, (rows, score.N_VERTICES)) + base[:, None]).astype(np.float32)
    np.save(folder / "preds.npy", preds)
    rows = preds.shape[0] if preds.ndim == 2 else rows
    starts = list(range(rows)) if starts is None else starts
    segs = [{"row": i, "start": float(s), "stop": float(s) + 1.0, "duration": 1.0} for i, s in enumerate(starts)]
    (folder / "segments.json").write_text(json.dumps(segs), encoding="utf-8")
    if words is None:
        words = [{"text": "hello", "start": 15.1, "duration": 0.3, "stop": 15.4},
                 {"text": "there", "start": 15.5, "duration": 0.3, "stop": 15.8},
                 {"text": "ghostly", "start": 16.1, "duration": 0.4, "stop": 16.5},
                 {"text": "long", "start": 17.0, "duration": 1.2, "stop": 18.2}]
    (folder / "events.json").write_text(json.dumps({"words": words}), encoding="utf-8")
    flags = {"job_id": folder.name, "analysed_s": float(rows if analysed_s is None else analysed_s),
             "original": {"has_audio": True, "sha256": "abc"},
             "silent_ranges": [[16.0, 17.0]] if silent is None else silent,
             "black_ranges": [[3.0, 4.0]] if black is None else black,
             "trimmed": False, "short_clip_warning": False, "audio_added_silent": False, "tonemapped": False,
             "language_assumed": "english"}
    flags.update(flags_extra or {})
    (folder / "flags.json").write_text(json.dumps(flags), encoding="utf-8")
    meta = {"job_id": folder.name, "framing": "predicted average-brain response"}
    if mock is not None:
        meta["mock"] = mock
    (folder / "predict_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (folder / "source.json").write_text(json.dumps({"label": "synthetic", "local_path": "", "source_url": "",
                                                    "owner": "test", "sha256": "abc"}), encoding="utf-8")
    return folder


def test_refuses_mock_nan_and_wrong_width():
    quiet = lambda *a, **k: None  # noqa: E731
    with tempfile.TemporaryDirectory() as root:
        for i, value in enumerate([True, None, "false", 0, "no"]):
            d = _write_fixture(Path(root) / f"mock{i}", mock=value)
            _expect_refused(lambda: score.score_dir(d, picture=False, log=quiet), "mock")
            assert not (d / "report.json").exists(), "a refused run must not write a report"
        nan = np.zeros((20, score.N_VERTICES), np.float32)
        nan[3, 100] = np.nan
        d = _write_fixture(Path(root) / "nan", preds=nan)
        _expect_refused(lambda: score.score_dir(d, picture=False, log=quiet), "NaN")
        inf = np.zeros((20, score.N_VERTICES), np.float32)
        inf[0, 0] = np.inf
        d = _write_fixture(Path(root) / "inf", preds=inf)
        _expect_refused(lambda: score.score_dir(d, picture=False, log=quiet), "inf")
        d = _write_fixture(Path(root) / "width", preds=np.zeros((20, 20483), np.float32))
        _expect_refused(lambda: score.score_dir(d, picture=False, log=quiet), "20484")
        d = _write_fixture(Path(root) / "flat1d", preds=np.zeros(20484, np.float32))
        _expect_refused(lambda: score.score_dir(d, picture=False, log=quiet), "20484")
        d = _write_fixture(Path(root) / "cli", mock=True)
        assert score.main([str(d), "--purpose", "test"]) == 2
        assert not (d / "report.json").exists()
    _expect_refused(lambda: score.check_meta({"mock": False, "x": 1}) or score.check_meta({}), "mock")


def test_end_to_end_synthetic_report():
    with tempfile.TemporaryDirectory() as root:
        d = _write_fixture(Path(root) / "job-synth")
        rep = score.score_dir(d, purpose="test", picture=score.MESH_NPZ.exists(), log=lambda *a, **k: None)
        on_disk = json.loads((d / "report.json").read_text(encoding="utf-8"))
        assert on_disk == json.loads(json.dumps(rep)), "report.json matches the returned report"
        assert set(rep) == CONTRACT_KEYS, set(rep) ^ CONTRACT_KEYS
        assert rep["framing"] == "predicted average-brain response" and rep["mock"] is False
        assert rep["scale"] == {"mode": "within-reel", "ref_version": None,
                                "label": "relative to this reel's own average"}
        assert rep["clip"] == {"seconds": 30.0, "rows": 30, "language": "english (assumed)"}
        assert len(rep["time_s"]) == len(rep["per_second"]) == 30
        for k in KEYS:
            L = rep["lines"][k]
            assert set(L) == {"label", "raw_z", "display_z", "shape_z", "shared", "trend_per_10s", "trend",
                              "trend_scale"}
            assert L["shared"] is None and L["trend_scale"] == "within-reel" and L["label"] == score.LINE_LABELS[k]
            assert all(len(L[f]) == 30 for f in ("raw_z", "display_z", "shape_z"))
        comb = rep["combined"]["shape_z"]
        avg = np.mean([rep["lines"][k]["shape_z"] for k in KEYS], axis=0)
        assert np.allclose(comb, avg, atol=1e-3)
        assert rep["calibration_only"]["pattern_change"][0] is None
        assert len(rep["calibration_only"]["overall_rms"]) == 30
        assert rep["hook_0_3s"]["rows"] == [0, 1, 2] and rep["hook_0_3s"]["scale"] == "within-reel"
        ps = rep["per_second"]
        assert [p["t"] for p in ps if p["black"]] == [3]
        assert [p["t"] for p in ps if p["silent"]] == [16]
        assert [p["t"] for p in ps if p["edge"]] == [0, 1, 28, 29]
        assert [p["t"] for p in ps if p["hook"]] == [0, 1, 2]
        assert rep["peaks"] and rep["peaks"][0]["t"] == 15, rep["peaks"]
        assert any(f["start"] <= 23 < f["end"] for f in rep["flat_stretches"]), rep["flat_stretches"]
        words = {w["text"]: w for w in rep["words"]}
        assert words["ghostly"]["ghost"] and words["long"]["stretched"] and not words["hello"]["ghost"]
        assert [h["phrase"] for h in rep["word_hits"]] == ["hello there"], rep["word_hits"]
        assert rep["stretched_words"] == [{"text": "long", "start": 17.0, "stop": 18.2}]
        codes = [w["code"] for w in rep["warnings"]]
        for c in ("test_only", "ghost_words", "black_frames", "english_assumed", "timing_untested"):
            assert c in codes, codes
        for c in ("short_clip", "rows_mismatch", "segment_steps", "no_words", "trimmed"):
            assert c not in codes, codes
        assert rep["compare"] is None and rep["raw"]["flags"] == "flags.json"
        assert rep["crosscheck"] is not None, "computed when masks-v1.json has no stored result for this job"
        if score.MESH_NPZ.exists():
            bp = rep["brain_picture"]
            assert bp["t"] == 15 and bp["path"] == "peak.png" and bp["sides"] == ["left", "right"]
            assert bp["vmin"] == -bp["vmax"] and bp["vmax"] > 0
            png = d / "peak.png"
            assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and png.stat().st_size < 400 * 1024
        else:
            print("  (mesh file missing: brain picture part skipped)")


def test_brain_picture_speed_and_size():
    if not score.MESH_NPZ.exists():
        print("  (mesh file missing: skipped)")
        return
    mesh = score.load_mesh()
    vals = np.random.default_rng(3).normal(0, 0.2, score.N_VERTICES)
    with tempfile.TemporaryDirectory() as root:
        p = Path(root) / "peak.png"
        t0 = time.perf_counter()
        score.render_brain(vals, mesh, p, float(np.percentile(np.abs(vals), 99)))
        took = time.perf_counter() - t0
        assert took < 2.0, f"brain picture took {took:.2f} s"
        assert p.stat().st_size < 400 * 1024, p.stat().st_size


def test_no_peak_means_no_picture():
    with tempfile.TemporaryDirectory() as root:
        flatp = np.zeros((25, score.N_VERTICES), np.float32)
        d = _write_fixture(Path(root) / "nopeak", preds=flatp, black=[], silent=[])
        (d / "peak.png").write_bytes(b"old")
        rep = score.score_dir(d, picture=True, log=lambda *a, **k: None)
        assert rep["peaks"] == [] and rep["brain_picture"] is None and rep["flat_stretches"] == []
        assert not (d / "peak.png").exists(), "a stale picture is removed"
        assert all(v == 0 for v in rep["lines"]["seeing"]["display_z"]), "constant lines give zeros, not NaN"


def test_warnings_short_clip_rows_steps_no_words():
    with tempfile.TemporaryDirectory() as root:
        rng = np.random.default_rng(1)
        P = rng.normal(0, 0.1, (8, score.N_VERTICES)).astype(np.float32)
        d = _write_fixture(Path(root) / "short", preds=P, analysed_s=7.5, words=[], silent=[], black=[],
                           starts=[0, 1, 2, 4, 5, 6, 7, 8], flags_extra={"trimmed": True, "tonemapped": True,
                                                                         "audio_added_silent": False})
        rep = score.score_dir(d, purpose="edit", picture=False, log=lambda *a, **k: None)
        codes = [w["code"] for w in rep["warnings"]]
        for c in ("short_clip", "segment_steps", "no_words", "trimmed", "tonemapped", "english_assumed",
                  "timing_untested"):
            assert c in codes, codes
        assert "test_only" not in codes and "rows_mismatch" not in codes and "black_frames" not in codes
        assert rep["time_s"] == [0.0, 1.0, 2.0, 4.0, 5.0, 6.0, 7.0, 8.0], "real start times are used"
        assert [p["t"] for p in rep["per_second"]] == [0, 1, 2, 4, 5, 6, 7, 8]
        d2 = _write_fixture(Path(root) / "rows", analysed_s=26.5, silent=[[0.0, 30.0]], words=[])
        codes2 = [w["code"] for w in score.score_dir(d2, picture=False, log=lambda *a, **k: None)["warnings"]]
        assert "rows_mismatch" in codes2 and "no_words" not in codes2, codes2
        d3 = _write_fixture(Path(root) / "silent", words=[], flags_extra={"audio_added_silent": True})
        codes3 = [w["code"] for w in score.score_dir(d3, picture=False, log=lambda *a, **k: None)["warnings"]]
        assert "audio_added_silent" in codes3 and "no_words" not in codes3, codes3


def test_warning_texts_are_clean():
    """Our own warning texts must not use the banned words (CLAUDE.md framing rule)."""
    import re
    banned = re.compile(r"\b(views?|viral|virality|reach|ctr|engagement|emotion(al)?|reward|dopamine|desire|"
                        r"amygdala|nacc|scores?|grade|winner)\b", re.I)
    with tempfile.TemporaryDirectory() as root:
        d = _write_fixture(Path(root) / "w", analysed_s=7.0, flags_extra={"trimmed": True, "tonemapped": True})
        rep = score.score_dir(d, purpose="test", picture=False, log=lambda *a, **k: None)
        texts = [w["text"] for w in rep["warnings"]] + [rep["offset"], rep["combined"]["note"], rep["scale"]["label"]]
        texts += [rep["lines"][k]["label"] for k in KEYS]
        for s in texts:
            assert not banned.search(s), s


# ---------------------------------------------------------------- the saved fixtures (optional)

def test_fixture_crosscheck_matches_stored_values():
    masks = score.load_masks()
    for job, stored in masks["results"].items():
        preds = ROOT / "outputs" / job / "preds.npy"
        if not preds.exists():
            print(f"  ({job} not present: skipped)")
            continue
        P = np.load(preds).astype(np.float64)
        fresh = score.crosscheck(job, P, {**masks, "results": {}})
        for key, _, _ in score.CROSS_PAIRS:
            assert abs(fresh[key] - stored[key]) < 2e-3, (job, key, fresh[key], stored[key])
            assert fresh[key] >= 0.7


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok", name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print("FAIL", name, type(e).__name__, e)
    print(f"{'all passed' if not failed else f'{failed} failed'}")
    sys.exit(1 if failed else 0)
