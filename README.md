# corvus-regex-ecma262 for Python

Regular expressions with the grammar and the answers of ECMA-262, the `RegExp` of JavaScript, for Python: the
[corvus-regex-ecma262](https://github.com/corvus-dotnet/corvus-regex-ecma262-rs) Rust crate, as a typed package with
wheels for Linux (glibc and musl), macOS and Windows, x64 and arm64, for every Python from 3.10.

- Every flag: `d`, `g`, `i`, `m`, `s`, `u`, `v` and `y`, with the grammar of each. Without `u` or `v` a pattern is
  read by the Annex B grammar and matched by UTF-16 code unit, as ECMA-262 matches it; with them, by code point. The
  `v` flag has nested classes, the difference and the intersection of classes, strings in a class and the properties
  of strings.
- ECMAScript 2025: lookbehind, named groups (and a name shared between alternatives), modifier groups such as
  `(?i:...)`, and every Unicode property ECMA-262 lists, from Unicode 17 tables the crate carries.
- `str` and `bytes` (UTF-8). A pattern answers as it does in a browser or Node, which Python's `re` does not: `\d`,
  `\w`, `\b`, `.` and `$`, case folding, `\p{...}` and the rest read as JavaScript reads them.
- Every match runs without the GIL. A pattern without a backreference is matched in time proportional to its size times
  the text, and `test` and `search` take a timeout, so neither a pattern nor a text from outside can make a program hang.

**Compliance.** Over the [ECMA-262 test data](https://github.com/corvus-dotnet/ecma262-regex-test-data) (what V8 says
about 117,889 patterns and 5,883,170 texts, `exec`, the global search, `replace` and `split` among them, and the
patterns and texts of test262, judged by test262's Unicode 17 answers where V8 has Unicode 16), through this package
over `str` and over `bytes`, it gives 26,892,331 right answers and none wrong, refuses no valid pattern, accepts no
invalid one and reaches no limit. CI runs the whole data on Linux and Windows on every change. (The data
asks 21,482 more questions, each a search that starts between the two halves of a character beyond the Basic
Multilingual Plane, which a `str` position cannot name; the crate answers them all over UTF-16.)

## Install

```
pip install corvus-regex-ecma262
```

## Getting started

```python
import corvus_regex_ecma262 as ecma

# The flags are those of new RegExp(pattern, flags).
date = ecma.compile(r"(?<year>\d{4})-(?<month>\d{2})", "gu")

date.test("due 2026-10")                               # True
m = date.search("due 2026-10")
m["year"], m.span(), m.groupdict()                     # '2026', (4, 11), {'year': '2026', 'month': '10'}

# Every match of a global search, as matchAll makes it.
[m.group() for m in date.finditer("2026-10, 2027-01")]  # ['2026-10', '2027-01']

# replace replaces every match with the g flag, and the first without it; a function may give each replacement.
date.replace("2026-10, 2027-01", "$<month>/$1")        # '10/2026, 01/2027'
date.replace("2026-10", lambda m: m["month"])          # '10'

# split splices in what the groups captured; a group that did not take part is None.
ecma.compile(r"\s*(;)\s*").split("a ; b;c")            # ['a', ';', 'b', ';', 'c']
```

## The API

| | |
|---|---|
| `compile(pattern, flags="")`, `Regex(pattern, flags="")` | Compiles a pattern as `new RegExp(pattern, flags)` does; raises `error` when it is not valid. |
| `is_valid(pattern, flags="")` | Whether a pattern is valid, without compiling it. |
| `Regex.test(string, pos=0, *, timeout=None)` | `RegExp.prototype.test` with `lastIndex` at `pos` (at `pos` alone with `y`). |
| `Regex.search(string, pos=0, *, timeout=None)` | The first match at or after `pos`, as `exec` finds it: a `Match`, or `None`. |
| `Regex.finditer(string)` | A global search as `matchAll` makes it: an iterator of `Match`. |
| `Regex.replace(string, replacement)` | `String.prototype.replace`: the first match, or every match with `g`; the replacement is a template or a function of the `Match`. |
| `Regex.replace_all(string, replacement)` | `String.prototype.replaceAll`: every match. |
| `Regex.split(string, limit=None)` | `String.prototype.split`: a list of strings, `None` for a group that did not take part. |
| `Regex.pattern`, `.flags`, `.groups`, `.group_names` | What the pattern is. |

A `Match` is read as an `re.Match` is: `group(*groups)`, `m[g]`, `groups(default)`, `groupdict(default)`, `start(g)`,
`end(g)`, `span(g)` (a group that did not take part is `None`, at -1), `string` and `re`; a group is a number or a name.

**Positions.** Over a `str` positions are code points, as Python indexes it; over `bytes` they are bytes of UTF-8.
Without `u` or `v` a pattern is matched by UTF-16 code unit, so a match can take half of a character beyond the Basic
Multilingual Plane, as in JavaScript: over a `str` its text holds that half as a lone surrogate, as a JavaScript
string would, and its start and end are the whole character's; over `bytes` the position between the halves is the
character's third byte. A `str` may hold lone surrogates; a lone surrogate written into a pattern is read as U+FFFD
(write it as the escape `\ud800` to match one).

**Errors.** `error` (a `ValueError`) says why a pattern did not compile in its message and in `kind`: `"pattern"`,
`"flags"` or `"too_large"`. A match that reaches its timeout, or its cap on backtracking memory, raises
`MatchLimitError`, a kind of `error`.

**Threads.** A `Regex` is immutable and may be used from any number of threads; matching releases the GIL.

## Benchmarks

The Industry workloads of dotnet/performance, this package against Python's `re`, the `regex` package and V8, are on
the central page, [corvus-oss.org/corvus-regex-ecma262-benchmarks](https://corvus-oss.org/corvus-regex-ecma262-benchmarks/),
measured nightly on one runner with every other Corvus ECMA-262 engine.

## Repository

- `src/lib.rs`: the binding (PyO3, abi3); `python/corvus_regex_ecma262`: the package and its type stubs.
- `tests/`: the tests; `tools/dataset.py`: the test-data runner (`python tools/dataset.py <data> wrong.tsv`).
- `tools/bench`: the benchmark harness and the script the image runs; `Dockerfile`: the image the central page runs.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
