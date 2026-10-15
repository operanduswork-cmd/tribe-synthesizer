"""Tests for strategist/media.py (D30 reel videos). Run: python strategist/test_media.py

Everything is synthetic (shortcodes like "TESTVID01", fake video files with a JSON tail that the
fake ffprobe reads). yt-dlp, ffmpeg, ffprobe and the vercel CLI are faked through media.run_tool
and media.tool, the database through media.open_db (a fake that runs strategist/db.py's own
reel_videos statements), and Apify through reel.fetch and reel.download_video; a stray network
call fails the test. Writes only to temp folders: the real swipe/, media/ and .env
are never read or touched."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
sys.path.insert(0, str(PROJECT_ROOT))
from strategist import db, media, store  # noqa: E402
from strategist import reel as sreel  # noqa: E402

FAKE_TOKEN = "vercel_blob_rw_SYNTHstore0001_SYNTHETICsecretNEVERprint0123456789"
SECRET_TAIL = FAKE_TOKEN.rsplit("_", 1)[-1]
MP4_HEAD = b"\x00\x00\x00\x20ftypisom"            # 12 bytes: a size, then the ftyp box
WEBM_HEAD = b"\x1a\x45\xdf\xa3webm-head"          # 12 bytes: an EBML (WebM) start
MARK = b"\nFAKE-META:"
MP4_FORMAT = "mov,mp4,m4a,3gp,3g2,mj2"


def fake_video(path: Path, duration: float, *, head=MP4_HEAD, fmt=MP4_FORMAT, video="h264", audio="aac",
               salt: str = "") -> Path:
    """A synthetic 'video': a container head, some bytes and a JSON tail the fake ffprobe reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"duration": duration, "format": fmt, "video": video, "audio": audio}
    path.write_bytes(head + b"\x00" * 64 + salt.encode() + MARK + json.dumps(meta).encode())
    return path


def read_meta(path: Path) -> dict:
    data = Path(path).read_bytes()
    return json.loads(data[data.rindex(MARK) + len(MARK):])


def no_network(*a, **k):
    raise AssertionError("unexpected network call in a test")


class FakeTools:
    """Plays yt-dlp, ffmpeg, ffprobe and `vercel blob` for media.run_tool. Records every call."""

    def __init__(self, blobs=None):
        self.calls = []
        self.ytdlp_duration = None     # None: yt-dlp fails (login wall)
        self.shift = 0.0               # seconds the fake encode adds
        self.out_mp4 = True            # False: the encode writes a WebM by mistake
        self.blobs = dict(blobs or {})
        self.echo_token = False        # vercel prints the token (the scrub must hide it)
        self.vercel_fail = None        # sub-command that fails, printing the token
        self.vercel_timeout = False
        self.page = None               # list page size, to test --next

    def names(self):
        return [c["tool"] for c in self.calls]

    def of(self, name):
        return [c for c in self.calls if c["tool"] == name]

    def __call__(self, cmd, *, cwd=None, timeout=None, env=None):
        cmd = [str(c) for c in cmd]
        if cmd[0] == "ffprobe-bin":
            name = "ffprobe"
        elif cmd[0] == "ffmpeg-bin":
            name = "ffmpeg"
        elif cmd[0] == "vercel-bin":
            name = "vercel"
        elif cmd[:4] == [sys.executable, "-P", "-m", "yt_dlp"]:
            name = "yt-dlp"
        else:
            raise AssertionError(f"unexpected tool: {cmd[:4]}")
        self.calls.append({"tool": name, "cmd": cmd, "cwd": cwd, "env": env})
        return getattr(self, name.replace("-", "_"))(cmd, cwd)

    @staticmethod
    def done(code=0, out="", err=""):
        return subprocess.CompletedProcess([], code, out, err)

    def ffprobe(self, cmd, cwd):
        path = Path(cmd[-1])
        try:
            m = read_meta(path)
        except (OSError, ValueError):
            return self.done(1, "", f"{path.name}: Invalid data found when processing input")
        streams = [{"codec_type": "video", "codec_name": m["video"], "pix_fmt": "yuv420p", "width": 720, "height": 1280}]
        if m["audio"]:
            streams.append({"codec_type": "audio", "codec_name": m["audio"]})
        body = {"format": {"format_name": m["format"], "duration": f"{m['duration']:.6f}"}, "streams": streams}
        return self.done(0, json.dumps(body))

    def ffmpeg(self, cmd, cwd):
        src, out = Path(cmd[cmd.index("-i") + 1]), Path(cmd[-1])
        m = read_meta(src)
        if self.out_mp4:
            fake_video(out, m["duration"] + self.shift, audio=m["audio"], salt=src.read_bytes().hex()[:40])
        else:
            fake_video(out, m["duration"], head=WEBM_HEAD, fmt="matroska,webm", video="vp9", audio="opus")
        return self.done(0)

    def yt_dlp(self, cmd, cwd):
        if self.ytdlp_duration is None:
            return self.done(1, "", "ERROR: [Instagram] synthetic: login required")
        template = cmd[cmd.index("-o") + 1]
        fake_video(Path(template.replace("%(ext)s", "webm")), self.ytdlp_duration, head=WEBM_HEAD,
                   fmt="matroska,webm", video="vp9", audio="opus")
        return self.done(0)

    def vercel(self, cmd, cwd):
        assert cmd[1] == "blob", cmd
        sub = cmd[2]
        token = cmd[cmd.index("--rw-token") + 1]
        assert token == FAKE_TOKEN, "the token must come from the (temp) .env"
        assert cmd[cmd.index("--scope") + 1] == "your-vercel-scope"
        leak = f"\ndebug: using token {token} ({SECRET_TAIL})" if self.echo_token else ""
        if self.vercel_timeout:
            raise subprocess.TimeoutExpired(cmd, 900)
        if self.vercel_fail == sub:
            return self.done(1, "", f"Error: synthetic failure for token {token}{leak}")
        if sub == "put":
            pathname = cmd[cmd.index("--pathname") + 1]
            self.blobs[pathname] = Path(cmd[3]).read_bytes()
            return self.done(0, "", f"Success! https://synth.private.blob.vercel-storage.com/{pathname}{leak}")
        if sub == "del":
            self.blobs.pop(cmd[3], None)
            return self.done(0, "", f"Success! Blob deleted{leak}")
        if sub == "list":
            names = sorted(p for p in self.blobs if p.startswith(cmd[cmd.index("--prefix") + 1]))
            start = int(cmd[cmd.index("--next") + 1].removeprefix("cur")) if "--next" in cmd else 0
            end = len(names) if not self.page else start + self.page
            rows = [f"  1d     1234     {p}     https://synth.private.blob.vercel-storage.com/{p}" for p in names[start:end]]
            text = "\n  Uploaded At     Size     Pathname     URL\n" + "\n".join(rows) + "\n"
            if end < len(names):
                text += f"> To display the next page run `vercel blob list --prefix reels/ --limit 1000 --next cur{end}`\n"
            return self.done(0, text, leak)
        raise AssertionError(f"unexpected vercel blob {sub}")


