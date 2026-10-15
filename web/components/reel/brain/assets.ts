// Fetch, unpack and check the brain view's data, once per URL per session (a module-level promise
// cache; the URLs carry the asset hash, so a cached promise can never go stale). The routes send
// the stored gzip with Content-Encoding: gzip, so the browser unpacks it; when a proxy has
// dropped that header the bytes still start with the gzip magic and DecompressionStream unpacks
// them here. Every file is checked by lib/brain/format.ts before anything draws it. A failed
// load is forgotten, so the next try fetches again. Browser only.

import { decodeAtlas, decodeFrames, decodeMesh, GZIP_MAGIC, type BrainAreasPayload, type BrainAtlas, type BrainFrames, type BrainMesh } from "@/lib/brain/format";

import type { BrainView } from "./view";

export type Progress = (received: number) => void;

const cache = new Map<string, Promise<unknown>>();

function once<T>(key: string, load: () => Promise<T>): Promise<T> {
  let hit = cache.get(key) as Promise<T> | undefined;
  if (!hit) {
    hit = load().catch((e) => {
      cache.delete(key);
      throw e;
    });
    cache.set(key, hit);
  }
  return hit;
}

async function gunzip(bytes: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([bytes as BlobPart]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** The response body as bytes, reporting the bytes received so far. */
async function body(url: string, onProgress?: Progress): Promise<Uint8Array> {
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok || !res.body) throw new Error(`brain data: ${res.status}`);
  const reader = res.body.getReader();
  const parts: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value);
    size += value.byteLength;
    onProgress?.(size);
  }
  const out = new Uint8Array(size);
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.byteLength;
  }
  return out[0] === GZIP_MAGIC[0] && out[1] === GZIP_MAGIC[1] ? gunzip(out) : out;
}

export const loadMesh = (view: BrainView, onProgress?: Progress): Promise<BrainMesh> =>
  once(view.urls.mesh, async () => decodeMesh(await body(view.urls.mesh, onProgress)));

export const loadAtlas = (view: BrainView, onProgress?: Progress): Promise<BrainAtlas> =>
  once(view.urls.atlas, async () => decodeAtlas(await body(view.urls.atlas, onProgress)));

export const loadFrames = (view: BrainView, onProgress?: Progress): Promise<BrainFrames> =>
  once(view.urls.frames, async () => decodeFrames(await body(view.urls.frames, onProgress), view.timeS.length));

/** The per-area series (Areas tab, the hover card). */
export const loadAreas = (view: BrainView): Promise<BrainAreasPayload> =>
  once(view.urls.areas, async () => {
    const res = await fetch(view.urls.areas, { credentials: "same-origin" });
    if (!res.ok) throw new Error(`brain areas: ${res.status}`);
    const data = (await res.json()) as BrainAreasPayload;
    if (data.job_id !== view.jobId || data.time_s.length !== view.timeS.length) throw new Error("brain areas: another read");
    return data;
  });

/** The areas payload if it has already arrived (no fetch), else null. */
const settled = new Map<string, BrainAreasPayload>();
export function areasNow(view: BrainView): BrainAreasPayload | null {
  return settled.get(view.urls.areas) ?? null;
}
export function loadAreasSettled(view: BrainView): Promise<BrainAreasPayload> {
  return loadAreas(view).then((a) => {
    settled.set(view.urls.areas, a);
    return a;
  });
}

export type BrainData = { mesh: BrainMesh; atlas: BrainAtlas; frames: BrainFrames };

/** Mesh, atlas and frames in parallel, with one progress figure (0..1) over their sizes. */
export function loadBrain(view: BrainView, onProgress?: (share: number) => void): Promise<BrainData> {
  const total = view.bytes.mesh + view.bytes.atlas + view.bytes.frames;
  const got = { mesh: 0, atlas: 0, frames: 0 };
  const tick = (k: keyof typeof got) => (n: number) => {
    got[k] = n;
    onProgress?.(Math.min(1, (got.mesh + got.atlas + got.frames) / Math.max(1, total)));
  };
  return Promise.all([loadMesh(view, tick("mesh")), loadAtlas(view, tick("atlas")), loadFrames(view, tick("frames"))]).then(
    ([mesh, atlas, frames]) => ({ mesh, atlas, frames }),
  );
}
