// Every read the dashboard makes. TRIBE_DATA_SOURCE=db reads Postgres through Drizzle (the
// cleaned pages the laptop pushed with strategist.sync); anything else reads the SYNTHETIC
// fixtures in web/fixtures. Every page is checked against its hosted schema either way
// (lib/hosted.ts), so a page the contract refuses is never shown.
//
// Cache Components is on (next.config.ts): db reads call connection(), so they run per request.
// Call these from a server component inside <Suspense> (see app/board/page.tsx).

import "server-only";

import { and, desc, eq, inArray } from "drizzle-orm";
import { cookies } from "next/headers";
import { connection } from "next/server";

import { brainAssets, images, jobEvents, jobs, pages, reelVideos, settings, type ReelVideo } from "@/db/schema";
import boardFixture from "@/fixtures/board.json";
import brainFixture from "@/fixtures/brain.json";
import labFixture from "@/fixtures/lab.json";
import metaFixture from "@/fixtures/meta.json";
import reelFixtureB from "@/fixtures/more/reel-DEMO0000002.json";
import reelFixtureC from "@/fixtures/more/reel-DEMO0000003.json";
import patternsFixture from "@/fixtures/patterns.json";
import reelFixture from "@/fixtures/reel.json";
import jobRowsFixture from "@/fixtures/rows/jobs.json";
import spendFixture from "@/fixtures/spend.json";
import tribeFixture from "@/fixtures/tribe.json";
import { assetKind, brainBelongs, brainPageProblems, type StoredBrainAsset } from "@/lib/brain/format";
import { fixtureAsset, withFixtureAssets } from "@/lib/brain/fixture";
import { db } from "@/lib/db";
import { dataSource } from "@/lib/env";
import {
  PageError,
  parsePage,
  type BoardPage,
  type BrainPage,
  type LabPage,
  type MetaPage,
  type PageByKind,
  type PageKind,
  type PatternsPage,
  type ReelPage,
  type SpendPage,
  type TribePage,
} from "@/lib/hosted";
import type { JobKind } from "@/lib/job-kinds";
import { runnerBeat } from "@/lib/redis";

export { dataSource };

/** The fixture pages per kind. Every board row has a reel page: the one with a TRIBE read in
 *  fixtures/reel.json, and two in facts mode (no deep read) in fixtures/more. The brain page
 *  belongs to that read (same job, reel and seconds); its binary assets are made in memory
 *  (lib/brain/fixture.ts). */
const FIXTURES: Record<PageKind, readonly unknown[]> = {
  board: [boardFixture],
  reel: [reelFixture, reelFixtureB, reelFixtureC],
  patterns: [patternsFixture],
  lab: [labFixture],
  tribe: [tribeFixture],
  brain: [brainFixture],
  meta: [metaFixture],
  spend: [spendFixture],
};

/** The key a page is stored under (strategist.contract.page_key). */
function fixtureKey(kind: PageKind, fixture: unknown): string {
  const page = fixture as Record<string, unknown>;
  switch (kind) {
    case "reel":
      return String(page.shortcode);
    case "lab":
      return String(page.id);
    case "tribe":
    case "brain":
      return String(page.job_id);
    case "spend":
      return String(page.month);
    default:
      return "index";
  }
}

// ---------------------------------------------------------------- pages

async function getPage<K extends PageKind>(kind: K, key: string): Promise<PageByKind[K] | null> {
  if (dataSource() === "fixtures") {
    const hit = FIXTURES[kind].find((f) => fixtureKey(kind, f) === key);
    return hit ? parsePage(kind, hit) : null;
  }
  await connection();
  const rows = await db()
    .select({ json: pages.json })
    .from(pages)
    .where(and(eq(pages.kind, kind), eq(pages.key, key)))
    .limit(1);
  return rows.length ? parsePage(kind, rows[0].json) : null;
}

async function listPages<K extends PageKind>(kind: K): Promise<Array<PageByKind[K]>> {
  if (dataSource() === "fixtures") return FIXTURES[kind].map((f) => parsePage(kind, f));
  await connection();
  const rows = await db().select({ json: pages.json }).from(pages).where(eq(pages.kind, kind)).orderBy(pages.key);
  return rows.map((r) => parsePage(kind, r.json));
}

/** The keys stored for one page kind (shortcodes for reels, draft ids for lab). */
export async function listKeys(kind: PageKind): Promise<string[]> {
  if (dataSource() === "fixtures") return FIXTURES[kind].map((f) => fixtureKey(kind, f)).sort();
  await connection();
  const rows = await db().select({ key: pages.key }).from(pages).where(eq(pages.kind, kind)).orderBy(pages.key);
  return rows.map((r) => r.key);
}

