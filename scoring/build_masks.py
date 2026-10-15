"""Build the four line masks (masks-v1) from real atlas parcels.

Build-time only. The scoring code later needs only numpy and scipy, never
mne, nibabel or nilearn (docs/SCORING.md 8.5). Run from the project folder:

    uv run --no-project --with mne --with nibabel --with nilearn --with scipy \
        python -I scoring/build_masks.py

Optional: add --verify-mne [SUBJECTS_DIR] to also run the upstream tribev2 code
path (mne.read_labels_from_annot; it needs the full fsaverage subject, a few
hundred MB, so point SUBJECTS_DIR to another folder if you like) and check that
our nibabel copy of get_hcp_labels gives the identical dict.

What it does (SCORING 8.1, 8.5, 9.1, 9.3, 21.2, 21.4):
  1. HCP-MMP1 annots for fsaverage (ico7) via mne.datasets.fetch_hcp_mmp_parcellation,
     read with nibabel, turned into the same dict as tribev2.utils.get_hcp_labels
     (mesh="fsaverage5", combine=False, hemi="both").
  2. The four line masks from the exact parcel names in SCORING 9.1. No wildcards.
     Vertex-index ranges are never used as regions: every vertex comes from a parcel.
  3. Cross-check masks: Yeo-7 (CBIG fsaverage5 annots) and Destrieux (nilearn).
  4. scoring/masks/masks-v1.json and scoring/masks/fsaverage5-mesh.npz.
  5. Cross-check run on the test fixtures (Pearson r of smoothed line means).

Downloads are cached in scoring/.atlas-cache/ and treated as data only.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "scoring" / ".atlas-cache"
OUT_DIR = ROOT / "scoring" / "masks"
MASKS_JSON = OUT_DIR / "masks-v1.json"
MESH_NPZ = OUT_DIR / "fsaverage5-mesh.npz"

N_HEMI = 10242          # fsaverage5 vertices per hemisphere (FSAVERAGE_SIZES upstream)
N_ICO7 = 163842         # fsaverage (ico7) vertices per hemisphere
N_TOTAL = 2 * N_HEMI    # 20484, left first then right (TRIBE output order)

TRIBEV2_COMMIT = "af58661791a351a448a489042a28f6c37e1c14b7"
BUILT = "2026-10-08"

# SCORING 9.1, exact HCP-MMP1 names as keys of get_hcp_labels (no wildcards).
LINES = {
    "seeing": {
        "label": "predicted visual response",
        "parcels": ["V1", "V2", "V3", "V4", "V3A", "V3B", "V6", "V6A", "MT", "MST"],
    },
    "hearing": {
        "label": "predicted auditory response",
        "parcels": ["A1", "LBelt", "MBelt", "PBelt", "A4"],
    },
    "language": {
        "label": "predicted language response",
        "parcels": ["44", "45", "IFSa", "STSdp", "STSvp", "STGa", "TE1a", "A5", "PSL", "SFL", "55b"],
    },
    "attention": {
        "label": "predicted attention-network response",
        "parcels": ["FEF", "LIPv", "LIPd", "VIP", "MIP", "AIP", "IP0", "IP1", "IP2",
                    "TPOJ1", "TPOJ2", "PFm", "IFJa", "IFJp"],
    },
}

# SCORING 9.2: left out of v1 attention; we only report where they fall in Yeo-7.
WATCH_PARCELS = ["PGi", "PGs"]

# ---- atlas sources ---------------------------------------------------------

HCP_URLS = {  # as hard-coded in mne.datasets.fetch_hcp_mmp_parcellation
    "lh": "https://ndownloader.figshare.com/files/5528816",
    "rh": "https://ndownloader.figshare.com/files/5528819",
}

CBIG_COMMIT = "634f676630929a71297852d01dd92a287103e861"  # ThomasYeoLab/CBIG master, 2026-10-01
CBIG_RAW = f"https://raw.githubusercontent.com/ThomasYeoLab/CBIG/{CBIG_COMMIT}"
CBIG_REF = "stable_projects/brain_parcellation/Yeo2011_fcMRI_clustering/1000subjects_reference"
CBIG_SPLIT = f"{CBIG_REF}/Yeo_JNeurophysiol11_SplitLabels"
YEO_FILES = {
    "lh.Yeo2011_7Networks_N1000.annot": f"{CBIG_SPLIT}/fsaverage5/label/lh.Yeo2011_7Networks_N1000.annot",
    "rh.Yeo2011_7Networks_N1000.annot": f"{CBIG_SPLIT}/fsaverage5/label/rh.Yeo2011_7Networks_N1000.annot",
    "lh.Yeo2011_7Networks_N1000.split_components.annot":
        f"{CBIG_SPLIT}/fsaverage5/label/lh.Yeo2011_7Networks_N1000.split_components.annot",
    "rh.Yeo2011_7Networks_N1000.split_components.annot":
        f"{CBIG_SPLIT}/fsaverage5/label/rh.Yeo2011_7Networks_N1000.split_components.annot",
    "7NetworksOrderedNames.csv": f"{CBIG_REF}/7NetworksOrderedNames.csv",
    "Yeo2011_7networks_N1000.split_components.glossary.csv":
        f"{CBIG_SPLIT}/Yeo2011_7networks_N1000.split_components.glossary.csv",
}
YEO_VISUAL = ["Visual"]
YEO_ATTENTION = ["Dorsal Attention", "Salience / Ventral Attention"]

DESTRIEUX_URLS = {  # as hard-coded in nilearn.datasets.fetch_atlas_surf_destrieux
    "lh": "https://www.nitrc.org/frs/download.php/9343/lh.aparc.a2009s.annot",
    "rh": "https://www.nitrc.org/frs/download.php/9342/rh.aparc.a2009s.annot",
}
# Transverse temporal gyrus (Heschl) + planum temporale. Matched exactly below.
DESTRIEUX_AUDITORY = ["G_temp_sup-G_T_transv", "G_temp_sup-Plan_tempo"]

FIXTURES = ["20261008-130514-b670602f", "20260101-000000-demo0000"]
CROSSCHECK_PAIRS = [  # (report key, HCP line, cross-check mask key)
    ("seeing_vs_yeo_visual", "seeing", "yeo_visual"),
    ("attention_vs_yeo_dorsal_ventral", "attention", "yeo_dorsal_ventral_attention"),
    ("hearing_vs_destrieux_auditory", "hearing", "destrieux_auditory"),
]
R_EXPECTED = 0.7  # SCORING 9.3 / 20

ATLAS_INFO = {
    "hcp_mmp1": {
        "name": "HCP-MMP1.0 (Glasser), projected on fsaverage",
        "files": ["lh.HCPMMP1.annot", "rh.HCPMMP1.annot"],
        "urls": HCP_URLS,
        "fetched_via": "mne.datasets.fetch_hcp_mmp_parcellation(accept=True, combine=False)",
        "dataset_page": "https://figshare.com/articles/dataset/HCP-MMP1_0_projected_on_fsaverage/3498446",
        "dataset_citation": "Mills, Kathryn (2016). HCP-MMP1.0 projected on fsaverage. figshare. Dataset. "
                            "https://doi.org/10.6084/m9.figshare.3498446.v2",
        "paper_citation": "Glasser MF, Coalson TS, Robinson EC, Hacker CD, Harwell J, Yacoub E, Ugurbil K, "
                          "Andersson J, Beckmann CF, Jenkinson M, Smith SM, Van Essen DC. A multi-modal "
                          "parcellation of human cerebral cortex. Nature 536(7615):171-178, 2016. "
                          "doi:10.1038/nature18933",
        "licence": {
            "annot_files": "CC BY 4.0 (figshare article 3498446 metadata: "
                           "https://creativecommons.org/licenses/by/4.0/)",
            "parcellation": "WU-Minn HCP Consortium Open Access Data Use Terms. The MNE docstring says use is "
                            "subject to the terms on https://balsa.wustl.edu/WN56; that page shows the same "
                            "Open Access Data Use Terms that mne prints. Clause 4: derived data may be "
                            "redistributed only under these same terms. Clause 5.1 acknowledgement wording: "
                            "\"Data were provided [in part] by the Human Connectome Project, WU-Minn Consortium "
                            "(Principal Investigators: David Van Essen and Kamil Ugurbil; 1U54MH091657) funded "
                            "by the 16 NIH Institutes and Centers that support the NIH Blueprint for "
                            "Neuroscience Research; and by the McDonnell Center for Systems Neuroscience at "
                            "Washington University.\"",
            "accepted_by_script": "accept=True, same as upstream tribev2.utils.get_hcp_labels",
        },
        "read_with": "nibabel.freesurfer.read_annot(orig_ids=True), copy of tribev2.utils.get_hcp_labels",
        "tribev2_function": "tribev2/utils.py get_hcp_labels(mesh='fsaverage5', combine=False, hemi='both') "
                            f"at commit {TRIBEV2_COMMIT}",
    },
    "yeo7": {
        "name": "Yeo2011 7 networks, N1000, fsaverage5",
        "repo": "https://github.com/ThomasYeoLab/CBIG",
        "commit": CBIG_COMMIT,
        "urls": {k: f"{CBIG_RAW}/{v}" for k, v in YEO_FILES.items()},
        "paper_citation": "Yeo BT, Krienen FM, Sepulcre J, Sabuncu MR, Lashkari D, Hollinshead M, Roffman JL, "
                          "Smoller JW, Zollei L., Polimeni JR, Fischl B, Liu H, Buckner RL. The organization of "
                          "the human cerebral cortex estimated by intrinsic functional connectivity. Journal of "
                          "Neurophysiology 106(3):1125-1165, 2011. (as written in the CBIG "
                          "Yeo_JNeurophysiol11_SplitLabels README; doi:10.1152/jn.00338.2011)",
        "licence": "Repository LICENSE.md: MIT License, \"Copyright (c) 2016 Computational Brain Imaging Group "
                   "(CBIG)\". No separate licence for the annot files was found in the "
                   "Yeo_JNeurophysiol11_SplitLabels README (data-specific terms unverified).",
        "network_names_from": "7NetworksOrderedNames.csv (same repo), checked against the label names inside "
                              "the split_components annots",
    },
    "destrieux": {
        "name": "Destrieux 2009 (aparc.a2009s), fsaverage5",
        "urls": DESTRIEUX_URLS,
        "fetched_via": "nilearn.datasets.fetch_atlas_surf_destrieux",
        "paper_citation": "Destrieux C, Fischl B, Dale A, Halgren E. Automatic parcellation of human cortical "
                          "gyri and sulci using standard anatomical nomenclature. NeuroImage 53(1):1-15, 2010. "
                          "doi:10.1016/j.neuroimage.2010.06.010",
        "licence": "unverified (replaced at build time by the 'License' line of the nilearn dataset "
                   "description, quoted as written)",
    },
    "fsaverage5_mesh": {
        "name": "fsaverage5 inflated mesh + sulcal depth bundled with nilearn",
        "fetched_via": "nilearn.datasets.fetch_surf_fsaverage('fsaverage5')",
        "licence": "unverified (FreeSurfer fsaverage shipped inside the nilearn package; replaced at build "
                   "time if the nilearn description has a 'License' line)",
    },
}


# ---- helpers ---------------------------------------------------------------

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest):
    """Fetch url to dest once (cached). Data only: nothing downloaded is executed."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "tribe-build-masks"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        f.write(r.read())
    tmp.replace(dest)
    return dest


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def licence_line(description):
    """The text under a 'License' heading in a nilearn dataset description, or ''."""
    m = re.search(r"License\s*\n-+\s*\n(.+)", str(description))
    return m.group(1).strip() if m else ""


