"""Checks on scoring/masks/masks-v1.json (built by build_masks.py).
Run: python scoring/test_masks.py   (numpy only; no mne, no network, no spend)."""

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
MASKS = HERE / "masks" / "masks-v1.json"
MESH = HERE / "masks" / "fsaverage5-mesh.npz"
N_HEMI, N_TOTAL = 10242, 20484

# SCORING 9.1, exact names.
EXPECTED_PARCELS = {
    "seeing": ["V1", "V2", "V3", "V4", "V3A", "V3B", "V6", "V6A", "MT", "MST"],
    "hearing": ["A1", "LBelt", "MBelt", "PBelt", "A4"],
    "language": ["44", "45", "IFSa", "STSdp", "STSvp", "STGa", "TE1a", "A5", "PSL", "SFL", "55b"],
    "attention": ["FEF", "LIPv", "LIPd", "VIP", "MIP", "AIP", "IP0", "IP1", "IP2",
                  "TPOJ1", "TPOJ2", "PFm", "IFJa", "IFJp"],
}


def _doc():
    return json.loads(MASKS.read_text(encoding="utf-8"))


def test_header():
    d = _doc()
    assert d["version"] == "masks-v1"
    assert d["mesh"] == "fsaverage5"
    assert d["n_vertices"] == N_TOTAL
    assert d["tribev2_commit"] == "af58661791a351a448a489042a28f6c37e1c14b7"
    assert d["checks"]["missing_parcel_names"] == []
    assert d["checks"]["hcp_parcels_per_hemisphere"] == 180


def test_lines_exact_parcels_both_hemispheres_no_overlap():
    d = _doc()
    assert set(d["lines"]) == set(EXPECTED_PARCELS)
    seen = np.zeros(N_TOTAL, dtype=int)
    for line, spec in d["lines"].items():
        assert spec["parcels"] == EXPECTED_PARCELS[line], line
        v = np.asarray(spec["vertices"])
        assert v.size and np.all(np.diff(v) > 0), f"{line}: vertices must be sorted and unique"
        assert v.min() >= 0 and v.max() < N_TOTAL
        assert spec["n_left"] == int(np.sum(v < N_HEMI)) > 0, line
        assert spec["n_right"] == int(np.sum(v >= N_HEMI)) > 0, line
        assert sum(sum(c) for c in spec["parcel_counts"].values()) == v.size, line
        seen[v] += 1
    assert seen.max() == 1, "a vertex sits in two lines"


def test_crosscheck_masks_and_results():
    d = _doc()
    for key in ("yeo_visual", "yeo_dorsal_ventral_attention", "destrieux_auditory"):
        c = d["crosscheck"][key]
        v = np.asarray(c["vertices"])
        assert c["labels"] and c["n_left"] > 0 and c["n_right"] > 0, key
        assert v.min() >= 0 and v.max() < N_TOTAL
    for job, res in d["crosscheck_results"]["fixtures"].items():
        for key in ("seeing_vs_yeo_visual", "attention_vs_yeo_dorsal_ventral", "hearing_vs_destrieux_auditory"):
            assert -1.0 <= res[key] <= 1.0, (job, key)


def test_mesh():
    if not MESH.exists():  # gitignored; build_masks.py regenerates it
        print("  (mesh npz missing: run build_masks.py)")
        return
    m = np.load(MESH)
    for side in ("left", "right"):
        assert m[f"infl_{side}"].shape == (N_HEMI, 3)
        assert m[f"sulc_{side}"].shape == (N_HEMI,)
        f = m[f"faces_{side}"]
        assert f.ndim == 2 and f.shape[1] == 3 and f.min() >= 0 and f.max() < N_HEMI


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
