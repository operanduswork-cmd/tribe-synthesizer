// The job kinds the site may queue, read from contracts/job-kinds.json (shared with the laptop
// runner, D26). Argument schemas are built into zod from the same file, so the site never
// accepts an argument the runner would refuse. Client and server safe (no I/O).

import { z } from "zod";

import contract from "@/contracts/job-kinds.json";
import { copy } from "@/lib/copy";

type FieldSpec = { type: "string"; pattern?: string; minLength?: number; maxLength?: number; enum?: string[] };
type ArgsSpec = { required: string[]; properties: Record<string, FieldSpec> };

export type JobKind = (typeof contract.kinds)[number]["kind"];
export type Billing = "none" | "claude_plan" | "apify" | "modal";

export type JobKindSpec = {
  kind: JobKind;
  stage: number;
  enabled: boolean;
  paid: boolean;
  estimate_usd: number;
  billing: Billing;
  label: string;
  sets_status?: string;
  args: ArgsSpec;
};

export const JOB_KIND_SPECS = contract.kinds as unknown as JobKindSpec[];
export const JOB_LIMITS = contract.limits;
export const JOB_PLATFORM = contract.platform;

export function jobSpec(kind: string): JobKindSpec | undefined {
  return JOB_KIND_SPECS.find((k) => k.kind === kind);
}

export function isJobKind(kind: string): kind is JobKind {
  return jobSpec(kind) !== undefined;
}

function fieldSchema(spec: FieldSpec): z.ZodType<string> {
  if (spec.type !== "string") throw new Error(`job args: only string fields are supported, got ${spec.type}`);
  if (spec.enum) return z.enum(spec.enum as [string, ...string[]]);
  let s = z.string();
  if (spec.minLength !== undefined) s = s.min(spec.minLength);
  if (spec.maxLength !== undefined) s = s.max(spec.maxLength);
  if (spec.pattern) s = s.regex(new RegExp(spec.pattern));
  return s;
}

const argSchemas = new Map<string, z.ZodType<Record<string, string>>>();

/** A strict zod object for one kind's args: unknown fields are refused, as in the contract. */
export function argsSchema(kind: JobKind): z.ZodType<Record<string, string>> {
  let s = argSchemas.get(kind);
  if (!s) {
    const spec = jobSpec(kind);
    if (!spec) throw new Error(`not an allowed job kind: ${kind}`);
    const required = new Set(spec.args.required);
    const shape: Record<string, z.ZodType> = {};
    for (const [name, field] of Object.entries(spec.args.properties)) {
      shape[name] = required.has(name) ? fieldSchema(field) : fieldSchema(field).optional();
    }
    s = z.strictObject(shape) as unknown as z.ZodType<Record<string, string>>;
    argSchemas.set(kind, s);
  }
  return s;
}

/** The result every job server action returns. `message` is UI text from copy/en.json. */
export type ActionResult =
  | { ok: true; message: string; jobId?: string; needsConfirm?: { estimateUsd: number } }
  | { ok: false; code: ActionCode; message: string };

export type ActionCode = "fixtures" | "disabled" | "invalid" | "unknown_kind" | "duplicate" | "not_waiting" | "failed";

/** The short UI label for a kind (copy.jobKinds), e.g. "Check draft" for lab.check. */
export function jobKindLabel(kind: JobKind): string {
  return copy.jobKinds[kind.replace(/\./g, "_") as keyof typeof copy.jobKinds] ?? kind;
}
