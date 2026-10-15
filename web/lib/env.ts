// Where the dashboard reads from. Fixtures mode (the default) uses the synthetic pages in
// web/fixtures and never touches a database or Upstash; db mode reads Postgres through Drizzle.

export type DataSource = "fixtures" | "db";

export function dataSource(): DataSource {
  return process.env.TRIBE_DATA_SOURCE === "db" ? "db" : "fixtures";
}
