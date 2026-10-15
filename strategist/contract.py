"""The hosted contract: page schemas, job kinds and a small JSON Schema checker.

    strategist/hosted_schema/<kind>.schema.json   one per hosted page kind (board, reel, patterns,
                                                  lab, tribe, brain, meta, spend); JSON Schema 2020-12
    web/contracts/job-kinds.json                  the job kinds the site may queue (D26)
    web/contracts/runner.json                     the Upstash key names the site and runner share
    web/contracts/brain-assets.json               the brain view's binary assets (D28; read by
                                                  strategist/brain_assets.py and strategist/db.py)

Every object schema has additionalProperties: false and every page has "v": 1. A string
that is shown on the site carries "x-layer" (counts, facts, shape, brain or ui), so the
web can set data-layer on it and the wall check (D20) can run on real pages:
layer_strings() walks a page with its schema and returns (path, layer, text).

validate() covers the keywords these files use (listed in KEYWORDS) with ECMA-like
regexes (re.ASCII). schema_problems() refuses any other keyword, so the files never rely
on something this checker would silently skip. validate(..., quiet=True) never repeats a
value from the page in its messages (strategist/hosted.py uses it, so a refusal never quotes
private words). Standard library only.
"""

from __future__ import annotations

import functools
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_DIR = HERE / "hosted_schema"
JOB_KINDS_PATH = HERE.parent / "web" / "contracts" / "job-kinds.json"
RUNNER_KEYS_PATH = HERE.parent / "web" / "contracts" / "runner.json"
LAYERS = ("counts", "facts", "shape", "brain", "ui")
KEYWORDS = {"type", "const", "enum", "pattern", "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
            "exclusiveMaximum", "minItems", "maxItems", "uniqueItems", "items", "prefixItems", "properties",
            "required", "additionalProperties", "$ref", "anyOf", "oneOf", "allOf", "not"}
ANNOTATIONS = {"$schema", "$id", "title", "description", "$comment", "$defs", "default", "examples",
               "x-layer", "x-kind", "x-key"}
TYPES = {"null", "boolean", "integer", "number", "string", "array", "object"}
CONSTRAINTS = ("pattern", "enum", "const")


class ContractError(Exception):
    """A page or job's arguments break the contract. The message lists why."""


# ---------------------------------------------------------------- loading

def page_kinds() -> list[str]:
    return sorted(p.name[:-len(".schema.json")] for p in SCHEMA_DIR.glob("*.schema.json"))


