// The site's Postgres connection (Drizzle over node-postgres), used only in db mode. It connects
// as the tribe_web role (web/db/roles.sql): read everything, insert jobs, set confirmed_at and
// cancel_requested, and flip Pause through set_paused(). The URL is never logged.

import "server-only";

import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import { Pool } from "pg";

import * as schema from "@/db/schema";

export type Db = NodePgDatabase<typeof schema>;

const globalForDb = globalThis as unknown as { tribePool?: Pool; tribeDb?: Db };

// Only TRIBE_WEB_DATABASE_URL. Never fall back to DATABASE_URL: the Neon integration fills that
// with the owner role, which would skip every tribe_web limit (D26).
function databaseUrl(): string {
  const url = process.env.TRIBE_WEB_DATABASE_URL;
  if (!url) throw new Error("db mode needs TRIBE_WEB_DATABASE_URL");
  return url;
}

/** The shared Drizzle client. Throws (without the URL) when no database is configured. */
export function db(): Db {
  if (!globalForDb.tribeDb) {
    const pool = new Pool({ connectionString: databaseUrl(), max: 3, idleTimeoutMillis: 10_000 });
    pool.on("error", () => {
      // A dropped idle connection: the pool replaces it. Nothing to log (the error can carry the URL).
    });
    globalForDb.tribePool = pool;
    globalForDb.tribeDb = drizzle(pool, { schema });
  }
  return globalForDb.tribeDb;
}
