// SYNTHETIC brain assets for fixtures mode (TRIBE_DATA_SOURCE unset or "fixtures"), built in
// memory at request time; nothing binary sits in web/fixtures and no FreeSurfer data is in web/.
//
// - Mesh: an order-5 icosphere per side, which has the same 10,242 points and 20,480 faces a
//   side as fsaverage5, stretched to the size of an inflated hemisphere with a flatter inner face
//   and made-up folds. Each side is centred near x = 0, as the real mesh is
//   (web/contracts/brain-assets.json), so the viewer places the sides apart itself.
// - Atlas: made-up patches. Per side, a cap on the inner face is the medial wall; the other
//   points are cut into bands front to back and handed out to the 180 areas in atlas order, with
//   exactly the point counts fixtures/brain.json gives (atlas.hcp.n_left / n_right), and each
//   area's network from atlas.hcp.network.
// - Frames: every point of an area carries that area's series from fixtures/brain.json
//   (areas.hcp_left / hcp_right), on the page's one scale (scale.vmax), so the area means of the
//   frames are the page's area means to within half a level, except in the areas whose series
//   run past the scale and clip at 127 (about 1% of values, as in a real read).
//
// The page's asset hashes describe the laptop's bytes, so getBrain swaps in the hashes of these
// assets (withFixtureAssets): the routes then check fixture bytes exactly as they check real ones.

import "server-only";

import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";

import { BRAIN, BRAIN_MAGIC, assetKind, assetVersion, type BrainAssetKind, type StoredBrainAsset } from "@/lib/brain/format";
import type { BrainPage } from "@/lib/hosted.gen";

// ---------------------------------------------------------------- geometry

type Sphere = { pos: Float64Array; faces: Uint32Array };

/** An icosphere on the unit sphere: 10 * 4^order + 2 points, 20 * 4^order faces. */
function icosphere(order: number): Sphere {
  const t = (1 + Math.sqrt(5)) / 2;
  const pts: number[] = [-1, t, 0, 1, t, 0, -1, -t, 0, 1, -t, 0, 0, -1, t, 0, 1, t, 0, -1, -t, 0, 1, -t, t, 0, -1, t, 0, 1, -t, 0, -1, -t, 0, 1];
  let faces: number[] = [
    0, 11, 5, 0, 5, 1, 0, 1, 7, 0, 7, 10, 0, 10, 11, 1, 5, 9, 5, 11, 4, 11, 10, 2, 10, 7, 6, 7, 1, 8, 3, 9, 4, 3, 4, 2, 3, 2, 6, 3,
    6, 8, 3, 8, 9, 4, 9, 5, 2, 4, 11, 6, 2, 10, 8, 6, 7, 9, 8, 1,
  ];
  for (let i = 0; i < pts.length; i += 3) {
    const l = Math.hypot(pts[i], pts[i + 1], pts[i + 2]);
    pts[i] /= l;
    pts[i + 1] /= l;
    pts[i + 2] /= l;
  }
  for (let level = 0; level < order; level++) {
    const mids = new Map<number, number>();
    const mid = (a: number, b: number): number => {
      const key = a < b ? a * 1_000_003 + b : b * 1_000_003 + a;
      let m = mids.get(key);
      if (m === undefined) {
        const x = pts[3 * a] + pts[3 * b];
        const y = pts[3 * a + 1] + pts[3 * b + 1];
        const z = pts[3 * a + 2] + pts[3 * b + 2];
        const l = Math.hypot(x, y, z);
        m = pts.length / 3;
        pts.push(x / l, y / l, z / l);
        mids.set(key, m);
      }
      return m;
    };
    const next: number[] = [];
    for (let i = 0; i < faces.length; i += 3) {
      const [a, b, c] = [faces[i], faces[i + 1], faces[i + 2]];
      const ab = mid(a, b);
      const bc = mid(b, c);
      const ca = mid(c, a);
      next.push(a, ab, ca, b, bc, ab, c, ca, bc, ab, bc, ca);
    }
    faces = next;
  }
  return { pos: Float64Array.from(pts), faces: Uint32Array.from(faces) };
}

/** Made-up sulcal depth: smooth folds, about -1.5 to 1.8 like the real range. */
function sulcAt(x: number, y: number, z: number): number {
  return 1.1 * Math.sin(4.1 * x + 2.3 * y) * Math.cos(3.7 * z - 1.1 * y) + 0.45 * Math.sin(9 * y + 2 * z) + 0.15;
}

type SideMesh = { coords: Float32Array; faces: Uint16Array; sulc: Float32Array };

/** One hemisphere: the sphere stretched to about 83 x 216 x 146 (fsaverage5 inflated), its inner
 *  face (towards the other side) flatter, centred near x = 0, faces wound outward. */
