// The brain view's binary assets (D28), read as web/contracts/brain-assets.json lays them out:
// TBF1 frames (int8, one row per second, one value per surface point), TBM1 mesh (f32 coords,
// u16 faces, f32 sulcal depth per side), TBA1 atlas (u8 HCP-MMP1 and Yeo-7 lookups). Each file
// starts with a fixed 16-byte little-endian header (a 4-byte ASCII magic, then three u32) and
// holds numbers only. Every decode checks the magic, the header numbers, the exact length and
// the value ranges before it hands an array out (strategist/brain_assets.py check_asset, line for
// line), and throws BrainFormatError on anything else.
//
// Also here: the cross-field checks on a brain page that the JSON schema cannot express, the D21
// check that a brain page belongs to the reel it is shown on, and the URLs of the brain routes.
// Pure functions: safe on the server and in the browser.

import contract from "@/contracts/brain-assets.json";
import type { BrainPage, TribePage } from "@/lib/hosted.gen";

export const BRAIN = {
  /** Surface points in a frame row: 10,242 left, then 10,242 right. */
  vertices: contract.vertices,
  perSide: contract.vertices_per_side,
  facesPerSide: contract.faces_per_side,
  headerBytes: contract.header_bytes,
  rowsMax: contract.rows_max,
  /** q runs -127..127; value = q / levels * scale.vmax. */
  levels: contract.levels,
  hcpAreas: contract.hcp_areas,
  yeoNetworks: contract.yeo_networks,
  storedMin: contract.stored_bytes.min,
  storedMax: contract.stored_bytes.max,
  rawMax: contract.raw_bytes.max,
} as const;

export const BRAIN_ASSET_KINDS = ["frames", "mesh", "atlas"] as const;
export type BrainAssetKind = (typeof BRAIN_ASSET_KINDS)[number];

export const BRAIN_MAGIC: Record<BrainAssetKind, string> = {
  frames: contract.kinds.frames.magic,
  mesh: contract.kinds.mesh.magic,
  atlas: contract.kinds.atlas.magic,
};

export const BRAIN_ASSET_KEY_RE = new RegExp(contract.key_pattern);
const KIND_KEY_RE: Record<BrainAssetKind, RegExp> = {
  frames: new RegExp(contract.kinds.frames.key_pattern),
  mesh: new RegExp(contract.kinds.mesh.key_pattern),
  atlas: new RegExp(contract.kinds.atlas.key_pattern),
};

/** The gzip magic (1f 8b) every stored asset starts with. */
export const GZIP_MAGIC = [0x1f, 0x8b] as const;

/** One stored asset as the brain_assets table holds it (lib/data.ts getBrainAsset). */
export type StoredBrainAsset = {
  key: string;
  kind: BrainAssetKind;
  /** The stored gzip bytes (served as they are, with Content-Encoding: gzip). */
  bytes: Uint8Array;
  /** The decompressed length (the page's `bytes`). */
  rawBytes: number;
  /** sha256 of the stored gzip bytes, hex (the page's `sha256`). */
  hash: string;
};

export class BrainFormatError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BrainFormatError";
  }
}

/** The asset kind a key's format names, or null when it is not a brain asset key. */
export function assetKind(key: string): BrainAssetKind | null {
  if (!BRAIN_ASSET_KEY_RE.test(key)) return null;
  return BRAIN_ASSET_KINDS.find((k) => KIND_KEY_RE[k].test(key)) ?? null;
}

/** The exact decompressed length of an asset (frames need their row count). */
export function rawSize(kind: BrainAssetKind, rows = 0): number {
  const { headerBytes: h, vertices: v, perSide: n, facesPerSide: f } = BRAIN;
  if (kind === "frames") return h + rows * v;
  if (kind === "mesh") return h + 2 * n * 3 * 4 + 2 * f * 3 * 2 + 2 * n * 4;
  return h + 2 * v;
}

// ---------------------------------------------------------------- reading

type Bytes = ArrayBuffer | ArrayBufferView;

function u8(data: Bytes): Uint8Array {
  if (data instanceof Uint8Array) return data;
  if (ArrayBuffer.isView(data)) return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  return new Uint8Array(data);
}

/** A copy on a fresh, aligned buffer when a typed view cannot sit on the bytes as they are. */
function aligned(b: Uint8Array): Uint8Array {
  return b.byteOffset % 4 === 0 ? b : new Uint8Array(b);
}