class FakeDb:
    """The reel_videos table in memory, driven by strategist/db.py's own SQL."""

    def __init__(self, rows=None):
        self.rows = dict(rows or {})
        self.closed = False
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        if sql == db.UPSERT_REEL_VIDEO:
            sc, path, digest, size, dur = params
            new = {"shortcode": sc, "pathname": path, "sha256": digest, "bytes": size, "duration_s": dur}
            changed = self.rows.get(sc) != new
            self.rows[sc] = new
            return SimpleNamespace(rowcount=int(changed), fetchone=lambda: None, fetchall=lambda: [])
        if sql.startswith("DELETE FROM reel_videos"):
            row = self.rows.pop(params[0], None)
            got = [(row["pathname"],)] if row else []
            return SimpleNamespace(rowcount=len(got), fetchone=lambda: got[0] if got else None, fetchall=lambda: got)
        if sql.startswith("SELECT shortcode, pathname, sha256, bytes, duration_s FROM reel_videos"):
            got = [(r["shortcode"], r["pathname"], r["sha256"], r["bytes"], r["duration_s"])
                   for _, r in sorted(self.rows.items())]
            return SimpleNamespace(rowcount=len(got), fetchone=lambda: got[0] if got else None, fetchall=lambda: got)
        raise AssertionError(f"unexpected SQL: {sql[:60]}")

    def close(self):
        self.closed = True


