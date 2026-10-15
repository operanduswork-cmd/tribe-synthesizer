// The hosted page check, ported line for line from strategist/contract.py `validate`, so the
// laptop and the site refuse the same pages. Only the JSON Schema keywords the hosted schemas
// use are supported. lib/hosted.ts wraps this in zod.

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Schema = boolean | { [key: string]: unknown };
type Node = { [key: string]: unknown };

const rxCache = new Map<string, RegExp>();
function rx(pattern: string): RegExp {
  let r = rxCache.get(pattern);
  if (!r) {
    r = new RegExp(pattern);
    rxCache.set(pattern, r);
  }
  return r;
}

export function resolve(root: Schema, ref: string): Schema {
  if (!ref.startsWith("#/")) throw new Error(`only local $ref is supported: ${ref}`);
  let node: unknown = root;
  for (const part of ref.slice(2).split("/")) {
    node = (node as Node)[part.replace(/~1/g, "/").replace(/~0/g, "~")];
  }
  return node as Schema;
}

const isObject = (v: unknown): v is Node => typeof v === "object" && v !== null && !Array.isArray(v);

function isType(v: unknown, t: string): boolean {
  switch (t) {
    case "null":
      return v === null;
    case "boolean":
      return typeof v === "boolean";
    case "integer":
      return typeof v === "number" && Number.isFinite(v) && Number.isInteger(v);
    case "number":
      return typeof v === "number" && Number.isFinite(v);
    case "string":
      return typeof v === "string";
    case "array":
      return Array.isArray(v);
    case "object":
      return isObject(v);
    default:
      return false;
  }
}

function same(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => same(x, b[i]));
  if (isObject(a) && isObject(b)) {
    const ka = Object.keys(a).sort();
    const kb = Object.keys(b).sort();
    return same(ka, kb) && ka.every((k) => same(a[k], b[k]));
  }
  return a === b;
}

function typeName(v: unknown): string {
  for (const t of ["null", "boolean", "integer", "number", "string", "array", "object"]) if (isType(v, t)) return t;
  return typeof v;
}

// Code points, as Python's len() counts them.
const length = (s: string) => [...s].length;

