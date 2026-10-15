"""Tests for the dashboard's text and files (web/). Run: python -m strategist.test_web_copy

- Every string in web/copy/en.json passes the dashboard/render.py rule checks (banned words,
  the counts/brain wall, cause words, pronouns) and has no em dash.
- Every string literal in web/**/*.ts(x) is free of banned words and em dashes.
- The licence footer, filled in, is docs/LICENCE.md section 12 A word for word.
- The hosted schema copies in web/contracts/hosted_schema match strategist/hosted_schema.
- The HCP clause 5.1 acknowledgement is reel.brain.credit.hcp only, LICENSES/CREDITS.md word
  for word (with "[in part]" written "in part").
- The numbers file (CSV) header: the footer is docs/LICENCE.md section 12 E word for word, and
  the Yeo-7 citation is the paper line in LICENSES/CREDITS.md.
- No file under web/ holds a laptop path, OneDrive, a private/ folder, a .env value or a real
  handle from swipe/creators (file names only; .env values are compared in memory, never printed).

node_modules and .next are skipped. Read-only; no network."""

import json
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from strategist import store  # noqa: E402

R = store.rules()   # dashboard/render.py: check_authored, find_banned, the wall and the rest

WEB = PROJECT_ROOT / "web"
COPY = WEB / "copy" / "en.json"
LICENCE = PROJECT_ROOT / "docs" / "LICENCE.md"
CREDITS = PROJECT_ROOT / "LICENSES" / "CREDITS.md"
SKIP_DIRS = {"node_modules", ".next", "playwright-report", "test-results", ".vercel"}
CODE_EXT = {".ts", ".tsx", ".mts", ".mjs", ".js"}
BINARY_EXT = {".ico", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2", ".ttf", ".otf"}
EM_DASH = "\u2014"

# The hosted page kinds (strategist/hosted_schema); each schema copy names the refused patterns.
KINDS = ("board", "reel", "patterns", "lab", "tribe", "brain", "meta", "spend")
# Files that name the refused patterns on purpose (they are the rules, not leaks).
RULE_FILES = {
    "contracts/README.md",
    ".vercelignore",
    *(f"contracts/hosted_schema/{k}.schema.json" for k in KINDS),
}
LEAK_RES = (
    ("laptop path", re.compile(r"[A-Za-z]:(?:\\\\|\\|/)+Users\b", re.IGNORECASE)),
    ("OneDrive", re.compile(r"onedrive", re.IGNORECASE)),
    ("private/ folder", re.compile(r"(?<![A-Za-z0-9_-])private[\\/]")),
)
# Strings or comments in TS/JS source; only the string groups are kept.
TOKEN_RE = re.compile(
    r"//[^\n]*|/\*.*?\*/"
    r"|\"((?:\\.|[^\"\\\n])*)\"|'((?:\\.|[^'\\\n])*)'|`((?:\\.|[^`\\])*)`",
    re.DOTALL)


def web_files():
    for p in sorted(WEB.rglob("*")):
        rel = p.relative_to(WEB)
        if not p.is_file() or SKIP_DIRS & set(rel.parts):
            continue
        yield p, rel.as_posix()


def copy_strings(node, path="copy"):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from copy_strings(v, f"{path}.{k}")


def code_literals(text):
    for m in TOKEN_RE.finditer(text):
        lit = next((g for g in m.groups() if g is not None), None)
        if lit:
            yield lit


def env_values():
    """Secret-looking values from the project .env files: (key, value), kept in memory only."""
    out = []
    for env in sorted(PROJECT_ROOT.glob(".env*")):
        if env.name == ".env.example" or not env.is_file():
            continue
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip("'\"")
            if len(value) >= 12:
                out.append((key.strip(), value))
    return out


def real_handles():
    folder = store.SWIPE / "creators"
    return sorted({p.stem.lstrip("@").lower() for p in folder.glob("*.json")}) if folder.is_dir() else []


class TestCopy(unittest.TestCase):
    def setUp(self):
        self.copy = json.loads(COPY.read_text(encoding="utf-8"))
        self.strings = list(copy_strings(self.copy))

    def test_has_strings(self):
        self.assertGreater(len(self.strings), 50)

    def test_rule_checks(self):
        R.check_authored(self.strings)
        R.check_banned(self.strings)
        R.check_mixed_layers(self.strings)
        R.check_cause(self.strings)
        R.check_pronouns(self.strings)

    def test_find_banned_each(self):
        bad = [(w, R.find_banned(t)) for w, t in self.strings if R.find_banned(t)]
        self.assertEqual(bad, [])

    def test_filled_templates_pass_find_banned(self):
        """A template is checked as the page shows it, with numbers in its {slots}: "{done}/{total}"
        alone is clean, but filled it reads "3/10", a rating."""
        bad = []
        for w, t in self.strings:
            if "{" not in t:
                continue
            for vals in (("3", "10"), ("1", "4"), ("7", "10")):
                it = iter(vals * 4)
                filled = re.sub(r"\{\w+\}", lambda m: next(it), t)
                if R.find_banned(filled):
                    bad.append((w, filled))
        self.assertEqual(bad, [])
        self.assertTrue(R.find_banned("3/10"), "the rating rule this test leans on is gone")

    def test_no_em_dash(self):
        self.assertEqual([w for w, t in self.strings if EM_DASH in t], [])

    def test_never_low(self):
        bad = [w for w, t in self.strings if re.search(r"(?<![A-Za-z])LOW(?![A-Za-z])", t)]
        self.assertEqual(bad, [], "say FLAT, not LOW")

    def test_licence_footer_word_for_word(self):
        text = LICENCE.read_text(encoding="utf-8")
        section = text[text.index("### A. Web page footer"):]
        expected = re.search(r"```\n(.+?)\n```", section, re.DOTALL).group(1).strip()
        f = self.copy["footer"]
        filled = f["text"].format(tribe=f["tribe"], licence=f["licence"], llama=f["llama"])
        self.assertEqual(filled, expected)
        self.assertIn("Built with Llama", filled)
        self.assertEqual(f["tribeUrl"], "https://github.com/facebookresearch/tribev2")
        self.assertEqual(f["licenceUrl"], "https://creativecommons.org/licenses/by-nc/4.0/")

    def test_hcp_acknowledgement_word_for_word(self):
        text = CREDITS.read_text(encoding="utf-8")
        line = next(ln for ln in text.splitlines() if "(clause 5.1)" in ln)
        expected = re.search(r'"(Data were provided[^"]+)"', line).group(1).replace("[in part]", "in part")
        self.assertTrue(expected.startswith("Data were provided in part by the Human Connectome Project"))
        # The brain view footer, the Areas tab and the numbers file all show this one key (D28).
        self.assertEqual(self.copy["reel"]["brain"]["credit"]["hcp"], expected)
        display = re.search(r'\*\*Display text, word for word\*\*.*?"(Data were provided[^"]+)"', text)
        self.assertIsNotNone(display, "CREDITS.md section 4 lost its display text")
        self.assertEqual(display.group(1), expected)
        shown = [(w, t) for w, t in self.strings if "Connectome" in t or "WU-Minn" in t or "1U54MH091657" in t]
        self.assertEqual([w for w, _ in shown], ["copy.reel.brain.credit.hcp"], "show the acknowledgement through one key")
        for where, t in shown:
            self.assertEqual(t, expected, where)

    def test_numbers_file_footer_and_citation_word_for_word(self):
        """The numbers file (CSV) header: the report footer is docs/LICENCE.md section 12 E word for
        word, and the Yeo-7 citation is the paper line in LICENSES/CREDITS.md."""
        text = LICENCE.read_text(encoding="utf-8")
        section = text[text.index("### E. Report footer"):]
        footer = re.search(r"```\n(.+?)\n```", section, re.DOTALL).group(1).strip()
        csv = self.copy["reel"]["download"]["csv"]
        self.assertEqual(csv["footer"], footer)
        self.assertIn("Built with Llama", csv["footer"])
        credits = CREDITS.read_text(encoding="utf-8")
        yeo = re.search(r"- \*\*Paper:\*\* (.+)", credits[credits.index("### Yeo-7 networks"):]).group(1).strip()
        self.assertEqual(csv["yeo"], yeo)
        self.assertIn("doi:10.1152/jn.00338.2011", csv["yeo"])

    def test_planted_word_is_caught(self):
        with self.assertRaises(R.RenderError):
            R.check_authored([("planted", "This reel will go viral")])
        with self.assertRaises(R.RenderError):
            R.check_authored([("planted", "42,000 plays and a high peak at 0:12")])


class TestCode(unittest.TestCase):
    def test_code_literals_clean(self):
        bad = []
        n = 0
        for p, rel in web_files():
            if p.suffix not in CODE_EXT or rel.endswith(".gen.ts"):
                continue
            for lit in code_literals(p.read_text(encoding="utf-8", errors="replace")):
                n += 1
                hits = R.find_banned(lit)
                if hits or EM_DASH in lit:
                    bad.append(f"{rel}: {sorted(set(hits)) or 'em dash'} in {lit[:60]!r}")
        self.assertGreater(n, 100)
        self.assertEqual(bad, [])

    def test_literal_scanner_finds_strings(self):
        src = 'const a = "plain"; // "commented views"\nconst b = `tpl ${x}`; /* "viral" */ const c = \'one\';'
        self.assertEqual(list(code_literals(src)), ["plain", "tpl ${x}", "one"])


class TestFiles(unittest.TestCase):
    def test_schema_copies_match(self):
        src = PROJECT_ROOT / "strategist" / "hosted_schema"
        self.assertEqual(sorted(p.name for p in src.glob("*.schema.json")), sorted(f"{k}.schema.json" for k in KINDS))
        self.assertTrue((WEB / "contracts" / "brain-assets.json").is_file())
        for s in sorted(src.glob("*.schema.json")):
            copy = WEB / "contracts" / "hosted_schema" / s.name
            self.assertTrue(copy.is_file(), f"missing {copy.name}: run npm run gen:hosted in web/")
            self.assertEqual(copy.read_bytes(), s.read_bytes(), f"{s.name} is stale: run npm run gen:hosted in web/")

    def test_no_leaks(self):
        handles = real_handles()
        handle_res = [(h, re.compile(r"(?<![A-Za-z0-9._])@?" + re.escape(h) + r"(?![A-Za-z0-9_])", re.IGNORECASE))
                      for h in handles]
        secrets = env_values()
        found = []
        for p, rel in web_files():
            if p.suffix.lower() in BINARY_EXT or p.name.startswith(".env"):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if rel not in RULE_FILES:
                found += [f"{rel}: {what}" for what, rx in LEAK_RES if rx.search(text)]
            found += [f"{rel}: real handle {h}" for h, rx in handle_res if rx.search(text)]
            found += [f"{rel}: the value of .env key {k}" for k, v in secrets if v in text]
        self.assertEqual(found, [])

    def test_leak_patterns_catch_plants(self):
        plants = ["C:\\Users\\someone\\x", "C:/Users/someone", "C:\\\\Users\\\\x", "OneDrive/Desktop", "swipe/reels/X/private/a"]
        for plant in plants:
            self.assertTrue(any(rx.search(plant) for _, rx in LEAK_RES), plant)
        self.assertFalse(any(rx.search("privately, a private note") for _, rx in LEAK_RES))

    def test_fixtures_have_no_real_handles(self):
        handles = real_handles()
        if not handles:
            self.skipTest("no swipe/creators on this machine")
        text = "\n".join(p.read_text(encoding="utf-8").lower() for p in (WEB / "fixtures").rglob("*.json"))
        self.assertEqual([h for h in handles if h in text], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
