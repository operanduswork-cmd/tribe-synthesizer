// Signed links to the reel videos in the private Vercel Blob store (D30). The store refuses an
// unsigned GET (403); a presigned GET answers Range requests (206), so the <video> can seek.
//
// One read-only signing token (operation "get", the whole store) is asked for with the store's
// read-write token, which never leaves the server: it is not logged, not sent to the page and not
// part of any link. The signing token is kept in memory for its hour and asked for again once
// fewer than 25 minutes are left (a full 20-minute link plus 5 minutes to spare), so every link
// lives its full 20 minutes and none is signed in the token's last 5. Each link names one blob
// and expires on its own; the page asks /reels/<sc>/video again when one has run out.

import "server-only";

import { issueSignedToken, presignUrl, type IssuedSignedToken } from "@vercel/blob";

/** How long one signed link stays valid. */
export const VIDEO_URL_TTL_MS = 20 * 60_000;
const TOKEN_TTL_MS = 60 * 60_000;
const TOKEN_MARGIN_MS = 5 * 60_000;
const ISSUE_TIMEOUT_MS = 8_000;

/** No BLOB_READ_WRITE_TOKEN in this deployment. */
export class VideoConfigError extends Error {
  constructor() {
    super("reel videos need BLOB_READ_WRITE_TOKEN");
    this.name = "VideoConfigError";
  }
}

type SigningToken = Pick<IssuedSignedToken, "clientSigningToken" | "delegationToken" | "validUntil">;

let cached: SigningToken | null = null;
let pending: Promise<SigningToken> | null = null;

/** The cached signing token, or a new one when fewer than 25 minutes are left on it. */
async function signingToken(now: number): Promise<SigningToken> {
  if (cached && cached.validUntil - now > VIDEO_URL_TTL_MS + TOKEN_MARGIN_MS) return cached;
  if (!pending) {
    const token = process.env.BLOB_READ_WRITE_TOKEN;
    if (!token) throw new VideoConfigError();
    pending = issueSignedToken({
      token,
      pathname: "*",
      operations: ["get"],
      validUntil: now + TOKEN_TTL_MS,
      abortSignal: AbortSignal.timeout(ISSUE_TIMEOUT_MS),
    })
      .then(({ clientSigningToken, delegationToken, validUntil }) => {
        cached = { clientSigningToken, delegationToken, validUntil };
        return cached;
      })
      .finally(() => {
        pending = null;
      });
  }
  return pending;
}

/** A GET link to one private blob, valid for 20 minutes. */
export async function presignReelVideo(pathname: string): Promise<string> {
  const now = Date.now();
  const signing = await signingToken(now);
  const { presignedUrl } = await presignUrl(signing, {
    operation: "get",
    pathname,
    access: "private",
    validUntil: Math.min(now + VIDEO_URL_TTL_MS, signing.validUntil),
  });
  return presignedUrl;
}