# ---- 1. HCP-MMP1, a copy of tribev2.utils.get_hcp_labels -------------------

def fetch_hcp():
    import mne
    subjects_dir = CACHE / "mne-subjects"
    subjects_dir.mkdir(parents=True, exist_ok=True)
    mne.datasets.fetch_hcp_mmp_parcellation(
        subjects_dir=subjects_dir, accept=True, combine=False, verbose=False)
    label_dir = subjects_dir / "fsaverage" / "label"
    return {"left": label_dir / "lh.HCPMMP1.annot", "right": label_dir / "rh.HCPMMP1.annot"}


def hcp_labels_one_hemi(annot_path, hemi):
    """Same dict as upstream get_hcp_labels(mesh='fsaverage5', combine=False, hemi=hemi).

    Upstream reads the annot through mne.read_labels_from_annot, which itself calls
    nibabel read_annot(orig_ids=True), keeps every ctab entry with >= 1 vertex,
    names it '<name>-lh' / '<name>-rh' and sorts by name. Then upstream does
    name[2:], removes '_ROI', removes '-lh'/'-rh', keeps vertices < 10242 and adds
    10242 on the right hemisphere.
    """
    import nibabel as nib
    annot, ctab, names = nib.freesurfer.read_annot(str(annot_path), orig_ids=True)
    check(annot.shape == (N_ICO7,), f"{annot_path.name}: expected {N_ICO7} vertices, got {annot.shape}")
    suffix = "-lh" if hemi == "left" else "-rh"
    mne_labels = []
    for label_id, raw in zip(ctab[:, -1], names):
        vertices = np.where(annot == label_id)[0]
        if len(vertices) == 0:
            continue
        mne_labels.append((raw.decode("utf-8") + suffix, raw.decode("utf-8"), vertices))
    mne_labels.sort(key=lambda x: x[0])  # mne sort=True

    out, raw_of = {}, {}
    for mne_name, raw, vertices in mne_labels:
        name = mne_name[2:]
        name = name.replace("_ROI", "")
        name = name.replace("-rh", "").replace("-lh", "")
        check(name not in out, f"duplicate key {name!r} in {annot_path.name}")
        out[name] = np.array(vertices)
        raw_of[name] = raw
    check(sum(len(v) for v in out.values()) == N_ICO7, f"{annot_path.name}: labels do not cover {N_ICO7}")
    offset = N_HEMI if hemi == "right" else 0
    out = {k: v[v < N_HEMI] + offset for k, v in out.items()}
    check(sum(len(v) for v in out.values()) == N_HEMI, f"{annot_path.name}: labels do not cover {N_HEMI}")
    return out, raw_of


