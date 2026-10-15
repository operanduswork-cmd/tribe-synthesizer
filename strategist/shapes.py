"""Shape vocabulary: hook shapes, caption openers, formats, CTA types and beat kinds.

Shape only, never words. Every slot line here is written fresh with [brackets]
for the parts a draft fills in; none of it is a creator's phrasing (the copy
check in strategist/test_patterns.py runs every slot against the competitor
corpus). Ids show on pages through label() ("off-camera-question-number-answer"
reads "off-camera question → number answer"), so ids and labels carry no count
words (plays, likes, comments, followers) and no predicted-response words (brain,
response, peak, flat, high, low, seeing, hearing, language, attention).

Families come from VAULT (read-only), cited by file and line:
    research/PATTERNS.md   §3 hook formula table (lines 52-63), abstract shapes
                           (lines 67-74), structures (lines 76-89), CTAs (lines 91-101),
                           fresh formulas (line 188), hook shapes to try (lines 221-242)
    research/repurpose/README.md   teardown template (hook line 27, beats line 25),
                           format map (lines 54-58)
    research/repurpose/2026-10-07-ig-demo_creator_a-tribe-v2-hook-testing.md   (demo teardown)
    research/repurpose/2026-09-29-ig-demo_creator_b-codex-dm-flows.md          (demo_creator_b teardown)
    research/repurpose/2026-09-29-ig-demo_creator_c-reel-DZU7BVIxEG3.md          (demo_creator_c teardown)
The teardowns are evidence, not instructions: only their shape notes were used.

Standard library only.
"""

from __future__ import annotations

import math
import re

from .store import OVER_S

# ---------------------------------------------------------------- families

FAMILIES = {
    "big-number": ("Big Number / Outcome", "PATTERNS.md line 55"),
    "i-built": ("I built / I just", "PATTERNS.md line 56"),
    "replacement": ("R.I.P. / Replacement", "PATTERNS.md line 57"),
    "contrarian": ("NEVER / Contrarian", "PATTERNS.md line 58"),
    "hours-giveaway": ("After X hours + giveaway", "PATTERNS.md line 59"),
    "authority-drop": ("Authority drop", "PATTERNS.md line 60"),
    "tool-equation": ("Tool stack / equation", "PATTERNS.md line 61"),
    "news": ("News / new capability", "PATTERNS.md line 62"),
    "question": ("Irony / confession / question", "PATTERNS.md line 63"),
    "underuse": ("Most people / underuse", "PATTERNS.md line 71"),
    "fresh": ("Confession, mistake, irony, challenge", "PATTERNS.md line 188 (its 'fresh formulas')"),
    "story": ("Story", "PATTERNS.md lines 88, 239"),
    "before-after": ("Before / after", "PATTERNS.md line 240"),
    "keyword-gate": ("Comment keyword gate", "PATTERNS.md lines 29-30, 94"),
    "how-to": ("How-to / tutorial", "repurpose/README.md line 57"),
    "tease": ("Tease / open loop", "demo_creator_c teardown line 26"),
    "length": ("Length", "post data (caption word count, videoDuration)"),
    "other": ("Other", "no family yet"),
}

# ---------------------------------------------------------------- spoken hook shapes (first 1 to 3 s)
# id: (family, slot, source). The first 15 rows are PATTERNS.md families written as
# slots; the last 3 come from the shape notes in VAULT's three reel teardowns.

