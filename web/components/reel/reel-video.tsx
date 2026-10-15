"use client";

// The reel's own video with its sound (D30): a private copy of the swipe reel, played only
// through the login-locked site (/reels/<sc>/video signs a 20-minute link into the private Blob
// store). It is the page's clock: ReelTime follows its time while it plays, and every seek (the
// timeline, the brain slider, a time chip, the keys) moves it, so the brain and the lanes show
// the second the video shows. Its own figure (data-chart="video") holds no counts and no brain
// values (D20). Our own controls over the picture: Play/Pause (the same action as the brain's
// Play) and sound, 44px on touch. A dark frame, no poster, until the picture is in; the source
// is set once the page is live, so no load event fires before the handlers are on.
//
// On an error (a link that ran out, a dropped connection) it asks the route again with a fresh
// query and goes back to the same time once, playing again if it was. After two failures in a
// row it shows a short note and a retry button, and Play falls back to the 1-s step.

import { PauseIcon, PlayIcon, Volume2Icon, VolumeXIcon } from "lucide-react";
import { useEffect, useEffectEvent, useRef, useState, useSyncExternalStore } from "react";

import { copy } from "@/lib/copy";
import { cn } from "@/lib/utils";

import { useReelTime } from "./reel-time";

const V = copy.reel.video;
const MAX_RETRIES = 2;
const BUTTON =
  "inline-flex size-8 items-center justify-center rounded-full bg-black/55 text-white transition-colors outline-none hover:bg-black/75 focus-visible:ring-2 focus-visible:ring-indigo-accent pointer-coarse:size-11";

const noSubscribe = () => () => {};

type Status = "loading" | "ready" | "failed";

export function ReelVideo({ sc, className }: { sc: string; className?: string }) {
  const { t, playing, toggle, pause, attachVideo } = useReelTime();
  const live = useSyncExternalStore(noSubscribe, () => true, () => false);
  const base = `/reels/${encodeURIComponent(sc)}/video`;
  const ref = useRef<HTMLVideoElement>(null);
  const [src, setSrc] = useState(base);
  const [status, setStatus] = useState<Status>("loading");
  const [muted, setMuted] = useState(false);
  const [ratio, setRatio] = useState<string | null>(null);
  const retries = useRef(0);
  // Where to go back to after a reload (once), and whether to play again.
  const restore = useRef<{ at: number; play: boolean } | null>(null);
  const failed = status === "failed";

  // The video is the clock while it works; a video that failed hands the clock back.
  useEffect(() => {
    const el = ref.current;
    if (!el || failed) return;
    attachVideo(el);
    return () => attachVideo(null);
  }, [failed, attachVideo]);

  useEffect(() => {
    if (ref.current) ref.current.muted = muted;
  }, [muted]);

  function reload(at: number, play: boolean) {
    restore.current = { at, play };
    setStatus("loading");
    setSrc(`${base}?r=${Date.now().toString(36)}`);
  }

  const onLoadedMetadata = useEffectEvent((v: HTMLVideoElement) => {
    if (v.videoWidth > 0 && v.videoHeight > 0) setRatio(`${v.videoWidth} / ${v.videoHeight}`);
    setStatus("ready");
    const back = restore.current;
    restore.current = null;
    if (back) {
      if (back.at > 0) v.currentTime = back.at;
      if (back.play) v.play().catch(() => {});
    } else if (t !== null && t > 0) {
      // The page opens on a second (the read's first HIGH): show that frame.
      v.currentTime = t;
    }
  });

  const onError = useEffectEvent((v: HTMLVideoElement) => {
    const wasPlaying = playing;
    if (wasPlaying) pause();
    if (retries.current >= MAX_RETRIES) {
      setStatus("failed");
      return;
    }
    retries.current += 1;
    // Before the first load currentTime reads 0: then the selected second is the place to be.
    reload(v.currentTime > 0 ? v.currentTime : (t ?? 0), wasPlaying);
  });

  // The media events, as native listeners: a load error can land while React holds its own
  // events back (a commit in flight), and a missed one would leave the frame loading for good.
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    const meta = () => onLoadedMetadata(v);
    const ok = () => {
      retries.current = 0;
    };
    const fail = () => onError(v);
    v.addEventListener("loadedmetadata", meta);
    v.addEventListener("canplay", ok);
    v.addEventListener("error", fail);
    return () => {
      v.removeEventListener("loadedmetadata", meta);
      v.removeEventListener("canplay", ok);
      v.removeEventListener("error", fail);
    };
  }, []);

  function retry() {
    retries.current = 0;
    reload(t ?? 0, false);
  }

  return (
    <figure data-chart="video" aria-label={V.label} className={cn("flex min-w-0 justify-center", className)}>
      <div
        data-video-frame={status}
        aria-busy={status === "loading"}
        className="relative h-[min(52dvh,28rem)] max-w-full overflow-hidden rounded-xl bg-black lg:h-[min(36dvh,22rem)]"
        style={{ aspectRatio: ratio ?? "9 / 16" }}
      >
        <video
          ref={ref}
          src={live ? src : undefined}
          playsInline
          preload="metadata"
          aria-label={V.label}
          onClick={toggle}
          className="absolute inset-0 size-full cursor-pointer object-contain"
        />
        {status === "loading" ? (
          <span data-layer="ui" className="sr-only">
            {V.loading}
          </span>
        ) : null}
        {failed ? (
          <div data-layer="ui" data-video-failed="" className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-3 text-center text-white">
            <p className="text-ui">{V.failed}</p>
            <button
              type="button"
              data-video-retry=""
              onClick={retry}
              className="inline-flex h-8 items-center rounded-full bg-white/15 px-3 text-ui font-medium text-white transition-colors outline-none hover:bg-white/25 focus-visible:ring-2 focus-visible:ring-indigo-accent pointer-coarse:h-11"
            >
              {V.retry}
            </button>
          </div>
        ) : (
          <div
            role="group"
            aria-label={V.controls}
            data-layer="ui"
            data-video-controls=""
            className="absolute inset-x-0 bottom-0 flex items-center gap-1.5 bg-linear-to-t from-black/60 to-black/0 p-2"
          >
            <button type="button" data-video-play="" aria-label={playing ? V.pause : V.play} onClick={toggle} className={BUTTON}>
              {playing ? <PauseIcon aria-hidden className="size-4" /> : <PlayIcon aria-hidden className="size-4 translate-x-px" />}
            </button>
            <button
              type="button"
              data-video-sound={muted ? "off" : "on"}
              aria-label={muted ? V.soundOn : V.soundOff}
              onClick={() => setMuted((m) => !m)}
              className={BUTTON}
            >
              {muted ? <VolumeXIcon aria-hidden className="size-4" /> : <Volume2Icon aria-hidden className="size-4" />}
            </button>
          </div>
        )}
      </div>
    </figure>
  );
}