def get_hcp_labels_both(paths):
    left, raw_left = hcp_labels_one_hemi(paths["left"], "left")
    right, raw_right = hcp_labels_one_hemi(paths["right"], "right")
    check(set(left) == set(right), "left and right HCP keys differ: "
          f"{sorted(set(left) ^ set(right))}")
    both = {k: np.concatenate([left[k], right[k]]) for k in left.keys()}
    # Every fsaverage5 vertex has exactly one label per hemisphere.
    for hemi_dict, lo in ((left, 0), (right, N_HEMI)):
        count = np.zeros(N_HEMI, dtype=int)
        for v in hemi_dict.values():
            check(np.all((v >= lo) & (v < lo + N_HEMI)), "vertex outside its hemisphere")
            np.add.at(count, v - lo, 1)
        check(np.all(count == 1), f"hemisphere at offset {lo}: vertices with label count != 1: "
              f"{int(np.sum(count != 1))}")
    raw_names = {"left": raw_left, "right": raw_right}
    return both, left, right, raw_names


def verify_with_mne(both, subjects_dir):
    """Run the upstream code path itself (mne.read_labels_from_annot) and compare.

    Needs the full fsaverage subject (surf files), so it downloads it into
    subjects_dir (MNE fetch_fsaverage, several hundred MB). Kept optional.
    """
    import mne
    subjects_dir = Path(subjects_dir)
    subjects_dir.mkdir(parents=True, exist_ok=True)
    mne.datasets.fetch_fsaverage(subjects_dir=subjects_dir, verbose=False)
    mne.datasets.fetch_hcp_mmp_parcellation(
        subjects_dir=subjects_dir, accept=True, combine=False, verbose=False)
    res = {}
    for hemi in ("left", "right"):
        labels = mne.read_labels_from_annot("fsaverage", "HCPMMP1", hemi="both",
                                            subjects_dir=subjects_dir, verbose=False)
        d = {}
        for label in labels:
            name, vertices = label.name, np.array(label.vertices)
            name = name[2:]
            name = name.replace("_ROI", "")
            if (hemi == "right" and "-lh" in name) or (hemi == "left" and "-rh" in name):
                continue
            name = name.replace("-rh", "").replace("-lh", "")
            d[name] = np.array(vertices)
        check(sum(len(v) for v in d.values()) == N_ICO7, "mne path: ico7 cover")
        off = N_HEMI if hemi == "right" else 0
        d = {k: v[v < N_HEMI] + off for k, v in d.items()}
        check(sum(len(v) for v in d.values()) == N_HEMI, "mne path: fsaverage5 cover")
        res[hemi] = d
    up = {k: np.concatenate([res["left"][k], res["right"][k]]) for k in res["left"].keys()}
    check(set(up) == set(both), f"mne path keys differ: {sorted(set(up) ^ set(both))}")
    for k in up:
        check(np.array_equal(up[k], both[k]), f"mne path differs for {k}")
    return {"checked": True, "result": "identical dict (keys, vertex arrays, order)",
            "mne_version": mne.__version__, "n_keys": len(up)}