/** Every way inst breaks schema, as "path: problem" (empty when it fits). */
export function validate(inst: unknown, schema: Schema, root: Schema = schema, path = ""): string[] {
  const where = path || "/";
  if (schema === true) return [];
  if (schema === false) return [`${where}: not allowed here`];
  const s = schema as Node;
  const errs: string[] = [];
  if (typeof s.$ref === "string") errs.push(...validate(inst, resolve(root, s.$ref), root, path));
  if (s.type !== undefined) {
    const types = (Array.isArray(s.type) ? s.type : [s.type]) as string[];
    if (!types.some((t) => isType(inst, t))) return [...errs, `${where}: expected ${types.join(" or ")}, got ${typeName(inst)}`];
  }
  if ("const" in s && !same(inst, s.const)) errs.push(`${where}: must be ${JSON.stringify(s.const)}`);
  if (Array.isArray(s.enum) && !s.enum.some((e) => same(inst, e))) errs.push(`${where}: not one of the allowed values`);
  if (typeof inst === "string") {
    if (typeof s.minLength === "number" && length(inst) < s.minLength) errs.push(`${where}: shorter than ${s.minLength}`);
    if (typeof s.maxLength === "number" && length(inst) > s.maxLength) errs.push(`${where}: over ${s.maxLength} characters`);
    if (typeof s.pattern === "string" && !rx(s.pattern).test(inst)) errs.push(`${where}: does not match ${s.pattern}`);
  }
  if (isType(inst, "number")) {
    const n = inst as number;
    if (typeof s.minimum === "number" && n < s.minimum) errs.push(`${where}: breaks minimum ${s.minimum}`);
    if (typeof s.maximum === "number" && n > s.maximum) errs.push(`${where}: breaks maximum ${s.maximum}`);
    if (typeof s.exclusiveMinimum === "number" && n <= s.exclusiveMinimum) errs.push(`${where}: breaks exclusiveMinimum`);
    if (typeof s.exclusiveMaximum === "number" && n >= s.exclusiveMaximum) errs.push(`${where}: breaks exclusiveMaximum`);
  }
  if (Array.isArray(inst)) {
    if (typeof s.minItems === "number" && inst.length < s.minItems) errs.push(`${where}: fewer than ${s.minItems} items`);
    if (typeof s.maxItems === "number" && inst.length > s.maxItems) errs.push(`${where}: more than ${s.maxItems} items`);
    if (s.uniqueItems === true && inst.some((a, i) => inst.slice(i + 1).some((b) => same(a, b)))) {
      errs.push(`${where}: items must be unique`);
    }
    const prefix = (s.prefixItems as Schema[] | undefined) ?? [];
    inst.forEach((item, i) => {
      const sub = i < prefix.length ? prefix[i] : ((s.items as Schema | undefined) ?? true);
      errs.push(...validate(item, sub, root, `${path}/${i}`));
    });
  }
  if (isObject(inst)) {
    const props = (s.properties as Record<string, Schema> | undefined) ?? {};
    for (const key of (s.required as string[] | undefined) ?? []) if (!(key in inst)) errs.push(`${where}: missing ${key}`);
    for (const [key, value] of Object.entries(inst)) {
      if (key in props) errs.push(...validate(value, props[key], root, `${path}/${key}`));
      else if ("additionalProperties" in s) {
        if (s.additionalProperties === false) errs.push(`${where}: unexpected field ${key}`);
        else errs.push(...validate(value, s.additionalProperties as Schema, root, `${path}/${key}`));
      }
    }
  }
  for (const key of ["anyOf", "oneOf"] as const) {
    const choices = s[key] as Schema[] | undefined;
    if (!choices) continue;
    const fits = choices.filter((c) => validate(inst, c, root, path).length === 0).length;
    if (key === "anyOf" && fits === 0) errs.push(`${where}: fits none of the anyOf choices`);
    if (key === "oneOf" && fits !== 1) errs.push(`${where}: fits ${fits} of the oneOf choices, needs exactly 1`);
  }
  for (const sub of (s.allOf as Schema[] | undefined) ?? []) errs.push(...validate(inst, sub, root, path));
  if (s.not !== undefined && validate(inst, s.not as Schema, root, path).length === 0) {
    errs.push(`${where}: matches a shape that is not allowed here`);
  }
  return errs;
}

export type Layer = "counts" | "facts" | "shape" | "brain" | "ui";

/** Every shown string in inst with its x-layer, as [path, layer, text] (contract.layer_strings). */
export function layerStrings(
  inst: unknown,
  schema: Schema | undefined,
  root: Schema = schema ?? true,
  path = "",
  layer?: Layer,
): Array<[string, Layer, string]> {
  if (!isObject(schema)) return [];
  const here = (schema["x-layer"] as Layer | undefined) ?? layer;
  if (typeof schema.$ref === "string") return layerStrings(inst, resolve(root, schema.$ref), root, path, here);
  for (const key of ["anyOf", "oneOf"] as const) {
    const choices = schema[key] as Schema[] | undefined;
    if (choices) {
      const pick = choices.find((c) => validate(inst, c, root, path).length === 0);
      return pick === undefined ? [] : layerStrings(inst, pick, root, path, here);
    }
  }
  if (typeof inst === "string") return here ? [[path || "/", here, inst]] : [];
  const out: Array<[string, Layer, string]> = [];
  if (isObject(inst)) {
    const props = (schema.properties as Record<string, Schema> | undefined) ?? {};
    for (const [k, v] of Object.entries(inst)) out.push(...layerStrings(v, props[k], root, `${path}/${k}`));
  } else if (Array.isArray(inst)) {
    const prefix = (schema.prefixItems as Schema[] | undefined) ?? [];
    inst.forEach((v, i) =>
      out.push(...layerStrings(v, i < prefix.length ? prefix[i] : (schema.items as Schema | undefined), root, `${path}/${i}`)),
    );
  }
  return out;
}
