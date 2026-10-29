# Getting started with Python

## Introduction

`corvus-regex-ecma262` is a typed Python package whose patterns answer as ECMAScript does. Where Python's `re` has its
own grammar and its own meaning for `\d`, `\w`, `\s`, `.`, case folding and Unicode properties, this package has
ECMA-262's, so a pattern written for JavaScript, or taken from a JSON Schema, matches the same texts here as it does
there. It is the corvus-regex-ecma262 Rust crate, held to V8's answers on the ECMA-262 test data, and a `Match` reads
as an `re.Match` does.

This guide covers:

- **Setup**: installing the wheel.
- **Patterns and flags**: the flags are ECMA-262's letters, and what each one does.
- **The edition and the version of Unicode**: the grammar of ECMAScript 2020, and the Unicode tables a pattern reads.
- **Matching**: `test`, `search`, `finditer`, `replace` and `split`, as `RegExp` and `String.prototype` define them.
- **Timeouts**: the limit of time and of memory a match may take.
- **UTF-8 and UTF-16**: `str`, `bytes` of UTF-8 and arrays of UTF-16 code units, each with its own positions.
- **Differences from re**: what to expect when the two meet.

## Setup

```
pip install corvus-regex-ecma262
```

There are wheels for Linux (glibc and musl), macOS and Windows, on x64 and arm64, for every Python from 3.10.

```python
import corvus_regex_ecma262 as ecma
```

## Patterns and flags

A pattern is written as it would be in JavaScript, and the flags are the letters `RegExp` takes, as a string:

| Flag | Meaning |
|---|---|
| `d` | Accepted for completeness; indices are always kept. |
| `g` | `replace` replaces every match; without it, the first, as `String.prototype.replace` does. |
| `i` | Canonicalize of the mode in force: simple case folding with `u` or `v`, `toUpperCase` without. Never the locale. |
| `m` | `^` and `$` at line terminators. |
| `s` | The dot matches line terminators. |
| `u` | The `u` flag grammar; matched by code point. |
| `v` | Set notation and properties of strings; matched by code point. `u` and `v` together is an error, as in ECMA-262. |
| `y` | A match only at the start position. |

```python
import corvus_regex_ecma262 as ecma

a = ecma.compile(r"\p{Script=Greek}+", "u")
b = ecma.compile(r"[[a-z]--[aeiou]]+", "v")
c = ecma.compile(r"^(?<year>\d{4})-(?<month>\d{2})$", "u")

assert a.test("αβγ")
assert b.test("rhythm")
assert c.group_names == ["year", "month"]
```

With no flag the pattern is read with the Annex B grammar and matched by UTF-16 code unit, which is what ECMA-262 does
with no flag. JSON Schema's reading, the `u` flag first and Annex B when that refuses, is two compiles, each with the
match timeout, so no default timeout is needed:

```python
import corvus_regex_ecma262 as ecma

def schema_pattern(pattern):
    try:
        return ecma.compile(pattern, "u", timeout=1.0)
    except ecma.error:
        return ecma.compile(pattern, "", timeout=1.0)

assert schema_pattern(r"^\p{L}+$").flags == "u"
assert schema_pattern(r"\-").flags == ""  # an identity escape, which only Annex B allows
```

A pattern that is not valid raises `error`, a `ValueError` whose message says why and whose `kind` is `"pattern"`;
invalid flags are `"flags"`. Every pattern has deterministic limits of size (`MAX_PATTERN_LENGTH`, `MAX_NESTING`), and
`"too_large"` says when one is passed.

```python
import corvus_regex_ecma262 as ecma

try:
    ecma.compile("a{2,1}", "u")
except ecma.error as e:
    assert e.kind == "pattern"
else:
    raise AssertionError("a pattern that is not valid was compiled")

assert not ecma.is_valid("a", "uv")
```

## The edition and the version of Unicode

JSON Schema 2020-12 names the grammar of ECMAScript 2020. `edition="es2020"` refuses what later editions added, and
nothing else: the `d` and `v` flags, modifier groups such as `(?i:...)`, a group name used by two groups, and a
property name or value that is not in the 2020 tables (such as `\p{Script=Yezidi}`). A pattern it accepts has the same
answers as in today's grammar.

The version of Unicode is chosen apart from the edition: `unicode_version` is 13, 17, 18, `"latest"` (18 today) or
None, the version of the V8 the answers are held to (17 today). It decides the members of each `\p{...}`, the
characters of a group name and the case folding of the `i` flag. `Regex.unicode_version` reports the version a pattern
was compiled with. Both are read when the pattern is compiled, so a match costs the same whichever is chosen.

```python
import corvus_regex_ecma262 as ecma

# ECMAScript 2020 as its edition was published, with the Unicode of its year.
greek = ecma.compile(r"^\p{Script=Greek}+$", "u", timeout=1.0, edition="es2020", unicode_version=13)
assert greek.test("αβγ") and greek.unicode_version == 13

# Vithkuqi is in Unicode 14 and later, so not in Unicode 13.
assert not ecma.is_valid(r"\p{Script=Vithkuqi}", "u", unicode_version=13)
assert ecma.UNICODE_VERSIONS == (13, 17, 18)
```