def unknown_keys(raw_names):
    """Labels that are not 'L_<parcel>_ROI' / 'R_<parcel>_ROI' (e.g. '???' medial wall)."""
    bad = set()
    for hemi, prefix in (("left", "L_"), ("right", "R_")):
        for key, raw in raw_names[hemi].items():
            if not (raw.startswith(prefix) and raw.endswith("_ROI")):
                bad.add(key)
    return sorted(bad)


# ---- 2. line masks ---------------------------------------------------------

def build_lines(both, unknown):
    lines, missing = {}, []
    for line, spec in LINES.items():
        miss = [p for p in spec["parcels"] if p not in both or p in unknown]
        if miss:
            missing += [f"{line}:{p}" for p in miss]
            lines[line] = {"label": spec["label"], "parcels": spec["parcels"], "error":
                           f"parcel names not found exactly: {miss}", "vertices": []}
            continue
        verts = np.unique(np.concatenate([both[p] for p in spec["parcels"]]))
        lines[line] = {
            "label": spec["label"],
            "parcels": spec["parcels"],
            "vertices": [int(v) for v in verts],
            "n_left": int(np.sum(verts < N_HEMI)),
            "n_right": int(np.sum(verts >= N_HEMI)),
            "parcel_counts": {p: [int(np.sum(both[p] < N_HEMI)), int(np.sum(both[p] >= N_HEMI))]
                              for p in spec["parcels"]},
        }
    return lines, missing