export const getBoard = (): Promise<BoardPage | null> => getPage("board", "index");
export const getReel = (sc: string): Promise<ReelPage | null> => getPage("reel", sc);
export const getPatterns = (): Promise<PatternsPage | null> => getPage("patterns", "index");
export const getLab = (id: string): Promise<LabPage | null> => getPage("lab", id);
export const getTribe = (jobId: string): Promise<TribePage | null> => getPage("tribe", jobId);
export const getMeta = (): Promise<MetaPage | null> => getPage("meta", "index");

/** This month's spend (UTC month). Fixtures mode returns the synthetic month whatever the date. */
export async function getSpend(month?: string): Promise<SpendPage | null> {
  if (dataSource() === "fixtures") return parsePage("spend", spendFixture);
  await connection();
  return getPage("spend", month ?? new Date().toISOString().slice(0, 7));
}

export type LabSummary = Pick<LabPage, "id" | "slug" | "kind" | "status" | "title" | "updated">;

/** Every draft, newest first, without the heavy parts. */
export async function listLabs(): Promise<LabSummary[]> {
  const all = await listPages("lab");
  return all
    .map(({ id, slug, kind, status, title, updated }) => ({ id, slug, kind, status, title, updated }))
    .sort((a, b) => (b.updated ?? "").localeCompare(a.updated ?? ""));
}

/** One TRIBE job's brain page (D28), checked against its schema and the cross-field rules in
 *  lib/brain/format.ts (PageError when refused), or null. In fixtures mode its asset blocks name
 *  the synthetic assets getBrainAsset serves. Show it on a reel only through getReelBrain or
 *  brainBelongs (D21). */
export async function getBrain(jobId: string): Promise<BrainPage | null> {
  const page = await getPage("brain", jobId);
  if (!page) return null;
  const problems = brainPageProblems(page);
  if (problems.length) throw new PageError("brain", problems);
  return dataSource() === "fixtures" ? withFixtureAssets(page) : page;
}

export type ReelBrain = { reel: ReelPage; tribe: TribePage; brain: BrainPage };

/** A reel with its read's tribe and brain pages, only when all three name the same job, reel and
 *  seconds (D21: never across reels); else null. */
export async function getReelBrain(sc: string): Promise<ReelBrain | null> {
  const reel = await getReel(sc);
  const read = reel?.tribe ?? null;
  if (!reel || !read || read.missing) return null;
  const [tribe, brain] = await Promise.all([getTribe(read.job_id), getBrain(read.job_id)]);
  return tribe && brain && brainBelongs(sc, read, tribe, brain) ? { reel, tribe, brain } : null;
}

/** One stored brain asset (the gzip bytes as stored, with its kind, decompressed length and
 *  hash), or null. The routes check it against the page before serving (lib/brain/serve.ts). */
export async function getBrainAsset(key: string): Promise<StoredBrainAsset | null> {
  const kind = assetKind(key);
  if (!kind) return null;
  if (dataSource() === "fixtures") {
    return fixtureAsset(
      FIXTURES.brain.map((f) => parsePage("brain", f)),
      key,
    );
  }
  await connection();
  const rows = await db()
    .select({
      key: brainAssets.key,
      kind: brainAssets.kind,
      mime: brainAssets.mime,
      encoding: brainAssets.encoding,
      bytes: brainAssets.bytes,
      rawBytes: brainAssets.rawBytes,
      hash: brainAssets.hash,
    })
    .from(brainAssets)
    .where(eq(brainAssets.key, key))
    .limit(1);
  const r = rows[0];
  if (!r || r.kind !== kind || r.mime !== "application/octet-stream" || r.encoding !== "gzip") return null;
  return { key: r.key, kind, bytes: r.bytes, rawBytes: r.rawBytes, hash: r.hash };
}

export type ReelVideoRow = Pick<ReelVideo, "shortcode" | "pathname" | "sha256" | "bytes" | "durationS">;

/** The test hook for fixtures mode: tests/video.spec.ts sets this cookie to "1" so a fixture
 *  reel gets a synthetic row and the player renders (Playwright serves a synthetic testsrc clip in
 *  place of the video route). db mode never reads it. */
export const VIDEO_TEST_COOKIE = "tribe-test-video";

/** Where a reel's private video sits in the Blob store (D30), or null when it has none. Fixtures
 *  mode has no videos, so this is null there unless the test hook is set. */
export async function getReelVideo(sc: string): Promise<ReelVideoRow | null> {
  if (dataSource() === "fixtures") {
    const jar = await cookies();
    if (jar.get(VIDEO_TEST_COOKIE)?.value !== "1") return null;
    if (!FIXTURES.reel.some((f) => fixtureKey("reel", f) === sc)) return null;
    return { shortcode: sc, pathname: `reels/${sc}-00000000.mp4`, sha256: "0".repeat(64), bytes: 1, durationS: 6 };
  }
  await connection();
  const rows = await db()
    .select({
      shortcode: reelVideos.shortcode,
      pathname: reelVideos.pathname,
      sha256: reelVideos.sha256,
      bytes: reelVideos.bytes,
      durationS: reelVideos.durationS,
    })
    .from(reelVideos)
    .where(eq(reelVideos.shortcode, sc))
    .limit(1);
  return rows[0] ?? null;
}