const LITTLE_ENDIAN = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;

function f32(b: Uint8Array, offset: number, count: number): Float32Array {
  if (LITTLE_ENDIAN) return new Float32Array(b.buffer, b.byteOffset + offset, count);
  const dv = new DataView(b.buffer, b.byteOffset + offset, count * 4);
  return Float32Array.from({ length: count }, (_, i) => dv.getFloat32(i * 4, true));
}

function u16(b: Uint8Array, offset: number, count: number): Uint16Array {
  if (LITTLE_ENDIAN) return new Uint16Array(b.buffer, b.byteOffset + offset, count);
  const dv = new DataView(b.buffer, b.byteOffset + offset, count * 2);
  return Uint16Array.from({ length: count }, (_, i) => dv.getUint16(i * 2, true));
}

export type BrainHeader = { magic: string; a: number; b: number; c: number };

/** The 16-byte header: the magic and three little-endian u32. */
export function readHeader(data: Bytes): BrainHeader {
  const b = u8(data);
  if (b.byteLength < BRAIN.headerBytes) {
    throw new BrainFormatError(`asset is ${b.byteLength} bytes, shorter than its ${BRAIN.headerBytes}-byte header`);
  }
  const dv = new DataView(b.buffer, b.byteOffset, BRAIN.headerBytes);
  return {
    magic: String.fromCharCode(b[0], b[1], b[2], b[3]),
    a: dv.getUint32(4, true),
    b: dv.getUint32(8, true),
    c: dv.getUint32(12, true),
  };
}

function expectMagic(kind: BrainAssetKind, head: BrainHeader) {
  if (head.magic !== BRAIN_MAGIC[kind]) throw new BrainFormatError(`${kind}: magic ${JSON.stringify(head.magic)}, expected ${BRAIN_MAGIC[kind]}`);
}

function expectLength(kind: BrainAssetKind, b: Uint8Array, want: number) {
  if (b.byteLength !== want) throw new BrainFormatError(`${kind}: ${b.byteLength} bytes, expected exactly ${want}`);
}

export type BrainFrames = {
  rows: number;
  vertices: number;
  levels: number;
  /** All rows, row-major: q[t * vertices + v]. */
  q: Int8Array;
};

/** TBF1. `rows`, when given, is the page's number of seconds and must match. */
export function decodeFrames(data: Bytes, rows?: number): BrainFrames {
  const b = aligned(u8(data));
  const head = readHeader(b);
  expectMagic("frames", head);
  const [n, v, levels] = [head.a, head.b, head.c];
  if (v !== BRAIN.vertices || levels !== BRAIN.levels) {
    throw new BrainFormatError(`frames: header says ${v} points at ${levels} levels, expected ${BRAIN.vertices} at ${BRAIN.levels}`);
  }
  if (n < 1 || n > BRAIN.rowsMax) throw new BrainFormatError(`frames: ${n} rows, expected 1 to ${BRAIN.rowsMax}`);
  if (rows !== undefined && n !== rows) throw new BrainFormatError(`frames: ${n} rows, the page has ${rows} seconds`);
  expectLength("frames", b, rawSize("frames", n));
  const q = new Int8Array(b.buffer, b.byteOffset + BRAIN.headerBytes, n * v);
  for (let i = 0; i < q.length; i++) if (q[i] < -levels) throw new BrainFormatError("frames: a value below -127 (never used)");
  return { rows: n, vertices: v, levels, q };
}

/** One second's row of a decoded frames file (a view, not a copy). */
export function frameRow(frames: BrainFrames, t: number): Int8Array {
  const r = Math.min(Math.max(0, Math.floor(t)), frames.rows - 1);
  return frames.q.subarray(r * frames.vertices, (r + 1) * frames.vertices);
}

/** A stored level back to model output on the reel's one scale. */
export function dequantise(q: number, vmax: number, levels: number = BRAIN.levels): number {
  return (q / levels) * vmax;
}

type Side<T> = { left: T; right: T };

export type BrainMesh = {
  version: number;
  perSide: number;
  facesPerSide: number;
  /** x, y, z per point; each side is centred near x = 0, so place the two sides apart along x. */
  coords: Side<Float32Array>;
  /** Three point indices per face, local to the side (0..10241), wound outward. */
  faces: Side<Uint16Array>;
  /** Sulcal depth per point: above 0 is deeper (darker grey). */
  sulc: Side<Float32Array>;
};

