# Getting started with Python

`corvus-regex-ecma262` is the Rust engine as a typed Python package. Its patterns have the grammar and the answers of
JavaScript's `RegExp`, held to V8's answers on the ECMA-262 test data, over `str`, `bytes` (UTF-8) and arrays of
UTF-16 code units.

## Install

```
pip install corvus-regex-ecma262
```

There are wheels for Linux (glibc and musl), macOS and Windows, on x64 and arm64, for every Python from 3.10.

## Compile a pattern

`compile` takes a pattern and its flags as `new RegExp(pattern, flags)` takes them: `d`, `g`, `i`, `m`, `s`, `u`, `v`
and `y`. Without `u` or `v` a pattern is read by the Annex B grammar and matched by UTF-16 code unit, as ECMA-262 reads
it; with them, by code point. A pattern that is not valid raises `error`, a `ValueError`, whose `kind` says why.

```python
import corvus_regex_ecma262 as ecma

date = ecma.compile(r"(?<year>\d{4})-(?<month>\d{2})", "gu")
assert date.groups == 2 and date.group_names == ["year", "month"]

try:
    ecma.compile("a{2,1}", "u")
except ecma.error as e:
    assert e.kind == "pattern"
else:
    raise AssertionError("a pattern that is not valid was compiled")

assert not ecma.is_valid("a", "uv")
```

## Match

A `Match` reads as an `re.Match` does. Over a `str` positions are code points, as Python indexes it.

```python
import corvus_regex_ecma262 as ecma

date = ecma.compile(r"(?<year>\d{4})-(?<month>\d{2})", "gu")
text = "due 2026-10, then 2027-01"

assert date.test(text)

m = date.search(text)
assert m.group() == "2026-10" and m.span() == (4, 11)
assert m["year"] == "2026" and m.groupdict() == {"year": "2026", "month": "10"}

# Every match of a global search, as matchAll makes it.
assert [m.group() for m in date.finditer(text)] == ["2026-10", "2027-01"]

# replace replaces every match with the g flag, and the first without it, with every $ form of ECMA-262;
# a function may give each replacement.
assert date.replace(text, "$<month>/$1") == "due 10/2026, then 01/2027"
assert date.replace("2026-10", lambda m: m["month"]) == "10"

# split splices in what the groups captured; a group that did not take part is None.
assert ecma.compile(r"\s*(;)\s*").split("a ; b;c") == ["a", ";", "b", ";", "c"]
```

## UTF-8 and UTF-16

Every method takes `bytes` of UTF-8, with positions in bytes, and an `array.array('H')` of UTF-16 code units, with
positions in code units, lone surrogates and all. `bytes` that are not UTF-8 raise `ValueError` before any of them is
read: none is matched, nor read as U+FFFD.

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

## Patterns and texts from outside

A match has no limit by default. A program that matches a pattern or a text it did not write gives the pattern a
match timeout in seconds, as a .NET `Regex` has: a match that runs past it, or whose backtracking memory reaches its
cap, raises `MatchLimitError`. No pattern can overflow the stack. `set_default_timeout` sets the timeout of every
pattern compiled after it, and `test` and `search` take a `timeout=` of their own.

```python
import corvus_regex_ecma262 as ecma

slow = ecma.compile(r"^(?:(a+)\1*)+$", timeout=0.1)
try:
    slow.test("a" * 60 + "b")
except ecma.MatchLimitError:
    pass
else:
    raise AssertionError("the match did not stop at its timeout")
```

## The edition and the version of Unicode

JSON Schema 2020-12 names the grammar of ECMAScript 2020. `edition="es2020"` refuses what later editions added: the
`d` and `v` flags, modifier groups, a group name used twice, and property names outside the 2020 tables.
`unicode_version` chooses the tables apart from it: 13, 17, 18, `"latest"` (18), or None for V8's (17). Both are read
when the pattern is compiled, so a match costs the same whatever they are.

```python
import corvus_regex_ecma262 as ecma

greek = ecma.compile(r"^\p{Script=Greek}+$", "u", timeout=1.0, edition="es2020", unicode_version=13)
assert greek.test("αβγ") and greek.unicode_version == 13

# Vithkuqi is in Unicode 14 and later, so not in Unicode 13.
assert not ecma.is_valid(r"\p{Script=Vithkuqi}", "u", unicode_version=13)
assert ecma.UNICODE_VERSIONS == (13, 17, 18)
```

## Differences from Python's re

- The grammar is ECMA-262's: a group is named `(?<name>...)`, not `(?P<name>...)`, and a backreference to it is
  `\k<name>`. The flags are a string as `RegExp` takes them, and `(?i:...)` groups set them inside a pattern; there
  is no `(?i)` prefix for the whole pattern, no `\A` or `\Z`, and no conditionals.
- `\d` is `[0-9]` and `\w` the 63 ASCII word characters, where `re` makes them Unicode in a `str` pattern; `\s` is
  ECMAScript's white space and line terminators, and `.` excludes LF, CR, U+2028 and U+2029.
- A replacement template writes a group as `$1` or `$<name>`, not `\1` or `\g<name>`, and `$&`, `` $` `` and `$'` are
  the match and the text before and after it.
- `replace` replaces every match only with the `g` flag (or `replace_all`), where `re.sub` replaces every match unless
  given a count.
- `re` has no limit on a match's time. Here a pattern without a backreference is matched in time linear in the text,
  and a pattern from outside should be given a `timeout`, which bounds every match.

## Where next

- [The API reference](api.md), generated from the package's typed stubs.
- [The README](../README.md), with how positions are read without `u` or `v`.
- [The benchmark page](https://corvus-oss.org/corvus-regex-ecma262-benchmarks/), with every engine measured nightly.
