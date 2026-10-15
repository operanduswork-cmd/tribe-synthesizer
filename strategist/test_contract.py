"""Tests for the hosted contract. Run: python strategist/test_contract.py

Covers strategist/hosted_schema/*.schema.json, web/fixtures/*.json (synthetic only),
web/contracts/job-kinds.json, the SQL and Drizzle files in web/db/, strategist/db.py
(against a fake connection) and store.locked(). No database, no Apify, no Modal, no
network: the one connect() test dials a closed local port. The real .env is never read
(load_env is pointed at a temp file), and swipe/, drafts/ and VAULT are never written
(the lock tests use a temp swipe folder)."""

import contextlib
import copy
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
# Run as a script, this folder is sys.path[0]; drop it so "render" can only mean dashboard/render.py.
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
sys.path.insert(0, str(PROJECT_ROOT))
from strategist import brain_assets as B, contract as C, db, lab, reel as sreel, store  # noqa: E402

R = store.rules()
WEB = PROJECT_ROOT / "web"
FIXTURES = WEB / "fixtures"
MIGRATION = WEB / "db" / "migrations" / "0000_init.sql"
MIGRATION_1 = WEB / "db" / "migrations" / "0001_brain_assets.sql"
MIGRATION_2 = WEB / "db" / "migrations" / "0002_reel_videos.sql"
JOURNAL = WEB / "db" / "migrations" / "meta" / "_journal.json"
ROLES = WEB / "db" / "roles.sql"
GRANTS_1 = WEB / "db" / "grants-0001.sql"
GRANTS_2 = WEB / "db" / "grants-0002.sql"
SCHEMA_TS = WEB / "db" / "schema.ts"
BRAIN_CONTRACT = WEB / "contracts" / "brain-assets.json"
KINDS = ("board", "reel", "patterns", "lab", "tribe", "brain", "meta", "spend")
JOB_KINDS = {"reel.accept": (1, False, 0), "reel.reject": (1, False, 0), "reel.discount": (1, False, 0),
             "patterns.build": (1, False, 0), "lab.check": (1, False, 0), "sync.push": (1, False, 0),
             "coach.new_draft": (2, False, 0), "coach.this_but": (2, False, 0), "coach.replace": (2, False, 0),
             "coach.tag_shapes": (2, False, 0), "reel.add_link": (1, True, 0.006),
             "reel.add_handle": (1, True, 0.1), "tribe.lanes": (3, True, 0.10)}
REAL_NAMES = ("demo_creator_a", "demo_creator_b", "demo_creator_c")
UUID = "0b9f3c1e-2a4d-4c6b-8e7f-1a2b3c4d5e6f"


def fixture(kind: str) -> dict:
    return json.loads((FIXTURES / f"{kind}.json").read_text(encoding="utf-8"))


def more_fixtures():
    """(kind, file name, page, raw text) for web/fixtures/more/<kind>-<key>.json: the extra pages
    (a reel page per board row) the site loads beside the one fixture per kind."""
    for p in sorted((FIXTURES / "more").glob("*.json")):
        kind = p.stem.split("-", 1)[0]
        raw = p.read_text(encoding="utf-8")
        yield kind, p.name, json.loads(raw), raw


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def sql_list(sql: str, anchor: str) -> list[str]:
    """The quoted values of the first IN (...) list after anchor."""
    at = sql.index(anchor)
    m = re.search(r"IN \(([^)]*)\)", sql[at:], re.S)
    return re.findall(r"'([^']+)'", m.group(1))


def ts_list(ts: str, name: str) -> list[str]:
    m = re.search(rf"export const {name} = \[(.*?)\] as const", ts, re.S)
    return re.findall(r'"([^"]+)"', m.group(1))


def statements(sql: str) -> list[str]:
    """The SQL statements of a file, comments dropped and whitespace squeezed (no $$ bodies)."""
    live = "\n".join(ln for ln in sql.splitlines() if not ln.strip().startswith("--"))
    live = re.sub(r"\$\$.*?\$\$", "$$", live, flags=re.S)
    return [" ".join(st.split()) for st in live.split(";") if st.strip()]


def web_writes(sql: str) -> list[str]:
    """(tables) of every GRANT to tribe_web that is more than SELECT/USAGE/EXECUTE."""
    out = []
    for st in statements(sql):
        m = re.match(r"GRANT (.+?) ON (?:TABLE )?(.+?) TO (.+)$", st)
        if not m or "tribe_web" not in m.group(3) or m.group(2).startswith(("SCHEMA", "FUNCTION", "SEQUENCE")):
            continue
        privs = re.sub(r"\([^)]*\)", "", m.group(1))
        if re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|ALL|REFERENCES|TRIGGER)\b", privs):
            out.append(m.group(2))
    return out


# ---------------------------------------------------------------- the checker itself