def check_lines(lines):
    seen = {}
    for line, d in lines.items():
        if d.get("error"):
            continue
        check(d["n_left"] > 0 and d["n_right"] > 0, f"{line}: needs vertices in both hemispheres")
        check(d["n_left"] + d["n_right"] == len(d["vertices"]), f"{line}: count mismatch")
        for v in d["vertices"]:
            check(v not in seen, f"vertex {v} in both {seen.get(v)} and {line}")
            seen[v] = line
        check(min(d["vertices"]) >= 0 and max(d["vertices"]) < N_TOTAL, f"{line}: vertex out of range")


# ---- 3. cross-check atlases ------------------------------------------------

def read_csv_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [[c.strip() for c in row] for row in csv.reader(f) if row]


def build_yeo():
    d = CACHE / "yeo2011-cbig"
    files = {}
    for name, rel in YEO_FILES.items():
        files[name] = download(f"{CBIG_RAW}/{rel}", d / name)
    import nibabel as nib

    rows = read_csv_rows(files["7NetworksOrderedNames.csv"])
    order = {int(r[0]): r[1] for r in rows[1:]}
    check(sorted(order) == list(range(1, 8)), f"unexpected network order file: {order}")
    gloss = {r[0]: r[1] for r in read_csv_rows(files["Yeo2011_7networks_N1000.split_components.glossary.csv"])[1:]}

    net_vertices = {n: [] for n in order.values()}
    dropped, label_names, agree = set(), {}, {}
    for hemi, off in (("lh", 0), ("rh", N_HEMI)):
        annot, ctab, names = nib.freesurfer.read_annot(str(files[f"{hemi}.Yeo2011_7Networks_N1000.annot"]))
        check(annot.shape[0] in (N_HEMI, N_ICO7), f"Yeo {hemi}: unexpected size {annot.shape}")
        annot = annot[:N_HEMI]  # fsaverage5 = first 10242 vertices of ico7
        names = [n.decode("utf-8") for n in names]
        label_names[hemi] = names
        net_of = np.full(N_HEMI, "", dtype=object)
        for idx, nm in enumerate(names):
            m = re.fullmatch(r"7Networks_(\d+)", nm)
            verts = np.where(annot == idx)[0]
            if not m:
                if len(verts):
                    dropped.add(nm)  # medial wall / unknown
                continue
            net = order[int(m.group(1))]
            net_of[verts] = net
            net_vertices[net] += [int(v) + off for v in verts]
        # Check the order file against the names inside the split-components annot.
        s_annot, _, s_names = nib.freesurfer.read_annot(
            str(files[f"{hemi}.Yeo2011_7Networks_N1000.split_components.annot"]))
        s_annot = s_annot[:N_HEMI]
        for idx, nm in enumerate(n.decode("utf-8") for n in s_names):
            if nm not in gloss or gloss[nm].lower() == "none":
                continue
            verts = np.where(s_annot == idx)[0]
            if not len(verts):
                continue
            net = gloss[nm].lower()
            agree.setdefault(net, [0, 0])
            agree[net][0] += int(np.sum([str(x).lower() == net for x in net_of[verts]]))
            agree[net][1] += len(verts)
    agreement = {k: round(a / b, 4) for k, (a, b) in agree.items()}
    for net, frac in agreement.items():
        check(frac >= 0.9, f"Yeo order check failed for {net}: only {frac:.2%} agree")
    for n in YEO_VISUAL + YEO_ATTENTION:
        check(n in net_vertices, f"Yeo network {n!r} not in order file {list(order.values())}")

    def mask(nets):
        v = sorted(set(sum((net_vertices[n] for n in nets), [])))
        return {"labels": [f"7Networks_{k} ({order[k]})" for k in sorted(order) if order[k] in nets],
                "vertices": v, "n_left": sum(x < N_HEMI for x in v), "n_right": sum(x >= N_HEMI for x in v)}

    info = {
        "network_order": {str(k): v for k, v in order.items()},
        "dropped_labels": sorted(dropped),
        "order_check_vs_split_components": agreement,
        "sha256": {k: sha256(p) for k, p in files.items()},
    }
    net_of_all = np.full(N_TOTAL, "", dtype=object)
    for n, vs in net_vertices.items():
        net_of_all[vs] = n
    return {"yeo_visual": mask(YEO_VISUAL), "yeo_dorsal_ventral_attention": mask(YEO_ATTENTION)}, info, net_of_all


