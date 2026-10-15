"use client";

// The selected second on the reel screen. The timeline's playhead, the brain scrubber, the Areas
// tab, the time chips on the card, the beats and the moments all read and set it, so a chip on
// the left moves the playhead and the brain on the right (YouTube Studio / Apollo reference).
//
// When the reel's video is on the page (D30, components/reel/reel-video.tsx attaches it), the
// video is the clock: play(), pause() and toggle() play and pause it (the brain's Play and the
// video's Play are one action), the second follows Math.floor(video.currentTime) on every
// animation frame while it plays, and every seek (the timeline, the brain slider, a time chip,
// the keys) moves the video to that second. Without a video, Play steps the selected second
// forward once a second. Either way Play stops at the end, when the tab is hidden, or when the
// playhead is dragged. `source` says what moved the second last, so the playhead can glide while
// playing (1000 ms), ease on keys and chips (120 ms) and follow a drag at once; under reduced
// motion nothing glides or blends, and Play still plays.

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";

import { TimeChip } from "@/components/shared/time-chip";
import type { Layer } from "@/lib/contract";
import { prefersReducedMotion } from "@/lib/use-reduced-motion";
import { cn } from "@/lib/utils";

import { parseChip } from "./time";

export const TIMELINE_ID = "reel-timeline";

/** What moved the selected second last. */
export type SeekSource = "drag" | "key" | "chip" | "play";

export type SeekOptions = {
  /** Scroll the timeline into view when it is off screen (phone); instant under reduced motion. */
  reveal?: boolean;
  /** Default "key" ("chip" when reveal is passed as `true`). A drag stops Play. */
  source?: SeekSource;
};

export type ReelTime = {
  /** The selected whole second, or null before anything is picked. */
  t: number | null;
  lastSec: number;
  /** Play is on: the video plays, or (without one) the second steps forward. */
  playing: boolean;
  /** What moved the second last; null for the second the page opened on. */
  source: SeekSource | null;
  /** Select a second (and move the video there). `seek(t, true)` is short for
   *  `seek(t, { reveal: true, source: "chip" })`. */
  seek: (t: number, opts?: boolean | SeekOptions) => void;
  /** Play from here (from 0 when nothing is picked or at the last second). */
  play: () => void;
  pause: () => void;
  toggle: () => void;
  /** The reel's video becomes the clock (null hands the clock back to the 1-s step). */
  attachVideo: (video: HTMLVideoElement | null) => void;
};

type State = { t: number | null; source: SeekSource | null; playing: boolean };
type Action =
  | { type: "seek"; t: number; source: SeekSource; lastSec: number }
  | { type: "play"; lastSec: number }
  | { type: "pause" }
  | { type: "tick"; lastSec: number }
  /** The video started playing (our Play, or the system's media keys). */
  | { type: "playing" }
  /** The video's own second, read while it plays and when it ends. */
  | { type: "sync"; t: number; lastSec: number; playing?: boolean };

const clampSec = (t: number, lastSec: number) => Math.min(Math.max(0, Math.floor(t)), lastSec);

/** The whole second the video shows (a hair of slack, so a seek to 5 that lands on 4.9999 reads 5). */
const videoSec = (video: HTMLVideoElement, lastSec: number) => clampSec(video.currentTime + 1e-3, lastSec);

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case "seek":
      return { t: clampSec(a.t, a.lastSec), source: a.source, playing: a.source === "drag" ? false : s.playing };
    case "play":
      if (a.lastSec <= 0) return s;
      return { t: s.t === null || s.t >= a.lastSec ? 0 : s.t, source: "play", playing: true };
    case "pause":
      return s.playing ? { ...s, playing: false } : s;
    case "tick": {
      if (!s.playing) return s;
      const next = (s.t ?? -1) + 1;
      return next >= a.lastSec ? { t: a.lastSec, source: "play", playing: false } : { t: next, source: "play", playing: true };
    }
    case "playing":
      return s.playing && s.source === "play" ? s : { ...s, source: "play", playing: true };
    case "sync": {
      const t = clampSec(a.t, a.lastSec);
      const playing = a.playing ?? s.playing;
      return s.t === t && s.source === "play" && s.playing === playing ? s : { t, source: "play", playing };
    }
  }
}

const Ctx = createContext<ReelTime | null>(null);

