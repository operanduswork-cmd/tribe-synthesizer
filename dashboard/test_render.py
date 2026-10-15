"""Local tests for the report page renderer. Run: python dashboard/test_render.py
Everything here is clearly synthetic (label "synthetic-test"). No Modal, no network, no spend.
Writes only to temp folders."""

import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import render  # noqa: E402

HERE = Path(__file__).resolve().parent
KEYS = ("seeing", "hearing", "language", "attention")
LABELS = {
    "seeing": "predicted visual response",
    "hearing": "predicted auditory response",
    "language": "predicted language response",
    "attention": "predicted attention-network response",
}
ROWS = 30
SCALE_LABEL = "relative to this reel's own average"


def _wave(phase, freq=0.35, amp=1.3):
    return [round(amp * math.sin(i * freq + phase), 4) for i in range(ROWS)]


def make_report(**over):
    lines = {}
    for i, k in enumerate(KEYS):
        disp = _wave(i * 0.9)
        lines[k] = {
            "label": LABELS[k], "raw_z": _wave(i * 0.9 + 0.2, 0.4), "display_z": disp,
            "shape_z": disp, "shared": None, "trend_per_10s": 0.05, "trend": "flat",
            "trend_scale": "within-reel",
        }
    combined = [round(sum(lines[k]["shape_z"][t] for k in KEYS) / 4, 4) for t in range(ROWS)]
    words = [
        {"text": "hello", "start": 0.4, "stop": 0.8, "rows": [0], "lang_z": 0.2, "ghost": True, "stretched": False},
        {"text": "post", "start": 8.1, "stop": 8.4, "rows": [8], "lang_z": 1.4, "ghost": False, "stretched": False},
        {"text": "it", "start": 8.45, "stop": 8.6, "rows": [8], "lang_z": 1.4, "ghost": False, "stretched": False},
        {"text": "POST", "start": 8.7, "stop": 9.2, "rows": [8, 9], "lang_z": 1.5, "ghost": False, "stretched": False},
        {"text": "</script><b>x</b>", "start": 14.0, "stop": 14.3, "rows": [14], "lang_z": 0.1, "ghost": False, "stretched": False},
        {"text": "slowly", "start": 18.0, "stop": 19.4, "rows": [18, 19], "lang_z": 1.2, "ghost": False, "stretched": True},
        {"text": "today", "start": 22.2, "stop": 22.6, "rows": [22], "lang_z": 1.1, "ghost": False, "stretched": False},
    ]
    report = {
        "framing": "predicted average-brain response", "scoring_version": "0.1", "masks_version": "masks-v1",
        "mock": False, "job_id": "synthetic-0000", "label": "synthetic-test", "purpose": "test",
        "source": {"local_path": "", "source_url": "", "owner": "synthetic test data (not a real reel)",
                   "fetched_via": "synthetic", "sha256": "0" * 64},
        "scale": {"mode": "within-reel", "ref_version": None, "label": SCALE_LABEL},
        "offset": "model-aligned, no extra shift (one-time timing test not run yet)",
        "clip": {"seconds": 29.6, "rows": ROWS, "language": "english (assumed)"},
        "warnings": [
            {"code": "timing_untested", "text": "timing not yet tested"},
            {"code": "english_assumed", "text": "English assumed"},
            {"code": "ghost_words", "text": "possible ghost words at 0:00"},
            {"code": "test_only", "text": "test reel: not for calibration"},
        ],
        "time_s": [float(t) for t in range(ROWS)],
        "per_second": [
            {"t": t, "black": t in (5, 6), "silent": t in (0, 27, 28), "edge": t < 2 or t >= ROWS - 2, "hook": t < 3}
            for t in range(ROWS)
        ],
        "lines": lines,
        "combined": {"shape_z": combined, "shared": None, "note": "locates moments only, not a rating"},
        "calibration_only": {"overall_rms": [1.0] * ROWS, "pattern_change": [None] + [0.1] * (ROWS - 1)},
        "hook_0_3s": {"scale": "within-reel", "rows": [0, 1, 2], "seeing": 0.7, "hearing": -0.2, "language": -1.1, "attention": 0.1},
        "peaks": [
            {"t": 12, "value": 1.6, "driving_lines": ["seeing", "attention"], "edge": False},
            {"t": 4, "value": 1.1, "driving_lines": ["hearing"], "edge": False},
        ],
        "flat_stretches": [
            {"start": 20, "end": 25, "mean": -1.3, "driving_lines": ["language"], "strong": None, "edge": False, "overlaps_black": False},
        ],
        "words": words,
        "word_hits": [
            {"phrase": "post it POST", "start": 8.1, "end": 9.2, "value": 1.5, "ghost_flag": False},
            {"phrase": "today", "start": 22.2, "end": 22.6, "value": 1.1, "ghost_flag": False},
        ],
        "stretched_words": [{"text": "slowly", "start": 18.0, "stop": 19.4}],
        "brain_picture": {"t": 12, "path": "peak.png", "vmin": 0.0, "vmax": 1.0, "sides": ["left", "right"]},
        "crosscheck": None,
        "compare": None,
        "raw": {"preds": "preds.npy", "segments": "segments.json", "events": "events.json", "flags": "flags.json"},
    }
    report.update(over)
    return report


