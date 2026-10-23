#!/usr/bin/env python3
"""The Industry benchmark from Python: each workload counted by each engine, in nanoseconds per count, under the
interleaved protocol every harness of the central benchmark page follows (docs/benchmarks/README.md in
corvus-regex-ecma262-rs), a port of the C harness's driver (tools/c/industry.c there):

    industry.py <workloads.json> [--engines corvus-str,corvus-bytes,re,regex,v8] [--v8 <industry.mjs>]
                [--rounds 3] [--seconds 0.7] [--passes 7] [--spread 0.05] [--filter <substring of the id>]
                [--out <results.json>]

The workloads are the outer loop, each workload's rounds next and the engines innermost, their order turned by one each
round, so that a workload's rounds are seconds apart, as its engines are. Each figure is a child process of its own
(`industry.py --one`, or `node industry.mjs --one` for V8), which warms for two fifths of its seconds, then times
`passes` passes of as many counts as fit the rest and reports their median. A workload's figure for an engine is the
median of its rounds, with the fastest and the slowest round as its spread; a figure whose spread, (slowest - fastest) /
median, is over --spread is listed in the run's facts (spread_over) and on stderr. A figure that does not finish in 30 s
is stopped and recorded as giving no result within 30 s, and is not run in the workload's later rounds.

The engines, each counting every match of a global search as a Python program that wants every match would, with
finditer:
- corvus-str and corvus-bytes: this package with the workload's flags and u, over the text as a str and as UTF-8 bytes;
- re: Python's re, which does not claim ECMA-262, given the pattern as it is with the flags i, m and s;
- regex: the regex package, which does not claim ECMA-262, the same way;
- v8: Node's RegExp (--v8), with gu added.

The texts are those of the reference run, in CORVUS_REGEX_TEXTS (or ~/.local/share/corvus-regex-benchmarks); the run
unzips each once into a directory of its own (CORVUS_REGEX_PLAIN), which the children read. POSIX only: the benchmark
runs on Linux, in the image.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

DEFAULT_ENGINES = ["corvus-str", "corvus-bytes", "re", "regex"]
NOT_ECMA262 = {"re", "regex"}
LABELS = {"corvus-str": "corvus-regex-ecma262 str", "corvus-bytes": "corvus-regex-ecma262 bytes", "re": "re",
          "regex": "regex", "v8": "V8"}


def text_dir() -> str:
    return os.environ.get("CORVUS_REGEX_TEXTS") or os.path.join(os.path.expanduser("~"), ".local", "share",
                                                                 "corvus-regex-benchmarks")


def load_text(file: str) -> str:
    plain = os.environ.get("CORVUS_REGEX_PLAIN")
    if plain:
        path = os.path.join(plain, file.removesuffix(".gz"))
        if os.path.exists(path):
            with open(path, encoding="utf-8", newline="") as f:
                return f.read()
    # newline="": the text exactly as it is. Python's text mode would turn its CRLF line ends into LF, so that every
    # engine here matched another text than V8's (sherlock's .* counted 23,439 where V8 counts 36,491).
    with gzip.open(os.path.join(text_dir(), file), "rt", encoding="utf-8", newline="") as f:
        s = f.read()
    return s.removeprefix("﻿")


def flags_u(flags: str) -> str:
    return flags if ("u" in flags or "v" in flags) else flags + "u"


def measure(seconds: float, passes: int, count):
    """Warms, then times passes: the median, the fastest and the slowest pass in nanoseconds per count, the count, and
    the counts timed."""
    expected = count()
    warm_end = time.perf_counter() + seconds * 0.4
    reps = 0
    while time.perf_counter() < warm_end:
        if count() != expected:
            raise RuntimeError("the count changed")
        reps += 1
    per_pass = max(1, round(reps * 0.6 / passes))
    times = []
    for _ in range(passes):
        t0 = time.perf_counter()
        for _ in range(per_pass):
            count()
        times.append((time.perf_counter() - t0) * 1e9 / per_pass)
    times.sort()
    return times[passes // 2], times[0], times[-1], expected, per_pass * passes


def one(path: str, index: int, engine: str, seconds: float, passes: int) -> dict:
    """One workload on one engine in this process: its figures, or the error."""
    workloads = json.load(open(path, encoding="utf-8"))
    if index >= len(workloads):
        return {"error": f"no workload {index}"}
    w = workloads[index]
    text = load_text(w["file"])
    try:
        if engine in ("corvus-str", "corvus-bytes"):
            import corvus_regex_ecma262 as ecma

            r = ecma.compile(w["pattern"], flags_u(w["flags"]))
            subject = text if engine == "corvus-str" else text.encode()

            def count():
                n = 0
                for _ in r.finditer(subject):
                    n += 1
                return n
        elif engine in ("re", "regex"):
            module = __import__(engine)
            f = 0
            if "i" in w["flags"]:
                f |= module.IGNORECASE
            if "m" in w["flags"]:
                f |= module.MULTILINE
            if "s" in w["flags"]:
                f |= module.DOTALL
            r = module.compile(w["pattern"], f)

            def count():
                n = 0
                for _ in r.finditer(text):
                    n += 1
                return n
        else:
            return {"error": f"unknown engine {engine}"}
        median, low, high, expected, reps = measure(seconds, passes, count)
    except Exception as e:  # a pattern an engine refuses, or a count that changed
        return {"error": f"{type(e).__name__}: {e}"}
    return {"median": round(median, 1), "min": round(low, 1), "max": round(high, 1), "count": expected, "reps": reps}


# A figure stopped at the limit, which the page shows as giving no result within 30 s.
STOPPED = {"error": "did not produce a result within 30 s", "limit": 30}


def figure(exe: list[str], v8: str | None, path: str, index: int, spec: str, seconds: str, passes: str) -> dict:
    """One figure in a child process: the child's line of JSON, or one with the error."""
    engine, _, program = spec.partition("@")
    if engine == "v8":
        cmd = ["node", v8, "--one", path, str(index), seconds, passes]
    elif program:
        cmd = [program, "--one", path, str(index), engine, seconds, passes]
    else:
        cmd = exe + ["--one", path, str(index), engine, seconds, passes]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except subprocess.TimeoutExpired:
        return dict(STOPPED)
    line = out.strip().splitlines()
    if not line:
        return {"error": "the process ended without figures"}
    try:
        return json.loads(line[-1])
    except ValueError:
        return {"error": "the process wrote no figures"}


