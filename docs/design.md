# corvus-regex-ecma262 for Python: design

An outline of the package as it is: what it offers, how it is built and why, and how it is tested and measured. The
[getting-started page](getting-started.md) shows how to use it.

## 1. What it is

A typed Python package of regular expressions with ECMA-262's grammar and answers (ECMAScript 2025). It is a binding,
through PyO3, to the corvus-regex-ecma262 Rust crate, whose engine it uses as it is; its `Match` reads as an
`re.Match` does.

**Why ECMA-262.** JSON Schema, OpenAPI and many wire formats specify their patterns as ECMAScript regular
expressions. Python's `re` has its own grammar and its own meaning for `\d`, `\w`, `\s`, `.` and case folding, so a
translation to it can never be exact. An engine that reads ECMA-262 directly, held to V8's answers over a large data
set (section 6), needs no translation.

## 2. Public surface

**Names.** `compile`, `is_valid`, `error`, `Regex` and `Match` follow `re` where `re` has the thing: `search`,
`finditer`, and a `Match` with `group`, `groups`, `groupdict`, `start`, `end`, `span`, `string` and `re`. Where
ECMA-262's algorithm differs from `re`'s, the method has the `RegExp` name: `test`, `replace`, `replace_all` and
`split`, so that `re.sub`'s replacement of every match is not mistaken for `String.prototype.replace`'s of the first.

**Flags.** The flags are ECMA-262's, as a string (`"gu"`), and nothing else.

**Edition and Unicode version.** By default a pattern is read with today's grammar (`edition="current"`, ECMAScript
2025) and V8's version of Unicode (`unicode_version=None`, 17 today). Either is overridden when the pattern is
compiled, independently of the other and of the flags: `"es2020"` is the grammar JSON Schema 2020-12 names, and
`unicode_version` is 13, 17, 18 or `"latest"`. Both are
resolved when the pattern is compiled, so a match costs the same whatever they are.

**Errors.** A pattern that does not compile raises `error`, a `ValueError`, whose `kind` is `"pattern"`, `"flags"` or
`"too_large"`, as `re.error` is named. A match that reaches its limit raises `MatchLimitError`, a kind of `error`.
`bytes` that are not UTF-8 raise a plain `ValueError`.

**ECMA-262 algorithms.** `replace` substitutes as `GetSubstitution` does (`$$`, `$&`, `` $` ``, `$'`, `$n`, `$nn`,
`$<name>`), or calls a function with each `Match`. `split` follows `RegExp.prototype[Symbol.split]`.

**Input.** Every method takes a `str` (positions in code points, as Python indexes it), `bytes` of UTF-8 (positions in
bytes) or an `array.array('H')` of UTF-16 code units (positions in code units). The groups, the pieces and the result
of `replace` come back as the input's kind.

**Limits.** No pattern and no text can hang a program or overflow the stack: a match timeout per pattern, or a
process-wide default (`set_default_timeout`), bounds every match and its backtracking memory, and the crate's size
limits (`MAX_PATTERN_LENGTH`, `MAX_NESTING`) are deterministic.

## 3. Engine

The engine is the Rust crate's: its parser, matcher, searches and automata, which
[the crate's design](https://github.com/corvus-dotnet/corvus-regex-ecma262-rs/blob/main/docs/design.md) describes. The
binding's work is between Python and the crate.

**A `str`, matched where it is cheapest and exact.** CPython keeps a `str`'s UTF-8 with the string once made, so the
binding matches that UTF-8, with no copy, when the pattern has the u or v flag or the text has no character beyond the
Basic Multilingual Plane. Without u or v, over a text with such a character, a match can take half of one, so the
binding matches the text's UTF-16 instead; and a `str` holding a lone surrogate, which has no UTF-8, is matched as
UTF-16 too. Either way, positions are turned into code points, going on from the last one asked for, since a search
asks in order; an ASCII text needs no turning.

**`bytes` and code units.** `bytes` are checked to be UTF-8 once, when the match starts, and matched as they are. An
`array.array('H')` is matched as the code units it holds, so a position between the halves of a character, which a
`str` cannot give, is given and taken as it is.

**The GIL.** Every match runs without the GIL, so threads match at once. A `Regex` is immutable and holds the crate's
compiled pattern, shared between threads.

## 4. The package

The wheels use the stable ABI (abi3) from Python 3.10, so one wheel serves every Python on a platform. The package's
type stubs (`_native.pyi`) carry every signature and docstring, and the API reference (`docs/api.md`) is generated from
them by `tools/docs/gen-api.py`, which CI checks is current.

## 5. Targets and layout

Python 3.10 and later. Wheels for Linux (manylinux and musllinux, x86_64 and aarch64), macOS (universal2) and Windows
(x64 and arm64), and an sdist that builds with Rust 1.89 or later.

- `src/lib.rs`: the binding (PyO3).
- `python/corvus_regex_ecma262`: the package and its type stubs.
- `tests/`: the tests, the getting-started page's examples among them; `tools/dataset.py`: the test-data runner.
- `tools/docs`: the API reference's generator; `tools/bench` and `tools/benchmarks`: the benchmark harness;
  `tools/release`: the release scripts.

## 6. Testing

**The ECMA-262 test data.** [`ecma262-regex-test-data`](https://github.com/corvus-dotnet/ecma262-regex-test-data)
holds V8's answers: validity under each grammar, `test` answers, the positions of `exec`, the global search, `y`,
`replace` and `split`, and every `exec` call of test262. `tools/dataset.py` runs all of it through the installed wheel,
over `str`, `bytes` and code units, with none wrong, refused or at a limit: on the Linux x86_64 and Windows x64 wheels on
every change, and on Linux as the data's own scripts write it for Unicode 13 and 18 and for ECMAScript 2020.

**Other tests.** `pytest` over every method, each encoding and the getting-started page's examples, on every wheel
with the oldest and the newest Python it supports.

## 7. Benchmarks

The harness image, `ghcr.io/corvus-dotnet/corvus-regex-ecma262-py`, runs the Industry workloads of
`dotnet/performance` over this package, `re`, the `regex` package and V8. The published figures are on
[the benchmark page](https://corvus-oss.org/corvus-regex-ecma262-benchmarks/), which runs every engine's image each
night; this repository publishes none of its own.

Three rows are not like for like with an engine that is not ECMA-262's, as the price of its rules under u: `.*` (`.`
excludes CR, so the CRLF text has more matches), `Sher[a-z]+|Hol[a-z]+` under i (the search must also find the long s
and the Kelvin sign), and `[a-q][^u-z]{13}x` (a supplementary character is two units, so the distance to the `x` is
not fixed).

## 8. Differences a Python user will meet

- The grammar is ECMA-262's: `(?<name>...)` and `\k<name>`, not `(?P<name>...)`; `(?i:...)` groups but no `(?i)`
  prefix, no `\A`, `\Z` or conditionals. `\d` is `[0-9]` and `\w` the 63 ASCII word characters, where `re` makes them
  Unicode.
- `replace` replaces every match only with the `g` flag; `re.sub` replaces every match unless given a count.
- A template writes a group as `$1` or `$<name>`, not `\1` or `\g<name>`.

The [getting-started page](getting-started.md) has the full list.