@functools.lru_cache(maxsize=None)
def load_schema(kind: str) -> dict:
    path = SCHEMA_DIR / f"{kind}.schema.json"
    if not re.match(r"^[a-z]+$", kind or "") or not path.is_file():
        raise ContractError(f"no hosted schema for page kind {kind!r}")
    return json.loads(path.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def load_job_kinds() -> dict:
    return json.loads(JOB_KINDS_PATH.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def load_runner_keys() -> dict:
    """The wake list, heartbeat and last-seen key names and timings (web/lib/redis.ts reads the same file)."""
    return json.loads(RUNNER_KEYS_PATH.read_text(encoding="utf-8"))


def job_spec(kind: str) -> dict:
    for k in load_job_kinds()["kinds"]:
        if k["kind"] == kind:
            return k
    raise ContractError(f"not an allowed job kind: {kind!r}")


# ---------------------------------------------------------------- the checker

@functools.lru_cache(maxsize=None)
def _rx(pattern: str):
    return re.compile(pattern, re.ASCII)


def resolve(root: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise ContractError(f"only local $ref is supported: {ref!r}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def _is_type(v, t: str) -> bool:
    if t == "null":
        return v is None
    if t == "boolean":
        return isinstance(v, bool)
    if isinstance(v, bool):
        return False
    if t == "integer":
        return isinstance(v, int) or (isinstance(v, float) and math.isfinite(v) and v.is_integer())
    if t == "number":
        return isinstance(v, int) or (isinstance(v, float) and math.isfinite(v))
    return isinstance(v, {"string": str, "array": list, "object": dict}[t])


def _same(a, b) -> bool:
    """JSON equality: true is not 1, 1 equals 1.0."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _name(v) -> str:
    for t in ("null", "boolean", "integer", "number", "string", "array", "object"):
        if _is_type(v, t):
            return t
    return type(v).__name__


ENUM_SHOWN = 12   # a longer enum (the 180 HCP codes) is summarised in messages


def validate(inst, schema, root=None, path: str = "", quiet: bool = False) -> list[str]:
    """Every way inst breaks schema, as 'path: problem' (empty when it fits). quiet=True leaves
    the page's own values out of the messages (they may be private words)."""
    root = schema if root is None else root
    where = path or "/"
    if schema is True:
        return []
    if schema is False:
        return [f"{where}: not allowed here"]
    errs = []
    if "$ref" in schema:
        errs += validate(inst, resolve(root, schema["$ref"]), root, path, quiet)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(inst, t) for t in types):
            return errs + [f"{where}: expected {' or '.join(types)}, got {_name(inst)}"]
    if "const" in schema and not _same(inst, schema["const"]):
        errs.append(f"{where}: must be {schema['const']!r}")
    if "enum" in schema and not any(_same(inst, e) for e in schema["enum"]):
        allowed = (f"the {len(schema['enum'])} allowed values" if len(schema["enum"]) > ENUM_SHOWN
                   else str(schema["enum"]))
        errs.append(f"{where}: not one of {allowed}" if quiet else f"{where}: {inst!r} is not one of {allowed}")
    if isinstance(inst, str):
        if "minLength" in schema and len(inst) < schema["minLength"]:
            errs.append(f"{where}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(inst) > schema["maxLength"]:
            errs.append(f"{where}: {len(inst)} characters, over {schema['maxLength']}")
        if "pattern" in schema and not _rx(schema["pattern"]).search(inst):
            errs.append(f"{where}: does not match {schema['pattern']}" if quiet
                        else f"{where}: {inst[:60]!r} does not match {schema['pattern']}")
    if _is_type(inst, "number"):
        for key, bad in (("minimum", lambda v, m: v < m), ("maximum", lambda v, m: v > m),
                         ("exclusiveMinimum", lambda v, m: v <= m), ("exclusiveMaximum", lambda v, m: v >= m)):
            if key in schema and bad(inst, schema[key]):
                errs.append(f"{where}: {inst} breaks {key} {schema[key]}")
    if isinstance(inst, list):
        if "minItems" in schema and len(inst) < schema["minItems"]:
            errs.append(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(inst) > schema["maxItems"]:
            errs.append(f"{where}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems") and any(_same(a, b) for i, a in enumerate(inst) for b in inst[i + 1:]):
            errs.append(f"{where}: items must be unique")
        prefix = schema.get("prefixItems") or []
        for i, item in enumerate(inst):
            sub = prefix[i] if i < len(prefix) else schema.get("items", True)
            errs += validate(item, sub, root, f"{path}/{i}", quiet)
    if isinstance(inst, dict):
        props = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in inst:
                errs.append(f"{where}: missing {key!r}")
        for key, value in inst.items():
            if key in props:
                errs += validate(value, props[key], root, f"{path}/{key}", quiet)
            elif "additionalProperties" in schema:
                if schema["additionalProperties"] is False:
                    errs.append(f"{where}: unexpected field" if quiet and not re.fullmatch(r"[A-Za-z0-9_]{1,40}", str(key))
                                else f"{where}: unexpected field {key!r}")
                else:
                    errs += validate(value, schema["additionalProperties"], root, f"{path}/{key}", quiet)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            fits = [not validate(inst, s, root, path) for s in schema[key]]
            if key == "anyOf" and not any(fits):
                errs.append(f"{where}: fits none of the anyOf choices"
                            + _closest(inst, schema[key], root, path, quiet))
            if key == "oneOf" and sum(fits) != 1:
                errs.append(f"{where}: fits {sum(fits)} of the oneOf choices, needs exactly 1"
                            + (_closest(inst, schema[key], root, path, quiet) if not any(fits) else ""))
    for sub in schema.get("allOf") or []:
        errs += validate(inst, sub, root, path, quiet)
    if "not" in schema and not validate(inst, schema["not"], root, path):
        errs.append(f"{where}: matches a shape that is not allowed here ({_brief(schema['not'])})")
    return errs


def _closest(inst, choices, root, path, quiet: bool = False) -> str:
    best = min((validate(inst, s, root, path, quiet) for s in choices), key=len)
    return f" (closest: {'; '.join(best[:3])})" if best else ""


def _brief(schema) -> str:
    return f"pattern {schema['pattern']}" if isinstance(schema, dict) and "pattern" in schema else "see the schema"


# ---------------------------------------------------------------- schema checks

def _subschemas(schema):
    """(label, sub-schema) pairs one level down."""
    if not isinstance(schema, dict):
        return
    for k, v in (schema.get("properties") or {}).items():
        yield f"properties.{k}", v
    for k, v in (schema.get("$defs") or {}).items():
        yield f"$defs.{k}", v
    for i, v in enumerate(schema.get("prefixItems") or []):
        yield f"prefixItems.{i}", v
    for key in ("items", "additionalProperties", "not"):
        if isinstance(schema.get(key), dict):
            yield key, schema[key]
    for key in ("anyOf", "oneOf", "allOf"):
        for i, v in enumerate(schema.get(key) or []):
            yield f"{key}.{i}", v


def _string_info(schema, root, seen=()) -> tuple[bool, bool]:
    """(can be a string, string is constrained by pattern/enum/const) through $ref and anyOf/oneOf."""
    if not isinstance(schema, dict):
        return False, False
    can = constrained = False
    t = schema.get("type")
    if t is not None:
        can = "string" in (t if isinstance(t, list) else [t])
    constrained = any(k in schema for k in CONSTRAINTS)
    if "$ref" in schema and schema["$ref"] not in seen:
        c2, k2 = _string_info(resolve(root, schema["$ref"]), root, seen + (schema["$ref"],))
        can, constrained = can or c2, constrained or k2
    for key in ("anyOf", "oneOf"):
        for sub in schema.get(key) or []:
            c2, k2 = _string_info(sub, root, seen)
            if c2:
                can, constrained = True, constrained or k2
    return can, constrained


def schema_problems(schema: dict, display: bool = True) -> list[str]:
    """Problems with a schema itself: unknown keywords, open objects, bad regexes, bad x-layer,
    and (display=True) a shown string with no constraint and no x-layer."""
    root = schema
    out = []

    def walk(s, label, value_slot):
        if isinstance(s, bool):
            return
        if not isinstance(s, dict):
            out.append(f"{label}: a schema must be an object or a boolean")
            return
        unknown = set(s) - KEYWORDS - ANNOTATIONS
        if unknown:
            out.append(f"{label}: keywords this checker does not know: {sorted(unknown)}")
        types = s.get("type")
        for t in types if isinstance(types, list) else [types] if types else []:
            if t not in TYPES:
                out.append(f"{label}: unknown type {t!r}")
        if "properties" in s or s.get("type") == "object":
            if s.get("additionalProperties") is not False:
                out.append(f"{label}: an object schema needs additionalProperties: false")
            missing = set(s.get("required") or []) - set(s.get("properties") or {})
            if missing:
                out.append(f"{label}: required names fields it does not define: {sorted(missing)}")
        if "pattern" in s:
            try:
                _rx(s["pattern"])
            except re.error as e:
                out.append(f"{label}: pattern does not compile ({e})")
        if "x-layer" in s:
            if s["x-layer"] not in LAYERS:
                out.append(f"{label}: x-layer {s['x-layer']!r} is not one of {LAYERS}")
            if not _string_info(s, root)[0]:
                out.append(f"{label}: x-layer on a value that is never a string")
        elif display and value_slot:
            can, constrained = _string_info(s, root)
            if can and not constrained:
                out.append(f"{label}: a shown string needs x-layer (or a pattern/enum/const if it is a key)")
        for sub_label, sub in _subschemas(s):
            slot = sub_label.startswith(("properties.", "prefixItems.")) or sub_label == "items"
            walk(sub, f"{label}.{sub_label}", slot)

    walk(schema, "(root)", False)
    return out


# ---------------------------------------------------------------- pages and jobs

def check_page(kind: str, page: dict, quiet: bool = False) -> dict:
    """Raise ContractError unless page fits strategist/hosted_schema/<kind>.schema.json.
    quiet=True: the message names paths and rules, never the page's values."""
    errs = validate(page, load_schema(kind), quiet=quiet)
    if errs:
        more = f" (and {len(errs) - 8} more)" if len(errs) > 8 else ""
        raise ContractError(f"{kind} page breaks its schema: " + "; ".join(errs[:8]) + more)
    return page


def check_job_args(kind: str, args: dict) -> dict:
    """Raise ContractError unless kind is allowed and args fit its schema in job-kinds.json."""
    spec = job_spec(kind)
    errs = validate(args, spec["args"])
    if errs:
        raise ContractError(f"{kind} arguments: " + "; ".join(errs[:8]))
    return args


def page_key(kind: str, page: dict) -> str:
    """The pages.key a page is stored under (its schema's x-key says the format)."""
    key = {"reel": "shortcode", "lab": "id", "tribe": "job_id", "brain": "job_id", "spend": "month"}.get(kind)
    value = page.get(key) if key else "index"
    if not isinstance(value, str) or not _rx(load_schema(kind)["x-key"]).search(value):
        raise ContractError(f"{kind} page has no valid key ({key or 'index'}: {value!r})")
    return value


def layer_strings(inst, schema, root=None, path: str = "", layer: str | None = None) -> list[tuple[str, str, str]]:
    """Every shown string in inst with its x-layer, as (path, layer, text)."""
    root = schema if root is None else root
    if not isinstance(schema, dict):
        return []
    layer = schema.get("x-layer", layer)
    if "$ref" in schema:
        return layer_strings(inst, resolve(root, schema["$ref"]), root, path, layer)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            pick = next((s for s in schema[key] if not validate(inst, s, root, path)), None)
            return layer_strings(inst, pick, root, path, layer) if pick is not None else []
    if isinstance(inst, str):
        return [(path or "/", layer, inst)] if layer else []
    out = []
    if isinstance(inst, dict):
        for k, v in inst.items():
            out += layer_strings(v, (schema.get("properties") or {}).get(k), root, f"{path}/{k}")
    elif isinstance(inst, list):
        prefix = schema.get("prefixItems") or []
        for i, v in enumerate(inst):
            out += layer_strings(v, prefix[i] if i < len(prefix) else schema.get("items"), root, f"{path}/{i}")
    return out