/** TBM1. */
export function decodeMesh(data: Bytes): BrainMesh {
  const b = aligned(u8(data));
  const head = readHeader(b);
  expectMagic("mesh", head);
  const [n, f, version] = [head.a, head.b, head.c];
  if (n !== BRAIN.perSide || f !== BRAIN.facesPerSide || version < 1 || version > 999) {
    throw new BrainFormatError(`mesh: header says ${n} points and ${f} faces a side (version ${version}), not fsaverage5`);
  }
  expectLength("mesh", b, rawSize("mesh"));
  let at = BRAIN.headerBytes;
  const take = <T>(read: (offset: number) => T, bytes: number): T => {
    const out = read(at);
    at += bytes;
    return out;
  };
  const coordsLeft = take((o) => f32(b, o, n * 3), n * 12);
  const coordsRight = take((o) => f32(b, o, n * 3), n * 12);
  const facesLeft = take((o) => u16(b, o, f * 3), f * 6);
  const facesRight = take((o) => u16(b, o, f * 3), f * 6);
  const sulcLeft = take((o) => f32(b, o, n), n * 4);
  const sulcRight = take((o) => f32(b, o, n), n * 4);
  for (const a of [coordsLeft, coordsRight, sulcLeft, sulcRight]) {
    for (let i = 0; i < a.length; i++) if (!Number.isFinite(a[i])) throw new BrainFormatError("mesh: a coordinate or depth is not a finite number");
  }
  for (const a of [facesLeft, facesRight]) {
    for (let i = 0; i < a.length; i++) if (a[i] >= n) throw new BrainFormatError("mesh: a face index is outside its side");
  }
  return {
    version,
    perSide: n,
    facesPerSide: f,
    coords: { left: coordsLeft, right: coordsRight },
    faces: { left: facesLeft, right: facesRight },
    sulc: { left: sulcLeft, right: sulcRight },
  };
}

export type BrainAtlas = {
  /** Per point: 0 = medial wall, k = 1..180 = atlas.hcp.labels[k - 1] (the same code on both sides). */
  hcp: Uint8Array;
  /** Per point: 0 = medial wall, k = 1..7 = atlas.yeo.labels[k - 1]. */
  yeo: Uint8Array;
};

/** TBA1. */
export function decodeAtlas(data: Bytes): BrainAtlas {
  const b = u8(data);
  const head = readHeader(b);
  expectMagic("atlas", head);
  const [v, areas, networks] = [head.a, head.b, head.c];
  if (v !== BRAIN.vertices || areas !== BRAIN.hcpAreas || networks !== BRAIN.yeoNetworks) {
    throw new BrainFormatError(`atlas: header says ${v} points, ${areas} areas, ${networks} networks`);
  }
  expectLength("atlas", b, rawSize("atlas"));
  const hcp = b.subarray(BRAIN.headerBytes, BRAIN.headerBytes + v);
  const yeo = b.subarray(BRAIN.headerBytes + v, BRAIN.headerBytes + 2 * v);
  for (let i = 0; i < v; i++) {
    if (hcp[i] > areas || yeo[i] > networks) throw new BrainFormatError("atlas: a lookup value outside 0..180 or 0..7");
  }
  return { hcp, yeo };
}

/** Check any decompressed asset against its kind (the routes run this before they serve). */
export function checkAsset(kind: BrainAssetKind, data: Bytes, rows?: number): void {
  if (kind === "frames") decodeFrames(data, rows);
  else if (kind === "mesh") decodeMesh(data);
  else decodeAtlas(data);
}

// ---------------------------------------------------------------- the page

/** What a brain page needs beyond its schema: every series as long as the seconds, the atlas
 *  order a permutation, the asset sizes exact. Empty when the page is whole. */
