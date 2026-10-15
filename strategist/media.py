"""Reel videos (D30): a private copy of each swipe reel's video, with sound, for the login-locked
dashboard, where it plays in step with the predicted average-brain response.

Usage (from the Tribe folder):
    python -m strategist.media fetch <sc> [<sc> ...] [--force]
    python -m strategist.media fetch --all [--force]
    python -m strategist.media fetch <sc>|--all --allow-apify --yes [--max-usd 0.12]
    python -m strategist.media push [--dry-run]
    python -m strategist.media status [--offline]

fetch takes each reel's video from the first source that works, in this order:
    1. Vault's copy, research/repurpose/media/<sc>/video.mp4 (read, never written);
    2. yt-dlp (python -m yt_dlp, free) on the reel link in reel.json, into a temp folder
       outside Tribe;
    3. only with --allow-apify and --yes: an Apify re-pull of the reel link (paid, about
       $0.003 a reel, logged to swipe/fetch-log.jsonl). Every "media re-pull" row in that log
       counts toward --max-usd (default and ceiling $0.12, the approved amount), and a re-pull
       that would go past it is refused.
It encodes with ffmpeg (ENCODE_ARGS, below) to media/<sc>.mp4, and refuses a source or an
encoded file whose length is more than 0.5 s from reel.json facts.duration_s, so the brain
seconds stay aligned with the picture.

push uploads each new or changed media/<sc>.mp4 (by sha256) to the private Vercel Blob store
as reels/<sc>-<sha8>.mp4 with the vercel CLI (BLOB_READ_WRITE_TOKEN read from the Tribe .env,
never printed, scrubbed from every line the CLI prints), records it in the reel_videos table
(strategist/db.py), and deletes the Blob files no row uses any more. A reel that left the
swipe file loses its row, its Blob file and its media/ copy.

status lists each reel: local file, size, length, and whether that exact file is uploaded.

media/ is the only folder that holds video. swipe/ and drafts/ stay video-free
(reel.assert_no_video runs after every fetch and push). Nothing here is public: the store is
private and the site plays a video only behind the login.
Exit codes: 0 ok, 2 refused (bad input, a failed check, or a paid step without --yes).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import db, store
from . import reel as sreel
from .store import StoreError

MEDIA = store.PROJECT_ROOT / "media"           # the only video folder (gitignored)
WEB = store.PROJECT_ROOT / "web"               # the vercel CLI runs from here
ENV_FILE = store.PROJECT_ROOT / ".env"         # BLOB_READ_WRITE_TOKEN lives here; read, never printed
TOKEN_ENV = "BLOB_READ_WRITE_TOKEN"
SCOPE = os.environ.get("TRIBE_VERCEL_SCOPE") or "your-vercel-scope"  # your own Vercel team or user slug
BLOB_PREFIX = "reels/"
VAULT_MEDIA = ("research", "repurpose", "media")  # under store.VAULT, read-only

SC_RE = re.compile(r"^[A-Za-z0-9_-]{5,20}$")     # the reel_videos CHECK (narrower than the store's)
FILE_RE = re.compile(r"^([A-Za-z0-9_-]{5,20})\.mp4$")
PATHNAME_RE = db.REEL_VIDEO_PATH_RE
LISTED_RE = re.compile(r"(?:^|\s)(reels/[A-Za-z0-9_.-]+)(?=\s|$)")   # the Pathname column of `vercel blob list`
NEXT_RE = re.compile(r"--next\s+(\S+)")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

TOLERANCE_S = 0.5
MAX_BYTES = db.REEL_VIDEO_MAX_BYTES
SECONDS = db.REEL_VIDEO_SECONDS
APPROVED_MAX_USD = 0.12        # D30 $0.07 + D31 round 4 $0.05: at most about $0.12 of Apify re-pulls in all
LOG_WHAT = "media re-pull"     # swipe/fetch-log.jsonl "what" prefix of these re-pulls
YTDLP_TIMEOUT_S = 600
FFMPEG_TIMEOUT_S = 900
VERCEL_TIMEOUT_S = 900

# The encode, exactly as the plan has it (720 wide, H.264 + AAC, a keyframe every 30 frames so
# seeking lands close, moov atom first so playback starts before the whole file loads, no metadata).
ENCODE_ARGS = ("-vf", "scale=720:-2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-g", "30",
               "-sc_threshold", "0", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-map_metadata", "-1")


class MediaError(Exception):
    """A media step was refused. The message says why and never holds the token."""


# ---------------------------------------------------------------- small helpers

def check_sc(sc) -> str:
    if not isinstance(sc, str) or not SC_RE.fullmatch(sc):
        raise MediaError(f"not a reel shortcode: {sc!r}")
    return sc


def media_path(sc: str) -> Path:
    return MEDIA / f"{check_sc(sc)}.mp4"


def vault_copy(sc: str) -> Path:
    return store.VAULT.joinpath(*VAULT_MEDIA, check_sc(sc), "video.mp4")


def _inside(path: Path, root: Path) -> bool:
    path, root = Path(path).resolve(), Path(root).resolve()
    return path == root or root in path.parents


def check_media_root() -> Path:
    """media/ itself: never inside swipe/ or drafts/ (those stay video-free)."""
    root = Path(MEDIA).resolve()
    for no in (store.SWIPE, store.DRAFTS):
        if _inside(root, no) or _inside(no, root):
            raise MediaError(f"media/ may not overlap {Path(no).name}/: {Path(no).name}/ stays video-free")
    return root


def check_media_path(path) -> str:
    """The shortcode of media/<sc>.mp4, or MediaError for any other path (outside media/, a
    subfolder, a link, another name or another type)."""
    path = Path(path)
    root = check_media_root()
    if path.is_symlink():
        raise MediaError(f"{path.name}: a link, not a file")
    if path.resolve().parent != root:
        raise MediaError(f"{path}: outside media/ (media/<sc>.mp4 is the only place a video goes)")
    m = FILE_RE.fullmatch(path.name)
    if not m:
        raise MediaError(f"{path.name}: not <shortcode>.mp4")
    return m.group(1)


def make_temp() -> Path:
    """A new temp folder outside Tribe, where downloads and encodes happen."""
    tmp = Path(tempfile.mkdtemp(prefix="tribe-media-"))
    if _inside(tmp, store.PROJECT_ROOT):
        shutil.rmtree(tmp, ignore_errors=True)
        raise MediaError("the temp folder is inside Tribe: set TEMP to a folder outside it")
    return tmp


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def fmt_size(n: int | None) -> str:
    return "-" if n is None else f"{n / 1e6:.1f} MB"


def fmt_s(s: float | None) -> str:
    return "-" if s is None else f"{s:.2f} s"


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text or "")


def last_line(text: str) -> str:
    lines = [ln.strip() for ln in strip_ansi(text).splitlines() if ln.strip()]
    return lines[-1][:300] if lines else "no output"


def scrub(text: str, token: str | None) -> str:
    """The text with the token (and its secret tail) replaced by ***."""
    out = str(text)
    if token:
        out = out.replace(token, "***")
        tail = token.rsplit("_", 1)[-1]
        if len(tail) >= 16:
            out = out.replace(tail, "***")
    return out


def expected_duration(reel: dict) -> float:
    d = (reel.get("facts") or {}).get("duration_s")
    if isinstance(d, bool) or not isinstance(d, (int, float)) or not math.isfinite(d) or d <= 0:
        raise MediaError(f"{reel.get('shortcode')}: reel.json has no facts.duration_s to check the video against")
    return float(d)


def swipe_shortcodes() -> list[str]:
    """Every swipe reel, archived ones included: their videos and reel_videos rows are kept (D31)."""
    return sorted(r["shortcode"] for r in store.list_reels(include_archived=True) if r.get("shortcode"))


# ---------------------------------------------------------------- tools (mocked in the tests)

def tool(name: str) -> str:
    """The full path of an external tool (vercel is a .cmd shim on Windows)."""
    path = shutil.which(name)
    if not path:
        raise MediaError(f"{name} is not installed or not on PATH")
    return path


def run_tool(cmd: list[str], *, cwd=None, timeout=None, env=None) -> subprocess.CompletedProcess:
    """Run one external tool, output captured, never through a shell and never with check=True
    (whose error text would hold the command line)."""
    return subprocess.run(cmd, cwd=cwd, timeout=timeout, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)


def probe(path: Path) -> dict:
    """ffprobe: {format, duration, video, pix_fmt, width, height, audio} (codec names, or None)."""
    cmd = [tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        r = run_tool(cmd, timeout=120)
    except subprocess.TimeoutExpired:
        raise MediaError(f"{Path(path).name}: ffprobe took too long") from None
    try:
        data = json.loads(r.stdout or "")
    except ValueError:
        data = None
    if r.returncode != 0 or not isinstance(data, dict):
        raise MediaError(f"{Path(path).name}: not a video ffprobe can read ({last_line(r.stderr)})")
    streams = [s for s in data.get("streams") or [] if isinstance(s, dict)]
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    try:
        duration = float((data.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    if duration is not None and not math.isfinite(duration):
        duration = None
    return {"format": str((data.get("format") or {}).get("format_name") or ""), "duration": duration,
            "video": video.get("codec_name"), "pix_fmt": video.get("pix_fmt"), "width": video.get("width"),
            "height": video.get("height"), "audio": audio.get("codec_name")}


def check_duration(got: float | None, expected: float, what: str) -> float:
    if got is None:
        raise MediaError(f"{what}: no length found")
    if abs(got - expected) > TOLERANCE_S:
        raise MediaError(f"{what} is {got:.2f} s and reel.json says {expected:.2f} s "
                         f"(more than {TOLERANCE_S} s apart, so the brain seconds would not line up)")
    return got


def check_mp4(path: Path, expected: float | None = None) -> dict:
    """An encoded reel video: an .mp4 file (ftyp box), H.264 video, within the size and length
    caps, and (when expected is given) within 0.5 s of reel.json. Returns its facts."""
    path = Path(path)
    if path.suffix.lower() != ".mp4":
        raise MediaError(f"{path.name}: not an .mp4 file")
    if not path.is_file():
        raise MediaError(f"{path.name}: no such file")
    size = path.stat().st_size
    if not 1 <= size <= MAX_BYTES:
        raise MediaError(f"{path.name}: {size} bytes, outside 1 to {MAX_BYTES}")
    with open(path, "rb") as f:
        head = f.read(12)
    if head[4:8] != b"ftyp":
        raise MediaError(f"{path.name}: not an MP4 file (no ftyp box)")
    info = probe(path)
    if "mp4" not in info["format"].split(",") or info["video"] != "h264":
        raise MediaError(f"{path.name}: not H.264 MP4 video ({info['format'] or '?'}, {info['video'] or 'no video'})")
    if info["duration"] is None or not SECONDS[0] <= info["duration"] <= SECONDS[1]:
        raise MediaError(f"{path.name}: length {fmt_s(info['duration'])}, outside {SECONDS[0]:g} to {SECONDS[1]:g} s")
    if expected is not None:
        check_duration(info["duration"], expected, path.name)
    return {**info, "bytes": size, "sha256": sha256_file(path)}


# ---------------------------------------------------------------- fetch

def encode(src: Path, out: Path) -> None:
    cmd = [tool("ffmpeg"), "-y", "-nostdin", "-loglevel", "error", "-i", str(src), *ENCODE_ARGS, str(out)]
    try:
        r = run_tool(cmd, timeout=FFMPEG_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise MediaError(f"ffmpeg took longer than {FFMPEG_TIMEOUT_S} s") from None
    if r.returncode != 0 or not out.is_file():
        raise MediaError(f"ffmpeg could not encode it ({last_line(r.stderr)})")


def install(encoded: Path, dest: Path) -> Path:
    """Move a checked encode into media/<sc>.mp4 (a partial file first, then an atomic replace)."""
    check_media_path(dest)
    Path(MEDIA).mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(f".{dest.stem}.partial")
    try:
        shutil.copyfile(encoded, partial)
        os.replace(partial, dest)
    finally:
        partial.unlink(missing_ok=True)
    return dest


def from_ytdlp(url: str, tmp: Path) -> Path:
    """The reel's video via yt-dlp, into tmp (outside Tribe). -P keeps the temp folder off the
    module path."""
    out = tmp / "ytdlp"
    out.mkdir()
    cmd = [sys.executable, "-P", "-m", "yt_dlp", "--no-playlist", "--no-progress", "--quiet", "--no-warnings",
           "--no-cache-dir", "--no-mtime", "-f", "bv*+ba/b", "--merge-output-format", "mp4",
           "-o", str(out / "source.%(ext)s"), url]
    try:
        r = run_tool(cmd, cwd=out, timeout=YTDLP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise MediaError(f"yt-dlp took longer than {YTDLP_TIMEOUT_S} s") from None
    got = sorted(p for p in out.glob("source.*") if p.is_file() and p.suffix not in (".part", ".ytdl"))
    if r.returncode != 0 or not got:
        raise MediaError(f"yt-dlp could not get it ({last_line(r.stderr)})")
    return got[0]


def apify_spent() -> float:
    """USD of every media re-pull in swipe/fetch-log.jsonl (the --max-usd total)."""
    path = store.fetch_log_path()
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and str(row.get("what") or "").startswith(LOG_WHAT + " "):
            est = row.get("est_usd")
            if isinstance(est, (int, float)) and not isinstance(est, bool) and math.isfinite(est):
                total += est
    return total


def from_apify(sc: str, url: str, tmp: Path, opts) -> Path:
    """The paid fallback: re-pull the reel link on Apify (reel.fetch logs it) and download its
    video (reel.download_video) into tmp. Only with --allow-apify, --yes and room under --max-usd."""
    cost = sreel.USD_PER_LINK
    if not opts.allow_apify:
        raise MediaError(f"not tried: the paid Apify re-pull (about ${cost:.3f}) runs only with --allow-apify --yes")
    spent = apify_spent()
    if spent + cost > opts.max_usd + 1e-9:
        raise MediaError(f"refused: media re-pulls have used ${spent:.3f}, and one more (${cost:.3f}) "
                         f"would pass the ${opts.max_usd:.2f} ceiling")
    if not sreel.gate(f"re-pull 1 public reel link for its video ({sc})", cost, opts.yes):
        raise MediaError("not run: the paid Apify re-pull needs --yes")
    body = {"directUrls": [url], "resultsType": "posts", "resultsLimit": 1, "addParentData": False}
    items = sreel.fetch(body, f"{LOG_WHAT} {sc}", cost)
    item = next((i for i in items if i.get("shortCode") == sc and not i.get("error")), None)
    video_url = str((item or {}).get("videoUrl") or "")
    if not video_url.startswith("https://"):
        raise MediaError("Apify found no video for that link (private, deleted or not a reel)")
    out = tmp / "apify"
    out.mkdir()
    return sreel.download_video(video_url, out / "source.mp4")


def reel_link(reel: dict, sc: str) -> str:
    url = str(reel.get("url") or "")
    return url if sreel.instagram_code(url) == sc else sreel.reel_url(sc)


def fetch_one(sc: str, opts, out=print) -> dict:
    """One reel's video into media/<sc>.mp4, from the first source that works."""
    check_sc(sc)
    reel = store.load_reel(sc)
    expected = expected_duration(reel)
    dest = media_path(sc)
    check_media_path(dest)
    if dest.exists() and not opts.force:
        return {"sc": sc, "source": "kept (already in media/; --force to redo)"}
    url = reel_link(reel, sc)
    tmp = make_temp()
    tried = []
    try:
        for name in ("Vault copy", "yt-dlp", "Apify re-pull"):
            try:
                if name == "Vault copy":
                    src = vault_copy(sc)
                    if not src.is_file():
                        tried.append(f"{name}: none")
                        continue
                elif name == "yt-dlp":
                    src = from_ytdlp(url, tmp)
                else:
                    src = from_apify(sc, url, tmp, opts)
                check_duration(probe(src)["duration"], expected, f"the {name}")
                encoded = tmp / "encoded.mp4"
                encoded.unlink(missing_ok=True)
                encode(src, encoded)
                info = check_mp4(encoded, expected)
                install(encoded, dest)
                return {"sc": sc, "source": name, "bytes": info["bytes"], "duration": info["duration"],
                        "audio": info["audio"]}
            except (MediaError, sreel.ReelError) as e:
                tried.append(f"{name}: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    raise MediaError(f"{sc}: no source worked. " + " | ".join(tried))


def cmd_fetch(args, out=print) -> int:
    if args.max_usd < 0 or args.max_usd > APPROVED_MAX_USD + 1e-9:
        raise MediaError(f"--max-usd must be from 0 to {APPROVED_MAX_USD:.2f} (the approved ceiling)")
    if bool(args.all) == bool(args.sc):
        raise MediaError("name one or more shortcodes, or --all (not both)")
    targets = swipe_shortcodes() if args.all else [check_sc(sc) for sc in args.sc]
    if not targets:
        raise MediaError("the swipe file has no reels")
    check_media_root()
    refused = 0
    for sc in targets:
        try:
            got = fetch_one(sc, args, out)
        except (MediaError, StoreError) as e:
            refused += 1
            out(f"{sc}: refused: {e}")
            continue
        if "bytes" in got:
            sound = "with sound" if got["audio"] else "NO SOUND TRACK"
            out(f"{sc}: {got['source']} -> media/{sc}.mp4, {fmt_size(got['bytes'])}, {fmt_s(got['duration'])}, {sound}")
        else:
            out(f"{sc}: {got['source']}")
    sreel.assert_no_video()
    out(f"{len(targets) - refused} of {len(targets)} ready in media/. Apify re-pulls so far: ${apify_spent():.3f} "
        f"of ${args.max_usd:.2f}.")
    return 2 if refused else 0


# ---------------------------------------------------------------- the Blob store (vercel CLI)

def blob_token() -> str:
    """BLOB_READ_WRITE_TOKEN from the environment or the Tribe .env. Never printed."""
    value = os.environ.get(TOKEN_ENV, "").strip()
    if not value and Path(ENV_FILE).is_file():
        for line in Path(ENV_FILE).read_text(encoding="utf-8").splitlines():
            key, sep, v = line.partition("=")
            if sep and key.strip() == TOKEN_ENV:
                value = v.strip().strip('"').strip("'")
    if not value:
        raise MediaError(f"{TOKEN_ENV} is not set in the Tribe .env (it is read, never printed)")
    return value


def vercel(args: list[str], token: str, timeout: int = VERCEL_TIMEOUT_S) -> str:
    """One `vercel blob ...` call from web/, the token passed with --rw-token. Returns its output
    (stdout and stderr, colours stripped, token scrubbed); MediaError when it fails."""
    cmd = [tool("vercel"), "blob", *args, "--rw-token", token, "--scope", SCOPE]
    env = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0"}
    try:
        r = run_tool(cmd, cwd=WEB, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise MediaError(f"vercel blob {args[0]} took longer than {timeout} s") from None
    except OSError as e:
        raise MediaError(scrub(f"vercel blob {args[0]} could not start ({type(e).__name__})", token)) from None
    text = scrub(strip_ansi(f"{r.stdout or ''}\n{r.stderr or ''}"), token)
    if r.returncode != 0:
        raise MediaError(f"vercel blob {args[0]} failed (exit {r.returncode}): {last_line(text)}")
    return text


def blob_list(token: str) -> set[str]:
    """Every pathname under reels/ in the store."""
    found, cursor = set(), None
    for _ in range(50):
        args = ["list", "--prefix", BLOB_PREFIX, "--limit", "1000"] + (["--next", cursor] if cursor else [])
        text = vercel(args, token)
        found |= {m.group(1) for m in LISTED_RE.finditer(text)}
        m = NEXT_RE.search(text)
        nxt = m.group(1).strip("`'\"") if m else None
        if not nxt or nxt == cursor:
            return found
        cursor = nxt
    raise MediaError("vercel blob list did not finish after 50 pages")


def blob_put(path: Path, pathname: str, token: str) -> None:
    if not PATHNAME_RE.fullmatch(pathname):
        raise MediaError(f"not a reel video pathname: {pathname!r}")
    text = vercel(["put", str(path), "--pathname", pathname, "--access", "private",
                   "--content-type", "video/mp4"], token)
    if pathname not in text:
        raise MediaError(f"vercel blob put did not report {pathname} ({last_line(text)})")


def blob_del(pathname: str, token: str) -> None:
    if not pathname.startswith(BLOB_PREFIX) or ".." in pathname:
        raise MediaError(f"not a reel video pathname: {pathname!r}")
    vercel(["del", pathname], token)


# ---------------------------------------------------------------- push and status

def open_db():
    """A tribe_runner connection, schema version checked (mocked in the tests)."""
    db.load_env()
    return db.connect()


def local_files() -> tuple[dict[str, Path], list[str]]:
    """({sc: media/<sc>.mp4}, [other names in media/])."""
    root = Path(MEDIA)
    files, other = {}, []
    if not root.is_dir():
        return files, other
    for p in sorted(root.iterdir()):
        if p.name.startswith(".") and p.name.endswith(".partial"):
            continue
        try:
            files[check_media_path(p)] = p
        except MediaError:
            other.append(p.name)
    return files, other


def cmd_push(args, out=print) -> int:
    reels = set(swipe_shortcodes())
    if not reels:
        raise MediaError("the swipe file has no reels: refusing to push (it would delete every online copy)")
    check_media_root()
    files, other = local_files()
    for name in other:
        out(f"skipped media/{name}: not <shortcode>.mp4")
    ready, refused = {}, 0
    for sc, path in files.items():
        if sc not in reels:
            continue
        try:
            ready[sc] = check_mp4(path, expected_duration(store.load_reel(sc)))
        except (MediaError, StoreError) as e:
            refused += 1
            out(f"{sc}: refused, not pushed: {e}")
    dry = "would " if args.dry_run else ""
    token = blob_token()
    conn = open_db()
    try:
        rows = {r["shortcode"]: r for r in db.list_reel_videos(conn)}
        stored = blob_list(token)
        keep = {r["pathname"] for sc, r in rows.items() if sc in reels}
        sent = same = 0
        for sc, info in sorted(ready.items()):
            want = db.reel_video_pathname(sc, info["sha256"])
            row = rows.get(sc)
            keep.add(want)
            if row and row["sha256"] == info["sha256"] and row["pathname"] == want and want in stored:
                same += 1
                continue
            if row and row["pathname"] != want:
                keep.discard(row["pathname"])
            if args.dry_run:
                out(f"{sc}: would upload {want} ({fmt_size(info['bytes'])})")
            else:
                if want not in stored:
                    blob_put(files[sc], want, token)
                db.upsert_reel_video(conn, sc, want, info["sha256"], info["bytes"], info["duration"])
                out(f"{sc}: uploaded {want} ({fmt_size(info['bytes'])}, {fmt_s(info['duration'])})")
            sent += 1
        gone = 0
        for sc in sorted(set(rows) - reels):       # the reel left the swipe file
            out(f"{sc}: {dry}remove the online copy (the reel left the swipe file)")
            if not args.dry_run:
                db.delete_reel_video(conn, sc)
            gone += 1
        for sc in sorted(set(files) - reels):
            out(f"{sc}: {dry}remove media/{sc}.mp4 (the reel left the swipe file)")
            if not args.dry_run:
                check_media_path(files[sc])
                files[sc].unlink()
        orphans = sorted(stored - keep)
        for pathname in orphans:
            out(f"{dry}delete {pathname} (replaced, or no row uses it)")
            if not args.dry_run:
                blob_del(pathname, token)
    finally:
        conn.close()
    sreel.assert_no_video()
    out(f"{'Dry run: ' if args.dry_run else ''}{sent} {dry}uploaded, {same} unchanged, {gone} removed, "
        f"{len(orphans)} Blob files {dry}deleted, {refused} refused.")
    return 2 if refused else 0


def cmd_status(args, out=print) -> int:
    reels = {r["shortcode"]: r for r in store.list_reels(include_archived=True) if r.get("shortcode")}
    files, other = local_files()
    rows, note = None, ""
    if args.offline:
        note = "uploaded: not checked (--offline)"
    else:
        try:
            conn = open_db()
            try:
                rows = {r["shortcode"]: r for r in db.list_reel_videos(conn)}
            finally:
                conn.close()
        except db.DbError as e:
            note = f"uploaded: not checked ({e})"
    out(f"{'reel':<14}{'local':<7}{'size':>10}{'length':>11}{'reel.json':>11}  uploaded")
    missing = 0
    for sc in sorted(set(reels) | set(files)):
        path = files.get(sc)
        size = length = digest = None
        if path:
            size = path.stat().st_size
            try:
                length = probe(path)["duration"]
            except MediaError:
                length = None
            digest = sha256_file(path) if rows is not None else None
        else:
            missing += 1
        want = ((reels.get(sc) or {}).get("facts") or {}).get("duration_s")
        if rows is None:
            up = "?"
        elif sc not in rows:
            up = "no"
        elif not path:
            up = "yes (no local file)"
        elif rows[sc]["sha256"] == digest:
            up = "yes"
        else:
            up = "no (an older file is online)"
        where = "" if sc in reels else "  (not in the swipe file)"
        out(f"{sc:<14}{'yes' if path else 'no':<7}{fmt_size(size):>10}{fmt_s(length):>11}"
            f"{fmt_s(want if isinstance(want, (int, float)) else None):>11}  {up}{where}")
    for name in other:
        out(f"media/{name}: not <shortcode>.mp4")
    if note:
        out(note)
    out(f"{len(reels) - missing} of {len(reels)} swipe reels have a local video.")
    return 0


# ---------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m strategist.media", description="Private copies of swipe reel videos (D30)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch", help="get and encode reel videos into media/ (free; Apify only with --allow-apify --yes)")
    p.add_argument("sc", nargs="*", help="reel shortcodes")
    p.add_argument("--all", action="store_true", help="every reel in the swipe file")
    p.add_argument("--force", action="store_true", help="redo a reel that already has media/<sc>.mp4")
    p.add_argument("--allow-apify", action="store_true", help="allow the paid Apify re-pull when the free sources fail")
    p.add_argument("--yes", action="store_true", help="go ahead with the paid Apify re-pull")
    p.add_argument("--max-usd", type=float, default=APPROVED_MAX_USD,
                   help=f"ceiling for all media re-pulls in swipe/fetch-log.jsonl (at most {APPROVED_MAX_USD})")
    p = sub.add_parser("push", help="upload new or changed videos to the private Blob store; delete unused ones")
    p.add_argument("--dry-run", action="store_true", help="show what would change; change nothing")
    p = sub.add_parser("status", help="each reel: local file, size, length, uploaded")
    p.add_argument("--offline", action="store_true", help="skip the database (uploaded shows ?)")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return {"fetch": cmd_fetch, "push": cmd_push, "status": cmd_status}[args.cmd](args)
    except (MediaError, StoreError, db.DbError, sreel.ReelError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
