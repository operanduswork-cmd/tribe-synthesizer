"""Score one TRIBE v2 output folder (stage 0: one reel, no reference scale yet).

Usage:
    python scoring/score.py <output_dir> [--purpose test|edit|calibration]

Reads preds.npy, segments.json, events.json, flags.json, predict_meta.json and
source.json from <output_dir>, plus scoring/masks/masks-v1.json and
scoring/masks/fsaverage5-mesh.npz. Writes <output_dir>/report.json (the report
contract the dashboard reads) and <output_dir>/peak.png (brain picture at the
top peak second).

Everything here is a "predicted average-brain response" on the within-reel
scale: "relative to this reel's own average". Spec: docs/SCORING.md sections
5, 6, 9.4, 10, 12, 13, 14 and 16. Every threshold is a starting point
[ours unless the spec cites a source], kept in the constants below.

Runtime needs only the standard library, numpy, scipy and matplotlib.
Exit code 2 = refused (mock output, NaN/inf, wrong width, missing inputs).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d

HERE = Path(__file__).resolve().parent
MASKS_JSON = HERE / "masks" / "masks-v1.json"
MESH_NPZ = HERE / "masks" / "fsaverage5-mesh.npz"

SCORING_VERSION = "0.1"
FRAMING = "predicted average-brain response"
SCALE_LABEL = "relative to this reel's own average"
OFFSET_TEXT = "model-aligned, no extra shift (one-time timing test not run yet)"
COMBINED_NOTE = "locates moments only, not a rating"

N_VERTICES = 20484
N_HEMI = 10242
LINE_KEYS = ("seeing", "hearing", "language", "attention")
LINE_LABELS = {
    "seeing": "predicted visual response",
    "hearing": "predicted auditory response",
    "language": "predicted language response",
    "attention": "predicted attention-network response",
}
PURPOSES = ("test", "edit", "calibration")

# Frozen starting points (SCORING 10, 12, 13, 20). Changing any of them means a new SCORING_VERSION.
SIGMA_S = 2.0            # gaussian sigma, seconds (techfreakworm)
TRUNCATE = 3.0           # gaussian truncate (techfreakworm)
PEAK_Z = 1.0             # combined shape z for a peak
PEAK_SPACING_S = 4.0     # peaks at least this far apart, picked greedily
PEAKS_KEPT = 3
DRIVE_Z = 1.0            # a line "drives" an event when its own shape z is beyond +/- this
FLAT_Z = -1.0            # combined shape z for a flat stretch
FLAT_MIN_S = 4.0         # flat stretch minimum length
FLAT_MERGE_GAP_S = 1.0   # runs this close or closer are merged
EDGE_S = 2.0             # first and last 2 s are edge seconds (lower confidence)
HOOK_END_S = 3.0         # hook window = rows starting at 0, 1, 2
TREND_FLAT = 0.2         # |slope per 10 s| <= this is "flat"
COVER_MIN_S = 0.5        # a second is black/silent when flagged ranges cover >= 0.5 s of it
GHOST_FRACTION = 0.5     # ghost word = >= 50% of its duration inside a silent range
STRETCHED_S = 1.0        # stretched word = duration >= 1.0 s
WORD_Z = 1.0             # word-hit cutoff on the language line
WORD_HITS_KEPT = 5
SHORT_CLIP_S = 10.0
ROWS_TOLERANCE_S = 2.0
STEP_TOLERANCE_S = 1e-3
MAX_TIMES_LISTED = 6     # how many m:ss times a warning lists before "and more"

# Brain picture (SCORING 14).
BRAIN_CMAP = "PuOr_r"    # diverging, not red/green
BRAIN_PERCENTILE = 99.0
BRAIN_PNG = "peak.png"
BRAIN_GREY_BELOW = 0.15  # |value| / vmax below this shows only the grey sulcal shading
BRAIN_FULL_AT = 0.5      # |value| / vmax at or above this shows full colour


class ScoreError(Exception):
    """Scoring refused or could not read its inputs. The message says why."""


# ---------------------------------------------------------------- small helpers

def fmt_time(seconds: float) -> str:
    s = max(0, int(math.floor(float(seconds) + 1e-9)))
    return f"{s // 60}:{s % 60:02d}"


def fmt_range(a: float, b: float) -> str:
    """Closed range for an end-exclusive span of whole seconds: [9, 12) -> 0:09-0:11."""
    last = max(a, b - 1)
    return fmt_time(a) if int(last) == int(a) else f"{fmt_time(a)}-{fmt_time(last)}"


def _r(x, nd: int = 4):
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None
    v = round(x, nd)
    return 0.0 if v == 0 else v


def _rl(arr, nd: int = 4) -> list:
    return [_r(v, nd) for v in np.asarray(arr, dtype=np.float64).tolist()]


def _second(t: float) -> int:
    return int(math.floor(float(t) + 1e-9))


def _load_json(path: Path, what: str):
    if not path.exists():
        raise ScoreError(f"{what} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ScoreError(f"{what} could not be read as JSON ({path}): {e}") from e


def _merge_ranges(ranges) -> list[tuple[float, float]]:
    clean = []
    for r in ranges or []:
        try:
            a, b = float(r[0]), float(r[1])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(a) and math.isfinite(b) and b > a:
            clean.append((a, b))
    clean.sort()
    out: list[tuple[float, float]] = []
    for a, b in clean:
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def covered(a: float, b: float, merged) -> float:
    """Seconds of [a, b] covered by already merged ranges."""
    total = 0.0
    for x, y in merged:
        total += max(0.0, min(b, y) - max(a, x))
    return total


def _runs(mask) -> list[tuple[int, int]]:
    """(i0, i1) end-exclusive index runs where mask is true."""
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


# ---------------------------------------------------------------- sanity checks (SCORING 6)

def check_meta(meta) -> None:
    if not isinstance(meta, dict):
        raise ScoreError("predict_meta.json is not a JSON object")
    if meta.get("mock") is not False:
        raise ScoreError(
            f"predict_meta.json mock is {meta.get('mock')!r}, not exactly false: "
            "refusing to score mock or fallback output")


def check_preds(P) -> None:
    P = np.asarray(P)
    if P.ndim != 2 or P.shape[1] != N_VERTICES:
        raise ScoreError(
            f"preds shape is {tuple(P.shape)}, expected (rows, {N_VERTICES}): wrong model or mesh, refusing")
    if P.shape[0] == 0:
        raise ScoreError("preds has no rows, refusing")
    if not np.issubdtype(P.dtype, np.number):
        raise ScoreError(f"preds dtype is {P.dtype}, not numeric, refusing")
    if not np.isfinite(P).all():
        bad = int((~np.isfinite(P)).sum())
        raise ScoreError(f"preds has {bad} NaN or inf values, refusing")


# ---------------------------------------------------------------- the maths (SCORING 10)

def zscore(x) -> np.ndarray:
    """Within-reel z (population SD). A constant line gives all zeros."""
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return x
    sd = float(x.std())
    if not math.isfinite(sd) or sd < 1e-12:
        return np.zeros_like(x)
    return (x - x.mean()) / sd


def smooth(x) -> np.ndarray:
    return gaussian_filter1d(np.asarray(x, dtype=np.float64), sigma=SIGMA_S, truncate=TRUNCATE, mode="reflect")


def linear_fit(y, t) -> tuple[float, float]:
    """Least-squares straight line y ~ slope * t + intercept."""
    y = np.asarray(y, dtype=np.float64)
    t = np.asarray(t, dtype=np.float64)
    if y.size < 2:
        return 0.0, float(y.mean()) if y.size else 0.0
    tc = t - t.mean()
    denom = float((tc * tc).sum())
    if denom <= 0:
        return 0.0, float(y.mean())
    slope = float((tc * (y - y.mean())).sum() / denom)
    return slope, float(y.mean() - slope * t.mean())


def detrend(y, t) -> np.ndarray:
    y = np.asarray(y, dtype=np.float64)
    slope, intercept = linear_fit(y, t)
    return y - (slope * np.asarray(t, dtype=np.float64) + intercept)


def trend_word(slope_per_10s: float) -> str:
    if abs(slope_per_10s) <= TREND_FLAT:
        return "flat"
    return "rising" if slope_per_10s > 0 else "falling"


def build_lines(P, masks: dict, time_s) -> dict:
    """Per line: raw mean, raw_z, display_z (smoothed z), shape_z (smoothed, detrended, z), trend."""
    P = np.asarray(P, dtype=np.float64)
    t = np.asarray(time_s, dtype=np.float64)
    out = {}
    for k in LINE_KEYS:
        idx = np.asarray(masks[k], dtype=np.int64)
        raw = P[:, idx].mean(axis=1)  # signed mean over the parcels' vertices
        s = smooth(raw)
        display = zscore(s)
        shape = zscore(detrend(s, t))
        slope10 = linear_fit(display, t)[0] * 10.0
        out[k] = {"raw": raw, "raw_z": zscore(raw), "display_z": display, "shape_z": shape,
                  "trend_per_10s": slope10, "trend": trend_word(slope10)}
    return out


def overall_rms(P) -> np.ndarray:
    P = np.asarray(P, dtype=np.float64)
    return np.sqrt(np.mean(P * P, axis=1))


def pattern_change(P) -> list:
    """[None, then 1 - Pearson r between row t and row t-1] (SCORING 9.4, calibration only)."""
    P = np.asarray(P, dtype=np.float64)
    out: list = [None]
    for i in range(1, P.shape[0]):
        a, b = P[i] - P[i].mean(), P[i - 1] - P[i - 1].mean()
        den = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
        out.append(None if den < 1e-12 else 1.0 - float((a * b).sum()) / den)
    return out


def pearson(a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    a, b = a - a.mean(), b - b.mean()
    den = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return None if den < 1e-12 else float((a * b).sum()) / den


# ---------------------------------------------------------------- per-second flags

def second_flags(time_s, ranges) -> np.ndarray:
    """True where the flagged ranges cover >= 0.5 s of [t, t+1)."""
    merged = _merge_ranges(ranges)
    return np.array([covered(float(t), float(t) + 1.0, merged) >= COVER_MIN_S - 1e-9 for t in time_s], dtype=bool)


def clip_end(time_s, row_stops=None) -> float:
    if row_stops is not None and len(row_stops):
        return float(row_stops[-1])
    return float(time_s[-1]) + 1.0


def edge_flags(time_s, t_end: float) -> np.ndarray:
    t = np.asarray(time_s, dtype=np.float64)
    return (t < EDGE_S - 1e-9) | (t >= t_end - EDGE_S - 1e-9)


def last_seconds(time_s, t_end: float) -> np.ndarray:
    t = np.asarray(time_s, dtype=np.float64)
    return t >= t_end - EDGE_S - 1e-9


# ---------------------------------------------------------------- peaks and flat stretches (SCORING 12.2)

def pick_peaks(C, time_s, black, shape_z: dict, t_end: float | None = None) -> list[dict]:
    C = np.asarray(C, dtype=np.float64)
    t = np.asarray(time_s, dtype=np.float64)
    n = len(C)
    if t_end is None:
        t_end = clip_end(t)
    in_last = last_seconds(t, t_end)
    cands = []
    for i in range(n):
        c = C[i]
        if not c >= PEAK_Z:
            continue
        if i > 0 and C[i - 1] > c:
            continue
        if i < n - 1 and C[i + 1] > c:
            continue
        if black[i] or in_last[i]:
            continue
        cands.append(i)
    cands.sort(key=lambda i: (-C[i], t[i]))
    picked: list[int] = []
    for i in cands:
        if all(abs(t[i] - t[j]) >= PEAK_SPACING_S - 1e-9 for j in picked):
            picked.append(i)
        if len(picked) == PEAKS_KEPT:
            break
    return [{
        "t": _second(t[i]),
        "value": _r(C[i]),
        "driving_lines": [k for k in LINE_KEYS if k in shape_z and shape_z[k][i] >= DRIVE_Z],
        "edge": bool(t[i] < EDGE_S - 1e-9),
        "_row": i,
    } for i in picked]


def find_flats(C, time_s, black, shape_z: dict, t_end: float | None = None) -> list[dict]:
    C = np.asarray(C, dtype=np.float64)
    t = np.asarray(time_s, dtype=np.float64)
    if t_end is None:
        t_end = clip_end(t)
    runs = _runs(C <= FLAT_Z)
    merged: list[list[int]] = []
    for i0, i1 in runs:
        if merged:
            prev_end = t[merged[-1][1] - 1] + 1.0
            if t[i0] - prev_end <= FLAT_MERGE_GAP_S + 1e-9:
                merged[-1][1] = i1
                continue
        merged.append([i0, i1])
    out = []
    for i0, i1 in merged:
        start, end = float(t[i0]), float(t[i1 - 1]) + 1.0
        if end - start < FLAT_MIN_S - 1e-9:
            continue
        out.append({
            "start": _second(start),
            "end": _second(end),
            "mean": _r(C[i0:i1].mean()),
            "driving_lines": [k for k in LINE_KEYS
                              if k in shape_z and float(np.mean(shape_z[k][i0:i1])) <= -DRIVE_Z],
            "strong": None,
            "edge": bool(start < EDGE_S - 1e-9 or end > t_end - EDGE_S + 1e-9),
            "overlaps_black": bool(np.any(np.asarray(black[i0:i1], dtype=bool))),
        })
    return out


# ---------------------------------------------------------------- words (SCORING 13)

def read_words(events) -> list[dict]:
    words = []
    for w in (events or {}).get("words") or []:
        try:
            start = float(w["start"])
        except (KeyError, TypeError, ValueError):
            continue
        if w.get("stop") is not None:
            stop = float(w["stop"])
        else:
            stop = start + float(w.get("duration") or 0.0)
        dur = float(w["duration"]) if w.get("duration") is not None else stop - start
        if not (math.isfinite(start) and math.isfinite(stop) and math.isfinite(dur)):
            continue
        words.append({"text": str(w.get("text") or "").strip(), "start": start,
                      "stop": max(stop, start), "duration": max(dur, 0.0)})
    return words


def word_rows(start: float, stop: float, row_starts, row_stops) -> list[int]:
    """Rows whose [start, stop) overlaps [word.start, word.stop]; a zero-length word maps to the row holding its start."""
    if stop - start <= 1e-9:
        return [i for i, (a, b) in enumerate(zip(row_starts, row_stops)) if a - 1e-9 <= start < b - 1e-9][:1]
    return [i for i, (a, b) in enumerate(zip(row_starts, row_stops)) if min(b, stop) - max(a, start) > 1e-9]


def is_ghost(start: float, stop: float, silent_merged) -> bool:
    dur = stop - start
    if dur <= 1e-9:
        return any(a <= start <= b for a, b in silent_merged)
    return covered(start, stop, silent_merged) >= GHOST_FRACTION * dur - 1e-9


def is_stretched(duration: float) -> bool:
    return round(float(duration), 6) >= STRETCHED_S


def map_words(words, row_starts, row_stops, lang_raw_z, silent_ranges) -> list[dict]:
    silent = _merge_ranges(silent_ranges)
    lang = np.asarray(lang_raw_z, dtype=np.float64)
    out = []
    for w in words:
        rows = word_rows(w["start"], w["stop"], row_starts, row_stops)
        lz = float(max(lang[i] for i in rows)) if rows else None
        out.append({
            "text": w["text"], "start": w["start"], "stop": w["stop"], "rows": rows, "lang_z": lz,
            "ghost": bool(is_ghost(w["start"], w["stop"], silent)),
            "stretched": bool(is_stretched(w["duration"])),
        })
    return out


def word_hits(mapped) -> list[dict]:
    """Join consecutive candidate words (adjacent in the transcript) into phrases; keep the top 5 by value.
    A non-candidate word (low, ghost or stretched) ends the phrase, so a phrase never skips a word."""
    phrases = []
    cur = None
    for w in mapped:
        cand = (w["lang_z"] is not None and w["lang_z"] >= WORD_Z and not w["ghost"]
                and not w["stretched"] and w["rows"])
        if not cand:
            cur = None
            continue
        if cur is not None and w["rows"][0] <= cur["last_row"] + 1:
            cur["texts"].append(w["text"])
            cur["end"] = max(cur["end"], w["stop"])
            cur["value"] = max(cur["value"], w["lang_z"])
            cur["last_row"] = max(cur["last_row"], max(w["rows"]))
        else:
            cur = {"texts": [w["text"]], "start": w["start"], "end": w["stop"], "value": w["lang_z"],
                   "last_row": max(w["rows"])}
            phrases.append(cur)
    phrases.sort(key=lambda p: (-p["value"], p["start"]))
    return [{"phrase": " ".join(x for x in p["texts"] if x), "start": _r(p["start"], 3), "end": _r(p["end"], 3),
             "value": _r(p["value"]), "ghost_flag": False} for p in phrases[:WORD_HITS_KEPT]]


# ---------------------------------------------------------------- masks and cross-check

def load_masks(path: Path = MASKS_JSON) -> dict:
    m = _load_json(path, "masks file")
    lines = {}
    for k in LINE_KEYS:
        try:
            v = np.asarray(m["lines"][k]["vertices"], dtype=np.int64)
        except (KeyError, TypeError, ValueError) as e:
            raise ScoreError(f"masks file has no usable vertex list for line {k!r}: {e}") from e
        if v.size == 0 or v.min() < 0 or v.max() >= N_VERTICES:
            raise ScoreError(f"masks file vertex list for {k!r} is empty or out of range")
        lines[k] = v
    cross = {}
    for name, block in (m.get("crosscheck") or {}).items():
        try:
            v = np.asarray(block["vertices"], dtype=np.int64)
        except (KeyError, TypeError, ValueError):
            continue
        if v.size and v.min() >= 0 and v.max() < N_VERTICES:
            cross[name] = v
    return {"version": m.get("version") or "masks-v1", "lines": lines, "cross": cross,
            "results": (m.get("crosscheck_results") or {}).get("fixtures") or {}}


CROSS_PAIRS = (
    ("seeing_vs_yeo_visual", "seeing", "yeo_visual"),
    ("attention_vs_yeo_dorsal_ventral", "attention", "yeo_dorsal_ventral_attention"),
    ("hearing_vs_destrieux_auditory", "hearing", "destrieux_auditory"),
)


def crosscheck(job_id: str, P, masks: dict):
    stored = masks["results"].get(job_id)
    if isinstance(stored, dict) and all(isinstance(stored.get(key), (int, float)) for key, _, _ in CROSS_PAIRS):
        return {key: _r(stored[key]) for key, _, _ in CROSS_PAIRS}
    if not masks["cross"]:
        return None
    P = np.asarray(P, dtype=np.float64)
    out = {}
    for key, line, cname in CROSS_PAIRS:
        if cname not in masks["cross"]:
            out[key] = None
            continue
        a = smooth(P[:, masks["lines"][line]].mean(axis=1))
        b = smooth(P[:, masks["cross"][cname]].mean(axis=1))
        out[key] = _r(pearson(a, b))
    return out if any(v is not None for v in out.values()) else None


# ---------------------------------------------------------------- brain picture (SCORING 14)

def _hemi_polys(coords, faces, vals, sulc, side: str, vmax: float, cmap):
    v = coords[faces].astype(np.float64)                      # (F, 3, 3)
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    cen = v.mean(axis=1)
    # Make normals point outward whatever the winding convention.
    if float(np.sum(n * (cen - coords.mean(axis=0)), axis=1).mean()) < 0:
        n = -n
    cam = np.array([-1.0, 0.0, 0.0]) if side == "left" else np.array([1.0, 0.0, 0.0])
    keep = n @ cam > 0                                        # faces turned towards the camera
    order = np.argsort(cen[keep] @ cam)                       # painter's algorithm: far first
    idx = np.nonzero(keep)[0][order]
    # Lateral view, z up. Left side: front of the brain on the left. Right side: front on the right.
    sx = -v[idx, :, 1] if side == "left" else v[idx, :, 1]
    polys = np.stack([sx, v[idx, :, 2]], axis=-1)
    light = cam + np.array([0.0, 0.25, 0.6])
    light /= np.linalg.norm(light)
    shade = 0.6 + 0.4 * np.clip(n[idx] @ light, 0.0, 1.0)
    fv = vals[faces[idx]].mean(axis=1)
    fs = sulc[faces[idx]].mean(axis=1)
    grey = 0.74 - 0.12 * np.tanh(2.0 * fs)                    # deeper (sulc > 0) = darker grey
    col = cmap(np.clip((fv + vmax) / (2.0 * vmax), 0.0, 1.0))[:, :3]
    a = np.clip((np.abs(fv) / vmax - BRAIN_GREY_BELOW) / (BRAIN_FULL_AT - BRAIN_GREY_BELOW), 0.0, 1.0)[:, None]
    rgb = ((1.0 - a) * grey[:, None] + a * col) * shade[:, None]
    return polys, np.clip(rgb, 0.0, 1.0)


def render_brain(values, mesh: dict, path: Path, vmax: float) -> None:
    """Left and right lateral sides of one row on the inflated fsaverage5 mesh. Pure matplotlib (Agg)."""
    from matplotlib import colormaps
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.cm import ScalarMappable
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import Normalize
    from matplotlib.figure import Figure

    values = np.asarray(values, dtype=np.float64)
    cmap = colormaps[BRAIN_CMAP]
    fig = Figure(figsize=(7.2, 3.2), dpi=100, facecolor="white")
    FigureCanvasAgg(fig)
    halves = (("left", values[:N_HEMI], mesh["infl_left"], mesh["faces_left"], mesh["sulc_left"]),
              ("right", values[N_HEMI:], mesh["infl_right"], mesh["faces_right"], mesh["sulc_right"]))
    ylim = max(float(np.abs(mesh["infl_left"][:, 1]).max()), float(np.abs(mesh["infl_right"][:, 1]).max())) * 1.02
    zlim = max(float(np.abs(mesh["infl_left"][:, 2]).max()), float(np.abs(mesh["infl_right"][:, 2]).max())) * 1.02
    for j, (side, vals, coords, faces, sulc) in enumerate(halves):
        ax = fig.add_axes((0.005 + 0.5 * j, 0.2, 0.49, 0.78))
        polys, rgb = _hemi_polys(np.asarray(coords), np.asarray(faces), vals, np.asarray(sulc), side, vmax, cmap)
        pc = PolyCollection(polys, facecolors=rgb, edgecolors=rgb, linewidths=0.25, antialiaseds=False)
        ax.add_collection(pc)
        ax.set_xlim(-ylim, ylim)
        ax.set_ylim(-zlim, zlim)
        ax.set_aspect("equal")
        ax.axis("off")
        fig.text(0.25 + 0.5 * j, 0.17, f"{side} side", ha="center", va="center", fontsize=9, color="#444444")
    cax = fig.add_axes((0.36, 0.07, 0.28, 0.035))
    sm = ScalarMappable(norm=Normalize(vmin=-vmax, vmax=vmax), cmap=cmap)
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal")
    cb.set_ticks([-vmax, 0.0, vmax])
    cb.set_ticklabels(["lower", "0", "higher"])
    cb.ax.tick_params(labelsize=8, length=2, colors="#444444")
    cb.outline.set_linewidth(0.5)
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp.png")
    fig.savefig(tmp, dpi=100, facecolor="white")
    os.replace(tmp, path)


def load_mesh(path: Path = MESH_NPZ) -> dict:
    if not path.exists():
        raise ScoreError(f"mesh file not found: {path} (rebuild it with scoring/build_masks.py)")
    with np.load(path, allow_pickle=False) as z:
        mesh = {k: z[k] for k in z.files}
    for k in ("infl_left", "faces_left", "sulc_left", "infl_right", "faces_right", "sulc_right"):
        if k not in mesh:
            raise ScoreError(f"mesh file is missing {k!r}: {path}")
    if mesh["infl_left"].shape[0] != N_HEMI or mesh["infl_right"].shape[0] != N_HEMI:
        raise ScoreError("mesh file is not fsaverage5 (10242 vertices per hemisphere)")
    return mesh


# ---------------------------------------------------------------- warnings

def _times_text(times) -> str:
    times = list(times)
    shown = ", ".join(times[:MAX_TIMES_LISTED])
    return shown + (f" and {len(times) - MAX_TIMES_LISTED} more" if len(times) > MAX_TIMES_LISTED else "")


def build_warnings(*, purpose, rows, analysed_s, time_s, steps_ok, flags, words, mapped, black) -> list[dict]:
    w = []

    def add(code, text):
        w.append({"code": code, "text": text})

    if purpose == "test":
        add("test_only", "test reel: not for calibration")
    if analysed_s < SHORT_CLIP_S or flags.get("short_clip_warning") is True:
        add("short_clip", "clip under 10 s: output may be flat")
    if abs(rows - analysed_s) > ROWS_TOLERANCE_S:
        add("rows_mismatch", f"{rows} rows for {analysed_s:.1f} s of clip: rows may have been dropped, "
                             "or the time step is not 1 s")
    if not steps_ok:
        add("segment_steps", "segment start times do not step by 1 s: the real start times are used")
    if flags.get("trimmed") is True:
        add("trimmed", f"clip was trimmed: only the first {analysed_s:.0f} s were analysed")
    if flags.get("audio_added_silent") is True:
        add("audio_added_silent", "the clip had no audio track, so silent audio was added: "
                                  "the hearing and language lines have no sound to follow")
    if flags.get("tonemapped") is True:
        add("tonemapped", "HDR video was tone-mapped to standard range before analysis")
    if not words:
        silent = _merge_ranges(flags.get("silent_ranges"))
        has_audio = ((flags.get("original") or {}).get("has_audio") is not False
                     and flags.get("audio_added_silent") is not True)
        mostly_silent = analysed_s > 0 and covered(0.0, analysed_s, silent) >= 0.9 * analysed_s
        if has_audio and not mostly_silent:
            add("no_words", "no words were transcribed although the audio is not silent: "
                            "the language line has no words to follow")
    ghosts = [m for m in mapped if m["ghost"]]
    if ghosts:
        add("ghost_words", f"possible ghost words at {_times_text(sorted({fmt_time(m['start']) for m in ghosts}))} "
                           "(inside silent stretches): never counted as word hits")
    black_ranges = _merge_ranges(flags.get("black_ranges"))
    if black_ranges:
        runs = _runs(np.asarray(black, dtype=bool))
        if runs:
            spans = [fmt_range(_second(time_s[i0]), _second(time_s[i1 - 1]) + 1) for i0, i1 in runs]
            n_black = int(np.asarray(black, dtype=bool).sum())
            add("black_frames", f"black frames in {n_black} s ({_times_text(spans)}): "
                                "those seconds are left out of peak finding")
        else:
            add("black_frames", "brief black frames (under half a second within any second): "
                                "no second is left out of peak finding")
    add("english_assumed", "speech assumed to be English: transcription is fixed to English")
    add("timing_untested", "timing not yet tested: the one-time 5 s offset check has not run")
    return w


# ---------------------------------------------------------------- the whole run

def score_dir(output_dir, purpose: str = "edit", masks_path: Path = MASKS_JSON, mesh_path: Path = MESH_NPZ,
              picture: bool = True, log=print) -> dict:
    out = Path(output_dir)
    if purpose not in PURPOSES:
        raise ScoreError(f"purpose must be one of {PURPOSES}, got {purpose!r}")
    if not out.is_dir():
        raise ScoreError(f"output folder not found: {out}")

    meta = _load_json(out / "predict_meta.json", "predict_meta.json")
    check_meta(meta)
    preds_path = out / "preds.npy"
    if not preds_path.exists():
        raise ScoreError(f"preds.npy not found: {preds_path}")
    try:
        P = np.load(preds_path, allow_pickle=False)
    except (OSError, ValueError) as e:
        raise ScoreError(f"preds.npy could not be read: {e}") from e
    check_preds(P)
    P = P.astype(np.float64)
    rows = int(P.shape[0])

    segments = _load_json(out / "segments.json", "segments.json")
    events = _load_json(out / "events.json", "events.json")
    flags = _load_json(out / "flags.json", "flags.json")
    src_path = out / "source.json"
    source = _load_json(src_path, "source.json") if src_path.exists() else {}
    if not isinstance(segments, list) or len(segments) != rows:
        n = len(segments) if isinstance(segments, list) else "no"
        raise ScoreError(f"segments.json has {n} entries for {rows} preds rows: cannot build the time axis")
    try:
        row_starts = np.array([float(s["start"]) for s in segments], dtype=np.float64)
        row_stops = np.array([float(s["stop"]) if s.get("stop") is not None else float(s["start"]) + 1.0
                              for s in segments], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as e:
        raise ScoreError(f"segments.json entries need numeric start times: {e}") from e
    if not (np.isfinite(row_starts).all() and np.isfinite(row_stops).all()):
        raise ScoreError("segments.json has non-finite start or stop times")
    steps_ok = bool(abs(row_starts[0]) <= STEP_TOLERANCE_S and
                    (rows < 2 or np.all(np.abs(np.diff(row_starts) - 1.0) <= STEP_TOLERANCE_S)))

    job_id = str(meta.get("job_id") or flags.get("job_id") or out.name)
    try:
        analysed_s = float(flags.get("analysed_s"))
    except (TypeError, ValueError):
        analysed_s = float(rows)
    masks = load_masks(masks_path)

    time_s = row_starts
    t_end = clip_end(time_s, row_stops)
    black = second_flags(time_s, flags.get("black_ranges"))
    silent = second_flags(time_s, flags.get("silent_ranges"))
    edge = edge_flags(time_s, t_end)
    hook_rows = [i for i in range(rows) if time_s[i] < HOOK_END_S - 1e-9]

    lines = build_lines(P, masks["lines"], time_s)
    shape = {k: lines[k]["shape_z"] for k in LINE_KEYS}
    C = np.mean([shape[k] for k in LINE_KEYS], axis=0)

    peaks = pick_peaks(C, time_s, black, shape, t_end)
    flats = find_flats(C, time_s, black, shape, t_end)

    words = read_words(events)
    mapped = map_words(words, row_starts, row_stops, lines["language"]["raw_z"], flags.get("silent_ranges"))
    hits = word_hits(mapped)

    warnings = build_warnings(purpose=purpose, rows=rows, analysed_s=analysed_s, time_s=time_s, steps_ok=steps_ok,
                              flags=flags, words=words, mapped=mapped, black=black)

    brain = None
    png = out / BRAIN_PNG
    if peaks and picture:
        top = max(peaks, key=lambda p: (p["value"], -p["t"]))
        row = top["_row"]
        vmax = float(np.percentile(np.abs(P[row]), BRAIN_PERCENTILE))
        if not vmax > 0:
            vmax = float(np.abs(P[row]).max()) or 1.0
        t0 = time.perf_counter()
        render_brain(P[row], load_mesh(mesh_path), png, vmax)
        log(f"brain picture: {png.name} at {fmt_time(top['t'])}, {time.perf_counter() - t0:.2f} s, "
            f"{png.stat().st_size // 1024} KB")
        brain = {"t": top["t"], "path": BRAIN_PNG, "vmin": _r(-vmax, 6), "vmax": _r(vmax, 6),
                 "sides": ["left", "right"]}
    elif png.exists():
        png.unlink()  # a picture from an earlier run would no longer match this report

    report = {
        "framing": FRAMING,
        "scoring_version": SCORING_VERSION,
        "masks_version": masks["version"],
        "mock": False,
        "job_id": job_id,
        "label": str(source.get("label") or job_id),
        "purpose": purpose,
        "source": {
            "local_path": str(source.get("local_path") or ""),
            "source_url": str(source.get("source_url") or ""),
            "owner": str(source.get("owner") or ""),
            "fetched_via": str(source.get("fetched_via") or ("local file" if source.get("local_path") else "")),
            "sha256": str(source.get("sha256") or (flags.get("original") or {}).get("sha256") or ""),
        },
        "scale": {"mode": "within-reel", "ref_version": None, "label": SCALE_LABEL},
        "offset": OFFSET_TEXT,
        "clip": {"seconds": _r(analysed_s, 3), "rows": rows,
                 "language": f"{flags.get('language_assumed') or 'english'} (assumed)"},
        "warnings": warnings,
        "time_s": _rl(time_s, 3),
        "per_second": [{"t": _second(time_s[i]), "black": bool(black[i]), "silent": bool(silent[i]),
                        "edge": bool(edge[i]), "hook": i in hook_rows} for i in range(rows)],
        "lines": {k: {
            "label": LINE_LABELS[k],
            "raw_z": _rl(lines[k]["raw_z"]),
            "display_z": _rl(lines[k]["display_z"]),
            "shape_z": _rl(lines[k]["shape_z"]),
            "shared": None,
            "trend_per_10s": _r(lines[k]["trend_per_10s"]),
            "trend": lines[k]["trend"],
            "trend_scale": "within-reel",
        } for k in LINE_KEYS},
        "combined": {"shape_z": _rl(C), "shared": None, "note": COMBINED_NOTE},
        "calibration_only": {"overall_rms": _rl(overall_rms(P), 6), "pattern_change": _rl_none(pattern_change(P), 6)},
        "hook_0_3s": {"scale": "within-reel", "rows": hook_rows,
                      **{k: _r(np.mean(lines[k]["raw_z"][hook_rows])) if hook_rows else None for k in LINE_KEYS}},
        "peaks": [{k: v for k, v in p.items() if not k.startswith("_")} for p in peaks],
        "flat_stretches": flats,
        "words": [{"text": m["text"], "start": _r(m["start"], 3), "stop": _r(m["stop"], 3), "rows": m["rows"],
                   "lang_z": _r(m["lang_z"]), "ghost": m["ghost"], "stretched": m["stretched"]} for m in mapped],
        "word_hits": hits,
        "stretched_words": [{"text": m["text"], "start": _r(m["start"], 3), "stop": _r(m["stop"], 3)}
                            for m in mapped if m["stretched"]],
        "brain_picture": brain,
        "crosscheck": crosscheck(job_id, P, masks),
        "compare": None,
        "raw": {"preds": "preds.npy", "segments": "segments.json", "events": "events.json", "flags": "flags.json"},
    }
    path = out / "report.json"
    tmp = out / "report.json.tmp"
    tmp.write_text(json.dumps(report, indent=1, allow_nan=False, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return report


def _rl_none(values, nd: int) -> list:
    return [None if v is None else _r(v, nd) for v in values]


def summary_text(report: dict) -> str:
    lines = [f"report.json written for {report['job_id']} ({report['label']}, purpose {report['purpose']}), "
             f"{report['clip']['rows']} rows, {report['scale']['label']}"]
    for p in report["peaks"]:
        lines.append(f"  peak {fmt_time(p['t'])}  combined {p['value']:+.2f}  lines: "
                     f"{', '.join(p['driving_lines']) or '-'}{'  (edge)' if p['edge'] else ''}")
    for f in report["flat_stretches"]:
        lines.append(f"  flat {fmt_range(f['start'], f['end'])}  mean {f['mean']:+.2f}  lines: "
                     f"{', '.join(f['driving_lines']) or '-'}{'  (edge)' if f['edge'] else ''}"
                     f"{'  (black)' if f['overlaps_black'] else ''}")
    for h in report["word_hits"]:
        lines.append(f"  word hit {fmt_time(h['start'])}  {h['value']:+.2f}  \"{h['phrase']}\"")
    for k in LINE_KEYS:
        L = report["lines"][k]
        lines.append(f"  trend {k}: {L['trend']} ({L['trend_per_10s']:+.2f} per 10 s)")
    lines.append(f"  warnings: {', '.join(w['code'] for w in report['warnings'])}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Score one TRIBE v2 output folder (predicted average-brain response).")
    ap.add_argument("output_dir")
    ap.add_argument("--purpose", choices=PURPOSES, default="edit")
    args = ap.parse_args(argv)
    try:
        report = score_dir(args.output_dir, purpose=args.purpose)
    except ScoreError as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2
    text = summary_text(report)
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