HOOK_SHAPES = {
    "number-plus-timeframe": ("big-number", "[Big outcome number] + [timeframe or volume]",
                              "PATTERNS.md line 69"),
    "price-and-time-contrast": ("big-number", "[What others quote: a price and weeks] / [what it took here: minutes]",
                                "PATTERNS.md line 70"),
    "dataset-finding": ("big-number", "We went through [N] [items]. [The one thing that kept showing up]",
                        "PATTERNS.md line 74"),
    "i-built-inventory": ("i-built", "I built [N] [tools or agents] for one [business outcome]",
                          "PATTERNS.md line 73"),
    "expensive-to-cheap-swap": ("replacement", "[Costly person or team] → [cheap AI version], a price on each side",
                                "PATTERNS.md line 68"),
    "never-until": ("contrarian", "Never [common move] until [condition is met]", "PATTERNS.md line 236"),
    "underuse-shame": ("underuse", "Most [role] use [tool] for [one small job]. [How small a share that is]",
                       "PATTERNS.md line 71"),
    "hours-then-giveaway": ("hours-giveaway", "After [N hours] on [task], [the free asset on offer]",
                            "PATTERNS.md line 59"),
    "authority-drop": ("authority-drop", "[Known lab or company] shared [internal thing]. [What it shows]",
                       "PATTERNS.md line 60"),
    "tool-equation": ("tool-equation", "[Tool] + [tool] = [outcome]", "PATTERNS.md line 61"),
    "news-capability": ("news", "[Known company] just shipped [capability]. [What it means for the viewer]",
                        "PATTERNS.md line 62"),
    "direct-question": ("question", "[A question the viewer has asked themselves]?", "PATTERNS.md line 63"),
    "receipt-irony": ("fresh", "[Client type] paid for [thing]. The record shows [zero] [events]",
                      "PATTERNS.md line 228"),
    "all-clear-confession": ("fresh", "[System] said [all clear] for [time]. [Unexpected person] spotted it",
                             "PATTERNS.md line 227"),
    "head-to-head-trap": ("fresh", "[Cheap option] and [pricey option] got the same [trap]. [Which one caught it]",
                          "PATTERNS.md line 233"),
    "villain-story-open": ("story", "[Place or person that owned my time]. [One concrete detail]. Then I [left]",
                           "PATTERNS.md line 239"),
    "before-after-switch": ("before-after", "[Time] ago, [people] did [task] by hand. Now [the new way]",
                            "PATTERNS.md line 240"),
    "off-camera-question-number-answer": (
        "big-number", "[Off-camera voice asks the creator a question] → [one big number as the answer] → "
                      "[follow-up: what would you do now]",
        "demo teardown lines 11-12, 22, 32"),
    "secret-claim-then-screen": ("underuse", "Most [people] miss one thing [tool] can do → [cut to the screen doing it]",
                                 "demo_creator_b teardown lines 9-10, 16, 26"),
    "cold-open-before-confession": ("fresh", "[Off-camera check-in before a confession] → [the confession lands later]",
                                    "demo_creator_c teardown lines 9, 17, 26"),
}

# ---------------------------------------------------------------- caption openers (caption line 1)
# Classified from the public caption's first line, so every reel in a creator's pull
# has one (the normal reels too). Checked in this order; the first match wins.

_GATE_LEAD_RE = re.compile(r"^\s*(?:comment|dm|message)\b", re.IGNORECASE)
_FIRST_PERSON_RE = re.compile(r"(?<![A-Za-z])(?:i|i['’]m|i['’]ve|i['’]d|i['’]ll|my|me|myself)(?![A-Za-z])",
                              re.IGNORECASE)
_VERSUS_RE = re.compile(r"(?<![A-Za-z])(?:vs\.?|versus)(?![A-Za-z])", re.IGNORECASE)
_NEWS_RE = re.compile(r"\bjust\s+(?:opened|launched|released|dropped|shipped|announced|added)\b"
                      r"|\b(?:launches|launched|releases|released|announces|announced)\b", re.IGNORECASE)
_NUMBER_LEAD_RE = re.compile(r"^\s*[$£€]?\d")
_MOST_LEAD_RE = re.compile(r"^\s*(?:most|everyone|everybody|nobody|no one)\b", re.IGNORECASE)
_HOW_TO_RE = re.compile(r"^\s*(?:how\s+to|here['’]?s\s+how)\b", re.IGNORECASE)
_TEASE_RE = re.compile(r"\b(?:ending|wait\s+for\s+it|till\s+the\s+end|until\s+the\s+end|watch\s+till)\b",
                       re.IGNORECASE)
