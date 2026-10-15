// Tribe dashboard database (Drizzle, Postgres). Mirrors migrations/0000_init.sql,
// 0001_brain_assets.sql and 0002_reel_videos.sql, which are the hand-checked source of truth:
// migrations are files only, never `drizzle-kit push`.
// Text columns with CHECK, never pg enums. The lists below must match
// strategist/hosted_schema/*.schema.json, web/contracts/job-kinds.json and strategist/db.py
// (strategist/test_contract.py checks the SQL side).

import { sql } from "drizzle-orm";
import {
  bigserial,
  boolean,
  check,
  customType,
  index,
  integer,
  jsonb,
  numeric,
  pgTable,
  primaryKey,
  real,
  smallint,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";

export const SCHEMA_VERSION = 3;

export const PAGE_KINDS = ["board", "reel", "patterns", "lab", "tribe", "meta", "spend", "brain"] as const;
export type PageKind = (typeof PAGE_KINDS)[number];

export const JOB_KINDS = [
  "reel.accept",
  "reel.reject",
  "reel.discount",
  "patterns.build",
  "lab.check",
  "sync.push",
  "coach.new_draft",
  "coach.this_but",
  "coach.replace",
  "coach.tag_shapes",
  "reel.add_link",
  "reel.add_handle",
  "tribe.lanes",
] as const;
export type JobKind = (typeof JOB_KINDS)[number];

export const PAID_JOB_KINDS = ["reel.add_link", "reel.add_handle", "tribe.lanes"] as const;

export const JOB_STATUSES = ["queued", "running", "done", "failed", "interrupted", "refused", "cancelled"] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

// The brain view's binary assets (D28): layouts, key format and size caps in contracts/brain-assets.json.
export const BRAIN_ASSET_KINDS = ["frames", "mesh", "atlas"] as const;
export type BrainAssetKind = (typeof BRAIN_ASSET_KINDS)[number];
export const BRAIN_ASSET_KEY_RE =
  "^(tribe/[0-9]{8}-[0-9]{6}-[0-9a-f]{8}/frames\\.i8|shared/(fsaverage5-inflated|atlas)-v[0-9]{1,3}\\.bin)$";

// The reel videos (D30): one private Blob file per swipe reel, named by shortcode and sha256.
export const REEL_VIDEO_SHORTCODE_RE = "^[A-Za-z0-9_-]{5,20}$";
export const REEL_VIDEO_PATHNAME_RE = "^reels/[A-Za-z0-9_-]{5,20}-[0-9a-f]{8}\\.mp4$";
export const REEL_VIDEO_MAX_BYTES = 60000000;

const inList = (values: readonly string[]) => sql.raw(values.map((v) => `'${v}'`).join(", "));

const bytea = customType<{ data: Uint8Array; driverData: Uint8Array }>({
  dataType() {
    return "bytea";
  },
});

export const schemaMeta = pgTable(
  "schema_meta",
  {
    id: smallint("id").primaryKey().default(1),
    version: integer("version").notNull(),
  },
  (t) => [check("schema_meta_id_check", sql`${t.id} = 1`), check("schema_meta_version_check", sql`${t.version} > 0`)],
);

export const pages = pgTable(
  "pages",
  {
    kind: text("kind").$type<PageKind>().notNull(),
    key: text("key").notNull(),
    v: integer("v").notNull(),
    json: jsonb("json").$type<Record<string, unknown>>().notNull(),
    hash: text("hash").notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    primaryKey({ columns: [t.kind, t.key] }),
    check("pages_kind_check", sql`${t.kind} IN (${inList(PAGE_KINDS)})`),
    check("pages_key_check", sql`${t.key} ~ '^[A-Za-z0-9_.-]{1,80}$'`),
    check("pages_v_check", sql`${t.v} > 0`),
    check("pages_json_check", sql`jsonb_typeof(${t.json}) = 'object'`),
    check("pages_hash_check", sql`${t.hash} ~ '^[0-9a-f]{64}$'`),
  ],
);

export const images = pgTable(
  "images",
  {
    key: text("key").primaryKey(),
    mime: text("mime").$type<"image/png">().notNull(),
    bytes: bytea("bytes").notNull(),
    hash: text("hash").notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    check("images_key_check", sql`${t.key} ~ '^[A-Za-z0-9_./-]{1,120}$'`),
    check("images_mime_check", sql`${t.mime} = 'image/png'`),
    check("images_bytes_check", sql`octet_length(${t.bytes}) BETWEEN 8 AND 1048576`),
    check("images_hash_check", sql`${t.hash} ~ '^[0-9a-f]{64}$'`),
  ],
);

export const jobs = pgTable(
  "jobs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    kind: text("kind").$type<JobKind>().notNull(),
    args: jsonb("args").$type<Record<string, unknown>>().notNull().default(sql`'{}'::jsonb`),
    // numeric comes back as a string from the driver: parse it where it is shown.
    estimateUsd: numeric("estimate_usd", { precision: 8, scale: 4 }).notNull().default("0"),
    idemKey: text("idem_key"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    confirmedAt: timestamp("confirmed_at", { withTimezone: true }),
    cancelRequested: boolean("cancel_requested").notNull().default(false),
    status: text("status").$type<JobStatus>().notNull().default("queued"),
    leaseUntil: timestamp("lease_until", { withTimezone: true }),
    startedAt: timestamp("started_at", { withTimezone: true }),
    finishedAt: timestamp("finished_at", { withTimezone: true }),
    result: jsonb("result").$type<Record<string, unknown> | null>(),
    errorCode: text("error_code"),
    refusal: text("refusal"),
  },
  (t) => [
    check("jobs_kind_check", sql`${t.kind} IN (${inList(JOB_KINDS)})`),
    check("jobs_args_check", sql`jsonb_typeof(${t.args}) = 'object' AND octet_length(${t.args}::text) <= 4096`),
    check("jobs_estimate_usd_check", sql`${t.estimateUsd} >= 0 AND ${t.estimateUsd} <= 10`),
    check("jobs_idem_key_check", sql`${t.idemKey} IS NULL OR ${t.idemKey} ~ '^[A-Za-z0-9_.:-]{8,120}$'`),
    check("jobs_status_check", sql`${t.status} IN (${inList(JOB_STATUSES)})`),
    check("jobs_result_check", sql`${t.result} IS NULL OR octet_length(${t.result}::text) <= 65536`),
    check("jobs_error_code_check", sql`${t.errorCode} IS NULL OR ${t.errorCode} ~ '^[a-z][a-z0-9_]{1,40}$'`),
    check("jobs_refusal_check", sql`${t.refusal} IS NULL OR char_length(${t.refusal}) <= 300`),
    check("jobs_running_check", sql`${t.status} <> 'running' OR (${t.startedAt} IS NOT NULL AND ${t.leaseUntil} IS NOT NULL)`),
    check("jobs_finished_check", sql`${t.status} IN ('queued', 'running') OR ${t.finishedAt} IS NOT NULL`),
    uniqueIndex("jobs_idem_live")
      .on(t.idemKey)
      .where(sql`${t.idemKey} IS NOT NULL AND ${t.status} IN ('queued', 'running')`),
    uniqueIndex("jobs_one_running_paid")
      .on(sql`(true)`)
      .where(sql`${t.status} = 'running' AND ${t.kind} IN (${inList(PAID_JOB_KINDS)})`),
    index("jobs_queued").on(t.createdAt, t.id).where(sql`${t.status} = 'queued'`),
    index("jobs_created").on(t.createdAt.desc()),
  ],
);

export const jobEvents = pgTable(
  "job_events",
  {
    id: bigserial("id", { mode: "number" }).primaryKey(),
    jobId: uuid("job_id")
      .notNull()
      .references(() => jobs.id, { onDelete: "cascade" }),
    at: timestamp("at", { withTimezone: true }).notNull().defaultNow(),
    line: text("line").notNull(),
  },
  (t) => [
    check("job_events_line_check", sql`char_length(${t.line}) BETWEEN 1 AND 300`),
    index("job_events_job").on(t.jobId, t.id),
  ],
);

export const settings = pgTable(
  "settings",
  {
    key: text("key").primaryKey(),
    value: jsonb("value").notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [check("settings_key_check", sql`${t.key} ~ '^[a-z][a-z0-9_]{1,40}$'`)],
);

// The brain view's assets: gzip binaries (frames per job, the shared mesh and atlas). tribe_web reads only.
export const brainAssets = pgTable(
  "brain_assets",
  {
    key: text("key").primaryKey(),
    kind: text("kind").$type<BrainAssetKind>().notNull(),
    mime: text("mime").$type<"application/octet-stream">().notNull(),
    encoding: text("encoding").$type<"gzip">().notNull().default("gzip"),
    bytes: bytea("bytes").notNull(),
    rawBytes: integer("raw_bytes").notNull(),
    hash: text("hash").notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    check("brain_assets_key_check", sql`${t.key} ~ ${sql.raw(`'${BRAIN_ASSET_KEY_RE}'`)}`),
    check("brain_assets_kind_check", sql`${t.kind} IN (${inList(BRAIN_ASSET_KINDS)})`),
    check("brain_assets_mime_check", sql`${t.mime} = 'application/octet-stream'`),
    check("brain_assets_encoding_check", sql`${t.encoding} = 'gzip'`),
    check("brain_assets_bytes_check", sql`octet_length(${t.bytes}) BETWEEN 18 AND 2097152`),
    check("brain_assets_raw_bytes_check", sql`${t.rawBytes} BETWEEN 16 AND 4194304`),
    check("brain_assets_hash_check", sql`${t.hash} ~ '^[0-9a-f]{64}$'`),
    check(
      "brain_assets_kind_matches",
      sql`(${t.kind} = 'frames' AND ${t.key} ~ '/frames\\.i8$') OR (${t.kind} = 'mesh' AND ${t.key} ~ '^shared/fsaverage5-inflated-') OR (${t.kind} = 'atlas' AND ${t.key} ~ '^shared/atlas-')`,
    ),
  ],
);

// Where each reel's video sits in the private Blob store (D30). No counts, no brain values.
// tribe_web reads only; strategist/media.py push writes the rows.
export const reelVideos = pgTable(
  "reel_videos",
  {
    shortcode: text("shortcode").primaryKey(),
    pathname: text("pathname").notNull(),
    sha256: text("sha256").notNull(),
    bytes: integer("bytes").notNull(),
    durationS: real("duration_s").notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    check("reel_videos_shortcode_check", sql`${t.shortcode} ~ ${sql.raw(`'${REEL_VIDEO_SHORTCODE_RE}'`)}`),
    check("reel_videos_pathname_check", sql`${t.pathname} ~ ${sql.raw(`'${REEL_VIDEO_PATHNAME_RE}'`)}`),
    check("reel_videos_sha256_check", sql`${t.sha256} ~ '^[0-9a-f]{64}$'`),
    check("reel_videos_bytes_check", sql`${t.bytes} BETWEEN 1 AND ${sql.raw(String(REEL_VIDEO_MAX_BYTES))}`),
    check("reel_videos_duration_s_check", sql`${t.durationS} BETWEEN 1 AND 600`),
    check(
      "reel_videos_pathname_matches",
      sql`${t.pathname} = 'reels/' || ${t.shortcode} || '-' || left(${t.sha256}, 8) || '.mp4'`,
    ),
  ],
);

export type Page = typeof pages.$inferSelect;
export type Job = typeof jobs.$inferSelect;
export type NewJob = Pick<typeof jobs.$inferInsert, "kind" | "args" | "estimateUsd" | "idemKey" | "confirmedAt">;
export type JobEvent = typeof jobEvents.$inferSelect;
export type BrainAsset = typeof brainAssets.$inferSelect;
export type ReelVideo = typeof reelVideos.$inferSelect;