def build_destrieux():
    from nilearn import datasets
    atlas = datasets.fetch_atlas_surf_destrieux(data_dir=str(CACHE / "nilearn"), verbose=0)
    labels = [x.decode("utf-8") if isinstance(x, bytes) else str(x) for x in atlas["labels"]]
    ml, mr = np.asarray(atlas["map_left"]), np.asarray(atlas["map_right"])
    check(ml.shape == (N_HEMI,) and mr.shape == (N_HEMI,), f"Destrieux maps not fsaverage5: {ml.shape}")
    missing = [n for n in DESTRIEUX_AUDITORY if n not in labels]
    temporal = [n for n in labels if "temp" in n.lower() or "transv" in n.lower()]
    info = {"n_labels": len(labels), "temporal_labels_seen": temporal,
            "sha256": {f"{h}.aparc.a2009s.annot": sha256(p) for h, p in (
                ("lh", CACHE / "nilearn" / "destrieux_surface" / "left.aparc.a2009s.annot"),
                ("rh", CACHE / "nilearn" / "destrieux_surface" / "right.aparc.a2009s.annot")) if p.exists()}}
    lic = licence_line(atlas.get("description", ""))
    if lic:
        info["licence"] = f"unverified: the nilearn dataset description states \"License: {lic}\""
    if missing:
        return None, dict(info, error=f"labels not found exactly: {missing}")
    ids = [labels.index(n) for n in DESTRIEUX_AUDITORY]
    v = sorted([int(x) for x in np.where(np.isin(ml, ids))[0]] +
               [int(x) + N_HEMI for x in np.where(np.isin(mr, ids))[0]])
    return {"destrieux_auditory": {"labels": DESTRIEUX_AUDITORY, "vertices": v,
                                   "n_left": sum(x < N_HEMI for x in v),
                                   "n_right": sum(x >= N_HEMI for x in v)}}, info


# ---- 4. mesh for the brain picture ----------------------------------------

