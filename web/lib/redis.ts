// Upstash Redis for the runner's wake list and heartbeat (contracts/runner.json). Used only in
// db mode. Works with the Vercel Marketplace names (KV_REST_API_*) or Upstash's own.

import "server-only";

import { Redis } from "@upstash/redis";

import runner from "@/contracts/runner.json";

export const RUNNER = runner;

let client: Redis | null | undefined;

/** The Upstash client, or null when it is not configured (the site still works; the runner polls). */
export function redis(): Redis | null {
  if (client === undefined) {
    const url = process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL;
    const token = process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;
    client = url && token ? new Redis({ url, token }) : null;
  }
  return client;
}

/** Wake the runner after a queue change. Never throws: the job row is the source of truth. */
export async function wakeRunner(jobId: string): Promise<boolean> {
  const r = redis();
  if (!r) return false;
  try {
    const p = r.pipeline();
    p.lpush(RUNNER.wake_key, jobId);
    p.ltrim(RUNNER.wake_key, 0, RUNNER.wake_max - 1);
    await p.exec();
    return true;
  } catch {
    return false;
  }
}

export type RunnerBeat = { alive: boolean; lastSeen: string | null };

/** Whether the runner's heartbeat key exists, and when it last beat. */
export async function runnerBeat(): Promise<RunnerBeat | null> {
  const r = redis();
  if (!r) return null;
  try {
    const [alive, lastSeen] = await Promise.all([r.exists(RUNNER.heartbeat_key), r.get<string>(RUNNER.last_seen_key)]);
    return { alive: alive === 1, lastSeen: typeof lastSeen === "string" ? lastSeen : null };
  } catch {
    return null;
  }
}