class MediaBase(unittest.TestCase):
    """Temp swipe/, drafts/, VAULT, media/ and .env; fake tools and database; no network."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="media-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for target, name, value in (
                (store, "SWIPE", self.tmp / "tribe" / "swipe"), (store, "DRAFTS", self.tmp / "tribe" / "drafts"),
                (store, "OUTPUTS", self.tmp / "tribe" / "outputs"), (store, "VAULT", self.tmp / "vault"),
                (media, "MEDIA", self.tmp / "tribe" / "media"), (media, "ENV_FILE", self.tmp / "tribe" / ".env"),
                (sreel, "ENV_FILE", self.tmp / "tribe" / "no.env")):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        (self.tmp / "tribe").mkdir()
        (self.tmp / "tribe" / ".env").write_text(f"OTHER=1\n{media.TOKEN_ENV}={FAKE_TOKEN}\n", encoding="utf-8")
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(media.TOKEN_ENV, None)
        self.tools = FakeTools()
        self.db = FakeDb()
        for name, value in (("run_tool", self.tools), ("tool", lambda n: f"{n}-bin"), ("open_db", lambda: self.db)):
            p = mock.patch.object(media, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("urllib.request.urlopen", side_effect=no_network)
        p.start()
        self.addCleanup(p.stop)

    def add_reel(self, sc, duration=30.0):
        store.save_json(store.reel_path(sc), {"shortcode": sc, "url": f"https://www.instagram.com/reel/{sc}/",
                                              "facts": {"duration_s": duration}})

    def vault(self, sc, duration, **kw):
        return fake_video(store.VAULT / "research" / "repurpose" / "media" / sc / "video.mp4", duration, **kw)

    def local(self, sc, duration=30.0, salt=""):
        return fake_video(media.MEDIA / f"{sc}.mp4", duration, salt=salt or sc)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = media.main(list(argv))
        return code, out.getvalue() + err.getvalue()

    def assert_no_video_outside_media(self):
        for root in (store.SWIPE, store.DRAFTS):
            if root.is_dir():
                self.assertEqual([p for p in root.rglob("*") if p.suffix.lower() in sreel.VIDEO_EXTS], [])


# ---------------------------------------------------------------- fetch

class FetchTests(MediaBase):

    def test_vault_copy_first_encoded_exactly_and_left_untouched(self):
        self.add_reel("TESTVID01", 30.0)
        src = self.vault("TESTVID01", 30.2)
        before = (src.read_bytes(), src.stat().st_mtime_ns)
        code, out = self.run_cli("fetch", "TESTVID01")
        self.assertEqual(code, 0, out)
        dest = media.MEDIA / "TESTVID01.mp4"
        info = media.check_mp4(dest, 30.0)
        self.assertEqual((info["video"], info["audio"]), ("h264", "aac"))
        self.assertIn("Vault copy -> media/TESTVID01.mp4", out)
        self.assertNotIn("yt-dlp", self.tools.names())
        [enc] = self.tools.of("ffmpeg")
        cmd = enc["cmd"]
        self.assertEqual(cmd[cmd.index("-i") + 1], str(src))
        self.assertEqual(cmd[cmd.index("-i") + 2:-1], list(media.ENCODE_ARGS))
        self.assertEqual(list(media.ENCODE_ARGS), [
            "-vf", "scale=720:-2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-g", "30",
            "-sc_threshold", "0", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-map_metadata", "-1"])
        out_path = Path(cmd[-1])
        self.assertFalse(out_path.parent.exists(), "the temp folder is removed after")
        self.assertNotIn(PROJECT_ROOT.resolve(), out_path.resolve().parents, "encodes happen outside Tribe")
        self.assertEqual((src.read_bytes(), src.stat().st_mtime_ns), before, "the VAULT copy is only read")
        self.assertEqual(sorted(p.name for p in media.MEDIA.iterdir()), ["TESTVID01.mp4"])
        self.assert_no_video_outside_media()

    def test_ytdlp_when_there_is_no_vault_copy(self):
        self.add_reel("TESTVID02", 41.5)
        self.tools.ytdlp_duration = 41.3
        code, out = self.run_cli("fetch", "TESTVID02")
        self.assertEqual(code, 0, out)
        [dl] = self.tools.of("yt-dlp")
        self.assertEqual(dl["cmd"][-1], "https://www.instagram.com/reel/TESTVID02/")
        self.assertEqual(dl["cmd"][:4], [sys.executable, "-P", "-m", "yt_dlp"])
        for folder in (Path(dl["cwd"]), Path(dl["cmd"][dl["cmd"].index("-o") + 1]).parent):
            self.assertNotIn(PROJECT_ROOT.resolve(), folder.resolve().parents)
            self.assertNotIn((self.tmp / "tribe").resolve(), folder.resolve().parents)
            self.assertFalse(folder.exists(), "the download is deleted after")
        self.assertEqual(media.check_mp4(media.MEDIA / "TESTVID02.mp4", 41.5)["duration"], 41.3)
        self.assertIn("yt-dlp -> media/TESTVID02.mp4", out)

    def test_existing_video_is_kept_unless_forced(self):
        self.add_reel("TESTVID01")
        self.vault("TESTVID01", 30.0)
        self.assertEqual(self.run_cli("fetch", "TESTVID01")[0], 0)
        code, out = self.run_cli("fetch", "--all")
        self.assertEqual(code, 0, out)
        self.assertIn("kept", out)
        self.assertEqual(len(self.tools.of("ffmpeg")), 1)
        self.assertEqual(self.run_cli("fetch", "TESTVID01", "--force")[0], 0)
        self.assertEqual(len(self.tools.of("ffmpeg")), 2)

    def test_refuses_a_duration_mismatch(self):
        self.add_reel("TESTVID01", 30.0)
        self.vault("TESTVID01", 30.6)           # 0.6 s off
        self.tools.ytdlp_duration = 29.4      # 0.6 s off the other way
        code, out = self.run_cli("fetch", "TESTVID01")
        self.assertEqual(code, 2, out)
        self.assertIn("more than 0.5 s apart", out)
        self.assertEqual(self.tools.of("ffmpeg"), [], "a mismatched source is never encoded")
        self.assertFalse((media.MEDIA / "TESTVID01.mp4").exists())

    def test_refuses_an_encode_that_drifts(self):
        self.add_reel("TESTVID01", 30.0)
        self.vault("TESTVID01", 30.0)
        self.tools.shift = 0.8
        code, out = self.run_cli("fetch", "TESTVID01")
        self.assertEqual(code, 2, out)
        self.assertIn("encoded.mp4 is 30.80 s and reel.json says 30.00 s", out)
        self.assertFalse((media.MEDIA / "TESTVID01.mp4").exists())
        self.assertEqual(sorted(media.MEDIA.iterdir()) if media.MEDIA.exists() else [], [])

    def test_refuses_a_reel_without_a_length(self):
        store.save_json(store.reel_path("TESTVID01"), {"shortcode": "TESTVID01", "facts": {"duration_s": None}})
        self.vault("TESTVID01", 30.0)
        code, out = self.run_cli("fetch", "TESTVID01")
        self.assertEqual(code, 2)
        self.assertIn("no facts.duration_s", out)
        self.assertEqual(self.tools.calls, [])

    def test_refuses_non_mp4(self):
        good = fake_video(self.tmp / "good.mp4", 30.0)
        self.assertEqual(media.check_mp4(good)["format"], MP4_FORMAT)
        cases = {
            "webm.mp4": dict(head=WEBM_HEAD),                          # no ftyp box
            "vp9.mp4": dict(video="vp9"),                              # not H.264
            "mkv.mp4": dict(fmt="matroska,webm"),                      # not an MP4 container
        }
        for name, kw in cases.items():
            with self.assertRaises(media.MediaError, msg=name):
                media.check_mp4(fake_video(self.tmp / name, 30.0, **kw))
        with self.assertRaisesRegex(media.MediaError, "not an .mp4 file"):
            media.check_mp4(fake_video(self.tmp / "clip.webm", 30.0))
        with self.assertRaisesRegex(media.MediaError, "outside 1 to 600"):
            media.check_mp4(fake_video(self.tmp / "long.mp4", 900.0))
        (self.tmp / "text.mp4").write_text("not a video", encoding="utf-8")
        with self.assertRaises(media.MediaError):
            media.check_mp4(self.tmp / "text.mp4")
        # an encode that comes out as something else is refused and never lands in media/
        self.add_reel("TESTVID01", 30.0)
        self.vault("TESTVID01", 30.0)
        self.tools.out_mp4 = False
        code, out = self.run_cli("fetch", "TESTVID01")
        self.assertEqual(code, 2, out)
        self.assertIn("no ftyp box", out)
        self.assertFalse((media.MEDIA / "TESTVID01.mp4").exists())

    def test_refuses_paths_outside_media(self):
        enc = fake_video(self.tmp / "enc.mp4", 30.0)
        outside = [self.tmp / "elsewhere" / "TESTVID01.mp4", store.SWIPE / "reels" / "TESTVID01" / "TESTVID01.mp4",
                   store.DRAFTS / "TESTVID01.mp4", media.MEDIA / "sub" / "TESTVID01.mp4",
                   media.MEDIA / ".." / "TESTVID01.mp4"]
        for path in outside:
            with self.assertRaisesRegex(media.MediaError, "outside media/", msg=str(path)):
                media.check_media_path(path)
            with self.assertRaises(media.MediaError):
                media.install(enc, path)
            self.assertFalse(path.exists(), path)
        for name in ("TESTVID01.mov", "TESTVID01.mp4.part", "bad sc.mp4", "abc.mp4", "A" * 21 + ".mp4"):
            with self.assertRaisesRegex(media.MediaError, "not <shortcode>.mp4", msg=name):
                media.check_media_path(media.MEDIA / name)
        self.assertEqual(media.check_media_path(media.MEDIA / "Dd-D7G_zDKx.mp4"), "Dd-D7G_zDKx")
        # media/ may never sit inside swipe/ or drafts/
        self.add_reel("TESTVID01")
        self.vault("TESTVID01", 30.0)
        for bad in (store.SWIPE / "media", store.DRAFTS / "media", store.SWIPE):
            with mock.patch.object(media, "MEDIA", bad):
                code, out = self.run_cli("fetch", "TESTVID01")
                self.assertEqual(code, 2, out)
                self.assertIn("stays video-free", out)
        self.assertEqual(self.tools.calls, [])
        self.assert_no_video_outside_media()

    def test_refuses_a_temp_folder_inside_tribe(self):
        self.add_reel("TESTVID01")
        self.vault("TESTVID01", 30.0)
        inside = PROJECT_ROOT / "media-test-never-created"
        with mock.patch("tempfile.mkdtemp", return_value=str(inside)), \
                mock.patch.object(media.shutil, "rmtree") as rm:
            code, out = self.run_cli("fetch", "TESTVID01")
        self.assertEqual(code, 2)
        self.assertIn("temp folder is inside Tribe", out)
        self.assertFalse(inside.exists())
        rm.assert_called_once()
        self.assertEqual(self.tools.calls, [])

    def test_cli_needs_shortcodes_or_all(self):
        for argv in (["fetch"], ["fetch", "TESTVID01", "--all"], ["fetch", "bad/sc"], ["fetch", "x"]):
            code, out = self.run_cli(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("refused", out)
        code, out = self.run_cli("fetch", "NOREEL001")
        self.assertEqual(code, 2)
        self.assertIn("no reel NOREEL001", out)


class ApifyTests(MediaBase):
    """The paid fallback: only with --allow-apify and --yes, and never past --max-usd in all."""

    def setUp(self):
        super().setUp()
        for sc in ("TESTVID01", "TESTVID02", "TESTVID03"):
            self.add_reel(sc, 30.0)
        self.fetch = mock.patch.object(sreel, "fetch", side_effect=self.fake_fetch).start()
        self.download = mock.patch.object(sreel, "download_video", side_effect=self.fake_download).start()
        self.addCleanup(mock.patch.stopall)

    @staticmethod
    def fake_fetch(body, what, est_usd):
        sc = sreel.instagram_code(body["directUrls"][0])
        store.log_fetch(what, 1, est_usd, sreel.APIFY_ACTOR, True)
        return [{"shortCode": sc, "videoUrl": f"https://cdn.example.test/{sc}.mp4"}]

    @staticmethod
    def fake_download(url, dest):
        return fake_video(dest, 30.1)

    def log_rows(self):
        path = store.fetch_log_path()
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

    def test_no_apify_without_allow_apify(self):
        code, out = self.run_cli("fetch", "TESTVID01", "--yes")
        self.assertEqual(code, 2, out)
        self.assertIn("runs only with --allow-apify --yes", out)
        self.fetch.assert_not_called()
        self.download.assert_not_called()
        self.assertEqual(self.log_rows(), [])

    def test_apify_needs_yes(self):
        code, out = self.run_cli("fetch", "TESTVID01", "--allow-apify")
        self.assertEqual(code, 2, out)
        self.assertIn("Not run. Add --yes", out)
        self.fetch.assert_not_called()
        self.assertEqual(self.log_rows(), [])

    def test_apify_with_allow_and_yes(self):
        code, out = self.run_cli("fetch", "TESTVID01", "--allow-apify", "--yes")
        self.assertEqual(code, 0, out)
        body, what, cost = self.fetch.call_args.args
        self.assertEqual(body["directUrls"], ["https://www.instagram.com/reel/TESTVID01/"])
        self.assertEqual((what, cost), ("media re-pull TESTVID01", sreel.USD_PER_LINK))
        self.assertEqual(self.download.call_args.args[0], "https://cdn.example.test/TESTVID01.mp4")
        self.assertNotIn(PROJECT_ROOT.resolve(), Path(self.download.call_args.args[1]).resolve().parents)
        self.assertTrue((media.MEDIA / "TESTVID01.mp4").is_file())
        [row] = self.log_rows()
        self.assertEqual((row["what"], row["est_usd"]), ("media re-pull TESTVID01", 0.003))
        self.assertAlmostEqual(media.apify_spent(), 0.003)
        self.assert_no_video_outside_media()

    def test_refuses_past_the_ceiling(self):
        for i in range(40):     # 40 earlier re-pulls: $0.12 used
            store.log_fetch(f"media re-pull OLD{i:06d}", 1, 0.003, sreel.APIFY_ACTOR, True)
        store.log_fetch("reel TESTVID09", 1, 0.003, sreel.APIFY_ACTOR, True)   # not a media re-pull
        self.assertAlmostEqual(media.apify_spent(), 0.12)
        code, out = self.run_cli("fetch", "TESTVID01", "--allow-apify", "--yes")
        self.assertEqual(code, 2, out)
        self.assertIn("would pass the $0.12 ceiling", out)
        self.fetch.assert_not_called()
        self.assertEqual(len(self.log_rows()), 41)

    def test_max_usd_stops_a_batch_and_can_not_be_raised(self):
        code, out = self.run_cli("fetch", "--all", "--allow-apify", "--yes", "--max-usd", "0.006")
        self.assertEqual(code, 2, out)
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(sorted(p.name for p in media.MEDIA.iterdir()), ["TESTVID01.mp4", "TESTVID02.mp4"])
        self.assertIn("TESTVID03: refused", out)
        for over in ("0.13", "1", "-0.01"):
            code, out = self.run_cli("fetch", "TESTVID03", "--allow-apify", "--yes", "--max-usd", over)
            self.assertEqual(code, 2)
            self.assertIn("--max-usd must be from 0 to 0.12", out)
        self.assertEqual(self.fetch.call_count, 2)

    def test_free_sources_come_first(self):
        self.vault("TESTVID01", 30.0)
        self.tools.ytdlp_duration = 30.0
        code, out = self.run_cli("fetch", "TESTVID01", "TESTVID02", "--allow-apify", "--yes")
        self.assertEqual(code, 0, out)
        self.fetch.assert_not_called()
        self.assertEqual(len(self.tools.of("yt-dlp")), 1)   # TESTVID01 came from VAULT


# ---------------------------------------------------------------- push and status

class PushTests(MediaBase):

    def setUp(self):
        super().setUp()
        for sc in ("TESTVID01", "TESTVID02"):
            self.add_reel(sc, 30.0)
            self.local(sc, 30.0)

    def pathname(self, sc):
        return f"reels/{sc}-{media.sha256_file(media.MEDIA / f'{sc}.mp4')[:8]}.mp4"

    def test_push_uploads_new_files_then_skips_unchanged_ones(self):
        code, out = self.run_cli("push")
        self.assertEqual(code, 0, out)
        puts = [c for c in self.tools.of("vercel") if c["cmd"][2] == "put"]
        self.assertEqual(len(puts), 2)
        for call, sc in zip(puts, ("TESTVID01", "TESTVID02")):
            self.assertEqual(call["cmd"][:4], ["vercel-bin", "blob", "put", str(media.MEDIA / f"{sc}.mp4")])
            self.assertEqual(call["cmd"][4:], ["--pathname", self.pathname(sc), "--access", "private",
                                               "--content-type", "video/mp4", "--rw-token", FAKE_TOKEN,
                                               "--scope", "your-vercel-scope"])
            self.assertEqual(Path(call["cwd"]), PROJECT_ROOT / "web")
            self.assertRegex(self.pathname(sc), db.REEL_VIDEO_PATH_RE)
        self.assertEqual(sorted(self.db.rows), ["TESTVID01", "TESTVID02"])
        row = self.db.rows["TESTVID01"]
        self.assertEqual(row["pathname"], self.pathname("TESTVID01"))
        self.assertEqual(row["sha256"], media.sha256_file(media.MEDIA / "TESTVID01.mp4"))
        self.assertEqual(row["bytes"], (media.MEDIA / "TESTVID01.mp4").stat().st_size)
        self.assertEqual(row["duration_s"], 30.0)
        self.assertTrue(self.db.closed)
        self.assertEqual(sorted(self.tools.blobs), sorted(self.pathname(s) for s in ("TESTVID01", "TESTVID02")))
        # the same files again: nothing uploaded, nothing deleted, rows untouched
        before, sql_before, rows_before = len(self.tools.calls), len(self.db.sql), dict(self.db.rows)
        code, out = self.run_cli("push")
        self.assertEqual(code, 0, out)
        again = [c["cmd"][2] for c in self.tools.calls[before:] if c["tool"] == "vercel"]
        self.assertEqual(again, ["list"])
        self.assertIn("0 uploaded, 2 unchanged, 0 removed, 0 Blob files deleted", out)
        self.assertEqual([sql.split()[0] for sql, _ in self.db.sql[sql_before:]], ["SELECT"])
        self.assertEqual(self.db.rows, rows_before)

    def test_a_changed_file_replaces_the_old_blob(self):
        self.assertEqual(self.run_cli("push")[0], 0)
        old = self.pathname("TESTVID01")
        self.local("TESTVID01", 30.0, salt="re-encoded")
        new = self.pathname("TESTVID01")
        self.assertNotEqual(old, new)
        code, out = self.run_cli("push")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.db.rows["TESTVID01"]["pathname"], new)
        self.assertIn(new, self.tools.blobs)
        self.assertNotIn(old, self.tools.blobs)
        self.assertIn(f"delete {old}", out)

    def test_a_reel_that_left_the_swipe_file_is_removed_everywhere(self):
        self.assertEqual(self.run_cli("push")[0], 0)
        gone = self.pathname("TESTVID02")
        shutil.rmtree(store.reel_dir("TESTVID02"))
        code, out = self.run_cli("push")
        self.assertEqual(code, 0, out)
        self.assertNotIn("TESTVID02", self.db.rows)
        self.assertNotIn(gone, self.tools.blobs)
        self.assertFalse((media.MEDIA / "TESTVID02.mp4").exists())
        self.assertTrue((media.MEDIA / "TESTVID01.mp4").exists())
        self.assertIn("TESTVID01", self.db.rows)

    def test_orphan_blobs_are_deleted_and_others_left(self):
        self.tools.blobs["reels/OLDREEL01-deadbeef.mp4"] = b"x"
        self.tools.blobs["elsewhere/keep-me.txt"] = b"x"
        self.tools.page = 1       # one row per list page: the --next cursor is followed
        code, out = self.run_cli("push")
        self.assertEqual(code, 0, out)
        self.assertNotIn("reels/OLDREEL01-deadbeef.mp4", self.tools.blobs)
        self.assertIn("elsewhere/keep-me.txt", self.tools.blobs)
        lists = [c for c in self.tools.of("vercel") if c["cmd"][2] == "list"]
        self.assertGreaterEqual(len(lists), 1)
        self.assertTrue(all(c["cmd"][3:7] == ["--prefix", "reels/", "--limit", "1000"] for c in lists))

    def test_a_bad_file_is_refused_and_its_online_copy_kept(self):
        self.assertEqual(self.run_cli("push")[0], 0)
        kept = self.pathname("TESTVID02")
        self.local("TESTVID02", 33.0, salt="wrong cut")      # 3 s off reel.json
        fake_video(media.MEDIA / "TESTVID03.mp4", 30.0, head=WEBM_HEAD)   # no reel, and not an MP4
        self.add_reel("TESTVID03", 30.0)
        code, out = self.run_cli("push")
        self.assertEqual(code, 2, out)
        self.assertIn("TESTVID02: refused, not pushed", out)
        self.assertIn("TESTVID03: refused, not pushed", out)
        self.assertEqual(self.db.rows["TESTVID02"]["pathname"], kept)
        self.assertIn(kept, self.tools.blobs)
        self.assertNotIn("TESTVID03", self.db.rows)

    def test_stray_files_are_never_uploaded(self):
        (media.MEDIA / "notes.txt").write_text("x", encoding="utf-8")
        fake_video(media.MEDIA / "TESTVID01.mov", 30.0)
        code, out = self.run_cli("push")
        self.assertEqual(code, 0, out)
        self.assertIn("skipped media/notes.txt", out)
        puts = [c["cmd"][3] for c in self.tools.of("vercel") if c["cmd"][2] == "put"]
        self.assertEqual(sorted(Path(p).name for p in puts), ["TESTVID01.mp4", "TESTVID02.mp4"])

    def test_empty_swipe_file_is_refused(self):
        shutil.rmtree(store.SWIPE / "reels")
        code, out = self.run_cli("push")
        self.assertEqual(code, 2)
        self.assertIn("would delete every online copy", out)
        self.assertEqual(self.tools.calls, [])
        self.assertEqual(self.db.sql, [])

    def test_dry_run_changes_nothing(self):
        self.tools.blobs["reels/OLDREEL01-deadbeef.mp4"] = b"x"
        code, out = self.run_cli("push", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("would upload", out)
        self.assertIn("would delete reels/OLDREEL01-deadbeef.mp4", out)
        self.assertEqual([c["cmd"][2] for c in self.tools.of("vercel")], ["list"])
        self.assertEqual(self.db.rows, {})
        self.assertIn("reels/OLDREEL01-deadbeef.mp4", self.tools.blobs)

    def test_the_token_never_shows(self):
        self.tools.echo_token = True
        code, out = self.run_cli("push")
        self.assertEqual(code, 0, out)
        for case in ("put", "list", "del"):
            self.tools.vercel_fail = case
            self.tools.blobs["reels/OLDREEL01-deadbeef.mp4"] = b"x"
            self.local("TESTVID01", 30.0, salt=f"change {case}")
            code, out2 = self.run_cli("push")
            self.assertEqual(code, 2, case)
            self.assertIn(f"vercel blob {case} failed", out2)
            out += out2
        self.tools.vercel_fail = None
        self.tools.vercel_timeout = True
        code, out3 = self.run_cli("push")
        self.assertEqual(code, 2)
        self.assertIn("took longer than", out3)
        out += out3
        self.assertIn("***", out)
        self.assertNotIn(FAKE_TOKEN, out)
        self.assertNotIn(SECRET_TAIL, out)
        try:
            media.blob_list(FAKE_TOKEN)
        except media.MediaError as e:
            self.assertNotIn(FAKE_TOKEN, str(e))
            self.assertIsNone(e.__cause__)
            self.assertTrue(e.__suppress_context__, "the timeout (whose text holds the command) is not chained")
        else:
            self.fail("the timeout must be refused")
        self.assertEqual(media.scrub(f"a {FAKE_TOKEN} b {SECRET_TAIL} c", FAKE_TOKEN), "a *** b *** c")

    def test_token_is_read_from_the_env_file_only_when_asked(self):
        (self.tmp / "tribe" / ".env").write_text("OTHER=1\n", encoding="utf-8")
        code, out = self.run_cli("push")
        self.assertEqual(code, 2)
        self.assertIn("BLOB_READ_WRITE_TOKEN is not set", out)
        self.assertEqual(self.tools.of("vercel"), [])
        self.assertNotIn(FAKE_TOKEN, out)


class StatusTests(MediaBase):

    def test_status_lists_local_file_size_length_and_uploaded(self):
        for sc in ("TESTVID01", "TESTVID02", "TESTVID03"):
            self.add_reel(sc, 30.0)
        self.local("TESTVID01", 30.0)
        self.local("TESTVID02", 30.0)
        self.assertEqual(self.run_cli("push")[0], 0)
        self.local("TESTVID02", 30.0, salt="newer")
        fake_video(media.MEDIA / "STRAYVID9.mp4", 12.0)
        code, out = self.run_cli("status")
        self.assertEqual(code, 0, out)
        lines = {ln.split()[0]: ln for ln in out.splitlines() if ln.strip()}
        self.assertRegex(lines["TESTVID01"], r"TESTVID01\s+yes\s+0\.0 MB\s+30\.00 s\s+30\.00 s\s+yes$")
        self.assertIn("no (an older file is online)", lines["TESTVID02"])
        self.assertRegex(lines["TESTVID03"], r"TESTVID03\s+no\s+-\s+-\s+30\.00 s\s+no$")
        self.assertIn("(not in the swipe file)", lines["STRAYVID9"])
        self.assertIn("2 of 3 swipe reels have a local video.", out)
        code, out = self.run_cli("status", "--offline")
        self.assertEqual(code, 0)
        self.assertIn("uploaded: not checked (--offline)", out)
        self.assertRegex(out, r"TESTVID01\s+yes.*\?$|TESTVID01\s+yes.*\?\n")

    def test_status_without_a_database(self):
        self.add_reel("TESTVID01")
        with mock.patch.object(media, "open_db", side_effect=db.DbError("TRIBE_RUNNER_DATABASE_URL is not set")):
            code, out = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("uploaded: not checked (TRIBE_RUNNER_DATABASE_URL is not set)", out)

    def test_output_wording(self):
        """Media output keeps to sizes, lengths and yes/no: none of the banned words."""
        render = store.rules()
        self.add_reel("TESTVID01")
        self.local("TESTVID01")
        texts = []
        for argv in (("status",), ("push", "--dry-run"), ("push",), ("status",)):
            texts.append(self.run_cli(*argv)[1])
        texts.append(media.__doc__)
        for t in texts:
            self.assertEqual(render.find_banned(t), [], t[:80])


class ArchivedReelTests(MediaBase):
    """D31: archiving a reel hides it from the site but never deletes its video or its row."""

    def setUp(self):
        super().setUp()
        for sc in ("TESTVID01", "TESTVID02"):
            self.add_reel(sc, 30.0)
            self.local(sc, 30.0)

    def archive(self, sc):
        doc = store.load_reel(sc)
        doc["archived"] = True
        store.save_reel(doc)

    def test_swipe_shortcodes_include_archived_reels(self):
        self.archive("TESTVID02")
        self.assertEqual([r["shortcode"] for r in store.list_reels()], ["TESTVID01"])
        self.assertEqual(media.swipe_shortcodes(), ["TESTVID01", "TESTVID02"])

    def test_push_keeps_the_video_and_row_of_an_archived_reel(self):
        code, out = self.run_cli("push")
        self.assertEqual(code, 0, out)
        self.archive("TESTVID02")
        before = len(self.tools.calls)
        code, out = self.run_cli("push")
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(self.db.rows), ["TESTVID01", "TESTVID02"])
        self.assertEqual(len(self.tools.blobs), 2)
        self.assertEqual([c["cmd"][2] for c in self.tools.calls[before:] if c["tool"] == "vercel"], ["list"])
        self.assertIn("0 removed, 0 Blob files deleted", out)
        self.assertTrue((media.MEDIA / "TESTVID02.mp4").is_file())

    def test_fetch_all_and_status_still_count_archived_reels(self):
        self.archive("TESTVID01")
        code, out = self.run_cli("status", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("TESTVID01", out)
        self.assertIn("2 of 2 swipe reels have a local video", out)
        code, out = self.run_cli("fetch", "--all")
        self.assertIn("TESTVID01: kept", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