def build_mesh():
    from nilearn import datasets, surface
    fs = datasets.fetch_surf_fsaverage("fsaverage5")
    out = {}
    for side in ("left", "right"):
        mesh = surface.load_surf_mesh(fs[f"infl_{side}"])
        coords = np.asarray(mesh.coordinates if hasattr(mesh, "coordinates") else mesh[0])
        faces = np.asarray(mesh.faces if hasattr(mesh, "faces") else mesh[1])
        sulc = np.asarray(surface.load_surf_data(fs[f"sulc_{side}"]))
        check(coords.shape == (N_HEMI, 3), f"infl_{side}: {coords.shape}")
        check(sulc.shape == (N_HEMI,), f"sulc_{side}: {sulc.shape}")
        check(faces.ndim == 2 and faces.shape[1] == 3 and faces.max() < N_HEMI and faces.min() >= 0,
              f"faces_{side}: bad shape or index")
        out[f"infl_{side}"] = coords.astype(np.float32)
        out[f"faces_{side}"] = faces.astype(np.int32)
        out[f"sulc_{side}"] = sulc.astype(np.float32)
    lic = licence_line(fs.get("description", "") if hasattr(fs, "get") else "")
    if lic:
        ATLAS_INFO["fsaverage5_mesh"]["licence"] = (
            f"unverified: the nilearn dataset description states \"License: {lic}\"")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(MESH_NPZ, **out)
    return {k: list(v.shape) for k, v in out.items()}


# ---- 5. cross-check run on fixtures ---------------------------------------

def smooth(x):
    from scipy.ndimage import gaussian_filter1d
    return gaussian_filter1d(np.asarray(x, dtype=np.float64), sigma=2, truncate=3)


def crosscheck_run(lines, cross):
    results = {}
    for job in FIXTURES:
        p = ROOT / "outputs" / job / "preds.npy"
        if not p.exists():
            results[job] = {"error": "preds.npy not found"}
            continue
        preds = np.load(p)
        check(preds.ndim == 2 and preds.shape[1] == N_TOTAL, f"{job}: preds shape {preds.shape}")
        src = {}
        sp = ROOT / "outputs" / job / "source.json"
        if sp.exists():
            src = json.loads(sp.read_text(encoding="utf-8"))
        res = {"label": src.get("label", ""), "purpose": "test", "rows": int(preds.shape[0])}
        sm = {}
        for line, d in lines.items():
            if not d.get("error"):
                sm[line] = smooth(preds[:, d["vertices"]].mean(axis=1))
        sx = {k: smooth(preds[:, d["vertices"]].mean(axis=1)) for k, d in cross.items()}
        r = lambda a, b: round(float(np.corrcoef(a, b)[0, 1]), 4)  # noqa: E731
        specificity = {}
        for key, line, xkey in CROSSCHECK_PAIRS:
            if xkey not in sx or line not in sm:
                res[key] = None
                continue
            res[key] = r(sm[line], sx[xkey])
            others = {k: r(sm[line], v) for k, v in sx.items() if k != xkey}
            specificity[key] = {"r_with_other_crosscheck_masks": others,
                                "matched_mask_is_highest": all(res[key] > o for o in others.values())}
        res["below_0.7"] = [k for k, _, _ in CROSSCHECK_PAIRS if res.get(k) is not None and res[k] < R_EXPECTED]
        res["specificity"] = specificity
        results[job] = res
    return results


def yeo_overlap(both, lines, net_of_all):
    """Share of each line's vertices (and PGi/PGs) in each Yeo-7 network (SCORING 21.3 evidence)."""
    def share(verts):
        nets = [net_of_all[v] or "medial wall / dropped" for v in verts]
        u, c = np.unique(nets, return_counts=True)
        return {str(k): round(int(n) / len(verts), 3) for k, n in sorted(zip(u, c), key=lambda t: -t[1])}
    out = {line: share(d["vertices"]) for line, d in lines.items() if not d.get("error")}
    for p in WATCH_PARCELS:
        if p in both:
            out[f"parcel:{p}"] = share([int(v) for v in both[p]])
    return out