def make_notes(**over):
    notes = {
        "job_id": "synthetic-0000", "author": "Claude", "scale_label": SCALE_LABEL,
        "notes": [
            {"id": "n1", "kind": "summary", "t_start": 0, "t_end": 29.6, "lines": ["combined"],
             "text": "0:00-0:29 (synthetic test). Dips and peaks here are relative to this reel's own average until a reference of your reels exists. The model predicts an average brain, not your audience: a second opinion next to your real retention graph.",
             "idea_to_test": None},
            {"id": "n2", "kind": "hook", "t_start": 0, "t_end": 3, "lines": ["seeing", "language"],
             "text": "0:00-0:02 (first 3 s): the seeing line starts above this reel's average while language starts below it. Only 3 points, edge seconds.",
             "idea_to_test": "Test: in your draft, say the first line of speech a second earlier."},
            {"id": "n3", "kind": "peak", "t_start": 12, "t_end": 13, "lines": ["seeing", "attention"],
             "text": "0:12: seeing and attention network lines are high for this reel.",
             "idea_to_test": "Test: in your draft, hold the main shot a beat longer in one cut and compare retention."},
            {"id": "n4", "kind": "flat", "t_start": 20, "t_end": 25, "lines": ["language"],
             "text": "0:20-0:24: the language line sits low for this reel. Not tested against retention.",
             "idea_to_test": "Test: in your draft, tighten any long stretch with no new picture."},
            {"id": "n5", "kind": "word", "t_start": 8, "t_end": 10, "lines": ["language"],
             "text": "0:08-0:09: the language line was high in the second this phrase was said.",
             "idea_to_test": None},
        ],
    }
    notes.update(over)
    return notes


def _tiny_png():
    w, h = 4, 2
    raw = b"".join(b"\x00" + bytes([200, 120, 40] * w) for _ in range(h))

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_fixture(root, report=None, notes="default", with_png=True, predict_meta=None):
    out = Path(root) / "outputs" / "synthetic-0000"
    out.mkdir(parents=True, exist_ok=True)
    report = report if report is not None else make_report()
    (out / "report.json").write_text(json.dumps(report), encoding="utf-8")
    if notes == "default":
        notes = make_notes()
    if notes is not None:
        (out / "notes.json").write_text(json.dumps(notes), encoding="utf-8")
    segs = [{"row": t, "start": float(t), "stop": float(t + 1), "duration": 1.0, "words": []} for t in range(ROWS)]
    (out / "segments.json").write_text(json.dumps(segs), encoding="utf-8")
    (out / "flags.json").write_text(json.dumps({"job_id": "synthetic-0000", "silent_ranges": [[0.0, 0.9]], "black_ranges": [[5.0, 7.0]], "analysed_s": 29.6}), encoding="utf-8")
    (out / "source.json").write_text(json.dumps({"job_id": "synthetic-0000", "label": "synthetic-test", "local_path": report["source"]["local_path"], "source_url": report["source"]["source_url"], "owner": report["source"]["owner"]}), encoding="utf-8")
    if predict_meta is not None:
        (out / "predict_meta.json").write_text(json.dumps(predict_meta), encoding="utf-8")
    if with_png:
        (out / "peak.png").write_bytes(_tiny_png())
    return out


def _render(out, root):
    return render.render(out, reports_root=Path(root) / "reports", log=lambda *a: None, swipe_root=Path(root) / "swipe")


def _expect_refused(fn, must_contain=None):
    try:
        fn()
    except render.RenderError as e:
        msg = str(e)
        if must_contain:
            assert must_contain.lower() in msg.lower(), f"refusal message lacks {must_contain!r}: {msg}"
        return msg
    raise AssertionError("expected RenderError")


def _json_blocks(html):
    return re.findall(r'<script type="application/json" id="([^"]+)">(.*?)</script>', html, re.S)


def _strip_data(html):
    """Drop the inlined JSON blocks (transcript is exempt) and data URIs before scanning our text."""
    html = re.sub(r'<script type="application/json"[^>]*>.*?</script>', "", html, flags=re.S)
    return re.sub(r"data:[a-z/+.-]+;base64,[A-Za-z0-9+/=]+", "", html)


def _main_script(html):
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(scripts) == 1, f"expected one inline code script, found {len(scripts)}"
    return scripts[0]


# ---------------------------------------------------------------- tests

def test_render_succeeds():
    with tempfile.TemporaryDirectory() as root:
        out = _render(make_fixture(root), root)
        assert out.exists() and out.name == "report.html"
        assert re.search(r"reports[\\/]\d{4}-\d{2}-\d{2}-synthetic-test[\\/]report\.html$", str(out)), out
        html = out.read_text(encoding="utf-8")
        assert "<title>Predicted response report</title>" in html
        assert "Predicted average-brain response, second by second. An average brain, not your audience." in html
        # plan (8 Oct): calibration is on hold, so the Trust 0/20 line is gone
        assert "Dips not yet tested against your retention" not in html and "0/20 reels" not in html
        assert "CC BY-NC 4.0" in html and "Built with Llama" in html and "TRIBE v2" in html
        ids = [i for i, _ in _json_blocks(html)]
        assert ids == ["data-report", "data-notes", "data-segments", "data-flags", "data-source", "data-page"], ids
        for i, body in _json_blocks(html):
            json.loads(body)  # every block parses
        page = json.loads(dict(_json_blocks(html))["data-page"])
        assert page["brain_img"].startswith("data:image/png;base64,")
        assert page["video_uri"] is None and page["no_video"]["text"].startswith("Video not kept on this laptop")
        assert "__REPORT_JSON__" not in html and "__PAGE_JSON__" not in html


def test_no_external_loads():
    with tempfile.TemporaryDirectory() as root:
        html = _render(make_fixture(root), root).read_text(encoding="utf-8")
        body = re.sub(r'<script type="application/json"[^>]*>.*?</script>', "", html, flags=re.S)
        for m in re.finditer(r"<([a-zA-Z][\w-]*)\b([^>]*)>", body):
            tag, attrs = m.group(1).lower(), m.group(2)
            for am in re.finditer(r"\b(src|href|srcset|poster|action|formaction|data|xlink:href)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", attrs, re.I):
                attr, val = am.group(1).lower(), am.group(2).strip("\"'")
                if attr == "href" and tag == "a":
                    assert val.startswith(("https://", "#")), f"odd link {val}"
                    continue
                assert attr == "src" and val.startswith("data:"), f"<{tag} {attr}={val}> would load something"
        low = body.lower()
        for bad in ("<link", "@import", "url(http", "url(//", "fetch(", "xmlhttprequest", "<iframe", "import(",
                    "<script src", "new worker", "eventsource", "websocket", "sendbeacon", "<object", "<embed"):
            assert bad not in low, f"found {bad!r} in the page"
        assert "Content-Security-Policy" in html and "default-src 'none'" in html