def first_line(cmd: str) -> str:
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.splitlines()[0].strip()
    except (IndexError, OSError):
        return ""


def field(path: str, prefix: str) -> str:
    try:
        for line in open(path, encoding="utf-8"):
            if line.startswith(prefix):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--one":
        _, _, path, index, engine, seconds, passes = sys.argv
        print(json.dumps(one(path, int(index), engine, float(seconds), int(passes))))
        return 0
    ap = argparse.ArgumentParser()
    ap.add_argument("workloads")
    ap.add_argument("--engines")
    ap.add_argument("--v8")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--seconds", default="0.7")
    ap.add_argument("--passes", default="7")
    ap.add_argument("--spread", type=float, default=0.05)
    ap.add_argument("--filter")
    ap.add_argument("--out")
    args = ap.parse_args()
    engines = args.engines.split(",") if args.engines else DEFAULT_ENGINES + (["v8"] if args.v8 else [])
    workloads = json.load(open(args.workloads, encoding="utf-8"))
    chosen = [k for k, w in enumerate(workloads) if not args.filter or args.filter in w["id"]]

    # The texts unzipped once, for every child.
    plain = tempfile.mkdtemp(prefix="corvus-regex-texts-py-")
    for w in workloads:
        path = os.path.join(plain, w["file"].removesuffix(".gz"))
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(load_text(w["file"]))
    os.environ["CORVUS_REGEX_PLAIN"] = plain
    exe = [sys.executable, os.path.abspath(__file__)]

    figures = {e: {} for e in engines}
    v8_engine = ""
    for c, k in enumerate(chosen):
        for rnd in range(args.rounds):
            for turn in range(len(engines)):
                e = engines[(turn + rnd) % len(engines)]
                # A figure stopped at the limit in an earlier round is not run again.
                if figures[e].get(k, {}).get("line") == STOPPED:
                    continue
                line = figure(exe, args.v8, args.workloads, k, e, args.seconds, args.passes)
                fig = figures[e].setdefault(k, {"each": [], "line": line})
                fig["line"] = line
                if "median" in line:
                    fig["each"].append(line["median"])
                else:
                    print(f"{e:<13} {workloads[k]['id']:<62} {json.dumps(line)}", file=sys.stderr)
                if e == "v8" and line.get("engine"):
                    v8_engine = line["engine"]
        print(f"workload {c + 1} of {len(chosen)} done", file=sys.stderr)
    shutil.rmtree(plain, ignore_errors=True)

    over, differ, results = [], [], {}
    for e in engines:
        rows = {}
        for k in chosen:
            fig = figures[e].get(k, {"each": [], "line": {}})
            line, each = fig["line"], fig["each"]
            wid = workloads[k]["id"]
            if len(each) < args.rounds:
                # A round with no figure (an error, a limit) makes the figure an error.
                rows[wid] = line if "error" in line else {"error": "a round gave no figure"}
                continue
            m, lo, hi = statistics.median(each), min(each), max(each)
            spread = (hi - lo) / m if m > 0 else 0
            if spread > args.spread:
                over.append(f"{e} {wid} {spread * 100:.1f}%")
                print(f"SPREAD {e:<13} {wid:<62} {spread * 100:.1f}% over {args.spread * 100:.1f}%", file=sys.stderr)
            n = line.get("count")
            entry = {"median": round(m, 1), "min": lo, "max": hi, "count": n, "rounds": len(each),
                     "spread": round(spread, 4), "each": each}
            # Without V8 in the run (V8=0), its count as the workloads carry it (v8Count, from the central run).
            if "v8" in figures:
                oracle = figures["v8"].get(k, {}).get("line", {}).get("count")
            else:
                oracle = workloads[k].get("v8Count")
            if oracle is not None and n != oracle and e != "v8":
                differ.append(f"{e} {wid} {n} vs V8 {oracle}")
                print(f"COUNT  {e:<13} {wid:<62} {n} against V8's {oracle}", file=sys.stderr)
                if e in NOT_ECMA262:
                    entry["differs"] = f"{LABELS[e]} {n}, V8 {oracle}"
                else:
                    entry = {"error": f"counted {n} where V8 counts {oracle}"}
            rows[wid] = entry
        results[e] = rows

    import corvus_regex_ecma262

    try:
        import regex as regex_module
        regex_version = getattr(regex_module, "__version__", "")
    except ImportError:
        regex_version = ""
    facts = {
        "cpu": field("/proc/cpuinfo", "model name"),
        "cores": str(os.cpu_count() or ""),
        "affinity": field("/proc/self/status", "Cpus_allowed_list"),
        "os": f"{platform.system()} {platform.release()}",
        "load": first_line("cut -d' ' -f1 /proc/loadavg"),
        "python": f"CPython {platform.python_version()}",
        "commit": os.environ.get("CORVUS_COMMIT") or first_line("git rev-parse HEAD 2>/dev/null"),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seconds": args.seconds,
        "passes": args.passes,
        "runner": os.environ.get("RUNNER_NAME", ""),
        "runner_os": os.environ.get("RUNNER_OS", ""),
        "image": " ".join(x for x in (os.environ.get("ImageOS", ""), os.environ.get("ImageVersion", "")) if x),
        "corvus-regex-ecma262": corvus_regex_ecma262.__version__,
        "re": platform.python_version(),
        "regex": regex_version,
        "rounds": str(args.rounds),
        "protocol": "interleaved",
        "spread_limit": f"{args.spread:g}",
        "spread_over": "; ".join(over),
        "counts_differ": "; ".join(differ),
        "v8": v8_engine,
    }
    data = {"facts": facts, "end": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "results": results}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    else:
        print(json.dumps(data, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