/** A stored PNG (the TRIBE peak picture), or null. */
export async function getImage(key: string): Promise<Uint8Array | null> {
  if (dataSource() === "fixtures") return null;
  await connection();
  const rows = await db().select({ bytes: images.bytes }).from(images).where(eq(images.key, key)).limit(1);
  return rows.length ? rows[0].bytes : null;
}

// ---------------------------------------------------------------- jobs and the runner

export type JobStatus = "queued" | "running" | "done" | "failed" | "interrupted" | "refused" | "cancelled";

export type JobRow = {
  id: string;
  kind: JobKind;
  args: Record<string, unknown>;
  estimateUsd: number;
  createdAt: string;
  confirmedAt: string | null;
  cancelRequested: boolean;
  status: JobStatus;
  startedAt: string | null;
  finishedAt: string | null;
  errorCode: string | null;
  refusal: string | null;
  events: Array<{ at: string; line: string }>;
};

const iso = (d: Date | string | null): string | null => (d === null ? null : d instanceof Date ? d.toISOString() : d);

/** The newest jobs with their fixed progress lines. */
export async function getJobs(limit = 50): Promise<JobRow[]> {
  if (dataSource() === "fixtures") {
    return jobRowsFixture.jobs.slice(0, limit).map((j) => ({
      id: j.id,
      kind: j.kind as JobKind,
      args: j.args,
      estimateUsd: Number(j.estimate_usd),
      createdAt: j.created_at,
      confirmedAt: j.confirmed_at,
      cancelRequested: j.cancel_requested,
      status: j.status as JobStatus,
      startedAt: j.started_at,
      finishedAt: j.finished_at,
      errorCode: j.error_code,
      refusal: j.refusal,
      events: j.events,
    }));
  }
  await connection();
  const rows = await db().select().from(jobs).orderBy(desc(jobs.createdAt)).limit(limit);
  const ids = rows.map((r) => r.id);
  const events = ids.length
    ? await db()
        .select({ jobId: jobEvents.jobId, at: jobEvents.at, line: jobEvents.line })
        .from(jobEvents)
        .where(inArray(jobEvents.jobId, ids))
        .orderBy(jobEvents.id)
    : [];
  return rows.map((r) => ({
    id: r.id,
    kind: r.kind,
    args: r.args,
    estimateUsd: Number(r.estimateUsd),
    createdAt: iso(r.createdAt)!,
    confirmedAt: iso(r.confirmedAt),
    cancelRequested: r.cancelRequested,
    status: r.status,
    startedAt: iso(r.startedAt),
    finishedAt: iso(r.finishedAt),
    errorCode: r.errorCode,
    refusal: r.refusal,
    events: events.filter((e) => e.jobId === r.id).map((e) => ({ at: iso(e.at)!, line: e.line })),
  }));
}

/** The Pause switch (settings.paused). */
export async function getPaused(): Promise<boolean> {
  if (dataSource() === "fixtures") return jobRowsFixture.settings.paused;
  await connection();
  const rows = await db().select({ value: settings.value }).from(settings).where(eq(settings.key, "paused")).limit(1);
  return rows.length ? rows[0].value === true : false;
}

export type RunnerState = "online" | "offline" | "unknown" | "fixtures";
export type RunnerStatus = { state: RunnerState; lastSeen: string | null; paused: boolean };

/** Runner online / offline (Upstash heartbeat), when it was last seen, and the Pause switch. */
export async function getRunnerStatus(): Promise<RunnerStatus> {
  if (dataSource() === "fixtures") {
    return { state: "fixtures", lastSeen: jobRowsFixture.runner.last_seen, paused: jobRowsFixture.settings.paused };
  }
  await connection();
  const [beat, paused] = await Promise.all([runnerBeat(), getPaused().catch(() => false)]);
  if (!beat) return { state: "unknown", lastSeen: null, paused };
  return { state: beat.alive ? "online" : "offline", lastSeen: beat.lastSeen, paused };
}

// ---------------------------------------------------------------- the command palette

export type PaletteItem = { group: "reels" | "drafts"; label: string; detail: string; href: string };

/** Reels and drafts for the command palette (pages and actions are added by the palette). */
export async function getPaletteItems(): Promise<PaletteItem[]> {
  const [board, labs] = await Promise.all([getBoard(), listLabs()]);
  const reels: PaletteItem[] = (board?.reels ?? []).map((r) => ({
    group: "reels",
    label: r.handle,
    detail: r.sc,
    href: `/reels/${encodeURIComponent(r.sc)}`,
  }));
  const drafts: PaletteItem[] = labs.map((l) => ({
    group: "drafts",
    label: l.title,
    detail: l.id,
    href: `/lab/${encodeURIComponent(l.id)}`,
  }));
  return [...reels, ...drafts];
}