def test_banned_word_in_note_refused():
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][2]["text"] = "0:12: this moment could go viral."
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "viral")
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][3]["idea_to_test"] = "Test: check the Score here."
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "score")
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][2]["text"] = "0:12: POST this version."
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "POST")
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][2]["text"] = "0:12: rates 85/100 here."
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "100")


def test_banned_word_in_warning_or_label_refused():
    with tempfile.TemporaryDirectory() as root:
        rep = make_report()
        rep["warnings"].append({"code": "short_clip", "text": "low engagement expected"})
        _expect_refused(lambda: _render(make_fixture(root, report=rep), root), "engagement")
    with tempfile.TemporaryDirectory() as root:
        rep = make_report()
        rep["lines"]["seeing"]["label"] = "predicted reward response"
        _expect_refused(lambda: _render(make_fixture(root, report=rep), root), "reward")


def test_mock_true_refused():
    with tempfile.TemporaryDirectory() as root:
        _expect_refused(lambda: _render(make_fixture(root, report=make_report(mock=True)), root), "mock")
    with tempfile.TemporaryDirectory() as root:
        rep = make_report()
        del rep["mock"]
        _expect_refused(lambda: _render(make_fixture(root, report=rep), root), "mock")
    with tempfile.TemporaryDirectory() as root:
        out = make_fixture(root, predict_meta={"mock": True})
        _expect_refused(lambda: _render(out, root), "mock")


def test_note_without_lines_refused():
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][2]["lines"] = []
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "line")
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        del notes["notes"][2]["lines"]
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "line")
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][2]["lines"] = ["amygdala_line"]
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root))


def test_notes_contract_refusals():
    cases = []
    n = make_notes(); n["notes"] = n["notes"][:3]; cases.append(("4 to 10", n))
    n = make_notes(); n["notes"] = [x for x in n["notes"] if x["kind"] != "summary"] + [dict(make_notes()["notes"][2], id="n9")]; cases.append(("summary", n))
    n = make_notes(); n["notes"][1]["idea_to_test"] = "Cut the intro."; cases.append(("Test:", n))
    n = make_notes(); n["notes"][2]["t_start"] = 13; cases.append(("t_start < t_end", n))
    n = make_notes(); n["notes"][3]["t_end"] = 45; cases.append(("inside the clip", n))
    n = make_notes(); n["notes"][2]["text"] = "Seeing is high here."; cases.append(("m:ss", n))
    n = make_notes(); n["notes"][2]["text"] = "0:12 " + "x" * 330; cases.append(("max 320", n))
    n = make_notes(); n["notes"][0]["text"] = "0:00-0:29: overall the lines move a lot."; cases.append(("own average", n))
    n = make_notes(job_id="other-job"); cases.append(("job_id", n))
    for must, notes in cases:
        with tempfile.TemporaryDirectory() as root:
            _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), must)
    with tempfile.TemporaryDirectory() as root:
        _expect_refused(lambda: _render(make_fixture(root, notes=None), root), "notes.json is missing")


def test_transcript_post_allowed():
    with tempfile.TemporaryDirectory() as root:
        rep = make_report()
        assert any(w["text"] == "POST" for w in rep["words"]) and any(w["text"] == "post" for w in rep["words"])
        assert "POST" in rep["word_hits"][0]["phrase"]
        html = _render(make_fixture(root, report=rep), root).read_text(encoding="utf-8")
        report_block = dict(_json_blocks(html))["data-report"]
        assert '"post it POST"' in report_block
    # lowercase "post" in our own note is plain English and allowed; uppercase is the verdict word.
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][2]["text"] = "0:12: seeing is high just after the post-roll card."
        _render(make_fixture(root, notes=notes), root)


def test_json_blocks_escape_script_close():
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][4]["text"] = "0:08-0:09: the phrase </script> <!-- is here."
        html = _render(make_fixture(root, notes=notes), root).read_text(encoding="utf-8")
        for i, body in _json_blocks(html):
            assert "</" not in body, f"{i} has an unescaped </"
            assert "<!--" not in body, f"{i} has an unescaped <!--"
        rb = dict(_json_blocks(html))["data-report"]
        assert "<\\/script><b>x<\\/b>" in rb
        assert json.loads(rb)["words"][4]["text"] == "</script><b>x</b>"
        nb = json.loads(dict(_json_blocks(html))["data-notes"])
        assert "</script> <!--" in nb["notes"][4]["text"]
        # Only the six data blocks and one code script close.
        assert html.count("</script>") == 7


def test_nan_refused():
    with tempfile.TemporaryDirectory() as root:
        rep = make_report()
        rep["lines"]["seeing"]["display_z"][3] = float("nan")
        _expect_refused(lambda: _render(make_fixture(root, report=rep), root), "NaN")


def test_page_text_has_no_banned_words():
    template = render.TEMPLATE_PATH.read_text(encoding="utf-8")
    assert render.find_banned(template) == [], render.find_banned(template)
    with tempfile.TemporaryDirectory() as root:
        html = _render(make_fixture(root), root).read_text(encoding="utf-8")
        assert render.find_banned(_strip_data(html)) == []
    # the scanner itself catches what it should
    for bad in ("views", "Viral", "virality", "reach", "CTR", "watch-time", "will perform", "engagement",
                "emotional", "rewards", "dopamine", "desire", "amygdala", "NAcc", "scores", "grade", "winner",
                "POST", "DEPLOY", "STRONG", "72/100", "0-100"):
        assert render.find_banned(f"a {bad} b"), bad
    for ok in ("view", "post", "strong", "brainscore", "scoring", "gradient", "overview", "preview", "20/20"):
        assert not render.find_banned(f"a {ok} b"), ok


