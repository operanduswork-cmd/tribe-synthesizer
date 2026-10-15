r"""The brain view's data (D28): one `brain` page per linked TRIBE job and the binary assets
behind it, built from outputs/<job>/preds.npy on the laptop.

    page     strategist/hosted_schema/brain.schema.json, keyed by job id like the tribe page:
             the colour scale, the asset keys (sha256 of the stored gzip bytes, decompressed
             length), the atlas (HCP-MMP1 codes, Yeo-7 names, a fixed display order) and area
             means (HCP 180 a side, Yeo-7 both sides, the four lines), 4 dp, per second
    assets   web/contracts/brain-assets.json: little-endian, a 16-byte header, no text, gzip
               tribe/<job>/frames.i8               TBF1  int8 [rows][20484], one scale per reel
               shared/fsaverage5-inflated-v1.bin   TBM1  f32 coords, u16 faces, f32 sulc
               shared/atlas-v1.bin                 TBA1  u8 HCP lookup, u8 Yeo lookup

One colour scale for the whole reel: vmax = p99 of |model output| over every cortex vertex
(HCP label not 0) and every second, rounded to 6 dp; q = clip(rint(x / vmax * 127), -127, 127).
Frames are the raw 1-s model rows (unsmoothed), symmetric around the model's zero, so the
legend reads "one colour scale for this whole reel". peak.png keeps its own-row scale
(SCORING 14), so its colours differ from the brain view's.

An area mean is the signed mean of the model output over the area's vertices (SCORING 10
step 1), computed here from float32 preds: the browser never averages quantised frames. Areas
are listed in a fixed atlas order (Yeo network, then Glasser index), never sorted by a value;
per-area within-reel z lives only in the web's CSV. Nothing here spans two jobs (D21).

Stays on the laptop: preds.npy and the full-precision per-vertex floats (the `vertices`
command below writes them to a folder of your choice, never under web/).

Refuses (fail closed): a bad job id or report, preds that are not (rows, 20484) or not finite,
rows that differ from report time_s or are over 90, a masks version that differs from the
atlas's, and line means whose within-reel z differs from the report's raw_z by over 2e-3.

Usage (from the Tribe folder):
    python -m strategist.brain_assets show <job>                sizes, rows and vmax (no values)
    python -m strategist.brain_assets vertices <job> --out DIR  every surface point, full precision
    python -m strategist.brain_assets fixture                   rewrite web/fixtures/brain.json (synthetic)
"""

from __future__ import annotations

import argparse
import functools
import gzip
import hashlib
import importlib.util
import json
import math
import re
import struct
import sys
import zlib
from pathlib import Path
from typing import NamedTuple

import numpy as np

from . import store

R = store.rules()
ROOT = store.PROJECT_ROOT
WEB = ROOT / "web"
CONTRACT_PATH = WEB / "contracts" / "brain-assets.json"
SCHEMA_PATH = ROOT / "strategist" / "hosted_schema" / "brain.schema.json"
SCORE_PY = ROOT / "scoring" / "score.py"
ATLAS_JSON = ROOT / "scoring" / "masks" / "atlas-v1.json"
MASKS_JSON = ROOT / "scoring" / "masks" / "masks-v1.json"
MESH_NPZ = ROOT / "scoring" / "masks" / "fsaverage5-mesh.npz"
SPEC_MASKS = ROOT / "scoring" / "masks" / "masks-v1.json"   # the line parcel names (SCORING 9.1)

V = 1
FRAMING = "predicted average-brain response"
SCALE_LABEL = "one colour scale for this whole reel"
POOLED = "every cortex vertex, every second"
PERCENTILE = 99
MESH_VERSION = 1
LINE_KEYS = ("seeing", "hearing", "language", "attention")
JOB_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{8}$")
RAW_Z_TOL = 2e-3
PAGE_MAX = 256 * 1024          # bytes of the brain page's canonical JSON
CLIP_MAX = 0.05
SYNTH_JOB = "20261001-101500-0a1b2c3d"    # the synthetic tribe fixture's job (web/fixtures/tribe.json)
SYNTH_SC = "DEMO0000001"
FOOTER_12E = ("Predicted average-brain response from TRIBE v2 (Meta FAIR, CC BY-NC 4.0). Built with Llama. "
              "Non-commercial use only. Not a view forecast.")


class BrainError(Exception):
    """A brain page or asset was refused. The message says why and holds no words."""


# ---------------------------------------------------------------- the contract file

@functools.lru_cache(maxsize=1)
def contract() -> dict:
    """web/contracts/brain-assets.json (the web reads the same file)."""
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _c(name):
    return contract()[name]


N_V = 20484
N_HEMI = 10242
N_FACES = 20480


def raw_size(kind: str, rows: int | None = None) -> int:
    """The exact decompressed length of an asset (frames needs its row count)."""
    c = contract()
    if kind == "frames":
        return c["header_bytes"] + int(rows) * c["vertices"]
    if kind == "mesh":
        return c["header_bytes"] + 2 * c["vertices_per_side"] * 3 * 4 + 2 * c["faces_per_side"] * 3 * 2 \
            + 2 * c["vertices_per_side"] * 4
    if kind == "atlas":
        return c["header_bytes"] + 2 * c["vertices"]
    raise BrainError(f"not a brain asset kind: {kind!r}")