class ValidatorTests(unittest.TestCase):
    """The minimal validator agrees with JSON Schema on the keywords the files use."""

    def test_keywords(self):
        s = {"type": "object", "additionalProperties": False, "required": ["a"],
             "properties": {"a": {"type": "integer", "minimum": 1}, "b": {"type": ["string", "null"], "maxLength": 3},
                            "c": {"type": "array", "prefixItems": [{"const": "x"}], "items": False}}}
        self.assertEqual(C.validate({"a": 1, "b": None, "c": ["x"]}, s), [])
        for bad in ({"a": True}, {"a": 0}, {}, {"a": 1, "z": 1}, {"a": 1, "b": "long"}, {"a": 1, "c": ["x", "y"]},
                    {"a": 1, "c": ["y"]}, {"a": 1.5}, {"a": float("nan")}):
            self.assertTrue(C.validate(bad, s), bad)
        self.assertEqual(C.validate(2.0, {"type": "integer"}), [])
        self.assertTrue(C.validate(1, {"const": True}))
        self.assertTrue(C.validate("a", {"oneOf": [{"type": "string"}, {"pattern": "a"}]}))   # fits both
        self.assertTrue(C.validate([1, 1], {"type": "array", "uniqueItems": True}))
        self.assertTrue(C.validate("x1", {"not": {"pattern": r"\d"}}))
        # ECMA-like: \d is ASCII only
        self.assertTrue(C.validate("١٢", {"type": "string", "pattern": r"^\d+$"}))

    def test_jsonschema_agrees_when_installed(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is not installed; the built-in checker is used")
        for kind in KINDS:
            jsonschema.Draft202012Validator(C.load_schema(kind)).validate(fixture(kind))

    def test_schema_problems_catches(self):
        self.assertTrue(C.schema_problems({"type": "object", "properties": {}}))   # open object
        self.assertTrue(C.schema_problems({"type": "string", "format": "date"}))   # unknown keyword
        self.assertTrue(C.schema_problems({"type": "object", "additionalProperties": False,
                                           "properties": {"t": {"type": "string"}}}))   # shown string, no layer
        self.assertTrue(C.schema_problems({"type": "object", "additionalProperties": False,
                                           "properties": {"t": {"type": "string", "x-layer": "views"}}}))
        self.assertTrue(C.schema_problems({"type": "integer", "x-layer": "ui"}))
        self.assertTrue(C.schema_problems({"type": "string", "pattern": "("}))


# ---------------------------------------------------------------- page schemas

class SchemaTests(unittest.TestCase):

    def test_one_schema_per_kind(self):
        self.assertEqual(sorted(C.page_kinds()), sorted(KINDS))
        self.assertEqual(sorted(db.PAGE_KINDS), sorted(KINDS))

    def test_each_schema_is_closed_versioned_and_layered(self):
        defs = None
        for kind in KINDS:
            s = C.load_schema(kind)
            self.assertEqual(s["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertEqual(s["x-kind"], kind)
            self.assertIs(s["additionalProperties"], False)
            self.assertIn("v", s["required"])
            self.assertEqual(s["properties"]["v"], {"type": "integer", "const": 1})
            re.compile(s["x-key"])
            self.assertEqual(C.schema_problems(s), [], kind)
            defs = defs or s["$defs"]
            self.assertEqual(s["$defs"], defs, f"{kind}: shared $defs drifted from the other schemas")

    def test_no_private_fields_in_schemas(self):
        for kind in KINDS:
            names = set()

            def walk(node):
                if isinstance(node, dict):
                    names.update((node.get("properties") or {}).keys())
                    for v in node.values():
                        walk(v)
                elif isinstance(node, list):
                    for v in node:
                        walk(v)
            walk(C.load_schema(kind))
            for banned in ("words", "word_hits", "segments", "transcript", "caption", "stills", "still", "src",
                           "local_path", "path", "raw", "quote", "events", "source", "per_second"):
                self.assertNotIn(banned, names, f"{kind} schema has a field {banned!r}")
        brain = C.load_schema("brain")["properties"]
        self.assertEqual(set(brain), {"v", "job_id", "shortcode", "framing", "masks_version", "precision", "time_s",
                                      "scale", "frames", "mesh", "atlas", "areas"})
        self.assertEqual(set(brain["scale"]["properties"]),   # one scale per reel: no per-row field
                         {"mode", "label", "vmax", "percentile", "pooled", "levels", "colormap", "grey_below",
                          "full_at", "clipped_share"})
        self.assertEqual(brain["scale"]["properties"]["label"]["const"], "one colour scale for this whole reel")
        self.assertEqual(set(brain["areas"]["properties"]), {"hcp_left", "hcp_right", "yeo", "lines"})
        self.assertEqual(set(brain["atlas"]["properties"]), {"key", "sha256", "bytes", "version", "hcp", "yeo", "order"})
        for name in ("frames", "mesh"):
            self.assertEqual(set(brain[name]["properties"]), {"key", "sha256", "bytes"})
        for name in ("hcp_left", "hcp_right", "yeo"):
            self.assertEqual(brain["areas"]["properties"][name]["items"]["maxItems"], 90)
        labels = brain["atlas"]["properties"]["hcp"]["properties"]["labels"]
        self.assertEqual(labels["items"]["x-layer"], "brain")
        self.assertEqual((labels["minItems"], labels["maxItems"], labels["uniqueItems"]), (180, 180, True))
        for code in labels["items"]["enum"] + brain["atlas"]["properties"]["yeo"]["properties"]["labels"]["items"]["enum"]:
            self.assertEqual(R.find_banned(code), [], code)       # HCP codes and atlas names only, no glosses
            R.check_authored([("atlas label", code)])
        self.assertNotIn("Amygdala", labels["items"]["enum"])
        tribe = C.load_schema("tribe")["properties"]
        self.assertEqual(set(tribe["peaks"]["items"]["properties"]), {"t", "driving_lines", "edge"})
        self.assertEqual(set(tribe["flat_stretches"]["items"]["properties"]), {"start", "end", "driving_lines", "edge"})
        self.assertEqual(set(tribe["lines"]["properties"]), {"seeing", "hearing", "language", "attention", "combined"})

    def test_board_sorts_never_name_a_tribe_field(self):
        s = C.load_schema("board")
        keys = s["properties"]["sorts"]["items"]["properties"]["key"]["enum"]
        for k in keys:
            self.assertIn(R.check_sort_key(k).lstrip("-"), {"x", "plays", "posted", "duration", "handle"})
        self.assertEqual(set(s["properties"]["reels"]["items"]["properties"]["sort"]["properties"]),
                         {"x", "plays", "posted", "duration", "handle"})


# ---------------------------------------------------------------- fixtures

class FixtureTests(unittest.TestCase):

    def test_every_fixture_fits_its_schema(self):
        self.assertEqual(sorted(p.stem for p in FIXTURES.glob("*.json")), sorted(KINDS))
        for kind in KINDS:
            page = fixture(kind)
            self.assertEqual(C.validate(page, C.load_schema(kind)), [], kind)
            C.check_page(kind, page)
            C.page_key(kind, page)
        for kind, name, page, _ in more_fixtures():
            self.assertIn(kind, KINDS, name)
            self.assertEqual(C.validate(page, C.load_schema(kind)), [], name)
            C.check_page(kind, page)
            self.assertEqual(name, f"{kind}-{C.page_key(kind, page)}.json")

    def test_every_board_row_has_a_reel_page(self):
        keys = {C.page_key("reel", fixture("reel"))} | {C.page_key(k, p) for k, _, p, _ in more_fixtures() if k == "reel"}
        self.assertEqual(keys, {r["sc"] for r in fixture("board")["reels"]})
        modes = {fixture("reel")["card"]["mode"]} | {p["card"]["mode"] for k, _, p, _ in more_fixtures() if k == "reel"}
        self.assertEqual(modes, {"tribe", "facts"}, "both card modes have a fixture")
        for kind, name, page, _ in more_fixtures():
            if kind == "reel":
                R.validate_card(copy.deepcopy(page["card"]))

    def test_fixtures_are_synthetic(self):
        real = set(REAL_NAMES)
        if (store.SWIPE / "reels").is_dir():
            real |= {p.name for p in (store.SWIPE / "reels").iterdir() if p.is_dir()}
        if (store.SWIPE / "creators").is_dir():
            real |= {p.stem for p in (store.SWIPE / "creators").glob("*.json")}
        if store.OUTPUTS.is_dir():
            real |= {p.name for p in store.OUTPUTS.iterdir() if p.is_dir()}
        raws = [(kind, (FIXTURES / f"{kind}.json").read_text(encoding="utf-8")) for kind in KINDS]
        raws += [(name, raw) for _, name, _, raw in more_fixtures()]
        for kind, raw in raws:
            for name in real:
                self.assertNotIn(name, raw, f"fixture {kind} holds a real name or id")
            for handle in re.findall(r"@([A-Za-z0-9._]+)", raw):
                self.assertTrue(handle.startswith("demo_"), f"{kind}: @{handle} is not a made-up demo handle")
            self.assertNotIn("—", raw, f"{kind}: em dash")
            self.assertNotRegex(raw, r"[A-Za-z]:\\|/Users/|OneDrive|private/|\.npy|\.env")

    def test_fixture_text_passes_the_rule_checks(self):
        pages = [(kind, fixture(kind)) for kind in KINDS] + [(k, p) for k, _, p, _ in more_fixtures()]
        for kind, page in pages:
            schema = C.load_schema(kind)
            shown = C.layer_strings(page, schema)
            self.assertTrue(shown or kind == "spend", kind)   # spend shows numbers only
            for path, layer, text in shown:
                self.assertIn(layer, C.LAYERS)
                self.assertEqual(R.find_banned(text), [], f"{kind}{path}: {text!r}")
                R.check_pronouns(text, f"{kind}{path}")
                if layer == "counts":
                    self.assertIsNone(R.BRAIN_TERMS_RE.search(text), f"{kind}{path} counts text names the brain layer")
                if layer == "brain":
                    self.assertIsNone(R.COUNT_TERMS_RE.search(text), f"{kind}{path} brain text names counts")
            # every string the fixture shows is either layered or a key the schema constrains
            self.assertLessEqual(len(shown), sum(1 for _ in strings(page)))

    def test_reel_card_meets_the_card_contract(self):
        card = copy.deepcopy(fixture("reel")["card"])
        R.validate_card(card)
        self.assertEqual(card["footnote"], R.CARD_FOOTNOTE)

    def test_tribe_fixture_lines_match_time(self):
        t = fixture("tribe")
        n = len(t["time_s"])
        for key in ("seeing", "hearing", "language", "attention", "combined"):
            self.assertEqual(len(t["lines"][key]["display_z"]), n, key)
        self.assertEqual(t["framing"], R.FRAMING)

    def test_brain_fixture_is_the_synthetic_page_on_the_tribe_fixture(self):
        """web/fixtures/brain.json is brain_assets.synthetic_page() on the tribe fixture's job, reel and
        seconds (rewrite it with: python -m strategist.brain_assets fixture)."""
        brain, tribe = fixture("brain"), fixture("tribe")
        self.assertEqual(brain, B.fixture_page(), "web/fixtures/brain.json is stale: python -m strategist.brain_assets fixture")
        self.assertEqual((brain["job_id"], brain["shortcode"], brain["time_s"]),
                         (tribe["job_id"], tribe["shortcode"], tribe["time_s"]))
        n = len(brain["time_s"])
        for name in ("hcp_left", "hcp_right", "yeo"):
            self.assertTrue(all(len(row) == n for row in brain["areas"][name]), name)
        self.assertEqual(brain["frames"]["bytes"], 16 + n * 20484)
        self.assertEqual(brain["frames"]["key"], f"tribe/{brain['job_id']}/frames.i8")
        if B.MESH_NPZ.is_file():   # the fixture's mesh is made up, never the FreeSurfer one
            real = B.pack("mesh", B.mesh_key(), B.mesh_raw(B.load_mesh()))
            self.assertNotEqual(brain["mesh"]["sha256"], real.hash)

    def test_bad_pages_are_refused(self):
        cases = []
        page = fixture("board")
        page["extra"] = 1
        cases.append(("board", page, "unexpected field"))
        page = fixture("board")
        page["reels"][0]["sort"]["tribe"] = 1
        cases.append(("board", page, "unexpected field"))
        page = fixture("board")
        page["sorts"][0]["key"] = "-tribe"
        cases.append(("board", page, "not one of"))
        page = fixture("reel")
        page["v"] = 2
        cases.append(("reel", page, "must be 1"))
        page = fixture("reel")
        page["card"]["lines"][1]["text"] = 'seeing line high for this reel · said: "…a quote…"'
        cases.append(("reel", page, "oneOf"))
        page = fixture("reel")
        page["card"]["lines"][3]["text"] = "Do this in your draft."
        cases.append(("reel", page, "oneOf"))
        page = fixture("reel")
        page["card"]["lines"][1], page["card"]["lines"][2] = page["card"]["lines"][2], page["card"]["lines"][1]
        cases.append(("reel", page, "oneOf"))
        page = fixture("reel")
        page["beats_empty"] = "The transcript stays in swipe/reels/DEMO0000001/private/ on this laptop."
        cases.append(("reel", page, "not allowed"))
        page = fixture("reel")
        page["facts"][0]["value"] = "0:42 (VAULT research/repurpose/data/DEMO0000001.json duration_s)"
        cases.append(("reel", page, "not allowed"))
        page = fixture("reel")
        page["stamps"]["page"] = "made on C:/Users/someone/OneDrive"
        cases.append(("reel", page, "not allowed"))
        page = fixture("reel")
        page["stills"] = []
        cases.append(("reel", page, "unexpected field"))
        page = fixture("tribe")
        page["words"] = [{"text": "hi", "start": 0.0}]
        cases.append(("tribe", page, "unexpected field"))
        page = fixture("tribe")
        page["peaks"][0]["value"] = 1.7
        cases.append(("tribe", page, "unexpected field"))
        page = fixture("tribe")
        page["framing"] = "viral score"
        cases.append(("tribe", page, "must be"))
        page = fixture("lab")
        page["hits"][0]["run"] = "six words shared with a creator"
        cases.append(("lab", page, "unexpected field"))
        page = fixture("patterns")
        page["patterns"][0]["contrast"] = "outliers 3/4"
        cases.append(("patterns", page, "does not match"))
        page = fixture("spend")
        page["month"] = "2026-13"
        cases.append(("spend", page, "does not match"))
        page = fixture("brain")
        page["atlas"]["hcp"]["labels"][0] = "Amygdala"
        cases.append(("brain", page, "not one of"))
        page = fixture("brain")
        page["words"] = [{"text": "hi", "start": 0.0}]
        cases.append(("brain", page, "unexpected field"))
        page = fixture("brain")
        page["scale"]["vmax_by_second"] = [0.4] * len(page["time_s"])
        cases.append(("brain", page, "unexpected field"))
        page = fixture("brain")
        page["scale"]["vmax"] = [0.4] * len(page["time_s"])
        cases.append(("brain", page, "expected number"))
        page = fixture("brain")
        page["framing"] = "viral score"
        cases.append(("brain", page, "must be"))
        page = fixture("brain")
        page["scale"]["label"] = "vs this reel's average"
        cases.append(("brain", page, "must be"))
        page = fixture("brain")
        page["areas"]["hcp_left"][0] = [0.1] * 91
        cases.append(("brain", page, "more than 90 items"))
        page = fixture("brain")
        page["frames"]["key"] = "C:/Users/someone/frames.i8"
        cases.append(("brain", page, "does not match"))
        page = fixture("brain")
        page["mesh"]["key"] = "shared/numbers.csv"
        cases.append(("brain", page, "does not match"))
        page = fixture("brain")
        page["precision"] = "fp16"
        cases.append(("brain", page, "not one of"))
        page = fixture("brain")
        page["atlas"]["order"][1] = page["atlas"]["order"][0]
        cases.append(("brain", page, "unique"))
        page = fixture("brain")
        page["areas"]["frames"] = [[0]]
        cases.append(("brain", page, "unexpected field"))
        for kind, page, why in cases:
            errs = C.validate(page, C.load_schema(kind))
            self.assertTrue(errs, f"{kind} should be refused ({why})")
            self.assertTrue(any(why in e for e in errs), f"{kind}: expected {why!r} in {errs}")
            with self.assertRaises(C.ContractError):
                C.check_page(kind, page)


# ---------------------------------------------------------------- job kinds

class JobKindTests(unittest.TestCase):

    def setUp(self):
        self.doc = C.load_job_kinds()
        self.kinds = {k["kind"]: k for k in self.doc["kinds"]}

    def test_import_kinds_are_on_with_their_video_estimates(self):
        """D31: the Import page's two kinds are enabled, paid on Apify, and priced with the video
        (a link $0.006, a handle $0.10); the limits they sit under are unchanged."""
        link, handle = self.kinds["reel.add_link"], self.kinds["reel.add_handle"]
        for spec in (link, handle):
            self.assertTrue(spec["enabled"])
            self.assertEqual((spec["stage"], spec["paid"], spec["billing"]), (1, True, "apify"))
        self.assertEqual((link["estimate_usd"], handle["estimate_usd"]), (0.006, 0.1))
        self.assertEqual(link["args"]["required"], ["sc"])
        self.assertEqual(handle["args"]["required"], ["handle"])
        self.assertEqual(self.doc["limits"]["apify_cap_usd"], 4.5)
        self.assertEqual(self.doc["limits"]["paid_running_max"], 1)
        self.assertEqual((self.doc["limits"]["paid_usd_per_day"], self.doc["limits"]["paid_jobs_per_day"]), (1.0, 10))
        for kind in ("coach.new_draft", "coach.this_but", "coach.replace", "coach.tag_shapes", "tribe.lanes"):
            self.assertFalse(self.kinds[kind]["enabled"], kind)

    def test_allow_list(self):
        self.assertEqual(self.doc["v"], 1)
        self.assertEqual(self.doc["platform"], "instagram")
        self.assertEqual(set(self.kinds), set(JOB_KINDS))
        for kind, (stage, paid, est) in JOB_KINDS.items():
            spec = self.kinds[kind]
            self.assertEqual((spec["stage"], spec["paid"], spec["estimate_usd"]), (stage, paid, est), kind)
            self.assertEqual(spec["enabled"], stage == 1, kind)   # D31: the two import kinds are paid and on
            self.assertEqual(spec["paid"], spec["estimate_usd"] > 0, kind)
            self.assertTrue(0 < len(spec["label"]) <= 80)
            self.assertEqual(R.find_banned(spec["label"]), [], kind)
            self.assertNotIn("—", spec["label"])
            self.assertEqual(C.schema_problems(spec["args"], display=False), [], kind)
            for name, prop in spec["args"]["properties"].items():
                self.assertIn(prop, list(self.doc["defs"].values()), f"{kind}.{name} drifted from defs")
        self.assertEqual(db.paid_kinds(), sorted(k for k, v in JOB_KINDS.items() if v[1]))
        self.assertEqual(self.doc["defs"]["label_status"]["enum"], ["accepted", "rejected"])
        self.assertEqual(self.kinds["reel.accept"]["sets_status"], "accepted")
        self.assertEqual(self.kinds["reel.reject"]["sets_status"], "rejected")

    def test_args(self):
        sc = "DEMO0000001"
        ok = [("reel.accept", {"sc": sc, "field": "all"}), ("reel.accept", {"sc": sc, "field": "beats.2"}),
              ("reel.reject", {"sc": sc, "field": "hook_shape"}),
              ("reel.discount", {"sc": sc, "reason": "Partner tag in the caption, not re-checked"}),
              ("patterns.build", {}), ("sync.push", {}), ("lab.check", {"draft_id": "20261009-demo-tool-explainer"}),
              ("coach.new_draft", {"slug": "try-cold-open"}),
              ("coach.new_draft", {"slug": "try-cold-open", "from_sc": sc, "brief": "Shorter.\nAbout lunch."}),
              ("coach.new_draft", {"slug": "try-x", "pattern_id": "hook.caption.cold-open-question"}),
              ("coach.this_but", {"draft_id": "20261009-demo-tool-explainer", "variant_id": "v2", "text": "but funnier"}),
              ("coach.replace", {"draft_id": "20261009-demo-tool-explainer", "replace": "sandwich", "with": "toast"}),
              ("coach.tag_shapes", {"sc": sc}), ("reel.add_link", {"sc": sc}),
              ("reel.add_handle", {"handle": "@demo_creator_a"}), ("reel.add_handle", {"handle": "demo.creator"}),
              ("tribe.lanes", {"sc": sc})]
        bad = [("reel.accept", {"sc": sc, "field": "hook"}), ("reel.accept", {"sc": sc}),
               ("reel.accept", {"sc": sc, "field": "all", "extra": 1}),
               ("reel.accept", {"sc": "https://www.instagram.com/reel/DEMO0000001/", "field": "all"}),
               ("reel.accept", {"sc": "A" * 21, "field": "all"}), ("reel.reject", {"sc": sc, "field": "all"}),
               ("reel.discount", {"sc": sc, "reason": ""}), ("reel.discount", {"sc": sc, "reason": "x" * 201}),
               ("reel.discount", {"sc": sc, "reason": "two\nlines"}), ("reel.discount", {"sc": sc, "reason": "bell\x07"}),
               ("patterns.build", {"x": 1}), ("lab.check", {"draft_id": "../etc/passwd"}),
               ("coach.new_draft", {"slug": "try-x", "brief": "x" * 501}),
               ("coach.new_draft", {"slug": "try-x", "brief": "esc\x1b[0m"}), ("coach.new_draft", {}),
               ("coach.this_but", {"draft_id": "20261009-demo-tool-explainer"}),
               ("reel.add_link", {"sc": "DEMO 01"}), ("reel.add_handle", {"handle": "bad handle!"}),
               ("reel.add_handle", {"handle": "@@demo"}), ("reel.add_handle", {"handle": "a" * 31}),
               ("tribe.lanes", {"sc": sc, "url": "https://example.com/x.mp4"}), ("tribe.lanes", {"sc": 12345})]
        for kind, args in ok:
            self.assertEqual(C.validate(args, self.kinds[kind]["args"]), [], (kind, args))
            C.check_job_args(kind, args)
        for kind, args in bad:
            self.assertTrue(C.validate(args, self.kinds[kind]["args"]), (kind, args))
            with self.assertRaises(C.ContractError):
                C.check_job_args(kind, args)
        with self.assertRaises(C.ContractError):
            C.check_job_args("shell.run", {})

    def test_args_never_wider_than_the_store(self):
        defs = self.doc["defs"]
        shortcodes = ["DEMO0000001", "abc_-9", "A" * 20, "A" * 21, "abcd", "a/b/c/d", "DEMO 001", ""]
        for v in shortcodes:
            if not C.validate(v, defs["shortcode"]):
                self.assertEqual(store.check_shortcode(v), v)
        handles = ["demo_creator_a", "@demo.creator", "a" * 30, "a" * 31, "bad handle", "@@x", "", "x-y", "@"]
        for v in handles:
            if not C.validate(v, defs["handle"]):
                store.check_handle(v)   # never accepts what the store refuses
        for v in ["20261009-demo-tool-explainer", "2026109-x", "20261009--x", "20261009-a", "20261009-ab"]:
            self.assertEqual(not C.validate(v, defs["draft_id"]), bool(lab.ID_RE.match(v)), v)
        for v in ["try-x", "-x", "a", "ab", "A1-b"]:
            self.assertEqual(not C.validate(v, defs["slug"]), bool(lab.SLUG_RE.match(v)), v)
        for v in ["hook_shape", "format", "cta", "beats", "beats.0", "beats.12", "all", "hook", "beats.", "beats.x"]:
            self.assertEqual(not C.validate(v, defs["field_reject"]), bool(sreel.FIELD_RE.match(v)), v)
            self.assertEqual(not C.validate(v, defs["field_accept"]), bool(sreel.FIELD_RE.match(v)) or v == "all", v)


# ---------------------------------------------------------------- SQL and Drizzle

class SqlTests(unittest.TestCase):

    def setUp(self):
        self.sql = MIGRATION.read_text(encoding="utf-8")
        self.sql1 = MIGRATION_1.read_text(encoding="utf-8")
        self.sql2 = MIGRATION_2.read_text(encoding="utf-8")
        self.ts = SCHEMA_TS.read_text(encoding="utf-8")
        self.brain = json.loads(BRAIN_CONTRACT.read_text(encoding="utf-8"))

    def test_lists_match_the_contract(self):
        kinds = [k["kind"] for k in C.load_job_kinds()["kinds"]]
        # 0000 made the first seven kinds; 0001 replaces the CHECK with all of them (brain added).
        self.assertEqual(sql_list(self.sql, "CREATE TABLE pages"), [k for k in db.PAGE_KINDS if k != "brain"])
        self.assertIn("ALTER TABLE pages DROP CONSTRAINT pages_kind_check;", self.sql1)
        self.assertEqual(sql_list(self.sql1, "ALTER TABLE pages ADD CONSTRAINT pages_kind_check"), list(db.PAGE_KINDS))
        self.assertEqual(sorted(db.PAGE_KINDS), sorted(C.page_kinds()))
        self.assertEqual(sql_list(self.sql, "CREATE TABLE jobs"), kinds)
        self.assertEqual(sql_list(self.sql, "status text NOT NULL"), list(db.STATUSES))
        self.assertEqual(sorted(sql_list(self.sql, "CREATE UNIQUE INDEX jobs_one_running_paid")), db.paid_kinds())
        self.assertEqual(ts_list(self.ts, "PAGE_KINDS"), list(db.PAGE_KINDS))
        self.assertEqual(ts_list(self.ts, "JOB_KINDS"), kinds)
        self.assertEqual(ts_list(self.ts, "JOB_STATUSES"), list(db.STATUSES))
        self.assertEqual(sorted(ts_list(self.ts, "PAID_JOB_KINDS")), db.paid_kinds())
        self.assertEqual(db.EXPECTED_SCHEMA, 3)
        self.assertIn(f"export const SCHEMA_VERSION = {db.EXPECTED_SCHEMA};", self.ts)
        self.assertIn("INSERT INTO schema_meta (id, version) VALUES (1, 1);", self.sql)
        # each migration ends by setting its own version; the last one is the runner's
        self.assertEqual(statements(self.sql1)[-1], "UPDATE schema_meta SET version = 2 WHERE id = 1")
        self.assertEqual(statements(self.sql2)[-1], f"UPDATE schema_meta SET version = {db.EXPECTED_SCHEMA} WHERE id = 1")
        self.assertEqual(sum("UPDATE schema_meta" in st for st in statements(self.sql2)), 1)
        self.assertEqual(sql_list(self.sql1, "kind text NOT NULL"), list(self.brain["kinds"]))
        self.assertEqual(ts_list(self.ts, "BRAIN_ASSET_KINDS"), list(self.brain["kinds"]))

    def test_brain_assets_table_matches_the_contract_file(self):
        c = self.brain
        key_re = re.search(r"key text PRIMARY KEY CHECK \(key ~ '([^']+)'\)", self.sql1).group(1)
        self.assertEqual(key_re, c["key_pattern"])
        ts_re = json.loads(re.search(r'export const BRAIN_ASSET_KEY_RE =\s*("(?:[^"\\]|\\.)*")', self.ts).group(1))
        self.assertEqual(ts_re, c["key_pattern"])
        self.assertIn(f"mime text NOT NULL CHECK (mime = '{c['mime']}')", self.sql1)
        self.assertIn(f"encoding text NOT NULL DEFAULT '{c['encoding']}' CHECK (encoding = '{c['encoding']}')", self.sql1)
        self.assertIn(f"CHECK (octet_length(bytes) BETWEEN {c['stored_bytes']['min']} AND {c['stored_bytes']['max']})",
                      self.sql1)
        self.assertIn(f"CHECK (raw_bytes BETWEEN {c['raw_bytes']['min']} AND {c['raw_bytes']['max']})", self.sql1)
        self.assertIn("REVOKE ALL ON brain_assets FROM PUBLIC;", self.sql1)
        self.assertEqual(c["stored_bytes"]["max"], 2 * 1024 * 1024)
        # the contract regex and the SQL CHECKs agree on sample keys
        kind_rules = {"frames": lambda k: k.endswith("/frames.i8"), "mesh": lambda k: k.startswith("shared/fsaverage5-inflated-"),
                      "atlas": lambda k: k.startswith("shared/atlas-")}
        good = ["tribe/20260101-000000-demo0000/frames.i8", "shared/fsaverage5-inflated-v1.bin", "shared/atlas-v1.bin",
                "shared/atlas-v999.bin"]
        bad = ["tribe/20260101-000000-demo0000/numbers.csv", "tribe/20260101-000000-demo0000/peak.png",
               "tribe/20261008-182653-68B712E3/frames.i8", "shared/atlas-v1000.bin", "shared/atlas-v1.bin\n",
               "tribe/../shared/atlas-v1.bin", "shared/mesh-v1.bin", "tribe/20260101-000000-demo0000+x/frames.i8",
               "C:/Users/someone/frames.i8", ""]
        for key in good:
            self.assertTrue(re.fullmatch(c["key_pattern"], key), key)
            kind = B.kind_of(key)
            self.assertTrue(kind and kind_rules[kind](key), key)
            self.assertEqual([k for k, rule in kind_rules.items() if rule(key)], [kind], key)
            db.check_brain_key(key, kind)
        for key in bad:
            self.assertIsNone(re.fullmatch(c["key_pattern"], key), repr(key))
            self.assertIsNone(B.kind_of(key), repr(key))
            with self.assertRaises(db.DbError):
                db.check_brain_key(key)
        self.assertNotIn("numbers", self.sql1.lower().replace("-- ", ""))   # the CSV is built on demand, never stored

    def test_reel_videos_table_matches_db_and_drizzle(self):
        """D30: one row per reel, where its video sits in the private Blob store. The SQL CHECKs,
        strategist/db.py and web/db/schema.ts agree; no counts or brain values in the table."""
        sql = self.sql2
        body = sql[sql.index("CREATE TABLE reel_videos"):sql.index("--> statement-breakpoint")]
        sc_re = re.search(r"shortcode text PRIMARY KEY CHECK \(shortcode ~ '([^']+)'\)", body).group(1)
        path_re = re.search(r"pathname text NOT NULL CHECK \(pathname ~ '([^']+)'\)", body).group(1)
        self.assertEqual(sc_re, db.REEL_VIDEO_SC_RE.pattern)
        self.assertEqual(path_re, db.REEL_VIDEO_PATH_RE.pattern)
        self.assertEqual(sc_re, "^[A-Za-z0-9_-]{5,20}$")
        self.assertEqual(path_re, r"^reels/[A-Za-z0-9_-]{5,20}-[0-9a-f]{8}\.mp4$")
        self.assertIn("sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$')", body)
        self.assertIn(f"bytes integer NOT NULL CHECK (bytes BETWEEN 1 AND {db.REEL_VIDEO_MAX_BYTES})", body)
        self.assertEqual(db.REEL_VIDEO_MAX_BYTES, 60_000_000)
        lo, hi = db.REEL_VIDEO_SECONDS
        self.assertIn(f"duration_s real NOT NULL CHECK (duration_s BETWEEN {lo:g} AND {hi:g})", body)
        self.assertIn("updated_at timestamptz NOT NULL DEFAULT now()", body)
        self.assertIn("CHECK (pathname = 'reels/' || shortcode || '-' || left(sha256, 8) || '.mp4')", body)
        cols = re.findall(r"^\s+([a-z_0-9]+) (?:text|integer|real|timestamptz)\b", body, re.M)
        self.assertEqual(cols, ["shortcode", "pathname", "sha256", "bytes", "duration_s", "updated_at"])
        for word in ("plays", "likes", "comments", "peak", "brain", "frames", "tribe"):
            self.assertNotIn(word, " ".join(cols))
        self.assertIn("REVOKE ALL ON reel_videos FROM PUBLIC;", sql)
        # schema.ts mirrors it
        ts_re = lambda name: json.loads(re.search(rf'export const {name} =\s*("(?:[^"\\]|\\.)*")', self.ts).group(1))
        self.assertEqual(ts_re("REEL_VIDEO_SHORTCODE_RE"), sc_re)
        self.assertEqual(ts_re("REEL_VIDEO_PATHNAME_RE"), path_re)
        self.assertIn(f"export const REEL_VIDEO_MAX_BYTES = {db.REEL_VIDEO_MAX_BYTES};", self.ts)
        ts_table = self.ts[self.ts.index('export const reelVideos = pgTable('):]
        ts_table = ts_table[:ts_table.index("\n);")]
        self.assertEqual(re.findall(r'^\s+\w+: \w+\("([a-z_0-9]+)"', ts_table, re.M), cols)
        for name in ("reel_videos_shortcode_check", "reel_videos_pathname_check", "reel_videos_sha256_check",
                     "reel_videos_bytes_check", "reel_videos_duration_s_check", "reel_videos_pathname_matches"):
            self.assertIn(f'"{name}"', ts_table)
        self.assertIn("BETWEEN 1 AND 600", ts_table)
        # sample pathnames: the SQL regex and db.py agree
        good = ["reels/DEMO0000001-0123abcd.mp4", "reels/Dd-D7GEzDKx-ffffffff.mp4", "reels/abcde-00000000.mp4"]
        bad = ["reels/DEMO0000001-0123ABCD.mp4", "reels/DEMO0000001.mp4", "reels/DEMO0000001-0123abcd.mov",
               "videos/DEMO0000001-0123abcd.mp4", "reels/../x-0123abcd.mp4", "reels/abcd-0123abcd.mp4",
               "reels/" + "A" * 21 + "-0123abcd.mp4", "reels/DEMO0000001-0123abcd.mp4\n", ""]
        for p in good:
            self.assertTrue(re.fullmatch(path_re, p), p)
        for p in bad:
            self.assertIsNone(re.fullmatch(path_re, p), repr(p))

    def test_brain_assets_grants(self):
        roles, grants = ROLES.read_text(encoding="utf-8"), GRANTS_1.read_text(encoding="utf-8")
        grants2 = GRANTS_2.read_text(encoding="utf-8")
        self.assertEqual(statements(grants), ["GRANT SELECT ON brain_assets TO tribe_web",
                                              "GRANT SELECT, INSERT, UPDATE, DELETE ON brain_assets TO tribe_runner"])
        self.assertEqual(statements(grants2), ["GRANT SELECT ON reel_videos TO tribe_web",
                                               "GRANT SELECT, INSERT, UPDATE, DELETE ON reel_videos TO tribe_runner"])
        st = statements(roles)
        self.assertIn("REVOKE ALL ON pages, images, brain_assets, reel_videos, jobs, job_events, settings, schema_meta "
                      "FROM PUBLIC", st)
        self.assertIn("GRANT SELECT ON pages, images, brain_assets, reel_videos, jobs, job_events, settings, schema_meta "
                      "TO tribe_web", st)
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE ON pages, images, brain_assets, reel_videos, jobs, job_events, "
                      "settings, schema_meta TO tribe_runner", st)
        # tribe_web writes only the jobs columns roles.sql names, never a page, image, brain asset or reel video
        for sql in (roles, grants, grants2):
            self.assertEqual(sorted(set(web_writes(sql))), ["jobs"] if sql is roles else [])
        self.assertEqual(web_writes("GRANT INSERT ON jobs, brain_assets TO tribe_web;"), ["jobs, brain_assets"])
        self.assertEqual(web_writes("GRANT ALL ON brain_assets TO tribe_web, tribe_runner;"), ["brain_assets"])

    def test_no_enums_and_breakpoints(self):
        self.assertNotRegex(self.sql, r"(?i)CREATE\s+TYPE|AS\s+ENUM")
        self.assertNotIn("pgEnum", self.ts)
        self.assertNotRegex(self.sql1, r"(?i)CREATE\s+TYPE|AS\s+ENUM")
        self.assertNotRegex(self.sql2, r"(?i)CREATE\s+TYPE|AS\s+ENUM")
        journal = json.loads(JOURNAL.read_text(encoding="utf-8"))
        tags = [e["tag"] for e in journal["entries"]]
        self.assertEqual(tags, ["0000_init", "0001_brain_assets", "0002_reel_videos"])
        self.assertEqual([e["idx"] for e in journal["entries"]], [0, 1, 2])
        self.assertTrue(all(e["breakpoints"] for e in journal["entries"]))
        whens = [e["when"] for e in journal["entries"]]
        self.assertEqual(whens, sorted(set(whens)), "journal entries must be in time order")
        for tag in tags:
            self.assertTrue((MIGRATION.parent / f"{tag}.sql").is_file(), tag)
        for sql in (self.sql, self.sql1, self.sql2):
            for chunk in sql.split("--> statement-breakpoint"):
                body = "\n".join(ln for ln in chunk.splitlines() if not ln.strip().startswith("--")).strip()
                body = re.sub(r"\$\$.*?\$\$", "$$", body, flags=re.S)
                self.assertLessEqual(body.count(";"), 1, f"one statement per chunk: {body[:60]!r}")

    def test_roles_hold_no_secret(self):
        roles = ROLES.read_text(encoding="utf-8")
        live = "\n".join(ln for ln in roles.splitlines() if not ln.strip().startswith("--"))
        self.assertNotRegex(live, r"(?i)PASSWORD\s+'")
        self.assertEqual(len(re.findall(r"LOGIN PASSWORD NULL", live)), 2)
        for ln in roles.splitlines():
            for pw in re.findall(r"PASSWORD\s+'([^']*)'", ln):
                self.assertRegex(pw, r"^<[A-Z_]+>$", "only placeholders in roles.sql")
        self.assertIn("GRANT UPDATE (confirmed_at, cancel_requested) ON jobs TO tribe_web;", roles)
        self.assertIn("GRANT EXECUTE ON FUNCTION set_paused(boolean) TO tribe_web;", roles)
        self.assertNotRegex(live, r"GRANT[^;]*(UPDATE|INSERT|DELETE)[^;(]*ON (pages|images|settings|job_events|brain_assets"
                                  r"|reel_videos)[^;]*tribe_web")

    def test_web_can_not_confirm_on_insert_or_redate_a_confirm(self):
        """D26: a paid job is inserted unconfirmed, and only a later confirm click (set once, to
        the database's now()) is his go; a cancel can't be taken back."""
        roles = ROLES.read_text(encoding="utf-8")
        self.assertEqual(sorted(sql_list(roles, "CREATE POLICY jobs_web_insert")), db.paid_kinds())
        self.assertIn("kind NOT IN (", roles[roles.index("CREATE POLICY jobs_web_insert"):])
        guard = roles[roles.index("CREATE FUNCTION jobs_web_guard()"):]
        for rule in ("OLD.confirmed_at IS NOT NULL", "now() <= OLD.created_at", "NEW.confirmed_at := now();",
                     "OLD.cancel_requested AND NOT NEW.cancel_requested", "OLD.status <> 'queued'"):
            self.assertIn(rule, guard)
        self.assertIn("CREATE TRIGGER jobs_web_guard BEFORE UPDATE ON jobs FOR EACH ROW", roles)
        self.assertIn("REVOKE ALL ON FUNCTION jobs_web_guard() FROM PUBLIC;", roles)


# ---------------------------------------------------------------- db.py with a fake connection

class FakeCursor:
    def __init__(self, rows=None, rowcount=None):
        self.rows = list(rows or [])
        self.rowcount = len(self.rows) if rowcount is None else rowcount

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeConn:
    """Records (sql, params); answers with the scripted cursors, or raises a scripted error."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        a = self.answers.pop(0) if self.answers else FakeCursor()
        if isinstance(a, Exception):
            raise a
        return a


class SqlState(Exception):
    def __init__(self, sqlstate):
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class DbTests(unittest.TestCase):

    def test_schema_version(self):
        self.assertEqual(db.check_schema(FakeConn(FakeCursor([(3,)]))), 3)
        for rows in ([(1,)], [(2,)], [(4,)], [], [(None,)]):   # a runner never writes to a schema it doesn't know
            with self.assertRaisesRegex(db.DbError, "expects 3"):
                db.check_schema(FakeConn(FakeCursor(rows)))

    def test_brain_assets(self):
        raw = B.header("atlas", 20484, 180, 7) + bytes(2 * 20484)
        a = B.pack("atlas", "shared/atlas-v1.bin", raw)
        conn = FakeConn(FakeCursor(rowcount=1), FakeCursor(rowcount=0))
        self.assertTrue(db.upsert_brain_asset(conn, a.key, a.kind, a.mime, a.data, a.raw_bytes, a.hash))
        self.assertFalse(db.upsert_brain_asset(conn, a.key, a.kind, a.mime, a.data, a.raw_bytes))
        sql, params = conn.calls[0]
        self.assertEqual(sql, db.UPSERT_BRAIN_ASSET)
        self.assertIn("ON CONFLICT (key)", sql)
        self.assertIn("IS DISTINCT FROM", sql)
        self.assertEqual(params, (a.key, "atlas", "application/octet-stream", a.data, len(raw), a.hash))
        big = b"\x1f\x8b" + bytes(2 * 1024 * 1024)
        for args in (("shared/atlas-v1.csv", "atlas", a.mime, a.data, a.raw_bytes),          # not a key
                     ("tribe/20261001-120000-0123abcd/numbers.csv", "frames", a.mime, a.data, 100),
                     (a.key, "mesh", a.mime, a.data, a.raw_bytes),                            # kind and key disagree
                     (a.key, "nope", a.mime, a.data, a.raw_bytes),
                     (a.key, a.kind, "text/csv", a.data, a.raw_bytes),                         # wrong mime
                     (a.key, a.kind, a.mime, raw, a.raw_bytes),                                # not gzip
                     (a.key, a.kind, a.mime, big, a.raw_bytes),                                # over 2 MiB
                     (a.key, a.kind, a.mime, b"\x1f\x8b", a.raw_bytes),                        # under 18 bytes
                     (a.key, a.kind, a.mime, a.data, 4 * 1024 * 1024 + 1),
                     (a.key, a.kind, a.mime, a.data, True),
                     (a.key, a.kind, a.mime, "text", a.raw_bytes)):
            with self.assertRaises(db.DbError, msg=args[:2]):
                db.upsert_brain_asset(FakeConn(), *args)
        with self.assertRaisesRegex(db.DbError, "sha256"):
            db.upsert_brain_asset(FakeConn(), a.key, a.kind, a.mime, a.data, a.raw_bytes, hash="0" * 64)
        conn = FakeConn(FakeCursor([("shared/atlas-v1.bin", a.hash)]))
        self.assertEqual(db.brain_asset_hashes(conn), {"shared/atlas-v1.bin": a.hash})
        conn = FakeConn(FakeCursor([("tribe/20261001-120000-0123abcd/frames.i8",)]))
        self.assertEqual(db.delete_missing_brain_assets(conn, [a.key, a.key]), ["tribe/20261001-120000-0123abcd/frames.i8"])
        self.assertEqual(conn.calls[0][1], ([a.key],))
        self.assertEqual(db.delete_missing_brain_assets(FakeConn(FakeCursor([])), []), [])   # no brain page: all go
        with self.assertRaises(db.DbError):
            db.delete_missing_brain_assets(FakeConn(), ["tribe/x/numbers.csv"])
        conn = FakeConn(FakeCursor([(a.key, "atlas", a.mime, "gzip", memoryview(a.data), len(raw), a.hash)]))
        self.assertEqual(db.list_brain_assets(conn), [{"key": a.key, "kind": "atlas", "mime": a.mime, "encoding": "gzip",
                                                       "bytes": a.data, "raw_bytes": len(raw), "hash": a.hash}])

    def test_reel_videos(self):
        sha = "0123abcd" + "e" * 56
        path = "reels/DEMO0000001-0123abcd.mp4"
        self.assertEqual(db.reel_video_pathname("DEMO0000001", sha), path)
        conn = FakeConn(FakeCursor(rowcount=1), FakeCursor(rowcount=0))
        self.assertTrue(db.upsert_reel_video(conn, "DEMO0000001", path, sha, 8_100_000, 37.8912))
        self.assertFalse(db.upsert_reel_video(conn, "DEMO0000001", path, sha, 8_100_000, 37.8912))
        sql, params = conn.calls[0]
        self.assertEqual(sql, db.UPSERT_REEL_VIDEO)
        self.assertIn("ON CONFLICT (shortcode)", sql)
        self.assertIn("IS DISTINCT FROM", sql)
        self.assertEqual(params, ("DEMO0000001", path, sha, 8_100_000, 37.891))
        for args in (("DEMO/001", path, sha, 100, 30.0),                                  # not a shortcode
                     ("abcd", "reels/abcd-0123abcd.mp4", sha, 100, 30.0),                 # 4 characters
                     ("A" * 21, path, sha, 100, 30.0),                                    # 21 characters
                     ("DEMO0000001", "reels/DEMO0000001-ffffffff.mp4", sha, 100, 30.0),  # not this file's sha8
                     ("DEMO0000002", path, sha, 100, 30.0),                               # another reel's name
                     ("DEMO0000001", "videos/DEMO0000001-0123abcd.mp4", sha, 100, 30.0),
                     ("DEMO0000001", path, sha.upper(), 100, 30.0),
                     ("DEMO0000001", path, sha[:63], 100, 30.0),
                     ("DEMO0000001", path, sha, 0, 30.0),
                     ("DEMO0000001", path, sha, 60_000_001, 30.0),
                     ("DEMO0000001", path, sha, True, 30.0),
                     ("DEMO0000001", path, sha, 100.0, 30.0),
                     ("DEMO0000001", path, sha, 100, 0.5),
                     ("DEMO0000001", path, sha, 100, 600.5),
                     ("DEMO0000001", path, sha, 100, float("nan")),
                     ("DEMO0000001", path, sha, 100, True),
                     ("DEMO0000001", path, sha, 100, "30")):
            with self.assertRaises(db.DbError, msg=args):
                db.upsert_reel_video(FakeConn(), *args)
        conn = FakeConn(FakeCursor([(path,)]), FakeCursor([]))
        self.assertEqual(db.delete_reel_video(conn, "DEMO0000001"), path)
        self.assertIsNone(db.delete_reel_video(conn, "DEMO0000001"))
        self.assertEqual(conn.calls[0][1], ("DEMO0000001",))
        self.assertIn("RETURNING pathname", conn.calls[0][0])
        with self.assertRaises(db.DbError):
            db.delete_reel_video(FakeConn(), "x' OR '1'='1")
        conn = FakeConn(FakeCursor([("DEMO0000001", path, sha, 8_100_000, 37.891)]))
        self.assertEqual(db.list_reel_videos(conn), [{"shortcode": "DEMO0000001", "pathname": path, "sha256": sha,
                                                      "bytes": 8_100_000, "duration_s": 37.891}])

    def test_upsert_page(self):
        page = fixture("meta")
        conn = FakeConn(FakeCursor(rowcount=1), FakeCursor(rowcount=0))
        self.assertTrue(db.upsert_page(conn, "meta", "index", 1, page))
        self.assertFalse(db.upsert_page(conn, "meta", "index", 1, page))
        sql, params = conn.calls[0]
        self.assertIn("ON CONFLICT (kind, key)", sql)
        self.assertIn("IS DISTINCT FROM", sql)
        self.assertEqual(params[:3], ("meta", "index", 1))
        self.assertEqual(json.loads(params[3]), page)
        self.assertEqual(params[4], db.page_hash(page))
        self.assertEqual(db.page_hash(page), db.page_hash(json.loads(json.dumps(page, sort_keys=False))))
        for args in (("secret", "index", 1, page), ("meta", "../x", 1, page), ("meta", "index", 2, page),
                     ("meta", "index", True, page), ("meta", "index", 1, dict(page, x=float("nan"))),
                     ("meta", "index", 1, [page])):
            with self.assertRaises(db.DbError):
                db.upsert_page(FakeConn(), *args)
        with self.assertRaises(db.DbError):
            db.upsert_page(FakeConn(), "meta", "index", 1, page, hash="abc")

    def test_delete_missing(self):
        conn = FakeConn(FakeCursor([("OLD000001",), ("AAA000001",)]))
        self.assertEqual(db.delete_missing(conn, "reel", ["DEMO0000001", "DEMO0000001"]), ["AAA000001", "OLD000001"])
        self.assertEqual(conn.calls[0][1], ("reel", ["DEMO0000001"]))
        with self.assertRaisesRegex(db.DbError, "every reel page"):
            db.delete_missing(FakeConn(), "reel", [])
        self.assertEqual(db.delete_missing(FakeConn(FakeCursor([])), "reel", [], allow_empty=True), [])
        with self.assertRaises(db.DbError):
            db.delete_missing(FakeConn(), "secret", ["x"])
        with self.assertRaises(db.DbError):
            db.delete_missing(FakeConn(), "reel", ["bad key!"])

    def test_images(self):
        png = db.PNG_MAGIC + b"\x00" * 32
        conn = FakeConn(FakeCursor(rowcount=1))
        self.assertTrue(db.upsert_image(conn, "tribe/20261001-101500-0a1b2c3d/peak.png", png))
        self.assertEqual(conn.calls[0][1][1], png)
        for key, data in (("x.png", b"\xff\xd8\xff"), ("x.png", db.PNG_MAGIC + b"\x00" * db.IMAGE_MAX),
                          ("bad key!", png)):
            with self.assertRaises(db.DbError):
                db.upsert_image(FakeConn(), key, data)

    def test_claim_next(self):
        row = (UUID, "tribe.lanes", '{"sc": "DEMO0000001"}', "0.1000", None, "t0", "t1")
        conn = FakeConn(FakeCursor([row]))
        job = db.claim_next(conn)
        self.assertEqual(job["id"], UUID)
        self.assertEqual(job["args"], {"sc": "DEMO0000001"})
        self.assertEqual(job["estimate_usd"], 0.1)
        sql, params = conn.calls[0]
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)
        self.assertIn("'paused'", sql)
        self.assertIn("confirmed_at IS NOT NULL", sql)
        self.assertEqual(params, (db.LEASE_S, db.paid_kinds(), db.paid_kinds()))
        self.assertIsNone(db.claim_next(FakeConn(FakeCursor([]))))
        self.assertIsNone(db.claim_next(FakeConn(SqlState("23505"))))
        with self.assertRaises(SqlState):
            db.claim_next(FakeConn(SqlState("08006")))

    def test_heartbeat_and_finish(self):
        self.assertEqual(db.heartbeat(FakeConn(FakeCursor([(True,)])), UUID), {"cancel_requested": True})
        self.assertIsNone(db.heartbeat(FakeConn(FakeCursor([])), UUID))
        with self.assertRaises(db.DbError):
            db.heartbeat(FakeConn(), "not-a-uuid")
        conn = FakeConn(FakeCursor([(UUID,)]))
        self.assertTrue(db.finish(conn, UUID, "done", result={"pages": 7}))
        sql, params = conn.calls[0]
        self.assertIn("status IN ('queued', 'running')", sql)
        self.assertEqual(params, ("done", '{"pages":7}', None, None, UUID))
        self.assertFalse(db.finish(FakeConn(FakeCursor([])), UUID, "done"))
        self.assertTrue(db.finish(FakeConn(FakeCursor([(UUID,)])), UUID, "refused", refusal="Confirm expired."))
        for args, kw in (((UUID, "running"), {}), ((UUID, "failed"), {}), ((UUID, "refused"), {}),
                         ((UUID, "failed"), {"error_code": "Bad Code"}),
                         ((UUID, "refused"), {"refusal": "x" * 301}), ((UUID, "refused"), {"refusal": "a\nb"}),
                         ((UUID, "done"), {"result": {"x": "y" * db.RESULT_MAX}}), ((UUID, "done"), {"result": [1]})):
            with self.assertRaises(db.DbError, msg=(args, kw)):
                db.finish(FakeConn(), *args, **kw)

    def test_stale_and_cancelled(self):
        self.assertEqual(db.interrupt_stale(FakeConn(FakeCursor([(UUID,)]))), [UUID])
        self.assertEqual(db.cancel_queued(FakeConn(FakeCursor([]))), [])

    def test_event_lines_are_fixed(self):
        sample = {"n": 3, "total": 7, "usd": 0.1, "code": "confirm_expired", "gone": 1}
        for key, template in db.EVENT_LINES.items():
            names = set(re.findall(r"\{(\w+)", template))
            line = db.event_line(key, **{k: sample[k] for k in names})
            self.assertLessEqual(len(line), db.LINE_MAX)
            self.assertEqual(R.find_banned(line), [], line)
            self.assertNotIn("—", line)
            R.check_mixed_layers([(key, line)])
        conn = FakeConn()
        self.assertEqual(db.add_event(conn, UUID, "synced", n=5, gone=0), "Pushed 5 pages, removed 0.")
        self.assertEqual(conn.calls[0][1], (UUID, "Pushed 5 pages, removed 0."))
        for key, kw in (("nope", {}), ("refused", {"code": "two words"}), ("refused", {"code": "Upper"}),
                        ("step", {"n": 1.5, "total": 2}), ("step", {"n": True, "total": 2}), ("step", {"n": 1}),
                        ("estimate", {"usd": float("inf")}), ("refused", {"code": "x" * 41})):
            with self.assertRaises(db.DbError, msg=(key, kw)):
                db.event_line(key, **kw)

    def test_settings(self):
        self.assertTrue(db.is_paused(FakeConn(FakeCursor([(True,)]))))
        self.assertFalse(db.is_paused(FakeConn(FakeCursor([(False,)]))))
        self.assertFalse(db.is_paused(FakeConn(FakeCursor([]))))
        self.assertFalse(db.is_paused(FakeConn(FakeCursor([("true",)]))))   # only a real JSON true pauses
        conn = FakeConn()
        db.settings_set(conn, "paused", True)
        self.assertEqual(conn.calls[0][1], ("paused", "true"))
        with self.assertRaises(db.DbError):
            db.settings_get(FakeConn(), "Bad Key")

    def test_env_is_loaded_quietly(self):
        with tempfile.TemporaryDirectory(prefix="contract-env-") as tmp:
            env = Path(tmp) / ".env"
            env.write_text("APIFY_TOKEN=apify_xyz\nTRIBE_RUNNER_DATABASE_URL=\"postgresql://r:pw123@h/db\"\n",
                           encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict(os.environ, {}, clear=False), contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(err):
                os.environ.pop(db.DSN_ENV, None)
                os.environ.pop("APIFY_TOKEN", None)
                self.assertEqual(db.load_env(path=env), [db.DSN_ENV])
                self.assertEqual(db.dsn_value(), "postgresql://r:pw123@h/db")
                self.assertNotIn("APIFY_TOKEN", os.environ)
                os.environ[db.DSN_ENV] = "postgresql://already@set/db"
                self.assertEqual(db.load_env(path=env), [])
                self.assertEqual(db.dsn_value(), "postgresql://already@set/db")
                os.environ.pop(db.DSN_ENV)
                with self.assertRaisesRegex(db.DbError, "not set"):
                    db.dsn_value()
            self.assertEqual(out.getvalue() + err.getvalue(), "")
        self.assertEqual(db.scrub("failed for postgresql://r:pw123@h/db and pw123", "postgresql://r:pw123@h/db"),
                         "failed for *** and ***")

    def test_connect_never_shows_the_password(self):
        try:
            import psycopg  # noqa: F401
        except ImportError:
            self.skipTest("psycopg is not installed")
        with self.assertRaises(db.DbError) as cm:
            db.connect("postgresql://runner:s3cret-pw@127.0.0.1:1/tribe?connect_timeout=3")
        self.assertNotIn("s3cret-pw", str(cm.exception))


# ---------------------------------------------------------------- store.locked()

HOLDER = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from strategist import store
store.SWIPE = Path(sys.argv[2])
with store.locked():
    print("held", flush=True)
    sys.stdin.readline()
"""


class LockTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="contract-lock-")
        self.swipe = Path(self.tmp.name) / "swipe"
        self.patch = mock.patch.object(store, "SWIPE", self.swipe)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_reentrant_and_used_by_save_reel(self):
        with store.locked() as path:
            self.assertEqual(path, self.swipe / ".lock")
            with store.locked():
                store.save_reel({"shortcode": "DEMO0000001", "owner": "demo_creator_a"})
            self.assertTrue(path.is_file())
        self.assertEqual(store.load_reel("DEMO0000001")["owner"], "demo_creator_a")
        self.assertEqual(store._LOCKS, {})

    def test_another_thread_waits_then_times_out(self):
        got = []

        def other():
            try:
                with store.locked(timeout=0.2):
                    got.append("held")
            except store.LockTimeout as e:
                got.append(str(e))
        with store.locked():
            t = threading.Thread(target=other)
            t.start()
            t.join(5)
        self.assertEqual(len(got), 1)
        self.assertIn("busy", got[0])
        t = threading.Thread(target=other)
        t.start()
        t.join(5)
        self.assertEqual(got[-1], "held")

    def test_another_process_blocks_with_a_clear_error(self):
        proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(PROJECT_ROOT), str(self.swipe)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(), "held")
            with self.assertRaisesRegex(store.LockTimeout, "another Tribe command or the runner"):
                with store.locked(timeout=0.3):
                    pass
            with self.assertRaises(store.StoreError):   # the CLIs catch StoreError and print "refused"
                self._save_with_short_timeout()
        finally:
            proc.stdin.close()
            proc.wait(10)
            proc.stdout.close()
        with store.locked(timeout=2):
            pass

    def _save_with_short_timeout(self):
        with mock.patch.object(store, "LOCK_TIMEOUT_S", 0.2):
            store.save_reel({"shortcode": "DEMO0000001"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