export function brainPageProblems(page: BrainPage): string[] {
  const out: string[] = [];
  const T = page.time_s.length;
  const series = (where: string, rows: number[][], n: number) => {
    if (rows.length !== n) out.push(`${where}: ${rows.length} rows, expected ${n}`);
    rows.forEach((r, i) => {
      if (r.length !== T) out.push(`${where}[${i}]: ${r.length} seconds, the page has ${T}`);
    });
  };
  series("areas.hcp_left", page.areas.hcp_left, BRAIN.hcpAreas);
  series("areas.hcp_right", page.areas.hcp_right, BRAIN.hcpAreas);
  series("areas.yeo", page.areas.yeo, BRAIN.yeoNetworks);
  for (const [k, s] of Object.entries(page.areas.lines)) if (s.length !== T) out.push(`areas.lines.${k}: ${s.length} seconds, the page has ${T}`);
  for (let i = 1; i < T; i++) if (!(page.time_s[i] > page.time_s[i - 1])) out.push("time_s: seconds out of order");
  const order = page.atlas.order;
  if (order.length !== BRAIN.hcpAreas || new Set(order).size !== BRAIN.hcpAreas || order.some((k) => !Number.isInteger(k) || k < 0 || k >= BRAIN.hcpAreas)) {
    out.push("atlas.order: not each of the 180 areas once");
  }
  if (assetKind(page.frames.key) !== "frames") out.push("frames.key: not a frames key");
  if (assetKind(page.mesh.key) !== "mesh") out.push("mesh.key: not a mesh key");
  if (assetKind(page.atlas.key) !== "atlas") out.push("atlas.key: not an atlas key");
  if (page.frames.key !== `tribe/${page.job_id}/frames.i8`) out.push("frames.key: names another job");
  if (page.frames.bytes !== rawSize("frames", T)) out.push(`frames.bytes: ${page.frames.bytes}, expected ${rawSize("frames", T)}`);
  if (page.mesh.bytes !== rawSize("mesh")) out.push(`mesh.bytes: ${page.mesh.bytes}, expected ${rawSize("mesh")}`);
  if (page.atlas.bytes !== rawSize("atlas")) out.push(`atlas.bytes: ${page.atlas.bytes}, expected ${rawSize("atlas")}`);
  return out.slice(0, 20);
}

/** D21: a brain page is shown on a reel only when the reel's read, its tribe page and the brain
 *  page all name the same job, the same reel and the same seconds. */
export function brainBelongs(sc: string, read: { job_id: string; missing: boolean } | null, tribe: TribePage | null, brain: BrainPage | null): boolean {
  if (!read || read.missing || !tribe || !brain) return false;
  if (tribe.job_id !== read.job_id || brain.job_id !== read.job_id) return false;
  if (brain.shortcode !== tribe.shortcode || (brain.shortcode !== null && brain.shortcode !== sc)) return false;
  return brain.time_s.length === tribe.time_s.length && brain.time_s.every((t, i) => t === tribe.time_s[i]);
}

/** What /reels/[sc]/brain/areas returns: the page's seconds and area means, rows in
 *  atlas.hcp.labels order (show them in atlas.order). */
export type BrainAreasPayload = {
  job_id: string;
  time_s: number[];
  areas: BrainPage["areas"];
};

// ---------------------------------------------------------------- URLs

/** The first 8 hex digits of an asset's sha256: the URL's cache key. */
export const sha8 = (sha256: string): string => sha256.slice(0, 8);

/** "v1" from shared/fsaverage5-inflated-v1.bin or shared/atlas-v1.bin. */
export function assetVersion(key: string): string | null {
  return /-(v\d{1,3})\.bin$/.exec(key)?.[1] ?? null;
}

const enc = encodeURIComponent;

export const brainUrls = {
  /** The shared mesh (gzip, immutable while ?h= names its hash). */
  mesh: (ref: { key: string; sha256: string }) => `/brain/mesh/${assetVersion(ref.key)}?h=${sha8(ref.sha256)}`,
  /** The shared atlas lookups (gzip, immutable while ?h= names its hash). */
  atlas: (ref: { key: string; sha256: string }) => `/brain/atlas/${assetVersion(ref.key)}?h=${sha8(ref.sha256)}`,
  /** This reel's frames (gzip, immutable while ?h= names its hash). */
  frames: (sc: string, ref: { sha256: string }) => `/reels/${enc(sc)}/brain/frames?h=${sha8(ref.sha256)}`,
  /** This reel's per-area series (JSON, BrainAreasPayload) for the Areas tab; ?h= is the frames
   *  hash, so the series and the frames always come from one build. */
  areas: (sc: string, frames: { sha256: string }) => `/reels/${enc(sc)}/brain/areas?h=${sha8(frames.sha256)}`,
  /** This reel's area numbers (CSV download). */
  csv: (sc: string) => `/reels/${enc(sc)}/brain/csv`,
} as const;