function sideMesh(sphere: Sphere, inner: 1 | -1): SideMesh {
  const n = sphere.pos.length / 3;
  const coords = new Float32Array(n * 3);
  const sulc = new Float32Array(n);
  let minX = Infinity;
  let maxX = -Infinity;
  const xs = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const [x, y, z] = [sphere.pos[3 * i], sphere.pos[3 * i + 1], sphere.pos[3 * i + 2]];
    const s = sulcAt(x * inner, y, z);
    sulc[i] = s;
    const r = 1 - 0.025 * s;
    const flat = x * inner > 0 ? 0.55 : 1;
    xs[i] = x * r * flat;
    coords[3 * i + 1] = 108 * y * r;
    coords[3 * i + 2] = 73 * z * r;
    minX = Math.min(minX, xs[i]);
    maxX = Math.max(maxX, xs[i]);
  }
  for (let i = 0; i < n; i++) coords[3 * i] = (82 * (xs[i] - minX)) / (maxX - minX) - 41 + inner * 0.8;
  const faces = new Uint16Array(sphere.faces.length);
  for (let f = 0; f < sphere.faces.length; f += 3) {
    const a = sphere.faces[f];
    let [b, c] = [sphere.faces[f + 1], sphere.faces[f + 2]];
    const p = (k: number, d: number) => sphere.pos[3 * k + d];
    const u = [p(b, 0) - p(a, 0), p(b, 1) - p(a, 1), p(b, 2) - p(a, 2)];
    const v = [p(c, 0) - p(a, 0), p(c, 1) - p(a, 1), p(c, 2) - p(a, 2)];
    const nx = u[1] * v[2] - u[2] * v[1];
    const ny = u[2] * v[0] - u[0] * v[2];
    const nz = u[0] * v[1] - u[1] * v[0];
    const out = nx * (p(a, 0) + p(b, 0) + p(c, 0)) + ny * (p(a, 1) + p(b, 1) + p(c, 1)) + nz * (p(a, 2) + p(b, 2) + p(c, 2));
    if (out < 0) [b, c] = [c, b];
    faces[f] = a;
    faces[f + 1] = b;
    faces[f + 2] = c;
  }
  return { coords, faces, sulc };
}

/** Per point of one side: 0 for the medial wall, else the 1-based area. */
function sideLookup(sphere: Sphere, inner: 1 | -1, counts: number[], order: number[]): Uint8Array {
  const n = sphere.pos.length / 3;
  const used = counts.reduce((a, b) => a + b, 0);
  const medial = n - used;
  if (medial < 0) throw new Error(`synthetic atlas: ${used} area points, more than the ${n} a side has`);
  const p = (i: number, d: number) => sphere.pos[3 * i + d];
  const pole = [inner, -0.1, 0];
  const byPole = Array.from({ length: n }, (_, i) => i).sort(
    (a, b) => p(b, 0) * pole[0] + p(b, 1) * pole[1] - (p(a, 0) * pole[0] + p(a, 1) * pole[1]) || a - b,
  );
  const lookup = new Uint8Array(n);
  const rest = byPole.slice(medial).sort((a, b) => p(a, 1) - p(b, 1) || a - b);
  const BANDS = 8;
  const walk: number[] = [];
  for (let k = 0; k < BANDS; k++) {
    const band = rest.slice(Math.round((k * rest.length) / BANDS), Math.round(((k + 1) * rest.length) / BANDS));
    band.sort((a, b) => Math.atan2(p(a, 2), p(a, 0) * inner) - Math.atan2(p(b, 2), p(b, 0) * inner) || a - b);
    if (k % 2) band.reverse();
    walk.push(...band);
  }
  let at = 0;
  for (const k of order) {
    for (let j = 0; j < counts[k]; j++) lookup[walk[at++]] = k + 1;
  }
  return lookup;
}

// ---------------------------------------------------------------- packing

function header(kind: BrainAssetKind, a: number, b: number, c: number): Uint8Array {
  const out = new Uint8Array(BRAIN.headerBytes);
  const magic = BRAIN_MAGIC[kind];
  for (let i = 0; i < 4; i++) out[i] = magic.charCodeAt(i);
  const dv = new DataView(out.buffer);
  dv.setUint32(4, a, true);
  dv.setUint32(8, b, true);
  dv.setUint32(12, c, true);
  return out;
}

function concat(parts: ArrayBufferView[]): Uint8Array {
  const size = parts.reduce((s, p) => s + p.byteLength, 0);
  const out = new Uint8Array(size);
  let at = 0;
  for (const p of parts) {
    out.set(new Uint8Array(p.buffer, p.byteOffset, p.byteLength), at);
    at += p.byteLength;
  }
  return out;
}

const le = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;
if (!le) throw new Error("synthetic brain assets need a little-endian machine");

