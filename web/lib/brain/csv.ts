// The numbers file for one reel's read ("Raw numbers (CSV)", D28): built from the schema-checked
// brain page, never stored. Comment lines first ("# " each: the LICENCE 12E footer, the reel, job,
// run date, precision, masks and atlas versions, what the values are, one reel only, atlas names,
// the HCP clause 5.1 acknowledgement with its terms, the Yeo-7 citation), then one header line and
// long rows: per second, the four lines, the seven Yeo-7 networks, then each HCP area left and
// right in fixed atlas order (Yeo network, then Glasser index), never sorted by a value. Values
// are the page's 4 dp area means; text cells are quoted, and a text cell that starts like a
// spreadsheet formula (= + - @, tab, return) is refused, never written. One reel only (D21).

import { copy, fmt } from "@/lib/copy";
import type { BrainPage } from "@/lib/hosted.gen";

export const AREAS_CSV_HEADER = "second,clock,level,area,hemisphere,network,feeds_line,value";

const LINES = ["seeing", "hearing", "language", "attention"] as const;
const C = copy.reel.download.csv;

export class CsvRefused extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CsvRefused";
  }
}

const FORMULA_START = /^[=+\-@\t\r]/;

function text(cell: string): string {
  if (FORMULA_START.test(cell)) throw new CsvRefused("a text cell starts like a spreadsheet formula");
  if (/[\r\n]/.test(cell)) throw new CsvRefused("a text cell holds a line break");
  return `"${cell.replace(/"/g, '""')}"`;
}

function value(v: number): string {
  if (typeof v !== "number" || !Number.isFinite(v)) throw new CsvRefused("a value is not a finite number");
  const s = v.toFixed(4);
  return s === "-0.0000" ? "0.0000" : s;
}

function second(t: number): string {
  if (!Number.isFinite(t) || t < 0) throw new CsvRefused("a second is not a number of seconds");
  return Number.isInteger(t) ? String(t) : String(Math.round(t * 1000) / 1000);
}

/** "m:ss", floored (components/reel/time.ts clock). */
function clock(t: number): string {
  const s = Math.max(0, Math.floor(t + 1e-6));
  const r = s % 60;
  return `${Math.floor(s / 60)}:${r < 10 ? "0" : ""}${r}`;
}

/** The comment lines, each "# " plus one sentence; a comma in one may never open a formula cell. */
export function areasCsvComments(page: BrainPage, sc: string, runDate: string): string[] {
  const lines = [
    C.footer,
    fmt(C.reel, { sc }),
    fmt(C.job, { job: page.job_id }),
    fmt(C.runDate, { date: runDate }),
    page.precision ? fmt(C.precision, { precision: page.precision }) : C.precisionNone,
    fmt(C.masks, { masks: page.masks_version }),
    fmt(C.atlas, { atlas: page.atlas.version }),
    C.units,
    C.oneReel,
    C.atlasNames,
    copy.reel.brain.credit.hcp,
    C.derived,
    C.yeo,
  ];
  for (const l of lines) {
    if (/[\r\n]/.test(l) || /,\s*[=+\-@]/.test(l) || /\{\w+\}/.test(l)) throw new CsvRefused("a comment line would break the file");
  }
  return lines.map((l) => `# ${l}`);
}

/** The whole numbers file for reel `sc` (LF line ends). Throws CsvRefused rather than write a
 *  doubtful cell. */
export function areasCsv(page: BrainPage, sc: string, runDate: string): string {
  const { hcp, yeo, order } = page.atlas;
  const out = [...areasCsvComments(page, sc, runDate), AREAS_CSV_HEADER];
  const network = (n: number) => text(yeo.labels[n - 1]);
  const both = text("both");
  const none = text("");
  page.time_s.forEach((t, i) => {
    const head = `${second(t)},${text(clock(t))}`;
    for (const line of LINES) out.push(`${head},${text("line")},${none},${both},${none},${text(line)},${value(page.areas.lines[line][i])}`);
    yeo.labels.forEach((_, n) => out.push(`${head},${text("network")},${none},${both},${network(n + 1)},${none},${value(page.areas.yeo[n][i])}`));
    for (const k of order) {
      const area = text(hcp.labels[k]);
      const net = network(hcp.network[k]);
      const feeds = text(hcp.line[k] ?? "");
      out.push(`${head},${text("area")},${area},${text("left")},${net},${feeds},${value(page.areas.hcp_left[k][i])}`);
      out.push(`${head},${text("area")},${area},${text("right")},${net},${feeds},${value(page.areas.hcp_right[k][i])}`);
    }
  });
  return out.join("\n") + "\n";
}

/** tribe-<sc>-<job_id>-areas.csv */
export const areasCsvFilename = (sc: string, jobId: string): string => `tribe-${sc}-${jobId}-areas.csv`;