def test_video_and_thumbnails():
    if not shutil.which("ffmpeg"):
        print("skip test_video_and_thumbnails (no ffmpeg)")
        return
    with tempfile.TemporaryDirectory() as root:
        clip = Path(root) / "synthetic clip.mp4"
        r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=30",
                            "-pix_fmt", "yuv420p", str(clip)], capture_output=True, timeout=120)
        assert r.returncode == 0, r.stderr
        rep = make_report()
        rep["source"]["local_path"] = str(clip)
        html = _render(make_fixture(root, report=rep), root).read_text(encoding="utf-8")
        page = json.loads(dict(_json_blocks(html))["data-page"])
        assert page["video_uri"].startswith("file:///") and "%20" in page["video_uri"]
        assert page["no_video"] is None
        assert set(page["thumbs"]) == {"peak:12", "peak:4", "flat:20-25"}, page["thumbs"].keys()
        assert all(v.startswith("data:image/jpeg;base64,") for v in page["thumbs"].values())
    with tempfile.TemporaryDirectory() as root:
        rep = make_report()
        rep["source"]["local_path"] = str(Path(root) / "gone.mp4")
        html = _render(make_fixture(root, report=rep), root).read_text(encoding="utf-8")
        page = json.loads(dict(_json_blocks(html))["data-page"])
        assert page["video_uri"] is None and "not found" in page["no_video"]["text"]


def test_other_creator_placeholder():
    with tempfile.TemporaryDirectory() as root:
        rep = make_report()
        rep["source"]["source_url"] = "https://example.com/reel/synthetic"
        html = _render(make_fixture(root, report=rep), root).read_text(encoding="utf-8")
        page = json.loads(dict(_json_blocks(html))["data-page"])
        assert page["no_video"]["text"] == "Video not kept on this laptop (another creator's reel). Open the original:"
        assert page["no_video"]["url"] == "https://example.com/reel/synthetic"


def test_page_js_syntax():
    node = shutil.which("node")
    if not node:
        print("skip test_page_js_syntax (no node)")
        return
    with tempfile.TemporaryDirectory() as root:
        html = _render(make_fixture(root), root).read_text(encoding="utf-8")
        js = Path(root) / "page.js"
        js.write_text(_main_script(html), encoding="utf-8")
        r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr


RANGE_CASES = [
    # (a, b, last_sec, expected): closed whole-second ranges, as the clock shows them
    (0, 7, 52, "0:00-0:06"), (9, 12, 52, "0:09-0:11"), (0, 3, 52, "0:00-0:02"), (20, 21, 52, "0:20"),
    (12.23, 14.291, 52, "0:12-0:14"), (18.873, 19.453, 52, "0:18-0:19"), (32.991, 34.051, 53, "0:32-0:34"),
    (37.892, 43.014, 53, "0:37-0:43"), (0, 54, 53, "0:00-0:53"), (50, 54, 53, "0:50-0:53"),
    (14.0, 14.0001, 30, "0:14"), (13.5, 14.0, 30, "0:13"), (0, 29.6, 29, "0:00-0:29"), (40, 99, 52, "0:40-0:52"),
    (59.5, 61.2, 70, "0:59-1:01"),
]


def test_page_range_convention():
    for a, b, last, want in RANGE_CASES:
        assert render.page_range(a, b, last) == want, (a, b, last, render.page_range(a, b, last), want)
    rep = make_report()
    assert render.last_second(rep) == ROWS - 1


def test_page_js_range_matches_python():
    node = shutil.which("node")
    if not node:
        print("skip test_page_js_range_matches_python (no node)")
        return
    tpl = render.TEMPLATE_PATH.read_text(encoding="utf-8")
    clamp = re.search(r"function clamp\(v, a, b\) \{[^\n]*\}", tpl).group(0)
    fmts = tpl[tpl.index("function fmt(t) {"):tpl.index("function band(z)")]
    js = (clamp + "\n" + fmts + "\nvar cases = " + json.dumps(RANGE_CASES) + ";\n"
          "console.log(JSON.stringify(cases.map(function (c) { LAST_SEC = c[2]; return fmtRange(c[0], c[1]); })));\n")
    with tempfile.TemporaryDirectory() as root:
        f = Path(root) / "range.js"
        f.write_text("var LAST_SEC = 0;\n" + js, encoding="utf-8")
        r = subprocess.run([node, str(f)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        got = json.loads(r.stdout)
    assert got == [c[3] for c in RANGE_CASES], got


def test_note_must_mention_its_own_range():
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][3]["text"] = "0:20-0:25: the language line sits low for this reel."  # rows [20, 25) are 0:20-0:24
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "'0:20-0:24'")
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][2]["text"] = "0:11-0:12: seeing is high for this reel."  # peak note [12, 13) is 0:12
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "'0:12'")
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][4].update(t_start=8.1, t_end=9.2, text="Spoken at 0:08-0:09: the language line was high.")
        _render(make_fixture(root, notes=notes), root)


def test_idea_comparing_reels_needs_one_scale():
    bad = [
        "Test: on one of your own reels, open with sound and see if the first 3 seconds sit higher than this.",
        "Test: put a spoken line in the first seconds of a reel of your own and see if the low stretch gets shorter.",
        "Test: two versions of this part, one with a cut and one without, and compare seeing and attention there.",
    ]
    ok = [
        "Test: cut two openings for the same body and compare their first 3 seconds (0:00-0:02) on one scale (A vs B).",
        "Test: hold this shot a beat longer in one cut and compare retention.",
        "Test: in your own reels, put a short pause before a key question and see if the language line rises in that second too.",
    ]
    for idea in bad:
        assert render.idea_needs_one_scale(idea), idea
        with tempfile.TemporaryDirectory() as root:
            notes = make_notes()
            notes["notes"][1]["idea_to_test"] = idea
            _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "one scale")
    for idea in ok:
        assert not render.idea_needs_one_scale(idea), idea