function pack(key: string, raw: Uint8Array): StoredBrainAsset {
  const kind = assetKind(key);
  if (!kind) throw new Error(`synthetic brain asset: not a brain asset key: ${key}`);
  const bytes = new Uint8Array(gzipSync(raw, { level: 9 }));
  if (bytes.byteLength > BRAIN.storedMax) throw new Error(`synthetic brain asset ${key}: ${bytes.byteLength} gzip bytes, over the limit`);
  return { key, kind, bytes, rawBytes: raw.byteLength, hash: createHash("sha256").update(bytes).digest("hex") };
}

let sphere: Sphere | null = null;
const getSphere = () => (sphere ??= icosphere(5));

function meshAsset(key: string): StoredBrainAsset {
  const s = getSphere();
  if (s.pos.length / 3 !== BRAIN.perSide || s.faces.length / 3 !== BRAIN.facesPerSide) throw new Error("synthetic mesh: not fsaverage5-sized");
  const left = sideMesh(s, 1);
  const right = sideMesh(s, -1);
  const version = Number(assetVersion(key)?.slice(1) ?? 1);
  const raw = concat([
    header("mesh", BRAIN.perSide, BRAIN.facesPerSide, version),
    left.coords,
    right.coords,
    left.faces,
    right.faces,
    left.sulc,
    right.sulc,
  ]);
  return pack(key, raw);
}

type Lookup = { hcp: Uint8Array; yeo: Uint8Array };

function lookupOf(page: BrainPage): Lookup {
  const s = getSphere();
  const { n_left, n_right, network } = page.atlas.hcp;
  const hcp = concat([sideLookup(s, 1, n_left, page.atlas.order), sideLookup(s, -1, n_right, page.atlas.order)]);
  const yeo = hcp.map((k) => (k === 0 ? 0 : network[k - 1]));
  return { hcp, yeo };
}

function atlasAsset(key: string, lookup: Lookup): StoredBrainAsset {
  return pack(key, concat([header("atlas", BRAIN.vertices, BRAIN.hcpAreas, BRAIN.yeoNetworks), lookup.hcp, lookup.yeo]));
}

function framesAsset(page: BrainPage, lookup: Lookup): StoredBrainAsset {
  const T = page.time_s.length;
  const V = BRAIN.vertices;
  const L = BRAIN.levels;
  const q = new Int8Array(T * V);
  for (let v = 0; v < V; v++) {
    const k = lookup.hcp[v];
    if (k === 0) continue;
    const series = (v < BRAIN.perSide ? page.areas.hcp_left : page.areas.hcp_right)[k - 1];
    for (let t = 0; t < T; t++) q[t * V + v] = Math.max(-L, Math.min(L, Math.round((series[t] / page.scale.vmax) * L)));
  }
  return pack(page.frames.key, concat([header("frames", T, V, L), q]));
}

// ---------------------------------------------------------------- per page, cached

type PageAssets = { frames: StoredBrainAsset; mesh: StoredBrainAsset; atlas: StoredBrainAsset };

const shared = new Map<string, StoredBrainAsset>();
const lookups = new Map<string, Lookup>();
const perJob = new Map<string, PageAssets>();

/** The synthetic frames, mesh and atlas behind one fixture brain page (built once a process). */
export function fixtureAssets(page: BrainPage): PageAssets {
  let hit = perJob.get(page.job_id);
  if (!hit) {
    let lookup = lookups.get(page.atlas.key);
    if (!lookup) lookups.set(page.atlas.key, (lookup = lookupOf(page)));
    let mesh = shared.get(page.mesh.key);
    if (!mesh) shared.set(page.mesh.key, (mesh = meshAsset(page.mesh.key)));
    let atlas = shared.get(page.atlas.key);
    if (!atlas) shared.set(page.atlas.key, (atlas = atlasAsset(page.atlas.key, lookup)));
    hit = { frames: framesAsset(page, lookup), mesh, atlas };
    perJob.set(page.job_id, hit);
  }
  return hit;
}

/** The fixture page with its asset blocks pointing at the synthetic assets' hashes and sizes. */
export function withFixtureAssets(page: BrainPage): BrainPage {
  const a = fixtureAssets(page);
  return {
    ...page,
    frames: { ...page.frames, sha256: a.frames.hash, bytes: a.frames.rawBytes },
    mesh: { ...page.mesh, sha256: a.mesh.hash, bytes: a.mesh.rawBytes },
    atlas: { ...page.atlas, sha256: a.atlas.hash, bytes: a.atlas.rawBytes },
  };
}

/** One synthetic asset by key, from the fixture pages, or null. */
export function fixtureAsset(pages: BrainPage[], key: string): StoredBrainAsset | null {
  for (const page of pages) {
    if (key !== page.frames.key && key !== page.mesh.key && key !== page.atlas.key) continue;
    const a = fixtureAssets(page);
    return [a.frames, a.mesh, a.atlas].find((x) => x.key === key) ?? null;
  }
  return null;
}
