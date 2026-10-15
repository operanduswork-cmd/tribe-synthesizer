"""Build the atlas lookups for the brain view (atlas-v1): HCP-MMP1 (180 areas a side) and
Yeo-7 networks, per fsaverage5 vertex, plus each area's network, line and size.

Build-time only, from the annots build_masks.py already cached (never downloads). Run from
the project folder:

    uv run --no-project --with nibabel --with numpy python -I scoring/build_atlas.py

It reuses build_masks.py's own parser (the copy of tribev2.utils.get_hcp_labels and the Yeo
reader), so the codes and vertices are exactly the ones masks-v1 was built from. It never
rewrites masks-v1.json or the mesh. It writes scoring/masks/atlas-v1.json:

  hcp.labels     the 180 HCP-MMP1 codes in the annot's colour-table order (Glasser index 1..180)
  hcp.network    each area's majority Yeo-7 network (1..7) over its vertices, both sides
                 (a tie, as for a10p and p10p, goes to the left side's majority)
  hcp.line       the line (masks-v1) each area belongs to, or null
  hcp.n_left/n_right  vertices per side
  yeo.names      network names verbatim from 7NetworksOrderedNames.csv
  yeo.labels     "Yeo network <k>: <name>", the text the brain view shows
  order          a fixed display order: Yeo network 1..7, then Glasser index (never by value)
  hcp_lookup     per vertex: 0 = medial wall ("???"), k = 1..180 = hcp.labels[k-1] (same code both sides)
  yeo_lookup     per vertex: 0 = medial wall, 1..7

Self-checks (it refuses to write on any failure): the annot hashes equal the ones masks-v1
recorded; each line's areas cover exactly the masks-v1 line vertices; Yeo network 1 and
networks {3, 4} equal the masks-v1 cross-check masks; the medial wall counts are 868/874
(HCP) and 888/881 (Yeo); every area has at least 12 vertices a side.

Atlas names mark places on the cortex, not feelings or functions: the view shows the HCP
short codes and the Yeo names as written, with no glosses.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "masks" / "atlas-v1.json"
MASKS_JSON = HERE / "masks" / "masks-v1.json"

VERSION = "atlas-v1"
BUILT = "2026-10-09"
HCP_NAME = "HCP-MMP1.0 (Glasser et al., 2016)"
YEO_NAME = "Yeo-7 networks (Yeo et al., 2011)"
MEDIAL_HCP = (868, 874)          # "???" vertices, left / right (masks-v1 unknown_labels_skipped)
MEDIAL_YEO = (888, 881)          # FreeSurfer_Defined_Medial_Wall, left / right
MIN_PER_SIDE = 12
SPLIT_SEEN = [29, 27, 23, 24, 14, 23, 40]   # areas per majority network, measured 9 Oct 2026


def load_build_masks():
    """scoring/build_masks.py as a module (python -I leaves the script folder off sys.path)."""
    spec = importlib.util.spec_from_file_location("tribe_build_masks", HERE / "build_masks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def ctab_codes(bm, path, hemi):
    """The parcel codes in the annot's colour-table order, named as hcp_labels_one_hemi names them."""
    import nibabel as nib
    _, _, names = nib.freesurfer.read_annot(str(path), orig_ids=True)
    suffix = "-lh" if hemi == "left" else "-rh"
    out = []
    for raw in names:
        raw = raw.decode("utf-8")
        name = (raw + suffix)[2:].replace("_ROI", "").replace("-rh", "").replace("-lh", "")
        out.append((name, raw))
    return out


