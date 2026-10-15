"""TRIBE v2 on Modal: the M1 backend.

What it does: one-time weight download, video preprocessing, and GPU prediction.
It returns the raw predicted average-brain response (preds.npy, shape (T, 20484)),
the time of each row (segments.json) and the words TRIBE used (events.json).
It does not score, rank or label anything. Scoring is M3 (docs/SCORING.md).

Run from the project folder with your own Modal profile (set TRIBE_MODAL_PROFILE; backend/tribe.ps1 checks it):
    modal run backend/tribe_app.py::smoke              # image + pins check, CPU only
    modal run backend/tribe_app.py::download_weights   # one-time, CPU, needs secret `huggingface`
    modal run backend/tribe_app.py --video-path reel.mp4 [--label name]
    modal run backend/tribe_app.py --url https://www.instagram.com/reel/XXXX/   # public only; yt-dlp, then Apify
    modal run backend/tribe_app.py --rerun-job <job_id> --precision bf16          # same clip again (speed test)

Every paid container writes a started row before work and a finished row after
(backend/ledger.py), and refuses to start past MONTHLY_BUDGET_CAP_USD (secret
`tribe-config`). See docs/GOTCHAS.md for why each pin and setting is here.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # so add_local_python_source finds ledger.py locally

APP_NAME = "tribe"
EXPECTED_PROFILE = os.environ.get("TRIBE_MODAL_PROFILE") or "your-modal-profile"  # set TRIBE_MODAL_PROFILE to the Modal profile you want to bill

# --- Pins (CLAUDE.md "Version pins", GOTCHAS.md section 1) -------------------
TRIBEV2_COMMIT = "af58661791a351a448a489042a28f6c37e1c14b7"  # Meta main, 23 Jun 2026
TRIBEV2_HF_REVISION = "f894e783020944dcd96e5568550afe2aa9743f9f"  # facebook/tribev2 weights, 27 Mar 2026
WHISPERX_VERSION = "3.8.6"  # upstream calls an unpinned `uvx whisperx`; we pre-install this one
UV_VERSION = "0.12.5"
EN_CORE_WEB_LG = (
    "en_core_web_lg @ https://github.com/explosion/spacy-models/releases/download/"
    "en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl"
)

# --- GPU (D13: A10G first, L40S if A10G runs out of memory) ------------------
# Picked with the TRIBE_GPU env var at `modal run` time and passed into every
# container, so local and remote definitions agree.
ALLOWED_GPUS = ("A10G", "L40S", "A100-80GB")
GPU = os.environ.get("TRIBE_GPU", "A10G").strip().upper()
# Block all outbound network in containers that should never download anything.
# Proves the weights volume is complete (plan item 8). Set TRIBE_BLOCK_NETWORK=0
# only to debug a first run.
BLOCK_NETWORK = os.environ.get("TRIBE_BLOCK_NETWORK", "1") == "1"
# CPU-only mode leaves the GPU class out of the app. Modal refuses to create an app
# with GPU functions until the account has a payment method, and the CPU steps
# (smoke, download_weights) don't need it. tribe.ps1 sets this for those steps.
CPU_ONLY = os.environ.get("TRIBE_CPU_ONLY", "0") == "1"

# --- Inputs (CLAUDE.md "Inputs") ---------------------------------------------
MIN_SECONDS = 10.0  # under ~10 s the output goes flat
WARN_SECONDS = 15.0  # DataCamp: under 15 to 30 s shows low activation
# Upstream ChunkEvents splits audio over 60 s and then duplicates every word
# (PRs #29, #81, open). 59 s keeps the re-encoded AAC track clear of that edge.
MAX_SECONDS = 59.0
# V-JEPA2 forward precision. fp32 is upstream. bf16 passed the 8 Oct 2026 test on Demo's reel
# (lines r >= 0.99996, same peak, flat and word hits; $0.31 -> $0.10), so it is the default (D24).
PRECISIONS = ("fp32", "bf16")
DEFAULT_PRECISION = "bf16"
VIDEO_EXTS = (".mp4", ".avi", ".mkv", ".mov", ".webm")
# iPhone HDR (HLG / PQ, BT.2020) must be tone-mapped to SDR BT.709, or V-JEPA2 sees washed-out frames.
HDR_TRANSFERS = ("arib-std-b67", "smpte2084")
HDR_FILTERS = ("zscale", "tonemap")
TONEMAP_VF = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
              "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv")

# --- Paths --------------------------------------------------------------------
WEIGHTS = "/weights"
RUNS = "/runs"
JOBS = f"{RUNS}/jobs"
LEDGER = f"{RUNS}/ledger"
RATES_PATH = "/app/rates.json"
UV_TOOLS = "/opt/uv/tools"
WHISPERX_PY = f"{UV_TOOLS}/whisperx/bin/python"
TRIBE_FEATURE_CACHE = "/tmp/tribe-cache"  # per container; keyed by file path, never shared

# --- Resources and limits (all feed the ledger's worst case) -----------------
SCALEDOWN_S = 2  # Modal minimum. GPU runs inference and then exits (no keep-warm).
GPU_CPU, GPU_MEM_MIB = 4.0, 24 * 1024
GPU_TIMEOUT_S, GPU_STARTUP_S = 30 * 60, 20 * 60
PRE_CPU, PRE_MEM_MIB, PRE_TIMEOUT_S = 2.0, 4 * 1024, 10 * 60
ORCH_CPU, ORCH_MEM_MIB = 0.25, 1024
ORCH_TIMEOUT_S = PRE_TIMEOUT_S + GPU_STARTUP_S + GPU_TIMEOUT_S + 15 * 60
DL_CPU, DL_MEM_MIB, DL_TIMEOUT_S = 2.0, 8 * 1024, 60 * 60
SMOKE_CPU, SMOKE_MEM_MIB, SMOKE_TIMEOUT_S = 1.0, 4 * 1024, 15 * 60

FRAMING = "Predicted average-brain response. Not views. Not virality. Not a forecast."

# --- Refuse to touch the wrong Modal account ----------------------------------
# Runs on the laptop whenever `modal run` / `modal deploy` imports this file.
if modal.is_local():
    from modal.config import _profile  # private in modal 1.3.2; MODAL_PROFILE env wins

    if os.environ.get("MODAL_TOKEN_ID") or os.environ.get("MODAL_TOKEN_SECRET"):
        raise RuntimeError(
            "Refusing: MODAL_TOKEN_ID/MODAL_TOKEN_SECRET are set and would override the "
            f"{EXPECTED_PROFILE!r} profile. Unset them."
        )
    if _profile != EXPECTED_PROFILE:
        raise RuntimeError(
            f"Refusing: active Modal profile is {_profile!r}, need {EXPECTED_PROFILE!r}. "
            f"Run: modal profile activate {EXPECTED_PROFILE}"
        )
    if GPU not in ALLOWED_GPUS:
        raise RuntimeError(f"TRIBE_GPU={GPU!r} is not one of {ALLOWED_GPUS}")

# --- Image ----------------------------------------------------------------------
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "ffmpeg")  # ffmpeg 5.1: our preprocessing, moviepy and WhisperX
    .env(
        {
            "UV_TOOL_DIR": UV_TOOLS,  # same at build and run time, so uvx finds the baked tool
            "UV_TOOL_BIN_DIR": "/opt/uv/bin",
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_NO_MANAGED_PYTHON": "1",
            "NLTK_DATA": "/opt/nltk_data",
        }
    )
    .uv_pip_install(
        f"tribev2[plotting] @ git+https://github.com/facebookresearch/tribev2.git@{TRIBEV2_COMMIT}",
        "torch==2.6.0",
        "torchvision==0.21.0",
        "torchaudio==2.6.0",
        "numpy==2.2.6",
        "scipy==1.15.3",
        "exca==0.5.20",  # 0.5.26+ and 0.6.0 break neuralset 0.0.2 (issue #65)
        "neuralset==0.0.2",
        "neuraltrain==0.0.2",
        "x_transformers==1.27.20",
        "transformers==5.17.0",  # Square Zero 1 Oct 2026 working set
        "huggingface_hub>=1.5,<2",
        "pyvista==0.46.5",
        "moviepy==2.2.1",
        "spacy==3.8.16",
        f"uv=={UV_VERSION}",  # gives tribev2 the `uvx` command for WhisperX
        uv_version=UV_VERSION,
    )
    # neuralset's AddText loads en_core_web_lg and pip-installs it at run time if
    # missing, which would repeat on every cold start. Bake it in.
    .uv_pip_install(EN_CORE_WEB_LG, uv_version=UV_VERSION)
    # WhisperX needs torch 2.8, so it lives in its own uv tool env. uvx then uses
    # this pinned install instead of resolving the newest release.
    .run_commands(
        f"uv tool install --python /usr/local/bin/python3.11 whisperx=={WHISPERX_VERSION}",
        f"{WHISPERX_PY} -c \"import nltk; nltk.download('punkt_tab', download_dir='/opt/nltk_data')\"",
        "uvx whisperx --help > /dev/null",
    )
    # At run time uvx re-resolves `whisperx` from the package index instead of using
    # the installed tool, which fails with the network blocked (seen on Modal, 8 Oct
    # 2026). A `uvx` shim first on PATH sends `uvx whisperx ...` straight to the
    # pinned install and passes anything else to the real uvx.
    .run_commands(
        "mkdir -p /opt/tribe-bin",
        "printf '#!/bin/sh\\nif [ \"$1\" = whisperx ]; then shift; "
        f"exec {UV_TOOLS}/whisperx/bin/whisperx \"$@\"; fi\\nexec /usr/local/bin/uvx \"$@\"\\n' "
        "> /opt/tribe-bin/uvx",
        "chmod +x /opt/tribe-bin/uvx",
    )
    .env({"PATH": "/opt/tribe-bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"})
    .run_commands("test \"$(command -v uvx)\" = /opt/tribe-bin/uvx", "uvx whisperx --help > /dev/null")
    .add_local_python_source("ledger")
    .add_local_file(str(HERE / "rates.json"), RATES_PATH)
)

# Caches on the weights volume. Set before any import, inherited by the uvx subprocess.
RUNTIME_ENV = {
    "HF_HOME": f"{WEIGHTS}/hf",  # TRIBE ckpt, Llama, V-JEPA2, w2v-BERT, faster-whisper
    "TORCH_HOME": f"{WEIGHTS}/torch",  # WhisperX English align model
    "UV_CACHE_DIR": "/tmp/uv-cache",
    "XDG_CACHE_HOME": "/tmp/xdg",
    "HF_HUB_DOWNLOAD_TIMEOUT": "300",
    "PYTHONUNBUFFERED": "1",
    "TRIBE_GPU": GPU,
    "TRIBE_BLOCK_NETWORK": "1" if BLOCK_NETWORK else "0",
    "TRIBE_CPU_ONLY": "1" if CPU_ONLY else "0",
}
OFFLINE_ENV = {**RUNTIME_ENV, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "UV_OFFLINE": "1"}

weights_vol = modal.Volume.from_name("tribe-weights", create_if_missing=True)
runs_vol = modal.Volume.from_name("tribe-runs", create_if_missing=True)
hf_secret = modal.Secret.from_name("huggingface", required_keys=["HF_TOKEN"])
config_secret = modal.Secret.from_name("tribe-config", required_keys=["MONTHLY_BUDGET_CAP_USD"])

app = modal.App(APP_NAME, image=image)


# --- Helpers (run inside containers) ------------------------------------------
def _write_json(path: str | Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


@contextlib.contextmanager
def _paid(run_id: str, kind: str, *, gpu: str | None, cpu: float, mem_mib: int, worst_s: int):
    """Cap check + started row before the work, finished row after it, even on failure.

    Wraps either work done in this container (smoke, download) or a .remote() call
    to another container (preprocess, predict), whose wall time is the billed time.
    """
    import ledger

    runs_vol.reload()
    rates = ledger.Rates.load(RATES_PATH)
    row = ledger.start_run(
        LEDGER, run_id=run_id, kind=kind, rates=rates, gpu=gpu,
        cpu_cores=cpu, memory_gib=mem_mib / 1024, timeout_s=worst_s,
    )
    runs_vol.commit()
    t0 = time.monotonic()
    status = "failed"
    try:
        yield row
        status = "done"
    except modal.exception.FunctionTimeoutError:
        status = "timeout"
        raise
    finally:
        ledger.finish_run(
            LEDGER, row, status=status, billed_seconds=time.monotonic() - t0 + SCALEDOWN_S
        )
        runs_vol.commit()


def _set_status(job_id: str, stage: str, **extra) -> None:
    _write_json(f"{JOBS}/{job_id}/status.json", {"job_id": job_id, "status": stage,
                                                  "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **extra})
    runs_vol.commit()


def _ffprobe(path: str | Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(out.stdout)


# ffmpeg prints times with %.6g, so they can be negative (-0.0213) or exponents (2.08e-05).
_NUM = r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"


def _ranges(stderr: str, start_key: str, end_key: str, total: float) -> list[list[float]]:
    """Pair each start with the end that follows it (silencedetect / blackdetect logs)."""
    out, start = [], None
    for key, val in re.findall(rf"({start_key}|{end_key}):\s*{_NUM}", stderr):
        t = min(max(float(val), 0.0), total)
        if key == start_key:
            start = t
        elif start is not None:
            if t > start:
                out.append([round(start, 2), round(t, 2)])
            start = None
    if start is not None and total > start:  # runs to the end of the clip
        out.append([round(start, 2), round(total, 2)])
    return out


def _sha256(path: str | Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- 1. Smoke test: image, pins and offline tooling (CPU, cents) ---------------
@app.function(
    cpu=SMOKE_CPU, memory=SMOKE_MEM_MIB, timeout=SMOKE_TIMEOUT_S, scaledown_window=SCALEDOWN_S,
    max_containers=1, volumes={RUNS: runs_vol}, secrets=[config_secret], env=OFFLINE_ENV,
    block_network=BLOCK_NETWORK,
)
def smoke() -> dict:
    import importlib.metadata as md

    run_id = "smoke-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    with _paid(run_id, "smoke", gpu=None, cpu=SMOKE_CPU, mem_mib=SMOKE_MEM_MIB,
               worst_s=SMOKE_TIMEOUT_S + SCALEDOWN_S):
        pkgs = ["tribev2", "torch", "torchvision", "torchaudio", "numpy", "scipy", "exca",
                "neuralset", "transformers", "huggingface_hub", "spacy", "en_core_web_lg", "uv"]
        versions = {p: md.version(p) for p in pkgs}
        expected = {"torch": "2.6.0", "torchvision": "0.21.0", "torchaudio": "2.6.0",
                    "numpy": "2.2.6", "scipy": "1.15.3", "exca": "0.5.20"}
        wrong = {p: versions[p] for p, v in expected.items() if not versions[p].startswith(v)}
        if wrong:
            raise RuntimeError(f"pin drift: {wrong}")

        from tribev2.demo_utils import TribeModel  # noqa: F401  (the import that breaks on bad pins)
        import scipy.signal
        import spacy

        scipy.signal.get_window("hann", 8)
        spacy.load("en_core_web_lg")
        punkt = Path("/opt/nltk_data/tokenizers/punkt_tab").exists()
        wx = subprocess.run(["uvx", "whisperx", "--help"], capture_output=True, text=True)
        wx_ver = subprocess.run([WHISPERX_PY, "-c", "import importlib.metadata as m; print(m.version('whisperx'))"],
                                capture_output=True, text=True).stdout.strip()
        ffmpeg = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
        filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        missing_filters = {f for f in HDR_FILTERS if not re.search(rf"\s{f}\s", filters)}
        problems = []
        if missing_filters:
            problems.append(f"ffmpeg lacks {sorted(missing_filters)}; HDR clips could not be tone-mapped")
        if not punkt:
            problems.append("nltk punkt_tab missing")
        if wx.returncode != 0:
            problems.append(f"uvx whisperx --help failed: {wx.stderr[-400:]}")
        if wx_ver != WHISPERX_VERSION:
            problems.append(f"whisperx {wx_ver!r} != {WHISPERX_VERSION}")
        if problems:
            raise RuntimeError("; ".join(problems))
        report = {"ok": True, "versions": versions, "whisperx": wx_ver, "ffmpeg": ffmpeg,
                  "hdr_filters": sorted(set(HDR_FILTERS) - missing_filters), "network_blocked": BLOCK_NETWORK}
        print(json.dumps(report, indent=1))  # `modal run ::smoke` drops return values
        return report


# --- 2. One-time weight download (CPU; the ONLY function with the HF token) ----
HF_REPOS = [
    # (repo, kwargs). Official gated Llama only (D5). Never an ungated mirror.
    ("meta-llama/Llama-3.2-3B", {"ignore_patterns": ["original/*"]}),  # skip the duplicate .pth copy
    ("facebook/w2v-bert-2.0", {}),
    ("facebook/vjepa2-vitg-fpc64-256", {}),
    ("Systran/faster-whisper-large-v3", {}),  # what `whisperx --model large-v3` loads
]
SKIP_FORMATS = ["*.msgpack", "*.h5", "*.ot", "*.onnx", "*.tflite"]  # Flax/TF/Rust/ONNX copies


@app.function(
    cpu=DL_CPU, memory=DL_MEM_MIB, timeout=DL_TIMEOUT_S, scaledown_window=SCALEDOWN_S, max_containers=1,
    volumes={WEIGHTS: weights_vol, RUNS: runs_vol}, secrets=[hf_secret, config_secret], env=RUNTIME_ENV,
)
def download_weights() -> dict:
    from huggingface_hub import snapshot_download

    run_id = "download-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    with _paid(run_id, "download_weights", gpu=None, cpu=DL_CPU, mem_mib=DL_MEM_MIB,
               worst_s=DL_TIMEOUT_S + SCALEDOWN_S):
        token = os.environ["HF_TOKEN"]  # never printed or written anywhere
        snapshots = {}
        # TRIBE itself into a local folder at a pinned revision, so from_pretrained
        # reads our copy (it would otherwise take HF main) and its UnsafeLoader only
        # ever sees this file.
        snapshot_download(
            "facebook/tribev2", revision=TRIBEV2_HF_REVISION, local_dir=f"{WEIGHTS}/tribev2",
            allow_patterns=["config.yaml", "best.ckpt", "LICENSE"], token=token,
        )
        snapshots["facebook/tribev2"] = TRIBEV2_HF_REVISION
        for repo, kw in HF_REPOS:
            ignore = SKIP_FORMATS + kw.get("ignore_patterns", [])
            path = snapshot_download(repo, token=token, ignore_patterns=ignore)
            snapshots[repo] = Path(path).name  # the resolved commit hash
            print(f"downloaded {repo} @ {snapshots[repo]}")
        # WhisperX's English align model is a torchaudio bundle (torch hub cache).
        subprocess.run(
            [WHISPERX_PY, "-c",
             "import torchaudio; torchaudio.pipelines.WAV2VEC2_ASR_LARGE_LV60K_960H.get_model()"],
            check=True,
        )
        manifest = _manifest(snapshots)
        weights_vol.commit()
        report = {"ok": True, "total_gb": manifest["total_gb"], "n_files": manifest["n_files"],
                  "snapshots": snapshots}
        print(json.dumps(report, indent=1))
        return report


def _manifest(snapshots: dict) -> dict:
    files = []
    for p in Path(WEIGHTS).rglob("*"):
        if p.is_file() and not p.is_symlink():
            files.append((str(p.relative_to(WEIGHTS)), p.stat().st_size))
    total = sum(s for _, s in files)
    manifest = {
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tribev2_commit": TRIBEV2_COMMIT,
        "snapshots": snapshots,
        "total_gb": round(total / 1e9, 2),
        "n_files": len(files),
        "large_files": sorted([f, round(s / 1e6, 1)] for f, s in files if s > 10e6),
    }
    _write_json(f"{WEIGHTS}/manifest.json", manifest)
    lines = [f"{f}\t{s / 1e6:.1f} MB" for f, s in sorted(files) if s > 1e6]
    Path(f"{WEIGHTS}/MANIFEST.txt").write_text(
        f"total {manifest['total_gb']} GB, {len(files)} files\n" + "\n".join(lines) + "\n", encoding="utf-8"
    )
    return manifest


# --- 3. Preprocess (CPU): probe, check length, trim, re-encode, find silence ---
@app.function(
    cpu=PRE_CPU, memory=PRE_MEM_MIB, timeout=PRE_TIMEOUT_S, scaledown_window=SCALEDOWN_S,
    volumes={RUNS: runs_vol}, env=RUNTIME_ENV, block_network=BLOCK_NETWORK,
)
def preprocess(job_id: str, original_name: str, expected_sha256: str) -> dict:
    runs_vol.reload()
    job = Path(JOBS) / job_id
    src = job / original_name
    flags: dict = {"job_id": job_id}

    def reject(reason: str) -> dict:
        flags.update(status="rejected_input", reason=reason)
        _write_json(job / "flags.json", flags)
        runs_vol.commit()
        return flags

    sha = _sha256(src)
    if sha != expected_sha256:
        return reject("upload hash mismatch")
    info = _ffprobe(src)
    fmt = info.get("format", {})
    streams = info.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"
             and not s.get("disposition", {}).get("attached_pic")]
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    duration = float(fmt.get("duration") or 0.0)
    if duration <= 0 and video:  # live/MediaRecorder WebM/MKV have no Duration element; scan packets
        pk = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", str(video[0]["index"]),
             "-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0", str(src)],
            check=True, capture_output=True, text=True,
        ).stdout
        ends = [sum(float(x) for x in ln.split(",") if x not in ("", "N/A"))
                for ln in pk.splitlines() if ln.strip()]
        duration = max(ends, default=0.0)
    v0 = video[0] if video else {}
    hdr = v0.get("color_transfer") in HDR_TRANSFERS
    flags["original"] = {
        "sha256": sha, "size_bytes": src.stat().st_size, "format": fmt.get("format_name"),
        "duration_s": round(duration, 3), "has_audio": has_audio,
        "video": {k: v0.get(k) for k in ("index", "codec_name", "width", "height", "avg_frame_rate", "nb_frames",
                                         "pix_fmt", "color_transfer", "color_primaries", "color_space")}
        if video else None,
    }
    if not video:
        return reject("no video stream (stills and audio-only files are not supported in v1)")
    if "image" in (fmt.get("format_name") or "") or v0.get("nb_frames") == "1":
        return reject("looks like a still image; images are off-distribution and rejected in v1")
    if duration <= 0:
        return reject("could not read the clip's length; re-save or remux the file and retry")
    if duration < MIN_SECONDS:
        return reject(f"clip is {duration:.1f} s; under {MIN_SECONDS:.0f} s the output is flat")

    analysed = min(duration, MAX_SECONDS)
    clip = job / "clip.mp4"
    vf = "scale='min(1920,iw)':'min(1920,ih)':force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2"
    if hdr:  # downscale first, then tone-map HLG/PQ BT.2020 to SDR BT.709
        vf += "," + TONEMAP_VF
    vf += ",format=yuv420p"
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-y", "-i", str(src)]
    if not has_audio:  # keep upstream's audio extraction happy; WhisperX is skipped below
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    cmd += [
        "-t", f"{analysed:.3f}",
        "-map", f"0:{v0['index']}",  # the stream we checked, not cover art
        "-map", "0:a:0" if has_audio else "1:a:0",
        "-vf", vf,
        "-fps_mode", "cfr", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(clip),
    ]
    enc = subprocess.run(cmd, capture_output=True, text=True)
    if enc.returncode != 0:
        raise RuntimeError(f"ffmpeg re-encode failed: {enc.stderr[-1500:]}")
    clip_info = _ffprobe(clip)
    clip_dur = float(clip_info["format"]["duration"])
    if clip_dur > 60.0:
        raise RuntimeError(f"re-encoded clip is {clip_dur:.2f} s; must stay at or under 60 s (PRs #29, #81)")

    silence = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(clip), "-map", "0:a:0",
         "-af", "silencedetect=noise=-35dB:d=0.5", "-f", "null", "-"],
        check=True, capture_output=True, text=True,
    ).stderr
    black = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(clip), "-map", "0:v:0",
         "-vf", "blackdetect=d=0.1:pix_th=0.10", "-an", "-f", "null", "-"],
        check=True, capture_output=True, text=True,
    ).stderr
    flags.update(
        status="ok",
        clip={"duration_s": round(clip_dur, 3), "sha256": _sha256(clip)},
        analysed_s=round(analysed, 3),
        trimmed=duration > MAX_SECONDS,
        short_clip_warning=duration < WARN_SECONDS,
        audio_added_silent=not has_audio,
        audio_only=not has_audio,  # no audio track: skip WhisperX instead of inventing words
        hdr_input=hdr,
        tonemapped=hdr,
        silent_ranges=_ranges(silence, "silence_start", "silence_end", clip_dur),
        black_ranges=_ranges(black, "black_start", "black_end", clip_dur),
        language_assumed="english",  # WhisperX is hard-coded to English upstream
    )
    _write_json(job / "flags.json", flags)
    src.unlink()  # keep only the normalised clip; the original's hash is in flags.json
    runs_vol.commit()
    return flags


# --- 4. Predict (GPU): load once, predict one clip, save, exit -----------------
def _segments_to_records(segments) -> list[dict]:
    out = []
    for i, seg in enumerate(segments):
        evs = seg.ns_events  # events overlapping [start, stop)
        out.append({
            "row": i,
            "start": round(float(seg.start), 3),
            "stop": round(float(seg.stop), 3),
            "duration": round(float(seg.duration), 3),
            "timeline": str(seg.timeline),
            "event_types": sorted({type(e).__name__ for e in evs}),
            "words": [str(e.text) for e in evs if type(e).__name__ == "Word"],
        })
    return out


# V-JEPA2 is 89% of a run's GPU time (COSTS-AND-TIMES 7c). This wraps neuralset's video
# forward pass to time each step and, for "bf16", to run only V-JEPA2 under autocast.
# Llama, Wav2Vec-BERT and the TRIBE head stay as upstream ships them. With "fp32" the
# maths is the same as upstream; only the timers are added.
_VJEPA: dict = {"orig": None, "precision": DEFAULT_PRECISION, "stats": None}


def _install_vjepa_patch() -> None:
    import torch
    from neuralset.extractors import video as nsv

    if _VJEPA["orig"] is not None:
        return
    orig = nsv._HFVideoModel.predict
    _VJEPA["orig"] = orig

    def predict(self, images, audio=None):
        if "vjepa2" not in self.model_name:
            return orig(self, images, audio)
        st = _VJEPA["stats"]
        t0 = time.monotonic()
        if st["last_end"] is not None:  # frame reading for this step happens before this call
            st["gap_s"].append(t0 - st["last_end"])
        inputs = self.processor(videos=list(images), return_tensors="pt")  # as upstream for vjepa2
        nsv._fix_pixel_values(inputs)
        inputs = inputs.to(self.model.device)
        torch.cuda.synchronize()
        t1 = time.monotonic()
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16,
                                                     enabled=_VJEPA["precision"] == "bf16"):
            pred = self.model(**inputs)
            if pred.hidden_states is not None:  # numpy can't take bf16; fp32 is a no-op
                pred.hidden_states = tuple(h.float() for h in pred.hidden_states)
        torch.cuda.synchronize()
        t2 = time.monotonic()
        st["proc_s"].append(t1 - t0)
        st["fwd_s"].append(t2 - t1)
        st["last_end"] = t2
        return pred

    nsv._HFVideoModel.predict = predict


def _vjepa_summary() -> dict:
    st = _VJEPA["stats"] or {}
    out: dict = {"precision": _VJEPA["precision"], "n_steps": len(st.get("fwd_s", []))}
    for key in ("gap_s", "proc_s", "fwd_s"):
        vals = st.get(key) or []
        out[f"{key}_total"] = round(sum(vals), 1)
        out[f"{key}_mean"] = round(sum(vals) / len(vals), 3) if vals else None
    return out


if not CPU_ONLY:  # GPU class, orchestrator and laptop entry point
    @app.cls(
        gpu=GPU, cpu=GPU_CPU, memory=GPU_MEM_MIB,
        timeout=GPU_TIMEOUT_S, startup_timeout=GPU_STARTUP_S,
        min_containers=0, max_containers=1, scaledown_window=SCALEDOWN_S,  # no keep-warm, one GPU at a time
        volumes={WEIGHTS: weights_vol, RUNS: runs_vol}, env=OFFLINE_ENV, block_network=BLOCK_NETWORK,
    )
    class Predict:
        @modal.enter()
        def load(self):
            t0 = time.monotonic()
            import glob

            import torch

            if not torch.cuda.is_available():
                raise RuntimeError("no CUDA device in the GPU container")
            if not Path(f"{WEIGHTS}/manifest.json").exists():
                raise RuntimeError("weights volume has no manifest.json: run download_weights first")
            self.gpu_name = torch.cuda.get_device_name(0)
            self.gpu_total_gb = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
            # WhisperX's ctranslate2 needs the cuDNN that ships inside its own tool env.
            # Only child processes read this (glibc reads LD_LIBRARY_PATH at start-up).
            libdirs = sorted(glob.glob(f"{UV_TOOLS}/whisperx/lib/python3*/site-packages/nvidia/*/lib"))
            if libdirs:
                os.environ["LD_LIBRARY_PATH"] = ":".join(libdirs + [os.environ.get("LD_LIBRARY_PATH", "")]).rstrip(":")

            from tribev2.demo_utils import TribeModel

            self.model = TribeModel.from_pretrained(
                f"{WEIGHTS}/tribev2",  # local pinned copy, no HF call
                cache_folder=TRIBE_FEATURE_CACHE,
                device="cuda",
                config_update={"data.num_workers": 0},  # config ships 20; workers crash in containers
            )
            if self.model.data.num_workers != 0 or self.model.data.TR != 1.0:
                raise RuntimeError(f"unexpected config: num_workers={self.model.data.num_workers}, TR={self.model.data.TR}")
            self.load_s = round(time.monotonic() - t0, 1)
            self.cold = True

        @modal.method()
        def predict(self, job_id: str, ticket: str, ticket_month: str, precision: str = DEFAULT_PRECISION) -> dict:
            import numpy as np
            import pandas as pd
            import torch

            if precision not in PRECISIONS:
                raise RuntimeError(f"precision {precision!r} is not one of {PRECISIONS}")
            _install_vjepa_patch()
            _VJEPA["precision"] = precision
            _VJEPA["stats"] = {"last_end": None, "gap_s": [], "proc_s": [], "fwd_s": []}
            runs_vol.reload()
            # No GPU work without an open ledger row (the orchestrator writes it).
            ledger_dir = Path(LEDGER) / ticket_month
            if not (ledger_dir / f"{ticket}.started.json").exists() or (ledger_dir / f"{ticket}.finished.json").exists():
                raise RuntimeError(f"no open ledger row {ticket!r}; GPU runs must go through process_job")

            job = Path(JOBS) / job_id
            flags = json.loads((job / "flags.json").read_text(encoding="utf-8"))
            clip = job / "clip.mp4"
            torch.cuda.reset_peak_memory_stats()

            t0 = time.monotonic()
            if flags.get("audio_only"):
                from tribev2.demo_utils import get_audio_and_text_events

                df = get_audio_and_text_events(
                    pd.DataFrame([{"type": "Video", "filepath": str(clip), "start": 0,
                                   "timeline": "default", "subject": "default"}]),
                    audio_only=True,
                )
            else:
                df = self.model.get_events_dataframe(video_path=str(clip))  # writes clip.wav + clip.tsv
            events_s = time.monotonic() - t0

            t1 = time.monotonic()
            preds, segments = self.model.predict(events=df, verbose=False)
            predict_s = time.monotonic() - t1

            # Fail loudly on anything that is not a real, sane prediction (no mock output, ever).
            preds = np.asarray(preds, dtype=np.float32)
            analysed = float(flags["analysed_s"])
            problems = []
            if preds.ndim != 2 or preds.shape[1] != 20484:
                problems.append(f"preds shape {preds.shape}, expected (T, 20484)")
            elif not np.isfinite(preds).all():
                problems.append("preds contain NaN or inf")
            elif preds.shape[0] > int(np.ceil(analysed)) + 1:
                problems.append(f"{preds.shape[0]} rows for a {analysed:.1f} s clip (word-duplication bug?)")
            elif float(preds.std(axis=0).mean()) == 0.0:
                problems.append("preds do not change over time")
            if len(segments) != preds.shape[0]:
                problems.append(f"{len(segments)} segments for {preds.shape[0]} rows")
            words = df.loc[df["type"] == "Word"].sort_values("start") if "type" in df.columns else df.iloc[0:0]
            if len(words) and float(words["start"].max()) > analysed + 1.0:
                problems.append("a word starts after the clip ends (word-duplication bug)")
            if problems:
                raise RuntimeError("refusing to save: " + "; ".join(problems))

            np.save(job / "preds.npy", preds)
            _write_json(job / "segments.json", _segments_to_records(segments))
            word_cols = [c for c in ("text", "start", "duration", "stop", "sequence_id", "sentence") if c in words.columns]
            _write_json(job / "events.json", {
                "event_type_counts": df["type"].value_counts().to_dict() if "type" in df.columns else {},
                "words": [{c: (round(float(r[c]), 3) if c in ("start", "duration", "stop") else
                               (int(r[c]) if c == "sequence_id" and pd.notna(r[c]) else str(r[c])))
                           for c in word_cols} for _, r in words.iterrows()],
            })
            meta = {
                "job_id": job_id,
                "framing": FRAMING,
                "mock": False,
                "gpu_requested": GPU,
                "gpu_name": self.gpu_name,
                "gpu_total_gb": self.gpu_total_gb,
                "cold_start": self.cold,
                "model_load_s": self.load_s if self.cold else 0.0,
                "events_s": round(events_s, 1),
                "predict_s": round(predict_s, 1),
                "precision": precision,
                "vjepa_timing": _vjepa_summary(),
                "rerun_of": flags.get("rerun_of", ""),
                "peak_vram_allocated_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
                "peak_vram_reserved_gb": round(torch.cuda.max_memory_reserved() / 1e9, 2),
                "preds_shape": list(preds.shape),
                "first_segment_start_s": float(segments[0].start) if segments else None,
                "last_segment_stop_s": float(segments[-1].stop) if segments else None,
                "n_words": int(len(words)),
                "audio_only": bool(flags.get("audio_only")),
                "time_shift_applied_s": 0,  # model output is already shifted 5 s (README); never shift again
                "tribev2_commit": TRIBEV2_COMMIT,
                "tribev2_hf_revision": TRIBEV2_HF_REVISION,
                "whisperx_version": WHISPERX_VERSION,
                "network_blocked": BLOCK_NETWORK,
            }
            _write_json(job / "predict_meta.json", meta)
            runs_vol.commit()
            self.cold = False
            return meta


    # --- 5. Orchestrator (tiny CPU): ledger + cap around every paid step -----------
    @app.function(
        cpu=ORCH_CPU, memory=ORCH_MEM_MIB, timeout=ORCH_TIMEOUT_S, scaledown_window=SCALEDOWN_S,
        volumes={RUNS: runs_vol}, secrets=[config_secret], env=RUNTIME_ENV,
    )
    def process_job(job_id: str, original_name: str, sha256: str, label: str = "", source_name: str = "",
                    source_url: str = "", precision: str = DEFAULT_PRECISION, rerun_of: str = "") -> dict:
        import shutil

        import ledger

        _set_status(job_id, "preprocessing", label=label, source_name=source_name, source_url=source_url)
        result: dict = {"job_id": job_id, "label": label, "source_name": source_name, "source_url": source_url,
                        "precision": precision, "rerun_of": rerun_of}
        try:
            with _paid(f"{job_id}.orch", "orchestrate", gpu=None, cpu=ORCH_CPU, mem_mib=ORCH_MEM_MIB,
                       worst_s=ORCH_TIMEOUT_S + SCALEDOWN_S):
                if rerun_of:  # same normalised clip in a new job dir (TRIBE caches features by path)
                    runs_vol.reload()
                    old, new = Path(JOBS) / rerun_of, Path(JOBS) / job_id
                    new.mkdir(parents=True, exist_ok=True)
                    flags = json.loads((old / "flags.json").read_text(encoding="utf-8"))
                    if flags.get("status") != "ok" or not (old / "clip.mp4").is_file():
                        raise RuntimeError(f"job {rerun_of} has no usable clip.mp4 to rerun")
                    shutil.copyfile(old / "clip.mp4", new / "clip.mp4")
                    flags.update(job_id=job_id, rerun_of=rerun_of)
                    _write_json(new / "flags.json", flags)
                    runs_vol.commit()
                else:
                    with _paid(f"{job_id}.pre", "preprocess", gpu=None, cpu=PRE_CPU, mem_mib=PRE_MEM_MIB,
                               worst_s=PRE_TIMEOUT_S + SCALEDOWN_S):
                        flags = preprocess.remote(job_id, original_name, sha256)
                result["flags"] = flags
                if flags.get("status") != "ok":
                    _set_status(job_id, "rejected_input", reason=flags.get("reason"))
                    return {**result, "status": "rejected_input", "reason": flags.get("reason")}

                _set_status(job_id, "predicting", gpu=GPU)
                gpu_worst = GPU_STARTUP_S + GPU_TIMEOUT_S + SCALEDOWN_S
                with _paid(f"{job_id}.gpu", "predict", gpu=GPU, cpu=GPU_CPU, mem_mib=GPU_MEM_MIB,
                           worst_s=gpu_worst) as row:
                    meta = Predict().predict.remote(job_id, row["run_id"], ledger.month_of(row), precision)
                result["predict"] = meta
                runs_vol.reload()
                result["month_to_date_usd"] = round(ledger.month_to_date_usd(LEDGER), 4)
                result["monthly_cap_usd"] = ledger.read_cap()
                _set_status(job_id, "done")
                return {**result, "status": "done"}
        except modal.exception.FunctionTimeoutError as e:  # _paid already logged the row as "timeout"
            _set_status(job_id, "timeout", error=str(e)[:2000])
            return {**result, "status": "timeout", "reason": str(e)[:2000]}
        except ledger.BudgetError as e:
            _set_status(job_id, "refused_budget", reason=str(e))
            return {**result, "status": "refused_budget", "reason": str(e)}
        except Exception as e:
            _set_status(job_id, "failed", error=f"{type(e).__name__}: {e}"[:2000])
            raise


    # --- 6. Laptop entry point: upload, run, wait, download results ----------------
    APIFY_ACTOR = "apify~instagram-scraper"  # public posts only; no Instagram login on our side
    MAX_UPLOAD_BYTES = 1 << 30

    def _env_value(name: str) -> str:
        """One value from the environment or the Tribe .env file. Never printed."""
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
        env_file = HERE.parent / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip() == name:
                    return value.strip().strip('"').strip("'")
        return ""

    def _instagram_code(url: str) -> str:
        # /reel/X, /reels/X, /p/X, /tv/X, also /<username>/reel/X and m.instagram.com; not /reels/audio/
        m = re.match(r"^https?://(?:www\.|m\.)?instagram\.com/(?:(?!share/)[^/?#]+/)?(?:p|tv|reels?)/(?!audio/)"
                     r"([A-Za-z0-9_-]+)", url)
        return m.group(1) if m else ""

    def _download_via_apify(url: str, dest: Path) -> tuple[str, dict]:
        """Fallback for a public Instagram reel that refuses anonymous downloads.

        Apify's instagram-scraper reads the public post (costs well under 1 cent of
        Apify credit). Needs APIFY_TOKEN in .env. Private or deleted reels still fail.
        """
        import urllib.request

        code = _instagram_code(url)
        token = _env_value("APIFY_TOKEN")
        if not code or not token:
            return "", {}
        print("Instagram refused an anonymous download; fetching the public reel through Apify instead")
        body = json.dumps({"directUrls": [f"https://www.instagram.com/reel/{code}/"], "resultsType": "posts",
                           "resultsLimit": 1, "addParentData": False}).encode()
        req = urllib.request.Request(
            f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items?timeout=240",
            data=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                items = json.load(r)
        except Exception as e:  # HTTP errors carry the status only, never the token
            raise SystemExit(f"Apify could not fetch that reel ({type(e).__name__}: {e}). "
                             "Save the reel to your laptop and pass the file instead.")
        item = next((i for i in items if isinstance(i, dict) and i.get("shortCode") == code
                     and str(i.get("videoUrl", "")).startswith("https://")), None)
        if item is None:
            raise SystemExit("Apify found no public video for that link (private, deleted or not a video). "
                             "Save the reel to your laptop and pass the file instead.")
        path = dest / f"Instagram-{code}.mp4"
        part = path.with_suffix(".part")
        size = 0
        with urllib.request.urlopen(urllib.request.Request(item["videoUrl"], headers={"User-Agent": "Mozilla/5.0"}),
                                    timeout=120) as r, open(part, "wb") as f:
            expected = int(r.headers.get("Content-Length") or 0)
            while chunk := r.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    f.close()
                    part.unlink(missing_ok=True)
                    raise SystemExit("that reel is over 1 GB; trim or compress it first")
                f.write(chunk)
        # read() returns b"" instead of raising when the server closes early, so check the size.
        if expected and size != expected:
            part.unlink(missing_ok=True)
            raise SystemExit(f"the reel download was cut off ({size} of {expected} bytes); try again")
        part.replace(path)
        return str(path), {"fetched_via": "apify", "owner": item.get("ownerUsername", ""),
                           "duration_s": item.get("videoDuration")}

    def _download_public_reel(url: str) -> tuple[str, dict]:
        """Download a PUBLIC reel on the laptop. Never logs in, never uses cookies.

        Tries yt-dlp first (free). Instagram usually refuses that without a login, so a
        public Instagram reel then goes through Apify. Otherwise stop and ask for the file.
        """
        if not re.match(r"^https?://", url):
            raise SystemExit(f"not a link: {url!r}")
        dest = Path(tempfile.gettempdir()) / "tribe-downloads"   # outside Tribe (D19)
        dest.mkdir(exist_ok=True)
        cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-cookies", "--no-cookies-from-browser",
               "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b", "--merge-output-format", "mp4",
               "-o", str(dest / "%(extractor_key)s-%(id)s.%(ext)s"),
               "--print", "after_move:filepath", "--no-simulate", "--quiet", "--no-warnings", url]
        print(f"downloading {url} (public, no login)")
        r = subprocess.run(cmd, capture_output=True, text=True)
        path = (r.stdout.strip().splitlines() or [""])[-1]
        if r.returncode == 0 and path and Path(path).is_file():
            print(f"downloaded to {path}")
            return path, {"fetched_via": "yt-dlp"}
        path, info = _download_via_apify(url, dest)
        if path:
            print(f"downloaded to {path}")
            return path, info
        raise SystemExit(
            "could not download that link without logging in "
            f"({(r.stderr or r.stdout).strip()[-300:]}). Save the reel to your laptop and pass the file instead."
        )


    @app.local_entrypoint()
    def main(video_path: str = "", url: str = "", label: str = "", rerun_job: str = "",
             precision: str = DEFAULT_PRECISION):
        import hashlib

        if precision not in PRECISIONS:
            raise SystemExit(f"--precision must be one of {PRECISIONS}")
        if rerun_job:
            return _rerun(rerun_job, label, precision)
        if bool(video_path) == bool(url):
            raise SystemExit("give exactly one of --video-path, --url or --rerun-job")
        fetched: dict = {}
        if url:
            code = _instagram_code(url)
            if code:  # drop share-tracking params like ?stkn=, keep the plain public link
                url = f"https://www.instagram.com/reel/{code}/"
            video_path, fetched = _download_public_reel(url)
        src = Path(video_path).expanduser().resolve()
        try:
            if not src.is_file():
                raise SystemExit(f"not a file: {src}")
            ext = src.suffix.lower()
            if ext not in VIDEO_EXTS:
                raise SystemExit(f"{ext!r} is not a supported video type {VIDEO_EXTS}")
            if src.stat().st_size > MAX_UPLOAD_BYTES:
                raise SystemExit("file over 1 GB; trim or compress it first")

            h = hashlib.sha256()
            with open(src, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            sha = h.hexdigest()
            job_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{sha[:8]}"  # unique path: TRIBE caches by path
            original_name = f"original{ext}"
            print(f"job {job_id}: uploading {src.name} ({src.stat().st_size / 1e6:.1f} MB) to volume tribe-runs")
            with runs_vol.batch_upload() as batch:
                batch.put_file(str(src), f"/jobs/{job_id}/{original_name}")
        finally:
            if url:  # a fetched reel may be another creator's: keep the link and numbers, not a copy (LICENCE.md)
                src.unlink(missing_ok=True)

        source = {"job_id": job_id, "label": label, "local_path": "" if url else str(src), "source_url": url,
                  "sha256": sha, **fetched}
        _run_and_fetch(job_id, process_job.spawn(job_id, original_name, sha, label, src.name, url, precision),
                       source)

    def _rerun(old_job: str, label: str, precision: str) -> None:
        """Run an existing job's normalised clip again (same input, new job dir), e.g. the bf16 test."""
        if not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{8}", old_job):
            raise SystemExit(f"not a job id: {old_job!r}")
        names = {Path(e.path).name for e in runs_vol.listdir(f"jobs/{old_job}")}
        if not {"clip.mp4", "flags.json"} <= names:
            raise SystemExit(f"jobs/{old_job} on tribe-runs has no clip.mp4/flags.json to rerun")
        old_src = HERE.parent / "outputs" / old_job / "source.json"
        source = json.loads(old_src.read_text(encoding="utf-8")) if old_src.is_file() else {}
        job_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{old_job[-8:]}"
        label = label or f"{source.get('label') or old_job}-{precision}"
        source.update(job_id=job_id, label=label, rerun_of=old_job, precision=precision)
        print(f"job {job_id}: rerun of {old_job} at {precision} on {GPU}. Keep this window open.")
        _run_and_fetch(job_id, process_job.spawn(job_id, "", "", label, f"rerun of {old_job}",
                                                 source.get("source_url", ""), precision, old_job), source)

    def _run_and_fetch(job_id: str, call, source: dict) -> None:
        t0 = time.monotonic()
        deadline = t0 + ORCH_TIMEOUT_S + 600
        while True:
            try:
                result = call.get(timeout=30)
                break
            except modal.exception.TimeoutError as e:  # FunctionTimeoutError / OutputExpiredError: the job ended
                raise SystemExit(f"job {job_id} ended: {type(e).__name__}: {e} (see jobs/{job_id}/status.json)")
            except TimeoutError:  # builtin: only this 30 s poll ran out; the job is still going
                if time.monotonic() > deadline:
                    raise SystemExit(f"job {job_id}: no result after {int(time.monotonic() - t0)} s")
                print(f"  ... still running ({int(time.monotonic() - t0)} s)")

        print(json.dumps({k: v for k, v in result.items() if k != "flags"}, indent=1, default=str))
        if result.get("status") != "done":
            raise SystemExit(f"job {job_id} ended with status {result.get('status')}")

        out = HERE.parent / "outputs" / job_id
        out.mkdir(parents=True, exist_ok=True)
        for name in ("predict_meta.json", "flags.json", "segments.json", "events.json", "preds.npy", "clip.tsv"):
            try:
                with open(out / name, "wb") as f:
                    for chunk in runs_vol.read_file(f"jobs/{job_id}/{name}"):
                        f.write(chunk)
            except FileNotFoundError:
                (out / name).unlink(missing_ok=True)
        # What the dashboard needs to find the video and name the report (never sent to Modal).
        # owner comes from Apify; a reel that isn't yours is for testing only, never calibration.
        (out / "source.json").write_text(json.dumps(source, indent=1), encoding="utf-8")
        print(f"saved to {out}")
        print(FRAMING)
