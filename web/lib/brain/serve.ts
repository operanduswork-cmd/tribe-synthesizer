// What the brain routes share (app/brain/*, app/reels/[sc]/brain/*): the 404, the URL hash
// check, and the asset check before any byte is served. An asset is served only when its key,
// kind, hash and decompressed length are the ones the page names, sha256 of its stored bytes is
// its hash, and its gzip unpacks to a whole asset of its kind (lib/brain/format.ts, the same
// checks as strategist/brain_assets.py check_asset). The unpack check runs once per hash per
// process; the hash check runs on every request.

import "server-only";

import { createHash } from "node:crypto";
import { gunzipSync } from "node:zlib";

import { BRAIN, GZIP_MAGIC, checkAsset, sha8, type BrainAssetKind, type StoredBrainAsset } from "@/lib/brain/format";

export const SC_RE = /^[A-Za-z0-9_-]{5,20}$/;
const H_RE = /^[0-9a-f]{8}$/;

export const notFound = () => new Response(null, { status: 404, headers: { "Cache-Control": "no-store" } });

/** The `?h=` cache key in a request URL, when it is 8 hex digits and names this hash. */
export function hashParamMatches(req: Request, sha256: string): boolean {
  const h = new URL(req.url).searchParams.get("h");
  return h !== null && H_RE.test(h) && h === sha8(sha256);
}

type Ref = { key: string; sha256: string; bytes: number };

const unpacked = new Set<string>();

/** Why a stored asset may not be served for this page reference, or null when it may. */
export function assetProblem(asset: StoredBrainAsset | null, ref: Ref, kind: BrainAssetKind, rows?: number): string | null {
  if (!asset) return "not stored";
  if (asset.key !== ref.key || asset.kind !== kind) return "another key or kind";
  if (asset.hash !== ref.sha256 || asset.rawBytes !== ref.bytes) return "not the asset the page names";
  const b = asset.bytes;
  if (b.byteLength < BRAIN.storedMin || b.byteLength > BRAIN.storedMax) return "stored size out of range";
  if (b[0] !== GZIP_MAGIC[0] || b[1] !== GZIP_MAGIC[1]) return "not gzip";
  if (createHash("sha256").update(b).digest("hex") !== asset.hash) return "hash does not match the bytes";
  const tag = `${kind}:${asset.hash}:${rows ?? ""}`;
  if (!unpacked.has(tag)) {
    let raw: Uint8Array;
    try {
      raw = gunzipSync(b, { maxOutputLength: BRAIN.rawMax });
    } catch {
      return "damaged gzip";
    }
    if (raw.byteLength !== asset.rawBytes) return "unpacks to another length";
    try {
      checkAsset(kind, raw, rows);
    } catch {
      return "not a whole asset of its kind";
    }
    unpacked.add(tag);
  }
  return null;
}

/** The stored gzip bytes as they are: the browser unpacks them (Content-Encoding: gzip). The URL
 *  carries the hash, so the response never changes under it. */
export function assetResponse(asset: StoredBrainAsset): Response {
  return new Response(new Uint8Array(asset.bytes), {
    headers: {
      "Content-Type": "application/octet-stream",
      "Content-Encoding": "gzip",
      "Cache-Control": "private, max-age=31536000, immutable",
      ETag: `"${asset.hash}"`,
    },
  });
}