def test_page_fixes_in_template():
    tpl = render.TEMPLATE_PATH.read_text(encoding="utf-8")
    # tab title carries the reel label; the static title stays as the fallback
    assert "document.title = label + ' · Predicted response report';" in tpl
    # "Built with Llama" links to the Llama licence (LICENCE 12A), not the model page
    m = re.search(r'<a href="([^"]+)"[^>]*>Built with Llama</a>', tpl)
    assert m and m.group(1) == "https://www.llama.com/llama3_2/license/", m and m.group(1)
    # word-hit caveats from SCORING 13: captions and lyrics
    assert "on-screen captions are not in this strip" in tpl and "song lyrics count as words" in tpl
    # keyboard scrubbing, moment highlight on every update, playhead capped at the clip end
    assert "scrub.addEventListener('keydown'" in tpl
    assert "lastSec" not in tpl and "lastMoments" in tpl
    assert "scrub.max = String(PLAY_END)" in tpl and "fmt(PLAY_END)" in tpl
    assert "hook window 0:00-0:03" not in tpl and "first 3 seconds (0:00-0:02)" in tpl


def test_cli_exit_codes():
    with tempfile.TemporaryDirectory() as root:
        out = make_fixture(root)
        reports = Path(root) / "reports"
        r = subprocess.run([sys.executable, str(HERE / "render.py"), str(out), "--no-open", "--reports-dir", str(reports)],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()).exists()
    with tempfile.TemporaryDirectory() as root:
        out = make_fixture(root, report=make_report(mock=True))
        r = subprocess.run([sys.executable, str(HERE / "render.py"), str(out), "--no-open", "--reports-dir", str(Path(root) / "reports")],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 2 and "Refused" in r.stderr and "mock" in r.stderr, (r.returncode, r.stderr)


# ---------------------------------------------------------------- the wall and the snippet card (plan 8 Oct)

SC = "SynthTest01"


def make_swipe(root, hook_id="question-then-number-answer", hook_status="suggested", **over):
    """A synthetic swipe/reels/<sc>/reel.json and swipe/creators/<handle>.json (contract shape)."""
    reel = {
        "shortcode": SC, "url": f"https://www.instagram.com/reel/{SC}/", "owner": "synthetic.creator",
        "posted": "2026-09-01", "type": "reel",
        "counts": {"plays": 312098, "likes": 9100, "comments": 240, "as_of": "2026-10-08T10:00:00Z", "as_of_note": None,
                   "source_field": {"plays": "videoPlayCount", "likes": "likesCount", "comments": "commentsCount"}},
        "x": {"plays": 17.84, "likes": 6.1, "comments": 3.2, "vs": "own median"},
        "outlier": True, "flags": {"thin_baseline": False, "paid": False, "gated_cta": False, "fresh": False,
                                   "over_60s": False, "under_2x": False},
        "discount": None,
        "facts": {"duration_s": 29.6, "first_word_s": 0.4, "words_per_s": 2.7, "text_on_screen_0s": True,
                  "cta": {"type": "comment keyword", "t": 26.0}, "source": {}},
        "shape": {"hook_shape": {"id": hook_id, "status": hook_status},
                  "format": {"value": "talking head", "status": "suggested"},
                  "cta": {"value": "comment keyword", "status": "suggested"},
                  "beats": [{"start": 0, "end": 3, "kind": "hook", "name": "question", "status": "suggested"},
                            {"start": 3, "end": 20, "kind": "body", "name": "demo", "status": "accepted"},
                            {"start": 20, "end": 25, "kind": "aside", "name": "dropped idea", "status": "rejected"}]},
        "tribe": {"job_id": "synthetic-0000", "run_date": "2026-10-08", "scale": "within-reel"},
        "imported_from": "synthetic", "added_at": "2026-10-08",
    }
    reel.update(over)
    d = Path(root) / "swipe" / "reels" / SC
    d.mkdir(parents=True, exist_ok=True)
    (d / "reel.json").write_text(json.dumps(reel), encoding="utf-8")
    c = Path(root) / "swipe" / "creators"
    c.mkdir(parents=True, exist_ok=True)
    (c / "synthetic.creator.json").write_text(json.dumps({"handle": "synthetic.creator", "baseline": {"n": 16}}), encoding="utf-8")
    return reel


def _swipe_report():
    rep = make_report()
    rep["source"]["source_url"] = f"https://www.instagram.com/reel/{SC}/"
    return rep


def _good_card():
    rep = make_report()
    return render.build_card(rep, make_notes(), None, [], None)


def _page(html):
    return json.loads(dict(_json_blocks(html))["data-page"])


def test_wall_mixed_layers_refused():
    for bad in ("17.8x own median, and the peak lands at 0:37", "312,098 plays while seeing is high",
                "an outlier with a flat ending", "the median reel has a low hook"):
        _expect_refused(lambda: render.check_mixed_layers([bad]), "wall")
    # the one allow-listed framing sentence, and each layer on its own line, pass
    render.check_mixed_layers([render.WALL_SENTENCE, "17.8x own median (16 reels)", "peak at 0:37, all four lines high"])
    _expect_refused(lambda: render.check_mixed_layers([render.WALL_SENTENCE + " The peak got 17.8x."]), "wall")
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][2]["text"] = "0:12: seeing is high for this reel, and the reel got 17.8x its usual plays."
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "wall")


def test_cause_words_refused():
    for bad in ("plays rose because of the hook", "that's why it got 2x", "which is why the line dips",
                "the open led to more likes", "the cut drove attention", "the music caused it", "this explains the peak"):
        _expect_refused(lambda: render.check_cause(bad), "cause")
    render.check_cause("the language line was high while this was said, nothing more")
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][3]["text"] = "0:20-0:24: the language line sits low because nobody speaks."
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "because")