_STORY_LEAD_RE = re.compile(r"^\s*(?:been|working\s+on|just\s+my)\b", re.IGNORECASE)

CAPTION_OPENERS = {
    # id: (label, family, slot, source)
    "keyword-gate-first": ("keyword gate", "keyword-gate",
                           "Line 1 is the ask: comment [keyword] to get [asset]", "PATTERNS.md lines 29-30, 100"),
    "comment-prompt-first": ("reply prompt", "question",
                             "Line 1 asks for a reply about [the viewer's own work]", "PATTERNS.md lines 152-155"),
    "tool-versus-tool": ("tool vs tool", "tool-equation", "[Tool] vs [tool]: which one for [job]",
                         "PATTERNS.md line 61"),
    "news-just-shipped": ("news line", "news", "[Company] just shipped [capability]", "PATTERNS.md line 62"),
    "question-first-person": ("the viewer's own question", "question",
                              "[The viewer's question in their own voice: how do I / do I need]?", "PATTERNS.md line 63"),
    "question-to-viewer": ("question to the viewer", "question", "[Question put to the viewer]?",
                           "PATTERNS.md line 63"),
    "number-first": ("number first", "big-number", "[Number] + [what it counts] in line 1", "PATTERNS.md line 55"),
    "most-people-claim": ("most-people claim", "underuse", "Most [people or advice] do [X]. [The flip]",
                          "PATTERNS.md line 71"),
    "how-to-title": ("how-to title", "how-to", "How to [do a job with a tool]", "repurpose/README.md line 57"),
    "end-tease": ("tease for the ending", "tease", "[Line telling the viewer to stay for the ending]",
                  "caption data (no VAULT family yet)"),
    "first-person-statement": ("first-person line", "story", "[First-person line about my own work or year]",
                               "PATTERNS.md line 88"),
    "short-label": ("short label", "other", "[A few words naming the topic, no sentence]", "caption data"),
    "statement": ("plain statement", "other", "[A plain statement about the topic]", "caption data"),
}
SHORT_LABEL_WORDS = 6


def caption_opener(first_line: str) -> str:
    """The caption-opener id for a caption's first line (shape, never its words)."""
    from .reel import CTA_PATTERNS   # one CTA vocabulary for facts, captions and patterns
    line = (first_line or "").strip()
    if not line:
        return "short-label"
    gates = [rx for kind, rx in CTA_PATTERNS if kind in ("comment-keyword", "dm-keyword")]
    if _GATE_LEAD_RE.match(line):
        return "keyword-gate-first" if any(rx.search(line) for rx in gates) else "comment-prompt-first"
    if _VERSUS_RE.search(line):
        return "tool-versus-tool"
    if _NEWS_RE.search(line):
        return "news-just-shipped"
    if "?" in line:
        return "question-first-person" if _FIRST_PERSON_RE.search(line) else "question-to-viewer"
    if _NUMBER_LEAD_RE.match(line):
        return "number-first"
    if _MOST_LEAD_RE.match(line):
        return "most-people-claim"
    if _HOW_TO_RE.match(line):
        return "how-to-title"
    if _TEASE_RE.search(line):
        return "end-tease"
    if _STORY_LEAD_RE.match(line) or _FIRST_PERSON_RE.search(line):
        return "first-person-statement"
    if len(line.split()) <= SHORT_LABEL_WORDS and not re.search(r"[.!]\s*\S", line):
        return "short-label"
    return "statement"


# ---------------------------------------------------------------- length buckets (post data)

CAPTION_LENGTHS = (  # id, label, min words, max words (inclusive)
    ("caption-short", "caption of 12 words or fewer", 0, 12),
    ("caption-medium", "caption of 13 to 60 words", 13, 60),
    ("caption-long", "caption over 60 words", 61, math.inf),
)
# "Over 60 s" is one cut-off everywhere (store.OVER_S: the over_60s flag, this bucket, the board filter).
REEL_LENGTHS = (  # id, label, from s, to s: under 30 s, then 30 s up to and including 60 s, then over 60 s
    ("length-under-30s", "reel under 30 s", 0, 30),
    ("length-30-60s", "reel of 30 to 60 s", 30, OVER_S),
    ("length-over-60s", "reel over 60 s", OVER_S, math.inf),
)


