#!/usr/bin/env python3
"""Writes the data file of the Python package's Industry benchmark run, in the shape of the results page (meta, vocab,
measures, impls, schemas, results), as the C and Rust harnesses write theirs. The central benchmark site
(https://corvus-oss.org/corvus-regex-ecma262-benchmarks/) runs this repository's image each night and builds the one
page of figures from its data file; this repository publishes no results of its own.

Usage: industry-results.py --workloads <workloads.json> --run <harness results json> --out <data file>
                           --compliance-dir <directory of compliance-<engine>.txt> [--run-url <url>]

The run is the output of the harness (tools/bench/industry.py), whose facts are the run's own record
of itself: the processor, the cores it was given, the system, the load when it started, the runner when it is a
GitHub-hosted one, the Python, the engines' versions, the commit, the seconds and passes of each figure, and the
time it ended. V8 runs inside the interleaved run and names its engine. Nothing is typed in: what is not in a record
is not said.

Each engine that claims ECMA-262 carries its compliance over the ECMA-262 test data, from the last line of its
data-set runner: this package's by tools/dataset.py, V8's by tools/benchmarks/v8/dataset.mjs. Python's re and the regex
package do not claim it, and carry "not ECMA-262".
"""
import argparse, json, os, re

ap = argparse.ArgumentParser()
ap.add_argument("--run", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--compliance-dir", required=True)
ap.add_argument("--run-url", default="")
ap.add_argument("--workloads", required=True)
args = ap.parse_args()

run = json.load(open(args.run, encoding="utf-8"))
facts = run["facts"]
v8 = {"engine": facts.get("v8", "V8"), "results": run["results"].get("v8", {})}
workloads = json.load(open(args.workloads, encoding="utf-8"))
ids = [w["id"] for w in workloads]


def compliance(engine, note=None):
    """The counts of a data-set runner's last line of counts. Every answer the engine never gave (a limit, a crash, a
    hang or a worker that gave up) is in `limited`, as the judging rule of the test data counts it: the runner's
    limit and errors."""
    path = os.path.join(args.compliance_dir, f"compliance-{engine}.txt")
    lines = [l for l in open(path, encoding="utf-8").read().splitlines() if l.startswith("records ")]
    if not lines:
        raise SystemExit(f"{path} has no line of counts")
    c = {k: int(v) for k, v in re.findall(r"(right|wrong|refused-valid|accepted-invalid|limit|errors) (\d+)", lines[-1])}
    out = {"right": c["right"], "wrong": c["wrong"], "refused": c["refused-valid"], "acceptedInvalid": c["accepted-invalid"],
           "limited": c.get("limit", 0) + c.get("errors", 0)}
    if note:
        out["note"] = note
    return out


ENGINES = [
    ("corvus-str", "corvus-regex-ecma262 str", "Python", facts.get("corvus-regex-ecma262", ""), compliance("corvus")),
    ("corvus-bytes", "corvus-regex-ecma262 bytes", "Python", facts.get("corvus-regex-ecma262", ""), compliance("corvus")),
    ("re", "re", "Python", facts.get("re", ""), "not ECMA-262"),
    ("regex", "regex", "Python", facts.get("regex", ""), "not ECMA-262"),
]
results = {}
for key, name, _, _, _ in ENGINES:
    rows = run["results"].get(key, {})
    results[name] = {}
    for w in ids:
        r = rows.get(w)
        if r is None:
            continue
        results[name][w] = None if "error" in r else {"time": {"median": r["median"], "min": r["min"], "max": r["max"]}}
v8_name = "V8"
ENGINES.append(("v8", v8_name, "V8", v8["engine"], compliance("v8")))
results[v8_name] = {}
for w in ids:
    r = v8["results"].get(w)
    results[v8_name][w] = {"time": {"median": r["median"], "min": r["min"], "max": r["max"]}} if r and "error" not in r else None
# Where re or regex counts otherwise than V8 (the oracle), the row says so; an ECMA-262 engine that does is an error
# above.
differs = {}
for key in ("re", "regex"):
    for w, r in run["results"].get(key, {}).items():
        if isinstance(r, dict) and "differs" in r:
            differs[w] = "; ".join(x for x in (differs.get(w), r["differs"]) if x)

TEXTS = {"sherlock": "Sherlock Holmes (0.6 M chars)", "leipzig": "Leipzig corpus (16 M chars)", "mariomka": "mariomka (0.05 M chars)",
         "rebar-ru": "OpenSubtitles ru (1.2 M chars)", "rebar-zh": "OpenSubtitles zh (0.3 M chars)"}
runner = " ".join(x for x in (facts.get("runner", ""), facts.get("runner_os", ""), facts.get("image", "")) if x)
host = f"{facts.get('cpu', '')}, {facts.get('os', '')}, {facts.get('cores', '')} cores (affinity {facts.get('affinity', '')}), load {facts.get('load', '')} at the start"
job = (f"interleaved: every workload in turn, each in {facts.get('rounds')} rounds of the engines in turn (their order "
       f"turned each round), each figure a process of its own warmed and timed for {facts.get('seconds')} s "
       f"({facts.get('passes')} passes); a workload's figure is the median of its rounds, the spread its fastest "
       f"and slowest round")
over = facts.get("spread_over", "")
spread = (f"over {float(facts.get('spread_limit', 0)) * 100:.0f}% (slowest - fastest) / median: {over}" if over
          else f"every figure within {float(facts.get('spread_limit', 0)) * 100:.0f}% (slowest - fastest) / median")
runtime = "; ".join(x for x in (facts.get("python", ""), v8["engine"]) if x)
data = {
    "meta": {
        "title": "corvus-regex-ecma262 from Python: the Industry benchmarks",
        "lede": "The Python package over str and bytes beside Python's re, the regex package and V8 over the Industry workloads of dotnet/performance.",
        "repo": "corvus-dotnet/corvus-regex-ecma262-py",
        "commit": facts.get("commit", "")[:7],
        "date": run.get("end") or facts.get("date", ""),
        "start": facts.get("date", ""),
        "runner": runner,
        "host": host,
        "runtime": runtime,
        "job": job,
        "runUrl": args.run_url,
        "runs": int(facts.get("passes") or 0),
        "versions": {name: version for _, name, _, version, _ in ENGINES},
        "facts": [["Host", host]] + ([["Runner", runner]] if runner else []) + [["Runtime", runtime], ["Harness", job]]
                 + [["Spread", spread]]
                 + ([["Counts", "re or regex counts otherwise than V8 on " + str(len(differs)) + " workloads (each says so)"]] if differs else []),
        "method": "<p>Each figure is one count of every match a global search finds over the whole text, with finditer, after an empty match going on one character later. "
                  "This package runs with the workload's flags and u, over the text as a str and as UTF-8 bytes; "
                  "Python's re and the regex package with the pattern as it is and the flags i, m and s; V8 with gu added.</p>",
    },
    "vocab": {
        "impl": "engine", "impls": "engines", "Impls": "Engines",
        "schema": "workload", "schemas": "workloads", "Schema": "Workload", "Schemas": "Workloads",
        "failed": "did not run", "centre": "Median", "spread": "fastest to slowest round",
        "barLegend": "median of the rounds", "whiskerLegend": "whisker: the fastest and the slowest round",
    },
    "measures": {"time": {"label": "Time", "long": "time per count", "parts": ["time"]}},
    "impls": [{"id": name, "name": name, "group": group, "version": version, "compliance": c} for _, name, group, version, c in ENGINES],
    "schemas": [{"name": w, "note": ("counts differ: " + differs[w]) if w in differs else "",
                 "meta": [["text", TEXTS.get(w.split(":")[0], w.split(":")[0])]]} for w in ids],
    "results": results,
}
os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
with open(args.out, "w", encoding="utf-8") as fo:
    json.dump(data, fo, indent=1, ensure_ascii=False)
print(f"wrote {args.out}: {len(ids)} workloads, {len(ENGINES)} engines")
