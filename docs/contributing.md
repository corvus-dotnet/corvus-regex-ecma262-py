# Contributing

This guide is for someone who wants to build the package, run its tests and gates, and open a pull request. It covers
the tools, the build step by step, the gates every change must pass, and how a pull request is released. The
[design document](design.md) describes what is underneath.

## 1. Tools

| Tool | Needed for | Version |
|---|---|---|
| Rust | The binding | The toolchain `rust-toolchain.toml` pins (1.98.0), which `rustup` installs on first use |
| Python | Everything | 3.10 or later |
| maturin | Building the binding into a virtual environment | Any recent version |
| pytest | The tests | Any recent version |
| Git | The repository and the test data | Any recent version |
| Node.js | The test data for other versions of Unicode and for ECMAScript 2020 | 24 (the V8 it carries is the oracle) |
| PowerShell 7 | The release scripts (`tools/release`) | 7.4 or later |

[uv](https://docs.astral.sh/uv/) makes the virtual environment and installs maturin and pytest into it; `pip` does as
well.

- **Windows:** `winget install Rustlang.Rustup Python.Python.3.13 Git.Git OpenJS.NodeJS.LTS Microsoft.PowerShell`,
  with the Visual Studio Build Tools' C++ workload for the linker.
- **Linux:** `rustup` from [rustup.rs](https://rustup.rs); Python 3, Git and a C compiler from the distribution;
  Node.js 24 from nodejs.org or the NodeSource feed; PowerShell from Microsoft's feed.
- **macOS:** `brew install rustup python git node@24 powershell`, then `rustup-init`, with the Xcode command line
  tools for the linker.

## 2. Getting the sources

```
git clone https://github.com/corvus-dotnet/corvus-regex-ecma262-py.git
git clone https://github.com/corvus-dotnet/ecma262-regex-test-data.git   # beside it: the test data
cd corvus-regex-ecma262-py
```

The test data is the oracle for the engine (design, section 6). It is not vendored; the commands below assume it at
`../ecma262-regex-test-data`.

## 3. Building and testing, step by step

Every command runs from the repository root.

1. **A virtual environment with the binding built into it.**

   ```
   uv venv .venv && . .venv/bin/activate        # .venv\Scripts\activate on Windows
   uv pip install maturin pytest
   maturin develop --uv
   ```

   Run `maturin develop` again after any change to `src/lib.rs`.
2. **Formatted and linted.** `cargo fmt --check` and `cargo clippy --locked --all-targets -- -D warnings` must pass.
3. **The tests.** `python -m pytest -q tests` runs the tests and the getting-started page's examples.
4. **The API reference.** After a change to the type stubs (`python/corvus_regex_ecma262/_native.pyi`), run
   `python tools/docs/gen-api.py`; `python tools/docs/gen-api.py --check` must pass.
5. **The test data.** `python tools/dataset.py ../ecma262-regex-test-data/data wrong-cases.tsv` must report 0 wrong, 0
   refused and 0 at a limit. For the other versions of Unicode and for ECMAScript 2020, write the data with its own
   scripts and run it with the package set to match:

   ```
   node ../ecma262-regex-test-data/unicode.js apply 13.0 /tmp/u13 ../ecma262-regex-test-data/data
   python tools/dataset.py /tmp/u13 wrong-u13.tsv --unicode 13
   node ../ecma262-regex-test-data/edition.js apply /tmp/es2020 "" ../ecma262-regex-test-data/data
   python tools/dataset.py /tmp/es2020 wrong-es2020.tsv --edition es2020
   ```

## 4. The crate and the wheels

The engine is the `corvus-regex-ecma262` crate from crates.io, at the version `Cargo.toml` names; a fix to the engine
is made in [the crate's repository](https://github.com/corvus-dotnet/corvus-regex-ecma262-rs), released, and taken
here by moving that version. `pyproject.toml`, `Cargo.toml` and `__version__` hold `0.0.0` and name one version, which
CI checks; a release writes its own. `wheels.yml` builds every wheel and the sdist, and tests each wheel with the
oldest and the newest Python it supports.

## 5. Benchmarks

`tools/bench/run.sh` is the benchmark harness the image runs (`Dockerfile`), and runs it anywhere; its header lists
what it needs and its settings. The published figures are on
[the benchmark page](https://corvus-oss.org/corvus-regex-ecma262-benchmarks/), which runs this repository's harness
image each night beside every other engine; a run on another machine is comparable with itself, never with the page.

## 6. What a pull request needs

- **The gates of section 3** passing on the change as pushed: formatting and clippy, the tests, the API reference,
  and the test data at 0 wrong in every setting.
- **A fix to the engine's answers in the crate**, with its case in the test data first: the data repository's
  families are built around the faults found, with V8 as the oracle.
- **A failing test first** for a bug in the binding: the test that reproduces it, then the fix.
- **The design document kept current**, describing the package as it is.
- **The type stubs** carrying every name, signature and docstring, since the API reference is generated from them.
- **The getting-started page** kept true: its examples are run by the tests.

### Conventions

- The binding is Rust, formatted by `rustfmt` and clean under clippy at `-D warnings`; the package is plain Python
  with type stubs.
- Nothing is copied that can be read in place: a `str`'s UTF-8, `bytes` and code units are matched where they lie.
- Every match runs without the GIL.

## 7. Releases

Every pull request merged into main releases what it changed, unless it is labelled `no_release`. `auto-release.yml`
runs `tools/release/release.ps1` on the merge: when the package changed since its last tag (`Cargo.toml`,
`Cargo.lock`, `pyproject.toml`, `rust-toolchain.toml`, `src/`, `python/`, or a published document), it makes a GitHub
release tagged `v<version>` with the next patch version, and `pypi-publish.yml` builds, tests and uploads every wheel
and the sdist to PyPI by trusted publishing. A change to the benchmark harness alone is a harness release, which
publishes the harness image. A pull request that needs a minor or major version sets `nextVersion` in
`.github/release.json`; a minor version is a breaking change.

`main` is protected by a ruleset: changes arrive by pull request, and the `CI gate` and `Harness image` checks must be
green on the branch as it will merge.
