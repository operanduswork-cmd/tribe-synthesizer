"use client";

// The 3D brain's canvas (loaded on demand by brain-section.tsx with next/dynamic, ssr: false; the
// only file that pulls in three.js, through brain-scene.ts). A thin React wrapper: it builds the
// scene once per data set, hands it the selected second, the palette (light or dark) and the
// focus, and frees it all on unmount. The scene draws on demand and never draws text; the card,
// legend and labels are DOM. data-layer="brain" and role="img" with a full label sit on the canvas
// itself, inside the brain chart (data-chart="brain").

import { useEffect, useImperativeHandle, useRef, type Ref } from "react";

import type { BrainAtlas, BrainFrames, BrainMesh } from "@/lib/brain/format";

import { getFocus, subscribeFocus } from "./brain-focus";
import { BrainScene, type Angle } from "./brain-scene";
import type { BrainPalette } from "./lut";
import type { BrainView } from "./view";

export type { Angle };

export type BrainCanvasHandle = {
  setAngle: (angle: "outside" | "inside") => void;
  reset: () => void;
};

type BrainCanvasProps = {
  view: BrainView;
  data: { mesh: BrainMesh; atlas: BrainAtlas; frames: BrainFrames };
  /** The selected second (clamped to the read's rows by the scene). */
  t: number;
  /** Play is stepping: blend from the second shown to the next (never under reduced motion). */
  playing: boolean;
  reduced: boolean;
  touch: boolean;
  palette: BrainPalette;
  label: string;
  onReady: () => void;
  onLost: () => void;
  onAngle: (angle: Angle) => void;
  /** Outside / Inside / Reset, for the DOM controls over the canvas. */
  handle?: Ref<BrainCanvasHandle>;
};

export function BrainCanvas({ view, data, t, playing, reduced, touch, palette, label, onReady, onLost, onAngle, handle }: BrainCanvasProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef<BrainScene | null>(null);
  // The latest callbacks and settings, read by the scene when it needs them.
  const live = useRef({ reduced, onReady, onLost, onAngle });
  useEffect(() => {
    live.current = { reduced, onReady, onLost, onAngle };
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    let scene: BrainScene;
    try {
      scene = new BrainScene(canvas, wrap, {
        view,
        data,
        palette,
        touch,
        reduced: () => live.current.reduced,
        onReady: () => live.current.onReady(),
        onLost: () => live.current.onLost(),
        onAngle: (a) => live.current.onAngle(a),
      });
    } catch {
      live.current.onLost();
      return;
    }
    sceneRef.current = scene;
    const unsub = subscribeFocus(() => scene.applyFocus(getFocus()));
    return () => {
      unsub();
      scene.dispose();
      sceneRef.current = null;
    };
    // Built once per data set; the second, palette and focus are applied below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, view]);

  useEffect(() => {
    sceneRef.current?.setSecond(t, playing);
  }, [t, playing, data]);

  useEffect(() => {
    sceneRef.current?.setPalette(palette);
  }, [palette, data]);

  useImperativeHandle(handle, () => ({
    setAngle: (a) => sceneRef.current?.turnTo(a),
    reset: () => sceneRef.current?.turnTo("outside"),
  }));

  return (
    <div ref={wrapRef} className="absolute inset-0">
      <canvas
        ref={canvasRef}
        data-brain-canvas=""
        data-layer="brain"
        data-scale-abs={view.vmax}
        role="img"
        aria-label={label}
        className="block size-full cursor-grab touch-pan-y select-none active:cursor-grabbing motion-safe:animate-brain-in"
      />
    </div>
  );
}