def mesh_key(version: int = MESH_VERSION) -> str:
    return f"shared/fsaverage5-inflated-v{version}.bin"


def atlas_key(version: str) -> str:
    return f"shared/{version}.bin"


def frames_key(job: str) -> str:
    return f"tribe/{job}/frames.i8"


def kind_of(key: str) -> str | None:
    """The asset kind a key's format names, or None when it is not a brain asset key."""
    if not isinstance(key, str) or not re.fullmatch(_c("key_pattern"), key):
        return None
    for kind, spec in contract()["kinds"].items():
        if re.fullmatch(spec["key_pattern"], key):
            return kind
    return None


# ---------------------------------------------------------------- scoring/score.py, reused

@functools.lru_cache(maxsize=1)
def scoring():
    """scoring/score.py as a module: load_masks, load_mesh, check_preds, zscore, _r and the BRAIN_* constants."""
    spec = importlib.util.spec_from_file_location("tribe_scoring", SCORE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- packing and checking

class Asset(NamedTuple):
    key: str
    kind: str
    mime: str
    raw: bytes        # decompressed
    data: bytes       # gzip, what the database stores
    hash: str         # sha256 of data

    @property
    def raw_bytes(self) -> int:
        return len(self.raw)

    def ref(self) -> dict:
        """The page's {key, sha256, bytes} block for this asset."""
        return {"key": self.key, "sha256": self.hash, "bytes": len(self.raw)}


def gz(raw: bytes) -> bytes:
    """gzip level 9 with mtime 0 and no file name: the same input always gives the same bytes."""
    return gzip.compress(bytes(raw), compresslevel=9, mtime=0)


def gunzip(data: bytes, limit: int | None = None) -> bytes:
    """Decompress one gzip member, refusing anything over limit bytes (never a bomb) or with trailing data."""
    limit = limit if limit is not None else contract()["raw_bytes"]["max"]
    if not isinstance(data, (bytes, bytearray, memoryview)) or bytes(data[:2]) != bytes.fromhex(_c("gzip_magic")):
        raise BrainError("not gzip data")
    d = zlib.decompressobj(wbits=31)
    try:
        out = d.decompress(bytes(data), limit + 1)
    except zlib.error as e:
        raise BrainError(f"damaged gzip data ({e})") from None
    if len(out) > limit or d.unconsumed_tail:
        raise BrainError(f"gzip data unpacks to over {limit} bytes")
    if not d.eof or d.unused_data:
        raise BrainError("gzip data is cut short or has trailing bytes")
    return out


def header(kind: str, a: int, b: int, c: int) -> bytes:
    return struct.pack("<4sIII", contract()["kinds"][kind]["magic"].encode("ascii"), a, b, c)


def check_asset(kind: str, raw: bytes, rows: int | None = None) -> dict:
    """Raise BrainError unless raw is a whole asset of this kind: magic, header values, exact
    length and value ranges. Returns the header fields by name. Structure only: an asset holds
    numbers, never text, so this is the privacy check too (a byte scan would only find noise)."""
    c = contract()
    if kind not in c["kinds"]:
        raise BrainError(f"not a brain asset kind: {kind!r}")
    spec = c["kinds"][kind]
    raw = bytes(raw) if isinstance(raw, (bytes, bytearray, memoryview)) else None
    if raw is None or len(raw) < c["header_bytes"]:
        raise BrainError(f"{kind}: shorter than the {c['header_bytes']}-byte header")
    magic, a, b, k = struct.unpack("<4sIII", raw[:c["header_bytes"]])
    if magic != spec["magic"].encode("ascii"):
        raise BrainError(f"{kind}: magic {magic!r}, expected {spec['magic']}")
    head = dict(zip(spec["header"], (a, b, k)))
    if kind == "frames":
        if head["vertices"] != c["vertices"] or head["levels"] != c["levels"]:
            raise BrainError(f"frames: header {head} is not {c['vertices']} vertices at {c['levels']} levels")
        if not 1 <= head["rows"] <= c["rows_max"]:
            raise BrainError(f"frames: {head['rows']} rows, expected 1 to {c['rows_max']}")
        if rows is not None and head["rows"] != rows:
            raise BrainError(f"frames: {head['rows']} rows, the page has {rows} seconds")
        want = raw_size("frames", head["rows"])
    elif kind == "mesh":
        if head["vertices_per_side"] != c["vertices_per_side"] or head["faces_per_side"] != c["faces_per_side"] \
                or not 1 <= head["version"] <= 999:
            raise BrainError(f"mesh: header {head} is not fsaverage5")
        want = raw_size("mesh")
    else:
        if head["vertices"] != c["vertices"] or head["hcp_areas"] != c["hcp_areas"] \
                or head["yeo_networks"] != c["yeo_networks"]:
            raise BrainError(f"atlas: header {head} is not {c['vertices']} vertices, 180 areas, 7 networks")
        want = raw_size("atlas")
    if len(raw) != want:
        raise BrainError(f"{kind}: {len(raw)} bytes, expected exactly {want}")
    body = raw[c["header_bytes"]:]
    if kind == "frames":
        q = np.frombuffer(body, dtype="<i1")
        if q.size and int(q.min()) < -c["levels"]:
            raise BrainError("frames: a value below -127 (never used)")
    elif kind == "mesh":
        nv, nf = c["vertices_per_side"], c["faces_per_side"]
        coords = np.frombuffer(body, dtype="<f4", count=2 * nv * 3)
        faces = np.frombuffer(body, dtype="<u2", count=2 * nf * 3, offset=2 * nv * 3 * 4)
        sulc = np.frombuffer(body, dtype="<f4", count=2 * nv, offset=2 * nv * 3 * 4 + 2 * nf * 3 * 2)
        if not (np.isfinite(coords).all() and np.isfinite(sulc).all()):
            raise BrainError("mesh: a coordinate or depth is not a finite number")
        if int(faces.max()) >= nv:
            raise BrainError("mesh: a face index is outside its side")
    else:
        n = c["vertices"]
        hcp = np.frombuffer(body, dtype="u1", count=n)
        yeo = np.frombuffer(body, dtype="u1", count=n, offset=n)
        if int(hcp.max()) > c["hcp_areas"] or int(yeo.max()) > c["yeo_networks"]:
            raise BrainError("atlas: a lookup value outside 0..180 or 0..7")
    return head


def check_key(kind: str, key: str) -> None:
    if kind_of(key) != kind:
        raise BrainError(f"not a {kind} asset key: {key!r}")


def pack(kind: str, key: str, raw: bytes) -> Asset:
    """Check raw and the key, then gzip it into an Asset."""
    check_key(kind, key)
    check_asset(kind, raw)
    data = gz(raw)
    if len(data) > contract()["stored_bytes"]["max"]:
        raise BrainError(f"{key}: {len(data)} gzip bytes, over the {contract()['stored_bytes']['max']} byte limit")
    return Asset(key, kind, _c("mime"), bytes(raw), data, hashlib.sha256(data).hexdigest())


def stored_problems(key, kind, mime, data, raw_bytes, digest, rows: int | None = None) -> tuple[list[str], bytes | None]:
    """Every problem with one stored asset (as a database row or a bundle entry holds it), and its
    decompressed bytes when they could be read. Key, kind and mime agree; sha256(data) is the hash;
    the gzip unpacks to raw_bytes; the structure check passes."""
    c = contract()
    out, raw = [], None
    where = f"asset {key}"
    if kind_of(key) is None:
        out.append(f"{where}: not a brain asset key")
    elif kind_of(key) != kind:
        out.append(f"{where}: stored as kind {kind!r}, its key says {kind_of(key)!r}")
    if mime != c["mime"]:
        out.append(f"{where}: stored as {mime!r}, not {c['mime']}")
    data = bytes(data) if isinstance(data, (bytes, bytearray, memoryview)) else b""
    if not c["stored_bytes"]["min"] <= len(data) <= c["stored_bytes"]["max"]:
        out.append(f"{where}: {len(data)} stored bytes, outside {c['stored_bytes']['min']} to {c['stored_bytes']['max']}")
    if hashlib.sha256(data).hexdigest() != digest:
        out.append(f"{where}: hash does not match its bytes")
    try:
        raw = gunzip(data)
    except BrainError as e:
        out.append(f"{where}: {e}")
        return out, None
    if len(raw) != raw_bytes:
        out.append(f"{where}: unpacks to {len(raw)} bytes, raw_bytes says {raw_bytes}")
    if kind in c["kinds"]:
        try:
            check_asset(kind, raw, rows)
        except BrainError as e:
            out.append(f"{where}: {e}")
    return out, raw


# ---------------------------------------------------------------- the atlas

def _int_list(doc, name, n, lo, hi):
    v = doc
    for part in name.split("."):
        v = v.get(part) if isinstance(v, dict) else None
    if not isinstance(v, list) or len(v) != n or not all(isinstance(x, int) and not isinstance(x, bool)
                                                         and lo <= x <= hi for x in v):
        raise BrainError(f"atlas file: {name} must be {n} whole numbers from {lo} to {hi}")
    return v


def parse_atlas(doc) -> dict:
    """An atlas-v1.json document, checked, as the lists the page holds plus numpy lookups."""
    if not isinstance(doc, dict):
        raise BrainError("atlas file is not a JSON object")
    version, masks_version = doc.get("version"), doc.get("masks_version")
    if not isinstance(version, str) or not re.match(r"^atlas-v\d{1,3}$", version):
        raise BrainError(f"atlas file version {version!r} is not atlas-v<n>")
    if not isinstance(masks_version, str) or not re.match(r"^masks-v\d{1,3}$", masks_version):
        raise BrainError(f"atlas file names no masks version ({masks_version!r})")
    hcp, yeo = doc.get("hcp") or {}, doc.get("yeo") or {}
    labels = hcp.get("labels")
    if not isinstance(labels, list) or len(labels) != 180 or len(set(labels)) != 180 \
            or not all(isinstance(x, str) and x for x in labels):
        raise BrainError("atlas file: hcp.labels must be 180 different codes")
    ylabels = yeo.get("labels")
    if not isinstance(ylabels, list) or len(ylabels) != 7 or len(set(ylabels)) != 7:
        raise BrainError("atlas file: yeo.labels must be 7 different names")
    network = _int_list(doc, "hcp.network", 180, 1, 7)
    n_left = _int_list(doc, "hcp.n_left", 180, 1, N_HEMI)
    n_right = _int_list(doc, "hcp.n_right", 180, 1, N_HEMI)
    order = _int_list(doc, "order", 180, 0, 179)
    if sorted(order) != list(range(180)):
        raise BrainError("atlas file: order is not a permutation of the 180 areas")
    if order != sorted(range(180), key=lambda i: (network[i], i)):
        raise BrainError("atlas file: order is not Yeo network, then Glasser index")
    line = hcp.get("line")
    if not isinstance(line, list) or len(line) != 180 or not all(x is None or x in LINE_KEYS for x in line):
        raise BrainError("atlas file: hcp.line must be 180 line keys or nulls")
    hl = np.asarray(_int_list(doc, "hcp_lookup", N_V, 0, 180), dtype=np.uint8)
    yl = np.asarray(_int_list(doc, "yeo_lookup", N_V, 0, 7), dtype=np.uint8)
    counts_l = np.bincount(hl[:N_HEMI], minlength=181)[1:]
    counts_r = np.bincount(hl[N_HEMI:], minlength=181)[1:]
    if counts_l.tolist() != n_left or counts_r.tolist() != n_right:
        raise BrainError("atlas file: n_left/n_right do not match the lookup")
    return {
        "version": version, "masks_version": masks_version,
        "hcp_name": hcp.get("name"), "yeo_name": yeo.get("name"),
        "labels": list(labels), "network": network, "line": list(line), "n_left": n_left, "n_right": n_right,
        "order": order, "yeo_labels": list(ylabels), "hcp_lookup": hl, "yeo_lookup": yl,
        "left_idx": [np.nonzero(hl[:N_HEMI] == k)[0] for k in range(1, 181)],
        "right_idx": [N_HEMI + np.nonzero(hl[N_HEMI:] == k)[0] for k in range(1, 181)],
        "yeo_idx": [np.nonzero(yl == k)[0] for k in range(1, 8)],
    }


@functools.lru_cache(maxsize=4)
def _atlas_cached(path: str, mtime_ns: int, size: int) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BrainError(f"atlas file could not be read ({type(e).__name__})") from None
    return parse_atlas(doc)


def load_atlas(path=None) -> dict:
    path = Path(path or ATLAS_JSON)
    if not path.is_file():
        raise BrainError(f"{path.name} not found: run scoring/build_atlas.py (uv run --no-project --with nibabel "
                         "--with numpy python -I scoring/build_atlas.py)")
    st = path.stat()
    return _atlas_cached(str(path.resolve()), st.st_mtime_ns, st.st_size)


def atlas_block(atlas: dict) -> dict:
    """The atlas fields a brain page holds (without the asset key, hash and size)."""
    return {"version": atlas["version"],
            "hcp": {"name": atlas["hcp_name"], "labels": atlas["labels"], "network": atlas["network"],
                    "line": atlas["line"], "n_left": atlas["n_left"], "n_right": atlas["n_right"]},
            "yeo": {"name": atlas["yeo_name"], "labels": atlas["yeo_labels"]},
            "order": atlas["order"]}


# ---------------------------------------------------------------- the binaries

def frames_raw(q) -> bytes:
    q = np.ascontiguousarray(q, dtype="<i1")
    if q.ndim != 2 or q.shape[1] != N_V:
        raise BrainError(f"frames: shape {q.shape}, expected (rows, {N_V})")
    return header("frames", q.shape[0], N_V, _c("levels")) + q.tobytes()


def mesh_raw(mesh: dict, version: int = MESH_VERSION) -> bytes:
    """TBM1 from the arrays scoring/score.py load_mesh returns. Faces are wound so the cross
    product points outward (as score.py _hemi_polys turns them)."""
    parts = {}
    for side in ("left", "right"):
        coords = np.asarray(mesh[f"infl_{side}"], dtype=np.float64)
        faces = np.asarray(mesh[f"faces_{side}"], dtype=np.int64)
        sulc = np.asarray(mesh[f"sulc_{side}"], dtype=np.float64)
        if coords.shape != (N_HEMI, 3) or faces.shape != (N_FACES, 3) or sulc.shape != (N_HEMI,):
            raise BrainError(f"mesh {side}: not fsaverage5 ({coords.shape}, {faces.shape}, {sulc.shape})")
        if faces.min() < 0 or faces.max() >= N_HEMI:
            raise BrainError(f"mesh {side}: a face index is outside its side")
        v = coords[faces]
        n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        if float(np.sum(n * (v.mean(axis=1) - coords.mean(axis=0)), axis=1).mean()) < 0:
            faces = faces[:, [0, 2, 1]]
        parts[side] = (coords.astype("<f4"), faces.astype("<u2"), sulc.astype("<f4"))
    body = b"".join(parts[s][0].tobytes() for s in ("left", "right")) \
        + b"".join(parts[s][1].tobytes() for s in ("left", "right")) \
        + b"".join(parts[s][2].tobytes() for s in ("left", "right"))
    return header("mesh", N_HEMI, N_FACES, version) + body


def atlas_raw(atlas: dict) -> bytes:
    return header("atlas", N_V, 180, 7) + atlas["hcp_lookup"].astype("u1").tobytes() \
        + atlas["yeo_lookup"].astype("u1").tobytes()


def load_mesh(path=None) -> dict:
    try:
        return scoring().load_mesh(Path(path or MESH_NPZ))
    except scoring().ScoreError as e:
        raise BrainError(str(e)) from None


@functools.lru_cache(maxsize=4)
def _shared_cached(atlas_sig, mesh_sig) -> tuple:
    atlas = load_atlas(atlas_sig[0])
    mesh = pack("mesh", mesh_key(), mesh_raw(load_mesh(mesh_sig[0])))
    return mesh, pack("atlas", atlas_key(atlas["version"]), atlas_raw(atlas))


def _sig(path):
    p = Path(path)
    st = p.stat()
    return (str(p.resolve()), st.st_mtime_ns, st.st_size)


def shared_assets(atlas_path=None, mesh_path=None) -> dict[str, Asset]:
    """The mesh and atlas assets every brain page shares, by key."""
    atlas_path, mesh_path = Path(atlas_path or ATLAS_JSON), Path(mesh_path or MESH_NPZ)
    load_atlas(atlas_path)
    if not mesh_path.is_file():
        raise BrainError(f"{mesh_path.name} not found: rebuild it with scoring/build_masks.py")
    mesh, atlas = _shared_cached(_sig(atlas_path), _sig(mesh_path))
    return {mesh.key: mesh, atlas.key: atlas}


# ---------------------------------------------------------------- the maths

def quantise(X, cortex) -> tuple[np.ndarray, float, float]:
    """(q int8 [rows][20484], vmax, clipped share) on one scale for the whole reel."""
    X = np.asarray(X, dtype=np.float64)
    a = np.abs(X[:, np.asarray(cortex, dtype=bool)])
    vmax = round(float(np.percentile(a, PERCENTILE)), 6) if a.size else 0.0
    if not (math.isfinite(vmax) and vmax > 0):
        raise BrainError("the model output is zero over the cortex: no colour scale")
    if vmax > 10:
        raise BrainError(f"vmax {vmax} is over 10: not TRIBE model output")
    levels = _c("levels")
    q = np.clip(np.rint(X / vmax * levels), -levels, levels).astype(np.int8)
    clipped = round(float(np.mean(a > vmax)), 4)
    if clipped > CLIP_MAX:
        raise BrainError(f"{clipped:.2%} of cortex values sit past the scale (over {CLIP_MAX:.0%})")
    return q, vmax, clipped


def _r4(values) -> list:
    r = scoring()._r
    return [r(v) for v in np.asarray(values, dtype=np.float64).tolist()]


def area_means(X, atlas: dict, line_vertices: dict) -> dict:
    """Signed means of the model output per area and second, 4 dp: HCP per side in atlas label
    order, Yeo-7 over both sides, and the four lines over their masks-v1 vertices."""
    X = np.asarray(X, dtype=np.float64)
    return {
        "hcp_left": [_r4(X[:, idx].mean(axis=1)) for idx in atlas["left_idx"]],
        "hcp_right": [_r4(X[:, idx].mean(axis=1)) for idx in atlas["right_idx"]],
        "yeo": [_r4(X[:, idx].mean(axis=1)) for idx in atlas["yeo_idx"]],
        "lines": {k: _r4(X[:, np.asarray(line_vertices[k], dtype=np.int64)].mean(axis=1)) for k in LINE_KEYS},
    }


def make_page(job: str, shortcode, precision, masks_version: str, time_s, X, atlas: dict, line_vertices: dict,
              shared: dict[str, Asset]) -> tuple[dict, dict[str, Asset]]:
    """The brain page and its assets from one job's per-vertex rows X (rows, 20484)."""
    X = np.asarray(X, dtype=np.float64)
    q, vmax, clipped = quantise(X, atlas["hcp_lookup"] != 0)
    frames = pack("frames", frames_key(job), frames_raw(q))
    mesh, atl = shared[mesh_key()], shared[atlas_key(atlas["version"])]
    s = scoring()
    page = {
        "v": V,
        "job_id": job,
        "shortcode": shortcode,
        "framing": FRAMING,
        "masks_version": masks_version,
        "precision": precision,
        "time_s": [float(t) for t in time_s],
        "scale": {"mode": "within-reel", "label": SCALE_LABEL, "vmax": vmax, "percentile": PERCENTILE,
                  "pooled": POOLED, "levels": _c("levels"), "colormap": s.BRAIN_CMAP,
                  "grey_below": s.BRAIN_GREY_BELOW, "full_at": s.BRAIN_FULL_AT, "clipped_share": clipped},
        "frames": frames.ref(),
        "mesh": mesh.ref(),
        "atlas": {**atl.ref(), **atlas_block(atlas)},
        "areas": area_means(X, atlas, line_vertices),
    }
    return page, {frames.key: frames, mesh.key: mesh, atl.key: atl}


# ---------------------------------------------------------------- one job

def _refuse(job, msg):
    raise BrainError(f"brain {job}: {msg}")


def build(job: str, link: dict | None = None, *, atlas_path=None, masks_path=None,
          mesh_path=None) -> tuple[dict, dict[str, Asset]]:
    """One linked job's brain page and its assets {key: Asset} (frames, mesh, atlas)."""
    if not isinstance(job, str) or not JOB_RE.fullmatch(job):
        raise BrainError(f"not a TRIBE job id: {job!r}")
    d = store.OUTPUTS / job
    try:
        report = R._load_json(d / "report.json", f"{job} report.json")
        meta = R._load_json(d / "predict_meta.json", f"{job} predict_meta.json", required=False)
        R.validate_report(report, meta)
    except R.RenderError as e:
        _refuse(job, str(e))
    if report.get("job_id") != job:
        _refuse(job, "report.json names another job")
    atlas = load_atlas(atlas_path)
    s = scoring()
    try:
        masks = s.load_masks(Path(masks_path or MASKS_JSON))
    except s.ScoreError as e:
        _refuse(job, str(e))
    if report.get("masks_version") != atlas["masks_version"] or masks["version"] != atlas["masks_version"]:
        _refuse(job, f"masks version {report.get('masks_version')!r} (report) / {masks['version']!r} (masks file) "
                     f"is not the atlas's {atlas['masks_version']!r}: rebuild the atlas or rescore")
    shared = shared_assets(atlas_path, mesh_path)
    preds = d / "preds.npy"
    if not preds.is_file():
        _refuse(job, "preds.npy not found")
    try:
        P = np.load(preds, allow_pickle=False)
        s.check_preds(P)
    except (OSError, ValueError) as e:
        _refuse(job, f"preds.npy could not be read ({type(e).__name__})")
    except s.ScoreError as e:
        _refuse(job, str(e))
    rows = int(P.shape[0])
    if rows != len(report["time_s"]):
        _refuse(job, f"{rows} preds rows for {len(report['time_s'])} seconds in report.json")
    if rows > _c("rows_max"):
        _refuse(job, f"{rows} rows: over the {_c('rows_max')} s a brain view holds")
    X = P.astype(np.float64)
    for k in LINE_KEYS:
        z = s.zscore(X[:, masks["lines"][k]].mean(axis=1))
        rep = (report["lines"][k] or {}).get("raw_z")
        if not isinstance(rep, list) or len(rep) != rows or not all(R._finite(v) for v in rep):
            _refuse(job, f"report.json lines.{k}.raw_z is missing or not {rows} numbers")
        gap = float(np.max(np.abs(z - np.asarray(rep, dtype=np.float64))))
        if gap > RAW_Z_TOL:
            _refuse(job, f"the {k} line's within-reel z differs from report.json by {gap:.4f}: "
                         "these preds and this report do not belong together")
    link = link or {}
    sc = link.get("shortcode") or R.shortcode_of(str((report.get("source") or {}).get("source_url") or ""))
    precision = (meta or {}).get("precision")
    page, assets = make_page(job, sc if sc and store.SHORTCODE_RE.match(sc) else None,
                             precision if precision in ("fp32", "bf16") else None, atlas["masks_version"],
                             report["time_s"], X, atlas, masks["lines"], shared)
    size = len(json.dumps(page, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    if size > PAGE_MAX:
        _refuse(job, f"the page is {size} bytes, over {PAGE_MAX}")
    return page, assets


def page_problems(page: dict, atlas_path=None) -> list[str]:
    """Structure checks on a schema-valid brain page: every series is one value per second, the
    atlas is atlas-v1.json exactly (codes, names, order), the asset keys belong to this job and
    the sizes match the layouts. Never quotes a value."""
    job = page.get("job_id")
    where = f"brain/{job}"
    out = []
    t = len(page.get("time_s") or [])
    areas = page.get("areas") or {}
    for name in ("hcp_left", "hcp_right", "yeo"):
        bad = [i for i, row in enumerate(areas.get(name) or []) if len(row) != t]
        if bad:
            out.append(f"{where} /areas/{name}: {len(bad)} row(s) are not one value per second")
    for k in LINE_KEYS:
        if len((areas.get("lines") or {}).get(k) or []) != t:
            out.append(f"{where} /areas/lines/{k}: not one value per second")
    frames, mesh, atl = page.get("frames") or {}, page.get("mesh") or {}, page.get("atlas") or {}
    if frames.get("key") != frames_key(job):
        out.append(f"{where} /frames/key: not this job's frames (nothing spans two jobs)")
    if frames.get("bytes") != raw_size("frames", t):
        out.append(f"{where} /frames/bytes: not {t} rows of {N_V} values")
    if mesh.get("key") != mesh_key() or mesh.get("bytes") != raw_size("mesh"):
        out.append(f"{where} /mesh: not the {mesh_key()} layout")
    if atl.get("bytes") != raw_size("atlas"):
        out.append(f"{where} /atlas/bytes: not the atlas layout")
    try:
        atlas = load_atlas(atlas_path)
    except BrainError as e:
        return out + [f"{where} /atlas: {e}"]
    if atl.get("key") != atlas_key(atlas["version"]):
        out.append(f"{where} /atlas/key: not {atlas_key(atlas['version'])}")
    want = atlas_block(atlas)
    for name, value in (("version", want["version"]), ("hcp", want["hcp"]), ("yeo", want["yeo"]),
                        ("order", want["order"])):
        if atl.get(name) != value:
            out.append(f"{where} /atlas/{name}: differs from {Path(atlas_path or ATLAS_JSON).name}")
    if page.get("masks_version") != atlas["masks_version"]:
        out.append(f"{where} /masks_version: not the atlas's masks version")
    size = len(json.dumps(page, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    if size > PAGE_MAX:
        out.append(f"{where}: {size} bytes, over {PAGE_MAX}")
    return out


# ---------------------------------------------------------------- synthetic data (tests, web fixture)

def schema_codes() -> tuple[list[str], list[str]]:
    """The 180 HCP codes and 7 Yeo labels the brain schema allows, in atlas order."""
    s = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["properties"]["atlas"]["properties"]
    return (list(s["hcp"]["properties"]["labels"]["items"]["enum"]),
            list(s["yeo"]["properties"]["labels"]["items"]["enum"]))


def spec_line_parcels() -> dict[str, list[str]]:
    """The four lines' HCP codes (SCORING 9.1, as masks-v1.json lists them)."""
    doc = json.loads(SPEC_MASKS.read_text(encoding="utf-8"))
    return {k: list(doc["lines"][k]["parcels"]) for k in LINE_KEYS}


def synthetic_atlas(line_parcels: dict | None = None, codes=None, yeo_labels=None) -> dict:
    """An atlas-v1.json-shaped document with made-up lookups: per side, vertex i belongs to area
    1 + i % 186 when i % 186 < 180 (else the medial wall), and area k to network 1 + (k - 1) * 7 // 180.
    Real codes and names, synthetic geometry: for tests and the web fixture only."""
    s_codes, s_yeo = schema_codes()
    codes, yeo_labels = list(codes or s_codes), list(yeo_labels or s_yeo)
    line_parcels = line_parcels if line_parcels is not None else spec_line_parcels()
    i = np.arange(N_HEMI)
    side = np.where((i % 186) < 180, (i % 186) + 1, 0)
    hcp = np.concatenate([side, side])
    network = [1 + (k * 7) // 180 for k in range(180)]
    yeo = np.where(hcp > 0, np.asarray([0] + network)[hcp], 0)
    line_of = {p: k for k in LINE_KEYS for p in line_parcels.get(k, [])}
    n = np.bincount(side, minlength=181)[1:].tolist()
    return {
        "version": "atlas-v1", "masks_version": "masks-v1", "mesh": "synthetic",
        "hcp": {"name": "HCP-MMP1.0 (Glasser et al., 2016)", "labels": codes, "network": network,
                "line": [line_of.get(c) for c in codes], "n_left": n, "n_right": n},
        "yeo": {"name": "Yeo-7 networks (Yeo et al., 2011)", "labels": yeo_labels},
        "order": sorted(range(180), key=lambda k: (network[k], k)),
        "hcp_lookup": [int(x) for x in hcp], "yeo_lookup": [int(x) for x in yeo],
    }


def synthetic_masks(atlas_doc: dict) -> dict:
    """A masks-v1.json-shaped document whose lines are the synthetic atlas's line areas."""
    hcp = np.asarray(atlas_doc["hcp_lookup"])
    lines = {}
    for k in LINE_KEYS:
        ks = [i + 1 for i, ln in enumerate(atlas_doc["hcp"]["line"]) if ln == k]
        lines[k] = {"parcels": [atlas_doc["hcp"]["labels"][j - 1] for j in ks],
                    "vertices": [int(v) for v in np.nonzero(np.isin(hcp, ks))[0]]}
    return {"version": atlas_doc["masks_version"], "lines": lines, "crosscheck": {}}


def synthetic_mesh() -> dict:
    """Arrays shaped like fsaverage5 (points on a sphere, made-up faces): no FreeSurfer data."""
    i = np.arange(N_HEMI, dtype=np.float64)
    z = 1 - 2 * (i + 0.5) / N_HEMI
    r = np.sqrt(1 - z * z)
    phi = i * math.pi * (3 - math.sqrt(5))
    pts = np.stack([40 * r * np.cos(phi), 100 * r * np.sin(phi), 70 * z], axis=1).astype(np.float32)
    j = np.arange(N_FACES)
    faces = np.stack([j % N_HEMI, (j + 1) % N_HEMI, (j + 97) % N_HEMI], axis=1).astype(np.int32)
    sulc = np.sin(i / 37.0).astype(np.float32)
    return {f"{k}_{s}": v for s in ("left", "right") for k, v in (("infl", pts), ("faces", faces), ("sulc", sulc))}


def synthetic_page(time_s=None, job: str = SYNTH_JOB, shortcode: str | None = SYNTH_SC) -> dict:
    """A schema-valid brain page with made-up values, for web/fixtures/brain.json: real HCP codes
    and Yeo names, a synthetic atlas and mesh, and every vertex of an area set to that area's
    made-up wave (so the area means are the waves and the frames follow them)."""
    time_s = [float(t) for t in (time_s if time_s is not None else range(6))]
    T = len(time_s)
    doc = synthetic_atlas()
    atlas = parse_atlas(doc)
    t = np.arange(T, dtype=np.float64)
    X = np.zeros((T, N_V))
    for k in range(180):
        net = atlas["network"][k]
        for side, idx in ((0, atlas["left_idx"][k]), (1, atlas["right_idx"][k])):
            wave = (0.22 * np.sin(0.29 * t + 0.8 * net) + 0.11 * np.sin(0.13 * t * (1 + (k % 5) / 6) + 0.7 * k + side)
                    + 0.03 * ((k % 3) - 1))
            X[:, idx] = np.round(wave, 4)[:, None]
    masks = synthetic_masks(doc)
    shared = {mesh_key(): pack("mesh", mesh_key(), mesh_raw(synthetic_mesh())),
              atlas_key(atlas["version"]): pack("atlas", atlas_key(atlas["version"]), atlas_raw(atlas))}
    lines = {k: np.asarray(masks["lines"][k]["vertices"]) for k in LINE_KEYS}
    page, _ = make_page(job, shortcode, None, "masks-v1", time_s, X, atlas, lines, shared)
    return page


FIXTURE = WEB / "fixtures" / "brain.json"
TRIBE_FIXTURE = WEB / "fixtures" / "tribe.json"


def fixture_page() -> dict:
    """web/fixtures/brain.json as it should be: the synthetic page on the synthetic tribe fixture's
    job, reel and seconds (so the web's timeline, brain and areas share one second)."""
    tribe = json.loads(TRIBE_FIXTURE.read_text(encoding="utf-8"))
    return synthetic_page(tribe["time_s"], job=tribe["job_id"], shortcode=tribe["shortcode"])


def fixture_text(page: dict) -> str:
    text = json.dumps(page, indent=1, ensure_ascii=False)
    num = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
    return re.sub(r"\[(\s*" + num + r"(?:,\s*" + num + r")*\s*)\]",
                  lambda m: "[" + ",".join(x.strip() for x in m.group(1).split(",")) + "]", text) + "\n"


def write_fixture(log=print) -> Path:
    """Write web/fixtures/brain.json (synthetic values only: no preds, no FreeSurfer data)."""
    FIXTURE.write_text(fixture_text(fixture_page()), encoding="utf-8", newline="\n")
    log(f"wrote {FIXTURE.relative_to(ROOT).as_posix()} (synthetic)")
    return FIXTURE


# ---------------------------------------------------------------- CLI (laptop only)

def _linked(job: str) -> str | None:
    for reel in store.list_reels():
        if isinstance(reel.get("tribe"), dict) and reel["tribe"].get("job_id") == job:
            return reel.get("shortcode")
    return None


def show(job: str, log=print) -> dict:
    """Sizes, rows and the scale (no values) for one job, built in memory."""
    sc = _linked(job)
    page, assets = build(job, {"shortcode": sc} if sc else None)
    body = json.dumps(page, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    log(f"brain view for {job}: {len(page['time_s'])} rows, vmax {page['scale']['vmax']} "
        f"(p{PERCENTILE} |x| over {POOLED}), {page['scale']['clipped_share']:.2%} past the scale, "
        f"precision {page['precision'] or 'not recorded'}; "
        + (f"linked to reel {sc}" if sc else "not linked to a reel: sync never hosts it"))
    for a in assets.values():
        log(f"  {a.kind:6s} {a.key:42s} raw {a.raw_bytes:>10,} B   gzip {len(a.data):>10,} B")
    log(f"  page   brain/{job:35s} json {len(body):>9,} B   gzip {len(gz(body)):>10,} B")
    return {"rows": len(page["time_s"]), "vmax": page["scale"]["vmax"], "page_bytes": len(body),
            "assets": {a.key: (a.raw_bytes, len(a.data)) for a in assets.values()}}


def vertices(job: str, out_dir, log=print) -> Path:
    """Every surface point of one job at full precision, as a CSV in out_dir (never under web/)."""
    out_dir = Path(out_dir).resolve()
    web = WEB.resolve()
    if out_dir == web or web in out_dir.parents:
        raise BrainError("web/ holds synthetic fixtures only: write the per-vertex file somewhere else")
    page, _ = build(job)
    atlas = load_atlas()
    P = np.load(store.OUTPUTS / job / "preds.npy", allow_pickle=False).astype(np.float32)
    names = atlas["labels"]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"tribe-{job}-vertices.csv"
    head = [f"# {FOOTER_12E}",
            f"# job {job}, {len(page['time_s'])} seconds, precision {page['precision'] or 'not recorded'}, "
            f"{page['masks_version']}, {atlas['version']}",
            "# TRIBE v2 model output per surface point (fsaverage5), full precision; relative only",
            "# one reel only: never put two reels' numbers side by side",
            "# atlas names mark places on the cortex, not feelings or functions",
            "# stays on this laptop"]
    cols = "vertex,hemisphere,area,network,feeds_line," + ",".join(f"s{int(t)}" for t in page["time_s"])
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(head) + "\n" + cols + "\n")
        for v in range(N_V):
            k, y = int(atlas["hcp_lookup"][v]), int(atlas["yeo_lookup"][v])
            area = names[k - 1] if k else "medial wall"
            net = atlas["yeo_labels"][y - 1] if y else "medial wall"
            line = (atlas["line"][k - 1] or "") if k else ""
            vals = ",".join(format(float(x), ".9g") for x in P[:, v])
            f.write(f"{v},{'left' if v < N_HEMI else 'right'},{area},\"{net}\",{line},{vals}\n")
    log(f"wrote {path} ({N_V} rows; it stays on this laptop)")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strategist.brain_assets",
                                 description="The brain view's data for one TRIBE job (laptop only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sh = sub.add_parser("show", help="sizes, rows and the colour scale (no values)")
    sh.add_argument("job")
    ve = sub.add_parser("vertices", help="every surface point at full precision, as a CSV (never under web/)")
    ve.add_argument("job")
    ve.add_argument("--out", required=True)
    sub.add_parser("fixture", help="rewrite web/fixtures/brain.json from synthetic values (no real data)")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "show":
            show(args.job)
        elif args.cmd == "fixture":
            write_fixture()
        else:
            vertices(args.job, args.out)
        return 0
    except (BrainError, store.StoreError) as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