export function ReelTimeProvider({
  lastSec,
  initialT = null,
  children,
}: {
  lastSec: number;
  /** The second the page opens on (the read's first HIGH away from the edges), or null. */
  initialT?: number | null;
  children: ReactNode;
}) {
  const [state, dispatch] = useReducer(reducer, null, () => ({
    t: initialT === null || !Number.isFinite(initialT) ? null : clampSec(initialT, lastSec),
    source: null,
    playing: false,
  }));

  // The reel's video, when one is on the page and loads (ReelVideo attaches it). The element sits
  // in a ref (it is the browser's, written to directly); `videoKey` changes with it, so the
  // effects below follow the element that is attached now.
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [videoKey, setVideoKey] = useState(0);
  const attachVideo = useCallback((el: HTMLVideoElement | null) => {
    if (videoRef.current === el) return;
    videoRef.current = el;
    setVideoKey((k) => k + 1);
  }, []);

  const seek = useCallback(
    (next: number, opts?: boolean | SeekOptions) => {
      const o: SeekOptions = typeof opts === "boolean" ? { reveal: opts, source: opts ? "chip" : "key" } : (opts ?? {});
      const source = o.source ?? "key";
      dispatch({ type: "seek", t: next, source, lastSec });
      const video = videoRef.current;
      if (video) {
        // A drag stops Play; the video goes to the second (a chip goes to its start even from
        // inside the same second; a drag moves it only when the second changes).
        if (source === "drag" && !video.paused) video.pause();
        const target = clampSec(next, lastSec);
        if (source === "chip" || videoSec(video, lastSec) !== target) video.currentTime = target;
      }
      if (!o.reveal) return;
      const el = document.getElementById(TIMELINE_ID);
      if (!el) return;
      const box = el.getBoundingClientRect();
      if (box.top < 0 || box.top > window.innerHeight * 0.6) {
        el.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
      }
    },
    [lastSec],
  );
  const play = useCallback(() => {
    const video = videoRef.current;
    if (video && lastSec > 0) {
      const from = state.t === null || state.t >= lastSec ? 0 : state.t;
      if (video.ended || videoSec(video, lastSec) !== from) video.currentTime = from;
      video.play().catch(() => {
        // Refused or cut short (no data yet, a reload): Play shows off again.
        if (video.paused) dispatch({ type: "pause" });
      });
    }
    dispatch({ type: "play", lastSec });
  }, [state.t, lastSec]);
  const pause = useCallback(() => {
    videoRef.current?.pause();
    dispatch({ type: "pause" });
  }, []);
  const toggle = useCallback(() => (state.playing ? pause() : play()), [state.playing, pause, play]);

  // Without a video: one step a second while playing; the step that reaches the last second
  // also stops.
  useEffect(() => {
    if (!state.playing || videoRef.current) return;
    const id = window.setInterval(() => dispatch({ type: "tick", lastSec }), 1000);
    return () => window.clearInterval(id);
  }, [state.playing, videoKey, lastSec]);

  // With a video: the second follows its currentTime on every frame while it plays (no
  // smoothing: whole seconds only, so reduced motion needs nothing more here).
  useEffect(() => {
    const video = videoRef.current;
    if (!state.playing || !video) return;
    let id = 0;
    let last = -1;
    const step = () => {
      const s = videoSec(video, lastSec);
      if (s !== last) {
        last = s;
        dispatch({ type: "sync", t: s, lastSec });
      }
      id = requestAnimationFrame(step);
    };
    id = requestAnimationFrame(step);
    return () => cancelAnimationFrame(id);
  }, [state.playing, videoKey, lastSec]);

  // The video's own play, pause and end (also from the system's media keys) set Play.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const onPlay = () => dispatch({ type: "playing" });
    const onPause = () => dispatch({ type: "pause" });
    const onEnded = () => dispatch({ type: "sync", t: videoSec(video, lastSec), lastSec, playing: false });
    video.addEventListener("play", onPlay);
    video.addEventListener("pause", onPause);
    video.addEventListener("ended", onEnded);
    return () => {
      video.removeEventListener("play", onPlay);
      video.removeEventListener("pause", onPause);
      video.removeEventListener("ended", onEnded);
    };
  }, [videoKey, lastSec]);

  // A hidden tab stops Play (it never runs on in the background), the video included.
  useEffect(() => {
    const onVisibility = () => {
      if (!document.hidden) return;
      videoRef.current?.pause();
      dispatch({ type: "pause" });
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  const value = useMemo(
    () => ({ t: state.t, lastSec, playing: state.playing, source: state.source, seek, play, pause, toggle, attachVideo }),
    [state.t, state.playing, state.source, lastSec, seek, play, pause, toggle, attachVideo],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useReelTime(): ReelTime {
  const v = useContext(Ctx);
  if (!v) throw new Error("useReelTime needs ReelTimeProvider");
  return v;
}

/** A time chip that selects its second on the timeline, and shows as selected while the
 *  playhead sits inside its span. */
export function SeekChip({ time, layer = "facts", className }: { time: string; layer?: Layer; className?: string }) {
  const { t, seek } = useReelTime();
  const span = parseChip(time);
  const cls = cn("whitespace-nowrap", className);
  if (!span) return <TimeChip time={time} layer={layer} className={cls} />;
  return (
    <TimeChip
      time={time}
      layer={layer}
      active={t !== null && t >= span.start && t < span.end}
      onClick={() => seek(span.start, { reveal: true, source: "chip" })}
      className={cls}
    />
  );
}