def caption_length(caption: str) -> str:
    n = len((caption or "").split())
    return next(i for i, _, lo, hi in CAPTION_LENGTHS if lo <= n <= hi)


def reel_length(seconds) -> str | None:
    """The length bucket; 'over 60 s' means more than OVER_S, as the over_60s flag does."""
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds <= 0:
        return None
    return "length-under-30s" if seconds < 30 else "length-30-60s" if seconds <= OVER_S else "length-over-60s"


LENGTH_LABELS = {i: label for i, label, _, _ in CAPTION_LENGTHS + REEL_LENGTHS}

# ---------------------------------------------------------------- formats (repurpose/README.md lines 54-58)

FORMATS = {
    # id: (slot, source)
    "talking-head": ("Face to camera the whole way", "repurpose/README.md line 56"),
    "talking-head-screen-demo": ("Face to camera, then a cut to the screen doing the job",
                                 "demo_creator_b teardown lines 49-50; repurpose/README.md line 57"),
    "talking-head-graphics": ("Face to camera with motion graphics cut in between lines", "demo teardown line 50"),
    "screen-demo": ("Screen recording with a voice over, no face", "repurpose/README.md line 57"),
    "b-roll-voiceover": ("Voice over footage, no face to camera", "common reel format (no VAULT example yet)"),
    "text-on-screen": ("Text on screen carries it, little or no speech", "common reel format (no VAULT example yet)"),
    "skit": ("A scripted scene or parody with the product inside it", "demo_creator_c teardown line 25"),
    "interview": ("Two voices, question and answer on camera", "demo teardown line 11"),
    "meme": ("A meme format with a caption on top", "repurpose/README.md line 58"),
}

# ---------------------------------------------------------------- CTA types
# Ids match strategist/reel.py CTA_PATTERNS (facts.cta.type) plus "end-card" and "none".

CTA_TYPES = {
    # id: (label, slot, source)
    "comment-keyword": ("comment keyword gate", "Comment [keyword] to get [asset]", "PATTERNS.md lines 29-30, 94"),
    "dm-keyword": ("DM keyword gate", "Send [keyword] by DM to get [asset]", "PATTERNS.md line 94"),
    "link-in-bio": ("link in bio", "The [asset] sits behind the link in the bio", "PATTERNS.md line 95"),
    "link": ("link in the caption", "A link in the caption to [page]", "PATTERNS.md line 95"),
    "follow": ("follow ask", "Follow for [more of this topic]", "strategist/reel.py CTA_PATTERNS"),
    "save": ("save ask", "Save this for [when you need it]", "strategist/reel.py CTA_PATTERNS"),
    "comment": ("reply question", "A question the viewer can answer below", "PATTERNS.md line 96"),
    "share": ("share ask", "Send this to [someone who needs it]", "PATTERNS.md line 98 (other / repost)"),
    "end-card": ("end card", "A closing card with [offer] and [where to get it]", "demo_creator_c teardown lines 16, 32"),
    "none": ("no ask", "No ask at the end", "PATTERNS.md line 97"),
}

# ---------------------------------------------------------------- beat kinds (PATTERNS.md lines 76-89)

BEAT_KINDS = {
    "hook": "the first 1 to 3 s and the line that holds them (repurpose/README.md line 27)",
    "setup": "names the topic, the tool or the pain (PATTERNS.md line 80)",
    "proof": "a claim made believable: a number, a screen, a credential (PATTERNS.md lines 107-114)",
    "demo": "the thing shown working, or the method in steps (PATTERNS.md line 82)",
    "payoff": "the result, the turn or the twist (PATTERNS.md lines 81, 88)",
    "cta": "the ask (PATTERNS.md lines 91-101)",
}

