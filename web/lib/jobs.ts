"use server";

// The run buttons' server actions (D26). The site only queues: it validates the kind and args
// against contracts/job-kinds.json, inserts a jobs row as tribe_web, and wakes the laptop runner
// through Upstash. The runner re-checks everything (limits, caps, expiry, re-estimate) before it
// starts. In fixtures mode every action is a no-op that says so.
//
// A free job is inserted confirmed. A paid job is inserted unconfirmed with its estimate; the
// confirm dialog's click calls confirmJob (that click is his go for that one job at that
// estimate), and "Not now" calls cancelJob.

import { createHash } from "node:crypto";

import { and, eq, inArray, isNull, sql } from "drizzle-orm";
import { refresh } from "next/cache";

import { jobs } from "@/db/schema";
import { copy, fmt } from "@/lib/copy";
import { db } from "@/lib/db";
import { dataSource } from "@/lib/env";
import { argsSchema, jobSpec, type ActionResult } from "@/lib/job-kinds";
import { wakeRunner } from "@/lib/redis";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const fixtures = (): ActionResult => ({ ok: false, code: "fixtures", message: copy.jobs.fixturesMode });
const failed = (): ActionResult => ({ ok: false, code: "failed", message: copy.jobs.failed });

/** Same kind and args while one is still live = the same job (jobs_idem_live refuses a second). */
function idemKey(kind: string, args: Record<string, string>): string {
  const canonical = JSON.stringify(Object.keys(args).sort().map((k) => [k, args[k]]));
  return `${kind}:${createHash("sha256").update(canonical).digest("hex").slice(0, 40)}`;
}

const isUniqueViolation = (e: unknown): boolean =>
  typeof e === "object" && e !== null && ((e as { code?: string }).code === "23505" || isUniqueViolation((e as { cause?: unknown }).cause));

/** Queue one job. Paid kinds come back with needsConfirm: open ConfirmJobDialog with that estimate. */
export async function enqueueJob(kind: string, args: unknown): Promise<ActionResult> {
  const spec = jobSpec(kind);
  if (!spec) return { ok: false, code: "unknown_kind", message: copy.jobs.unknownKind };
  if (!spec.enabled) return { ok: false, code: "disabled", message: fmt(copy.jobs.disabled, { stage: spec.stage }) };
  const parsed = argsSchema(spec.kind).safeParse(args ?? {});
  if (!parsed.success) {
    const field = parsed.error.issues.map((i) => i.path.join(".") || "args").join(", ");
    return { ok: false, code: "invalid", message: fmt(copy.jobs.invalid, { problem: field }) };
  }
  if (dataSource() === "fixtures") return fixtures();

  let id: string;
  try {
    // Raw SQL on purpose: tribe_web may insert only these five columns, and Drizzle's insert
    // names every column (with DEFAULT), which the column grant refuses.
    const res = await db().execute<{ id: string }>(sql`
      INSERT INTO jobs (kind, args, estimate_usd, idem_key, confirmed_at)
      VALUES (${spec.kind}, ${JSON.stringify(parsed.data)}::jsonb, ${spec.estimate_usd},
              ${idemKey(spec.kind, parsed.data)}, ${spec.paid ? null : sql`now()`})
      RETURNING id`);
    id = res.rows[0].id;
  } catch (e) {
    if (isUniqueViolation(e)) return { ok: false, code: "duplicate", message: copy.jobs.duplicate };
    return failed();
  }
  if (spec.paid) {
    refresh();
    return { ok: true, jobId: id, message: copy.jobs.confirm.title, needsConfirm: { estimateUsd: spec.estimate_usd } };
  }
  const woke = await wakeRunner(id);
  refresh();
  return { ok: true, jobId: id, message: woke ? copy.jobs.queued : copy.jobs.queuedOffline };
}

/** His confirm click on a paid job: sets confirmed_at on a queued, unconfirmed, uncancelled row. */
export async function confirmJob(id: string): Promise<ActionResult> {
  if (!UUID_RE.test(id)) return { ok: false, code: "invalid", message: fmt(copy.jobs.invalid, { problem: "id" }) };
  if (dataSource() === "fixtures") return fixtures();
  try {
    const rows = await db()
      .update(jobs)
      // The database stamps the time (roles.sql jobs_web_guard sets it to now() for tribe_web anyway).
      .set({ confirmedAt: sql`now()` })
      .where(and(eq(jobs.id, id), eq(jobs.status, "queued"), isNull(jobs.confirmedAt), eq(jobs.cancelRequested, false)))
      .returning({ id: jobs.id });
    if (!rows.length) return { ok: false, code: "not_waiting", message: copy.jobs.notWaiting };
  } catch {
    return failed();
  }
  await wakeRunner(id);
  refresh();
  return { ok: true, jobId: id, message: copy.jobs.confirmed };
}

/** Ask the runner to cancel a queued or running job (it stops at the next safe point). */
export async function cancelJob(id: string): Promise<ActionResult> {
  if (!UUID_RE.test(id)) return { ok: false, code: "invalid", message: fmt(copy.jobs.invalid, { problem: "id" }) };
  if (dataSource() === "fixtures") return fixtures();
  try {
    const rows = await db()
      .update(jobs)
      .set({ cancelRequested: true })
      .where(and(eq(jobs.id, id), inArray(jobs.status, ["queued", "running"])))
      .returning({ id: jobs.id });
    if (!rows.length) return { ok: false, code: "not_waiting", message: copy.jobs.notWaiting };
  } catch {
    return failed();
  }
  await wakeRunner(id);
  refresh();
  return { ok: true, jobId: id, message: copy.jobs.cancelRequested };
}

/** The Pause switch, through set_paused() (the only way tribe_web can change settings). */
export async function setPaused(paused: boolean): Promise<ActionResult> {
  if (typeof paused !== "boolean") return { ok: false, code: "invalid", message: fmt(copy.jobs.invalid, { problem: "paused" }) };
  if (dataSource() === "fixtures") return fixtures();
  try {
    await db().execute(sql`SELECT set_paused(${paused})`);
  } catch {
    return failed();
  }
  refresh();
  return { ok: true, message: paused ? copy.jobs.paused : copy.jobs.resumed };
}
