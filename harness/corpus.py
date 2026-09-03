"""Hostile input corpus for differential testing.

Deliberately NOT a happy path. The C-1 defect (two arms agreeing on the digest
algorithm and disagreeing on the bytes) is invisible to every ASCII test, so a
corpus that does not attack the encoder finds nothing.

Non-ASCII is written as \\u escapes, never as literals, so this file survives
tooling that normalises or strips invisible characters. That is not fussiness: a
corpus whose own transport mangles the payload is testing the transport.

Every case is (id, units, why). `why` is printed on divergence so a reader does
not have to reverse-engineer what the case was probing.
"""

NAN = float("nan")
INF = float("inf")

CASES = [
    ("ascii-baseline",  [{"summary": "one unit"}], "control; must agree"),
    # --- the encoder attack surface -------------------------------------
    ("latin1-accent",   [{"summary": "caf\u00e9"}], "ensure_ascii: escape vs raw UTF-8. THIS IS C-1."),
    ("accent-NFC",      [{"s": "caf\u00e9"}], "NFC precomposed U+00E9"),
    ("accent-NFD",      [{"s": "cafe\u0301"}], "NFD decomposed e + U+0301: same grapheme, different codepoints"),
    ("cjk",             [{"summary": "\u65e5\u672c\u8a9e"}], "CJK, 3-byte UTF-8"),
    ("emoji",           [{"summary": "\U0001f600"}], "astral plane, surrogate pair in UTF-16"),
    ("emoji-zwj",       [{"summary": "\U0001f469\u200d\U0001f4bb"}], "ZWJ sequence"),
    ("rtl-arabic",      [{"summary": "\u0645\u0631\u062d\u0628\u0627"}], "RTL script"),
    ("rtl-hebrew",      [{"summary": "\u05e2\u05d1\u05e8\u05d9\u05ea"}], "RTL script"),
    ("bidi-override",   [{"summary": "a\u202eb"}], "bidi override control character"),
    ("bom",             [{"summary": "\ufeffx"}], "byte order mark inside a string"),
    ("smart-quotes",    [{"summary": "\u201cx\u201d"}], "curly quotes; common in real prose"),
    ("lone-surrogate",  [{"summary": "\ud800"}], "unpaired surrogate: legal in a Python str, NOT encodable as UTF-8"),
    ("control-chars",   [{"summary": "a\tb\nc\u0000d"}], "tab, newline, NUL"),
    ("unicode-in-key",  [{"caf\u00e9": 1}], "non-ASCII in the KEY, not the value"),
    # --- structural ------------------------------------------------------
    ("key-order-a",     [{"a": 1, "b": 2}], "insertion order A"),
    ("key-order-b",     [{"b": 2, "a": 1}], "insertion order B; compared against key-order-a"),
    ("empty-units",     [], "F-9's zero clause"),
    ("empty-string",    [{"summary": ""}], "empty value"),
    ("nested",          [{"a": {"b": [1, {"c": "d"}]}}], "nesting"),
    ("null-value",      [{"summary": None}], "JSON null inside units"),
    ("long-field",      [{"summary": "x" * 100000}], "100k field; size and any truncation"),
    ("many-units",      [{"i": i} for i in range(500)], "500 units"),
    # --- number encoding -------------------------------------------------
    ("float-nan",       [{"n": NAN}], "allow_nan default True emits bare NaN (INVALID JSON); allow_nan=False raises"),
    ("float-inf",       [{"n": INF}], "same, Infinity"),
    ("int-vs-float-a",  [{"n": 1}], "int 1"),
    ("int-vs-float-b",  [{"n": 1.0}], "float 1.0; compared against int-vs-float-a"),
    ("big-int",         [{"n": 2 ** 70}], "beyond float64"),
]

#: Digests compared against each other WITHIN one arm, to catch an arm that
#: collapses two payloads that must stay distinct, or separates two that must not.
INTERNAL_PAIRS = [
    ("accent-NFC", "accent-NFD", "distinct", "different codepoints; must not collide"),
    ("key-order-a", "key-order-b", "same", "sort_keys makes insertion order irrelevant"),
    ("int-vs-float-a", "int-vs-float-b", "distinct", "1 and 1.0 encode differently"),
]