def test_extended_banned_words_refused():
    for bad in ("performance", "top performing", "top-performing", "proven", "best hook", "Best Hooks", "outperformed",
                "outperforms", "winning", "guaranteed"):
        assert render.find_banned(f"a {bad} b"), bad
    for ok in ("perform a test", "prove nothing", "win", "hook"):
        assert not render.find_banned(f"a {ok} b"), ok
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][1]["idea_to_test"] = "Test: in your draft, use the proven opener."
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "proven")
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        notes["notes"][0]["text"] += " Not a best hook."
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "best hook")


def test_hook_line_names_refused():
    card = _good_card()
    for bad in ("seeing starts high", "language line low at the start", "attention network up", "combined rises"):
        c = json.loads(json.dumps(card))
        c["lines"][0]["text"] = bad
        _expect_refused(lambda: render.validate_card(c), "HOOK")
    # a hook shape tagged with a line name never reaches the card
    with tempfile.TemporaryDirectory() as root:
        make_swipe(root, hook_id="seeing-first-open")
        _expect_refused(lambda: _render(make_fixture(root, report=_swipe_report()), root), "HOOK")


def test_pattern_line_needs_contrast():
    render.check_pattern_line("question hook: outliers 4/6 vs normal 3/20")
    render.check_pattern_line("number list: outliers only, no comparison yet")
    for bad in ("question hook: outliers 4/6", "question hook works in 4 of 6 outliers", "outliers 7/6 vs normal 3/20", ""):
        _expect_refused(lambda: render.check_pattern_line(bad), "pattern line")


def test_sort_key_guard():
    for ok, want in (("x", "x"), ("-x", "-x"), ("plays", "plays"), ("-counts.plays", "-plays"), ("posted", "posted"),
                     ("duration", "duration"), ("handle", "handle")):
        assert render.check_sort_key(ok) == want, ok
    for bad in ("tribe", "tribe.job_id", "tribe.run_date", "peak", "-peaks", "flat_stretches", "hook_0_3s.language",
                "attention", "brain"):
        _expect_refused(lambda: render.check_sort_key(bad), "never sort")
    _expect_refused(lambda: render.check_sort_key("likes"), "unknown sort key")


def test_card_prose_no_decimals():
    assert not render.no_decimals("combined +1.74 at 0:37") and render.no_decimals("peak at 0:37, about 3 words a second")
    card = _good_card()
    card["lines"][1]["text"] = "all four lines high for this reel (combined 1.74)"
    _expect_refused(lambda: render.validate_card(card), "decimals")


def test_creator_pronouns_refused():
    for bad in ("17.8x her median", "his hook", "she opens on a question", "he cuts at 0:03", "a note for him"):
        _expect_refused(lambda: render.check_pronouns(bad), "pronoun")
    render.check_pronouns("17.8x own median: the creator opens on a question, @synthetic.creator")
    card = _good_card()
    card["counts"] = {"text": "@synthetic.creator · 312,098 plays · 17.8x her median"}
    _expect_refused(lambda: render.validate_card(card), "pronoun")


def test_mock_output_refused_even_with_swipe_reel():
    with tempfile.TemporaryDirectory() as root:
        make_swipe(root)
        rep = _swipe_report()
        rep["mock"] = True
        _expect_refused(lambda: _render(make_fixture(root, report=rep), root), "mock")


def test_card_contract_refusals():
    card = _good_card()
    render.validate_card(card)
    assert [ln["tag"] for ln in card["lines"]] == ["HOOK", "HIGH", "FLAT", "TRY", "TRY"]
    cases = []
    c = _good_card(); c["lines"][2]["tag"] = "LOW"; cases.append(("FLAT", c))
    c = _good_card(); c["lines"].pop(); cases.append(("in that order", c))
    c = _good_card(); c["lines"][1]["text"] = "x" * 140; cases.append(("max 140", c))
    c = _good_card(); c["lines"][1]["text"] = "high for this reel, again at 0:20"; cases.append(("one time chip", c))
    c = _good_card(); c["lines"][3]["text"] = "Test: in your draft, cut at " + c["lines"][1]["time"] + "."; cases.append(("each time appears once", c))
    c = _good_card(); c["lines"][3]["text"] = "Cut the intro of your draft."; cases.append(("Test:", c))
    c = _good_card(); c["lines"][3]["text"] = "Test: cut the intro."; cases.append(("your draft", c))
    c = _good_card(); c["lines"][4]["text"] = "Test: in your draft, see if the 3 seconds sit higher than this."; cases.append(("one scale", c))
    c = _good_card(); c["footnote"] = "Predicted response."; cases.append(("footnote", c))
    c = _good_card(); c["lines"][0]["text"] = "Trust: 0/20 reels"; cases.append(("Trust", c))
    c = _good_card(); c["lines"][0]["text"] = "first word spoken · 312,098 plays"; cases.append(("counts strip", c))
    c = _good_card(); c["counts"] = {"text": "@synthetic.creator · 312,098 plays · peak at 0:37"}; cases.append(("counts strip", c))
    c = _good_card(); c["counts"] = {"text": "@synthetic.creator · 312,098 views"}; cases.append(("views", c))
    c = _good_card(); c["lines"][2].update(edge=True, text="language line low for this reel"); cases.append(("lower confidence", c))
    for must, c in cases:
        _expect_refused(lambda: render.validate_card(c), must)