## Matching

The methods are those of a `RegExp`, with the position as an argument where JavaScript keeps `lastIndex`. A `Match`
reads as an `re.Match` does:

```python
import corvus_regex_ecma262 as ecma

date = ecma.compile(r"(?<year>\d{4})-(?<month>\d{2})", "gu")
text = "due 2026-10, then 2027-01"

assert date.test(text)
m = date.search(text)
assert m.group() == "2026-10" and m.span() == (4, 11)
assert m["year"] == "2026" and m[2] == "10" and m.groupdict() == {"year": "2026", "month": "10"}

# Every match of a global search, as matchAll makes it.
assert [m.group() for m in date.finditer(text)] == ["2026-10", "2027-01"]

# replace replaces every match with the g flag, and the first without it, with every $ form of ECMA-262, or a function.
assert date.replace(text, "$<month>/$1") == "due 10/2026, then 01/2027"
assert date.replace(text, lambda m: m["year"]) == "due 2026, then 2027"

# split puts what the groups captured between the pieces; a group that did not take part is None.
assert ecma.compile(r"\s*(;)\s*").split("a ; b;c") == ["a", ";", "b", ";", "c"]
```

`search(string, pos)` is `exec` with `lastIndex` set to `pos`, and `y` anchors it there. `test` makes no `Match`, and
`finditer` makes each match as it is read. A `Regex` is immutable, and safe to share between threads; the matching
runs without the GIL.

## Timeouts

A match has no limit by default. A pattern compiled with `timeout=` (in seconds) abandons a match that reaches it, or
that reaches the cap on backtracking memory the timeout brings, with `MatchLimitError`, whatever the pattern:

```python
import corvus_regex_ecma262 as ecma

slow = ecma.compile(r"^(?:(a+)\1*)+$", timeout=0.1)
assert slow.timeout == 0.1
try:
    slow.test("a" * 60 + "b")
except ecma.MatchLimitError:
    pass
else:
    raise AssertionError("the match did not stop at its timeout")
```

A pattern compiled without a timeout takes `default_timeout()`, which is None (no limit) unless `set_default_timeout`
sets it. A program that matches patterns or texts from outside should set one, for example with
`ecma.set_default_timeout(1.0)` when it starts. `test` and `search` take a `timeout=` of their own for one match.

A pattern without a backreference is matched in time linear in the text, and no pattern can overflow the stack, so the
timeout is what bounds the others.

## UTF-8 and UTF-16

Every method takes a `str`, with positions in code points as Python indexes it; `bytes` of UTF-8, with positions in
bytes; and an `array.array('H')` of UTF-16 code units, lone surrogates and all, with positions in code units. `bytes`
are matched as they are, with no transcoding, and are checked before they are read: `bytes` that are not UTF-8 raise
`ValueError`, and are never matched or read as U+FFFD.

```python
from array import array
import corvus_regex_ecma262 as ecma

dot_b = ecma.compile(".b", "u")
assert dot_b.search("a😀b").span() == (1, 3)                  # code points
assert dot_b.search("a😀b".encode()).span() == (1, 6)         # bytes of UTF-8

units = array("H", "a😀b".encode("utf-16-le"))
assert dot_b.search(units).span() == (1, 4)                   # UTF-16 code units

try:
    dot_b.test(b"\xff")
except ValueError:
    pass
else:
    raise AssertionError("bytes that are not UTF-8 were matched")
```

Under the `u` and `v` flags a character is a code point in every encoding, so a class, a dot or a quantifier takes a
four-byte sequence as one character. With no flag ECMA-262 matches by UTF-16 code unit, so a match can take half of a
character beyond the Basic Multilingual Plane: in a `str` its text holds that half as a lone surrogate, as in
JavaScript, and its start and end are the whole character's; over `bytes` the position between the halves is the
character's third byte.

## Differences from re

The methods follow `RegExp`, and a `Match` reads as `re`'s does; the meaning follows ECMA-262. The differences a user
coming from `re` will meet:

- **The grammar.** A group is named `(?<name>...)`, not `(?P<name>...)`, and a backreference to it is `\k<name>`. No
  `(?i)` inline option (ECMA-262 has `(?i:...)` groups), no `\A` or `\Z`, and no conditionals. The flags are a
  separate string.
- **The character classes.** `\d` is `[0-9]` and `\w` the 63 ASCII word characters, where `re` makes them Unicode in a
  `str` pattern; `\s` is ECMAScript's white space and line terminators, and `.` excludes the four line terminators
  (LF, CR, U+2028, U+2029).
- **Replacement.** A template writes a group as `$1` or `$<name>`, not `\1` or `\g<name>`, and `$&`, `` $` `` and `$'`
  are the match and the text before and after it. `replace` replaces every match only with the `g` flag, and
  `replace_all` always does, where `re.sub` replaces every match unless given a count.
- **Split.** `split` is JavaScript's, which puts what the groups captured between the pieces, as `re.split` does, and
  takes a limit on the number of pieces.
- **Timeouts.** `re` has no limit on a match's time. Here a pattern without a backreference is matched in time linear
  in the text, and a timeout bounds the others.