def main():
    bm = load_build_masks()
    masks = json.loads(MASKS_JSON.read_text(encoding="utf-8"))
    check(masks.get("version") == "masks-v1", "masks-v1.json has another version")
    N_HEMI, N_TOTAL = bm.N_HEMI, bm.N_TOTAL

    # ---- inputs: cached annots only, hashes as masks-v1 recorded them
    label_dir = bm.CACHE / "mne-subjects" / "fsaverage" / "label"
    hcp_paths = {"left": label_dir / "lh.HCPMMP1.annot", "right": label_dir / "rh.HCPMMP1.annot"}
    yeo_dir = bm.CACHE / "yeo2011-cbig"
    missing = [str(p.relative_to(ROOT)) for p in list(hcp_paths.values()) + [yeo_dir / n for n in bm.YEO_FILES]
               if not p.is_file()]
    check(not missing, f"annots not cached (run scoring/build_masks.py first; nothing is downloaded here): {missing}")
    hcp_sha = {p.name: bm.sha256(p) for p in hcp_paths.values()}
    check(hcp_sha == masks["atlas"]["hcp_mmp1"]["sha256"], "HCP annots differ from the ones masks-v1 was built from")
    yeo_sha = {n: bm.sha256(yeo_dir / n) for n in bm.YEO_FILES}
    check(yeo_sha == masks["atlas"]["yeo7"]["sha256"], "Yeo files differ from the ones masks-v1 was built from")

    # ---- HCP-MMP1: the same dict as masks-v1, codes in colour-table order
    both, left, right, raw_names = bm.get_hcp_labels_both(hcp_paths)
    unknown = bm.unknown_keys(raw_names)
    check(unknown == ["?"], f"unexpected non-parcel labels: {unknown}")
    order_l = [(n, r) for n, r in ctab_codes(bm, hcp_paths["left"], "left") if n not in unknown]
    order_r = [(n, r) for n, r in ctab_codes(bm, hcp_paths["right"], "right") if n not in unknown]
    labels = [n for n, _ in order_l]
    check(labels == [n for n, _ in order_r], "left and right colour tables list the areas in different orders")
    check(all(r == f"L_{n}_ROI" for n, r in order_l) and all(r == f"R_{n}_ROI" for n, r in order_r),
          "colour-table names are not L_<code>_ROI / R_<code>_ROI")
    check(len(labels) == 180 and len(set(labels)) == 180, f"expected 180 HCP codes, got {len(labels)}")
    check(set(labels) == set(both) - set(unknown), "colour table and label dict disagree")

    hcp_lookup = np.zeros(N_TOTAL, dtype=np.int64)
    seen = np.zeros(N_TOTAL, dtype=np.int64)
    for k, code in enumerate(labels, 1):
        v = np.asarray(both[code], dtype=np.int64)
        hcp_lookup[v] = k
        seen[v] += 1
    seen[np.asarray(both["?"], dtype=np.int64)] += 1
    check(np.all(seen == 1), "a vertex has no HCP label or two")
    medial = (int(np.sum(hcp_lookup[:N_HEMI] == 0)), int(np.sum(hcp_lookup[N_HEMI:] == 0)))
    check(medial == MEDIAL_HCP, f"HCP medial wall counts {medial}, expected {MEDIAL_HCP}")
    n_left = [int(len(left[c])) for c in labels]
    n_right = [int(len(right[c])) for c in labels]
    check(min(n_left) >= MIN_PER_SIDE and min(n_right) >= MIN_PER_SIDE,
          f"an area has fewer than {MIN_PER_SIDE} vertices on a side")

    # ---- Yeo-7 (build_masks.build_yeo reads the cached files; download() returns the cache)
    _, yeo_info, net_of_all = bm.build_yeo()
    names_by_k = {int(k): v for k, v in yeo_info["network_order"].items()}
    check(sorted(names_by_k) == list(range(1, 8)), "Yeo order file is not networks 1..7")
    yeo_names = [names_by_k[k] for k in range(1, 8)]
    k_of = {name: k for k, name in names_by_k.items()}
    yeo_lookup = np.array([k_of.get(str(n), 0) if n else 0 for n in net_of_all], dtype=np.int64)
    medial_y = (int(np.sum(yeo_lookup[:N_HEMI] == 0)), int(np.sum(yeo_lookup[N_HEMI:] == 0)))
    check(medial_y == MEDIAL_YEO, f"Yeo medial wall counts {medial_y}, expected {MEDIAL_YEO}")
    cross = masks["crosscheck"]
    check(np.array_equal(np.nonzero(yeo_lookup == 1)[0], np.asarray(cross["yeo_visual"]["vertices"])),
          "Yeo network 1 differs from the masks-v1 yeo_visual cross-check mask")
    check(np.array_equal(np.nonzero(np.isin(yeo_lookup, (3, 4)))[0],
                         np.asarray(cross["yeo_dorsal_ventral_attention"]["vertices"])),
          "Yeo networks 3 and 4 differ from the masks-v1 attention cross-check mask")

    # ---- per area: majority network over both sides (a tie goes to the left side's majority,
    # then to the lower network number), line
    network = []
    is_left = np.arange(N_TOTAL) < N_HEMI
    for k in range(1, 181):
        inside = (hcp_lookup == k) & (yeo_lookup > 0)
        both_n = np.bincount(yeo_lookup[inside], minlength=8)[1:]
        left_n = np.bincount(yeo_lookup[inside & is_left], minlength=8)[1:]
        check(both_n.sum() > 0, f"{labels[k - 1]}: no vertex inside a Yeo network")
        best = [j for j in range(7) if both_n[j] == both_n.max()]
        network.append(int(max(best, key=lambda j: (left_n[j], -j)) + 1))
    split = [network.count(k) for k in range(1, 8)]
    line_of = {}
    for line, spec in masks["lines"].items():
        verts = set()
        for p in spec["parcels"]:
            check(p in labels, f"{line}: parcel {p!r} is not an HCP code")
            check(p not in line_of, f"{p} is in two lines")
            line_of[p] = line
            verts |= {int(v) for v in both[p]}
        check(sorted(verts) == spec["vertices"], f"{line}: its areas do not cover the masks-v1 vertices exactly")
    line = [line_of.get(c) for c in labels]
    order = sorted(range(180), key=lambda i: (network[i], i))

    doc = {
        "version": VERSION,
        "masks_version": masks["version"],
        "mesh": "fsaverage5",
        "n_vertices": N_TOTAL,
        "vertex_order": masks["vertex_order"],
        "built": BUILT,
        "build_env": {"python": sys.version.split()[0], "numpy": np.__version__,
                      "nibabel": __import__("nibabel").__version__, "script": "scoring/build_atlas.py",
                      "parser": "scoring/build_masks.py hcp_labels_one_hemi, get_hcp_labels_both, build_yeo"},
        "about": "Atlas names mark places on the cortex, not feelings or functions. Areas are shown in this "
                 "fixed order (Yeo network, then Glasser index), never sorted by a value.",
        "hcp": {"name": HCP_NAME, "labels": labels, "network": network, "line": line,
                "n_left": n_left, "n_right": n_right,
                "medial_wall": {"label": "???", "n_left": medial[0], "n_right": medial[1]}},
        "yeo": {"name": YEO_NAME, "names": yeo_names,
                "labels": [f"Yeo network {k}: {n}" for k, n in enumerate(yeo_names, 1)],
                "network_rule": "each HCP area takes the Yeo network most of its vertices (both sides) fall in; "
                                "a tie goes to the left side's majority, then to the lower network number",
                "areas_per_network": split,
                "medial_wall": {"labels": yeo_info["dropped_labels"], "n_left": medial_y[0], "n_right": medial_y[1]}},
        "order": order,
        "hcp_lookup": [int(x) for x in hcp_lookup],
        "yeo_lookup": [int(x) for x in yeo_lookup],
        "sha256": {**hcp_sha, **yeo_sha},
        "licence": {
            "hcp_mmp1": {k: masks["atlas"]["hcp_mmp1"][k] for k in
                         ("name", "dataset_page", "dataset_citation", "paper_citation", "licence")},
            "yeo7": {k: masks["atlas"]["yeo7"][k] for k in ("name", "repo", "commit", "paper_citation", "licence")},
        },
        "checks": {
            "annot_sha256_equal_masks_v1": True,
            "lines_cover_masks_v1_exactly": True,
            "yeo_1_equals_crosscheck_yeo_visual": True,
            "yeo_3_4_equal_crosscheck_attention": True,
            "medial_wall_hcp": list(medial),
            "medial_wall_yeo": list(medial_y),
            "min_vertices_per_side": [min(n_left), min(n_right)],
        },
    }
    text = json.dumps(doc, indent=1, ensure_ascii=False)
    text = re.sub(r"\[(\s*-?\d+(?:,\s*-?\d+)*\s*)\]",
                  lambda m: "[" + ",".join(x.strip() for x in m.group(1).split(",")) + "]", text)
    OUT.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}: 180 areas a side, 7 networks, {N_TOTAL} vertices")
    print(f"  medial wall HCP {medial}, Yeo {medial_y}; smallest area {min(n_left)} left / {min(n_right)} right")
    print(f"  areas per majority network 1..7: {split}"
          + ("" if split == SPLIT_SEEN else f"  (differs from the {SPLIT_SEEN} measured on 9 Oct)"))
    print(f"  lines: {sum(1 for x in line if x)} areas feed a line; self-checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