def test_card_lines_from_report():
    card = _good_card()
    by = {ln["tag"]: ln for ln in card["lines"][:3]}
    # HOOK: facts only (first non-ghost word at 8.1 s); an unknown fact is left out, the chip follows "first word at"
    assert by["HOOK"]["time"] == "0:08" and by["HOOK"]["text"] == "hook shape not tagged yet · first word at", by["HOOK"]
    # HIGH: the top peak (0:12, value 1.6), not the first one
    assert by["HIGH"]["time"] == "0:12" and "seeing and attention lines high for this reel" in by["HIGH"]["text"], by["HIGH"]
    assert by["FLAT"]["time"] == "0:20-0:24" and "lower confidence" not in by["FLAT"]["text"]
    assert card["footnote"] == "HIGH/FLAT: predicted average-brain response, vs this reel's own average."
    assert card["counts"] is None
    # TRY lines: Claude's ideas for the top peak and the flat stretch first
    assert [ln["text"] for ln in card["lines"][3:]] == [make_notes()["notes"][2]["idea_to_test"], make_notes()["notes"][3]["idea_to_test"]]
    # HOOK uses events.json words[0].start when there is one
    card2 = render.build_card(make_report(), make_notes(), {"words": [{"text": "Hi", "start": 1.2, "stop": 1.4}]}, [], None)
    assert card2["lines"][0]["time"] == "0:01"
    # an edge flat stretch is marked
    rep = make_report(flat_stretches=[{"start": 26, "end": 30, "mean": -1.4, "driving_lines": ["seeing", "hearing", "language", "attention"],
                                       "strong": None, "edge": True, "overlaps_black": False}])
    flat = render.build_card(rep, make_notes(), None, [], None)["lines"][2]
    assert flat["time"] == "0:26-0:29" and flat["text"].endswith("last 2 s, lower confidence"), flat
    # the HIGH quote is the reel's speech in that second, and dropped when it would break a card rule
    rep = make_report()
    rep["words"].append({"text": "ship", "start": 12.2, "stop": 12.5, "rows": [12], "lang_z": 1.0, "ghost": False, "stretched": False})
    rep["words"].append({"text": "today", "start": 12.6, "stop": 12.9, "rows": [12], "lang_z": 1.0, "ghost": False, "stretched": False})
    assert render.build_card(rep, make_notes(), None, [], None)["lines"][1]["text"].endswith('said: "…ship today…"')
    rep["words"][-1]["text"] = "virality"
    high = render.build_card(rep, make_notes(), None, [], None)["lines"][1]["text"]
    assert "virality" not in high and "said" not in high, high   # one clean word left is no quote (2 or more)


def test_card_needs_two_draft_ideas():
    with tempfile.TemporaryDirectory() as root:
        notes = make_notes()
        for n in notes["notes"][1:]:
            n["idea_to_test"] = None
        notes["notes"][2]["idea_to_test"] = "Test: in your draft, hold the main shot a beat longer."
        _expect_refused(lambda: _render(make_fixture(root, notes=notes), root), "at least 2 idea_to_test")


def test_card_on_top_and_counts_strip_apart():
    tpl = render.TEMPLATE_PATH.read_text(encoding="utf-8")
    # counts strip, then the card, then the folds in the plan's order, then the licence footer
    order = [tpl.index(s) for s in ('id="counts"', 'id="snippet"', 'id="fold-beats"', 'id="fold-hits"', 'id="fold-lanes"',
                                    'id="fold-moments"', 'id="fold-about"', '<footer class="foot">')]
    assert order == sorted(order), order
    assert "Transcript (hits only)" in tpl and "Full lanes" in tpl and "All moments" in tpl and "About this data" in tpl
    assert render.WALL_SENTENCE in tpl and "Trust" not in tpl and "performance.now" not in tpl
    # the framing is said once in our text (About), plus the card footnote and the licence credit
    assert tpl.count("Predicted average-brain response, second by second.") == 1
    with tempfile.TemporaryDirectory() as root:
        make_swipe(root)
        html = _render(make_fixture(root, report=_swipe_report()), root).read_text(encoding="utf-8")
        page = _page(html)
        card = page["card"]
        assert card["counts"]["text"] == ("@synthetic.creator · 0:29 · 312,098 plays · 17.8x own median (16 reels) "
                                          "· as of 2026-10-08"), card["counts"]
        hook = card["lines"][0]
        assert hook["time"] == "0:00" and "question then number answer (suggested)" in hook["text"], hook
        assert "text on screen at start: yes" in hook["text"]
        for ln in card["lines"]:
            assert not render.COUNT_TERMS_RE.search(render.card_line_text(ln)), ln
        assert [b["name"] for b in page["beats"]] == ["question", "demo"]  # the rejected beat is left out
    with tempfile.TemporaryDirectory() as root:
        make_swipe(root, hook_status="accepted")
        hook = _page(_render(make_fixture(root, report=_swipe_report()), root).read_text(encoding="utf-8"))["card"]["lines"][0]
        assert "question then number answer" in hook["text"] and "(suggested)" not in hook["text"], hook
    with tempfile.TemporaryDirectory() as root:  # no swipe file: no strip
        assert _page(_render(make_fixture(root), root).read_text(encoding="utf-8"))["card"]["counts"] is None


def test_new_rule_probes_refused():
    # the wall: TRIBE, peaked, spiked, neural activity, predicted activation next to a count
    for bad in ("18x own median; TRIBE peaked at 0:37", "312,098 plays, and the TRIBE lines spiked at 0:37",
                "18.0x own median and neural activity rose at 0:37", "outliers show stronger predicted activation"):
        _expect_refused(lambda: render.check_mixed_layers([bad]), "wall")
    # cause words
    for bad in ("The hook is why it got 312,098 plays", "Due to the hook, it got 18x", "Thanks to the hook, it spread",
                "the hook resulted in more likes", "the open drives plays", "a reel driven by its hook",
                "as a result, the comments rose"):
        _expect_refused(lambda: render.check_cause(bad), "cause")
    render.check_cause("Driven by: seeing, attention")             # which lines make up a peak, inside one reel
    render.check_cause("0:27: one peak, driven by seeing and attention.")
    render.check_cause("if (p.driving_lines) { }")
    # banned: performance forms, view count, rank and rating forms, emotion labels
    for bad in ("performed", "underperformed", "it performs", "a high performer", "view count", "#1 hook", "ranked 1st",
                "a 9/10 open", "the 2nd best", "joy", "excitement", "fear", "a sad dip"):
        assert render.find_banned(f"x {bad} y"), bad
    for ok in ("perform a test", "outliers 1/10 vs normal 3/10", "color: #1a1a1a", "&#8212;", "0:10-0:12"):
        assert not render.find_banned(ok), ok
    assert not render.find_banned("I was excited to try it", emotions=False)   # his own script lines may say it