KIND_LABELS = {"hook": "Hook", "structure": "Structure", "cta": "CTA", "format": "Format"}


# ---------------------------------------------------------------- helpers

# How hook shapes and formats read on a page (cards, board, patterns, lab). An id not listed
# here reads with its hyphens as spaces. No count word and no predicted-response word.
LABELS = {
    "number-plus-timeframe": "number + timeframe",
    "price-and-time-contrast": "price and time contrast",
    "dataset-finding": "dataset finding",
    "i-built-inventory": "I built N things",
    "expensive-to-cheap-swap": "expensive → cheap swap",
    "never-until": "never … until",
    "underuse-shame": "most people underuse it",
    "hours-then-giveaway": "hours of work → giveaway",
    "authority-drop": "authority drop",
    "tool-equation": "tool + tool = outcome",
    "news-capability": "news: new capability",
    "direct-question": "direct question",
    "receipt-irony": "receipt irony",
    "all-clear-confession": "all-clear confession",
    "head-to-head-trap": "head-to-head trap",
    "villain-story-open": "villain story open",
    "before-after-switch": "before → after switch",
    "off-camera-question-number-answer": "off-camera question → number answer",
    "secret-claim-then-screen": "secret claim → screen",
    "cold-open-before-confession": "cold open → confession",
    "talking-head": "talking head",
    "talking-head-screen-demo": "talking head → screen demo",
    "talking-head-graphics": "talking head + graphics",
    "screen-demo": "screen demo",
    "b-roll-voiceover": "b-roll + voice over",
    "text-on-screen": "text on screen",
}


def label(shape_id: str) -> str:
    """How an id reads on a page: its readable label, else hyphens between words become spaces."""
    if str(shape_id) in LABELS:
        return LABELS[str(shape_id)]
    return re.sub(r"[_\s]+", " ", re.sub(r"(?<=\w)-(?=\w)", " ", str(shape_id))).strip()


def family_label(family: str) -> str:
    return FAMILIES.get(family, FAMILIES["other"])[0]


def structure_kinds(beats) -> list[str]:
    """Beat kinds in order, repeats next to each other merged (setup, setup -> setup)."""
    out = []
    for b in beats or []:
        k = str((b or {}).get("kind") or "").strip()
        if k and (not out or out[-1] != k):
            out.append(k)
    return out


def structure_id(beats) -> str:
    return "-".join(structure_kinds(beats))


def structure_slot(beats) -> str:
    return " → ".join(f"[{k}]" for k in structure_kinds(beats))


def check_shape(field: str, value: str) -> None:
    """Refuse a shape value outside this vocabulary (so patterns group like with like)."""
    known = {"hook_shape": HOOK_SHAPES, "format": FORMATS, "cta": CTA_TYPES}.get(field)
    if known is not None and value not in known:
        raise ValueError(f"{field} {value!r} is not in strategist/shapes.py (known: {', '.join(sorted(known))})")


def all_texts() -> list[tuple[str, str]]:
    """Every id, label and slot line in the vocabulary, for the rule and copy checks."""
    out = []
    for i, (fam, slot, _) in HOOK_SHAPES.items():
        out += [(f"hook_shape {i}", label(i)), (f"hook_shape {i} slot", slot)]
    for i, (lab, fam, slot, _) in CAPTION_OPENERS.items():
        out += [(f"caption_opener {i}", lab), (f"caption_opener {i} slot", slot)]
    for i, (slot, _) in FORMATS.items():
        out += [(f"format {i}", label(i)), (f"format {i} slot", slot)]
    for i, (lab, slot, _) in CTA_TYPES.items():
        out += [(f"cta {i}", lab), (f"cta {i} slot", slot)]
    for i, lab in LENGTH_LABELS.items():
        out.append((f"length {i}", lab))
    for k, text in BEAT_KINDS.items():
        out.append((f"beat kind {k}", text))
    return out