# ---- main -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-mne", nargs="?", const=str(CACHE / "mne-fsaverage"), default=None,
                    metavar="SUBJECTS_DIR",
                    help="also run the upstream mne code path (downloads fsaverage into SUBJECTS_DIR)")
    args = ap.parse_args()

    import mne, nibabel, nilearn, scipy  # noqa: E401  (versions recorded below)
    CACHE.mkdir(parents=True, exist_ok=True)

    # 1. HCP-MMP1
    hcp_paths = fetch_hcp()
    both, left, right, raw_names = get_hcp_labels_both(hcp_paths)
    unknown = unknown_keys(raw_names)
    parcels = sorted(k for k in both if k not in unknown)
    unknown_info = {k: {"raw_left": raw_names["left"].get(k), "raw_right": raw_names["right"].get(k),
                        "n_left": int(len(left[k])), "n_right": int(len(right[k]))} for k in unknown}
    print(f"HCP-MMP1: {len(both)} keys, {len(parcels)} parcels per hemisphere, unknown labels: {unknown_info}")
    check(len(parcels) == 180, f"expected 180 HCP parcels per hemisphere, got {len(parcels)}")
    mne_check = verify_with_mne(both, args.verify_mne) if args.verify_mne else {"checked": False}
    if mne_check["checked"]:
        print("upstream mne code path gives the same dict:", mne_check)

    # 2. line masks
    lines, missing = build_lines(both, set(unknown))
    check_lines(lines)
    for line, d in lines.items():
        if d.get("error"):
            print(f"  {line}: NOT BUILT, {d['error']}")
        else:
            print(f"  {line:9s} {len(d['parcels']):2d} parcels  n_left={d['n_left']:4d}  "
                  f"n_right={d['n_right']:4d}  total={len(d['vertices'])}")

    # 3. cross-check masks
    cross, problems = {}, []
    try:
        yeo, yeo_info, net_of_all = build_yeo()
        cross.update(yeo)
        ATLAS_INFO["yeo7"].update(yeo_info)
    except Exception as e:  # record and continue (task step 4)
        problems.append(f"Yeo-7 cross-check atlas not built: {e!r}")
        net_of_all = None
    try:
        dx, dx_info = build_destrieux()
        ATLAS_INFO["destrieux"].update(dx_info)
        if dx:
            cross.update(dx)
        else:
            problems.append(f"Destrieux: {dx_info.get('error')}")
    except Exception as e:
        problems.append(f"Destrieux cross-check atlas not built: {e!r}")
    for k, d in cross.items():
        check(d["n_left"] > 0 and d["n_right"] > 0, f"cross-check {k}: needs both hemispheres")
        print(f"  cross-check {k:30s} n_left={d['n_left']:5d} n_right={d['n_right']:5d}  {d['labels']}")
    ATLAS_INFO["hcp_mmp1"]["sha256"] = {p.name: sha256(p) for p in hcp_paths.values()}
    ATLAS_INFO["hcp_mmp1"]["unknown_labels_skipped"] = unknown_info

    # 4. mesh
    mesh_shapes = build_mesh()
    print("mesh:", mesh_shapes)

    # 5. cross-check run
    results = crosscheck_run(lines, cross)
    for job, res in results.items():
        print(f"  r {job}: {res}")

    doc = {
        "version": "masks-v1",
        "mesh": "fsaverage5",
        "n_vertices": N_TOTAL,
        "vertex_order": "left hemisphere 0-10241, right hemisphere 10242-20483 (TRIBE v2 output order)",
        "atlas": ATLAS_INFO,
        "tribev2_commit": TRIBEV2_COMMIT,
        "built": BUILT,
        "build_env": {"python": sys.version.split()[0], "numpy": np.__version__, "scipy": scipy.__version__,
                      "mne": mne.__version__, "nibabel": nibabel.__version__, "nilearn": nilearn.__version__,
                      "script": "scoring/build_masks.py"},
        "checks": {
            "hcp_parcels_per_hemisphere": len(parcels),
            "every_fsaverage5_vertex_one_hcp_label_per_hemisphere": True,
            "lines_in_both_hemispheres": all(not d.get("error") for d in lines.values()),
            "no_vertex_in_two_lines": True,
            "upstream_mne_path": mne_check,
            "missing_parcel_names": missing,
        },
        "lines": lines,
        "crosscheck": cross,
        "crosscheck_results": {
            "method": "per second: mean of preds over HCP line vertices and over the cross-check mask "
                      "vertices (signed), each gaussian_filter1d(sigma=2, truncate=3), Pearson r",
            "expectation": f"r >= {R_EXPECTED} (SCORING 9.3)",
            "fixtures": results,
        },
        "parcel_yeo_overlap": yeo_overlap(both, lines, net_of_all) if net_of_all is not None else None,
        "problems": problems,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=1)
    # Keep integer lists (vertex ids, counts) on one line each.
    text = re.sub(r"\[(\s*-?\d+(?:,\s*-?\d+)*\s*)\]",
                  lambda m: "[" + ",".join(x.strip() for x in m.group(1).split(",")) + "]", text)
    MASKS_JSON.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {MASKS_JSON.relative_to(ROOT)} and {MESH_NPZ.relative_to(ROOT)}")
    if problems:
        print("problems:", problems)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