def test_high_quote_skips_verdict_words():
    def high(words):
        rep = make_report()
        for i, w in enumerate(words):
            rep["words"].append({"text": w, "start": 12.1 + i * 0.15, "stop": 12.2 + i * 0.15, "rows": [12],
                                 "lang_z": 1.0, "ghost": False, "stretched": False})
        return render.build_card(rep, make_notes(), None, [], None)["lines"][1]["text"]
    base = "seeing and attention lines high for this reel"
    assert high(("connect", "the", "strongest", "predicted", "response.")) == base + ' · said: "…connect the…"'
    assert high(("the", "strongest", "predicted", "response.")) == base   # no clean run of 2 words: no quote
    assert high(("the", "best", "hook")) == base


def test_counts_strip_one_x_and_every_flag():
    reel = {"owner": "a.creator", "counts": {"plays": 312098, "as_of": "2026-10-06T20:46:49+00:00",
                                             "as_of_note": "pull date unknown (file date); counts from a record"},
            "x": {"plays": 17.95}, "facts": {"duration_s": 53.4, "source": {"cta": "inferred: 6 repeated words"}},
            "flags": {"thin_baseline": True, "gated_cta": True, "fresh": True, "under_2x": False},
            "_baseline": {"n": 14, "kind": "reels only", "median": {"plays": 17385.5}}}
    text = render.counts_strip(reel)["text"]
    assert text == ("@a.creator · 0:53 · 312,098 plays · 18.0x own median (14 reels) · thin baseline · "
                    "gated call to action, guessed from comments · fresh when pulled, counts not settled · "
                    "file date 2026-10-06 (pull date unknown)"), text
    reel["_baseline"] = {"n": 11, "kind": "all post types (VAULT record), not reels only",
                         "source": "VAULT repurpose record, not re-checked", "median": {"plays": 15742.5}}
    reel["flags"] = {"under_2x": True}
    reel["counts"]["plays"] = 8113
    text = render.counts_strip(reel)["text"]
    assert "0.5x own median (11 posts, all types, not re-checked)" in text and "under 2x: taste, not proof" in text, text
    card = _good_card()
    card["counts"] = render.counts_strip(reel)
    render.validate_card(card)


def test_edge_flat_on_a_call_to_action_gives_no_try_line():
    rep = make_report(flat_stretches=[{"start": 26, "end": 30, "mean": -1.4, "driving_lines": list(KEYS), "strong": None,
                                       "edge": True, "overlaps_black": False}])
    notes = make_notes()
    notes["notes"][3].update(t_start=26, t_end=30, text="0:26-0:29: low for this reel.",
                             idea_to_test="Test: in your draft, keep talking to the last second.")
    tries = [ln["text"] for ln in render.build_card(rep, notes, None, [], None)["lines"][3:]]
    assert "Test: in your draft, keep talking to the last second." in tries
    reel = {"facts": {"cta": {"type": "comment keyword", "t": 27.5}}}
    tries = [ln["text"] for ln in render.build_card(rep, notes, None, [], reel)["lines"][3:]]
    assert "Test: in your draft, keep talking to the last second." not in tries, tries


def test_rerender_reuses_the_job_folder_and_links_the_card():
    import datetime as dt
    with tempfile.TemporaryDirectory() as root:
        make_swipe(root)
        out = make_fixture(root, report=_swipe_report())
        first = render.render(out, reports_root=Path(root) / "reports", today=dt.date(2026, 10, 8), log=lambda *a: None,
                              swipe_root=Path(root) / "swipe")
        card_page = Path(root) / "reports" / "swipe" / "reels" / f"{SC}.html"
        card_page.parent.mkdir(parents=True)
        card_page.write_text("<!doctype html>", encoding="utf-8")
        again = render.render(out, reports_root=Path(root) / "reports", today=dt.date(2026, 10, 9), log=lambda *a: None,
                              swipe_root=Path(root) / "swipe")
        assert again == first and first.parent.name == "2026-10-08-synthetic-test", (first, again)
        assert len(list((Path(root) / "reports").glob("*-synthetic-test"))) == 1
        page = _page(again.read_text(encoding="utf-8"))
        assert page["swipe_href"] == f"../swipe/reels/{SC}.html" and page["private"] is True
        assert page["rendered"] == "2026-10-09"


def test_template_wording_and_chip_order():
    tpl = render.TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "your retention" not in tpl and "your real retention" not in tpl
    js = _main_script(tpl)
    # the claim first, then its time chip (as on the swipe cards); a chip scrolls the lanes into view
    assert js.index("body.appendChild(document.createTextNode(ln.text));") < js.index("var b = H('button', 'time-btn', ln.time, body);")
    assert "tl.scrollIntoView" in js
    assert 'id="h-private"' in tpl and "The four lines: seeing, hearing, language and attention" in tpl


def test_facts_card_without_tribe():
    with tempfile.TemporaryDirectory() as root:
        reel = make_swipe(root)
    card = render.build_card(None, ["Test: in your draft, open on the question.", "Test: in your draft, answer by 0:03."],
                             None, None, reel)
    render.validate_card(card)
    assert [ln["tag"] for ln in card["lines"]] == ["HOOK", "BEATS", "PACE", "TRY", "TRY"]
    assert card["footnote"] is None and card["mode"] == "facts"
    assert card["lines"][1]["text"] == "question → demo (suggested)"
    assert card["lines"][2]["text"] == "about 3 words a second · call to action: comment keyword" and card["lines"][2]["time"] == "0:26"
    assert card["lines"][0]["text"] == "question then number answer (suggested) · text on screen at start: yes · first word at"


if __name__ == "__main__":
    passed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            passed += 1
            print("ok", name)
    print(f"{passed} passed")
