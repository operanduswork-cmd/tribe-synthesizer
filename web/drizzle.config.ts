// Drizzle Kit, for applying the hand-written migrations in db/migrations only.
// Never `drizzle-kit push` and never `generate` over the hand-checked SQL: the next change is a
// hand-written 0001_*.sql plus a journal entry (web/contracts/README.md).

import { defineConfig } from "drizzle-kit";

export default defineConfig({
  dialect: "postgresql",
  schema: "./db/schema.ts",
  out: "./db/migrations",
  dbCredentials: {
    // The owner's URL, set by hand in the shell for a migration; never the web or runner role.
    url: process.env.TRIBE_OWNER_DATABASE_URL ?? "",
  },
  strict: true,
  verbose: true,
});
