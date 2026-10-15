"""Local timed transcript with faster-whisper (MIT) on the laptop CPU. Free, no API.

Usage:
    python -m strategist.transcribe <audio_or_video> [--out words.json] [--model small.en]
                                    [--compare outputs/<job>/events.json]

Writes words.json as [{text, start, stop}] (seconds). A video is read by ffmpeg
into a 16 kHz mono wav in a temp folder first; the wav is deleted afterwards.
The model downloads once from Hugging Face (open weights, no token) into the
usual Hugging Face cache.

Never falls back to a paid service. If faster-whisper is missing it stops with
a clear message (pip install faster-whisper).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_MODEL = "small.en"   # base.en is the faster fallback (--model base.en)
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
NO_SPEECH_MAX = 0.6     # Whisper's own no-speech threshold
WORD_PROB_MIN = 0.5


class TranscribeError(Exception):
    """Transcription could not run. The message says why and what to do."""


def is_word(text: str) -> bool:
    """A token with at least one letter or digit (a lone "." from the transcriber is not a word)."""
    return bool(re.search(r"\w", text or ""))


def _model(name: str):
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # Windows cache note, harmless
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise TranscribeError(
            "faster-whisper is not installed. Install it with: pip install faster-whisper "
            "(MIT, runs on the CPU, free). No paid fallback is used.") from e
    # int8 on the CPU: the same off-CUDA setting the backend uses for WhisperX (GOTCHAS).
    return WhisperModel(name, device="cpu", compute_type="int8")


def extract_audio(video: Path, wav: Path) -> Path:
    """16 kHz mono wav for the transcriber. Raises TranscribeError without ffmpeg."""
    if not shutil.which("ffmpeg"):
        raise TranscribeError("ffmpeg is not on PATH; it is needed to read the audio track")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1",
                        "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], capture_output=True, text=True)
    if r.returncode != 0 or not wav.is_file():
        raise TranscribeError(f"ffmpeg could not read the audio of {video.name}: {r.stderr.strip()[-300:]}")
    return wav


def transcribe_audio(audio: Path, model: str = DEFAULT_MODEL) -> list[dict]:
    """Timed words from a wav (or any file ffmpeg/av can decode)."""
    whisper = _model(model)
    segments, _info = whisper.transcribe(str(audio), language="en", word_timestamps=True,
                                         beam_size=5, condition_on_previous_text=False)
    words = []
    for seg in segments:
        # Whisper invents a lone "you" in music or silence (seen at 0:50 on the Sintel
        # trailer: no-speech 0.89, word probability 0.13). Drop such segments.
        if seg.no_speech_prob > NO_SPEECH_MAX and all(w.probability < WORD_PROB_MIN for w in seg.words or []):
            continue
        for w in seg.words or []:
            text = w.word.strip()
            if is_word(text):
                words.append({"text": text, "start": round(float(w.start), 3), "stop": round(float(w.end), 3)})
    return words


def transcribe_media(path: Path, model: str = DEFAULT_MODEL) -> list[dict]:
    """Timed words from an audio or video file. Video audio goes through a temp wav that is deleted."""
    path = Path(path)
    if not path.is_file():
        raise TranscribeError(f"file not found: {path}")
    if path.suffix.lower() in AUDIO_EXTS:
        return transcribe_audio(path, model)
    with tempfile.TemporaryDirectory(prefix="strategist-audio-") as tmp:
        wav = extract_audio(path, Path(tmp) / "audio.wav")
        return transcribe_audio(wav, model)


def words_from_events(events_path: Path) -> list[dict]:
    """Timed words from a TRIBE job's events.json (WhisperX on Modal)."""
    data = json.loads(Path(events_path).read_text(encoding="utf-8"))
    rows = data.get("words", []) if isinstance(data, dict) else data
    out = []
    for w in rows:
        if isinstance(w, dict) and is_word(str(w.get("text", "")).strip()) and w.get("start") is not None:
            stop = w.get("stop", w["start"] + (w.get("duration") or 0))
            out.append({"text": str(w["text"]).strip(), "start": round(float(w["start"]), 3),
                        "stop": round(float(stop), 3)})
    return out


def compare(words: list[dict], reference: list[dict]) -> dict:
    """First-word time and word count against a reference transcript."""
    def first(ws):
        return ws[0]["start"] if ws else None
    a, b = first(words), first(reference)
    return {"words": len(words), "reference_words": len(reference),
            "word_count_diff": len(words) - len(reference),
            "first_word_s": a, "reference_first_word_s": b,
            "first_word_diff_s": round(a - b, 3) if a is not None and b is not None else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Local timed transcript (faster-whisper, CPU, free)")
    ap.add_argument("media")
    ap.add_argument("--out", help="where to write words.json (default: print a summary only)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--compare", help="a TRIBE events.json to compare first-word time and word count with")
    args = ap.parse_args(argv)
    t0 = time.monotonic()
    try:
        words = transcribe_media(Path(args.media), args.model)
    except TranscribeError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    took = time.monotonic() - t0
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(words, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {len(words)} words to {args.out}")
    print(f"model {args.model}, cpu int8, {took:.1f} s")
    if args.compare:
        print(json.dumps(compare(words, words_from_events(Path(args.compare))), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
