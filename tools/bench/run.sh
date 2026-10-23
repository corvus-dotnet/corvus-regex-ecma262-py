#!/usr/bin/env bash
# The Python benchmark harness, which the central benchmark site runs each night (as the image, Dockerfile) and anyone
# can run: it works out the compliance of this package and of V8 over the test data, runs every engine over the
# Industry workloads under the interleaved protocol, and writes the run's one data file in the results page's shape.
#
#   tools/bench/run.sh <workloads.json> <texts directory> <out.json> [test data directory]
#
# It needs this package and the regex package installed in the Python on PATH (python3), and Node 24. ROUNDS,
# SECONDS_EACH, PASSES, SPREAD and JOB=short are the protocol's (tools/benchmarks/protocol.sh); CORES runs the harness
# under taskset, SETTLE waits that many seconds before it, RUN_URL names the run, and KEEP copies the run's files to a
# directory.
set -euo pipefail
here="$(cd "$(dirname "$0")/../.." && pwd)"
abs() { mkdir -p "$(dirname "$1")"; echo "$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; }
workloads="$(abs "${1:?workloads.json}")"
texts="$(mkdir -p "${2:?texts directory}" && cd "$2" && pwd)"
out_file="$(abs "${3:?out.json}")"
data="${4:-}"
. "$here/tools/benchmarks/protocol.sh"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
timed() { if [ -n "${CORES:-}" ]; then taskset -c "$CORES" "$@"; else "$@"; fi; }
cd "$here"
if [ -z "$data" ]; then
  git clone --quiet --depth 1 https://github.com/corvus-dotnet/ecma262-regex-test-data "$work/test-data"
  data="$work/test-data/data"
fi
# COUNT_GATE=1 (the harness-image job): every workload counted by this library's engines beside V8, one round of the
# least timing, each count checked against V8's by count-gate.py; nothing else runs.
if [ "${COUNT_GATE:-0}" = 1 ]; then
  export CORVUS_REGEX_TEXTS="$texts"
  python3 tools/bench/industry.py "$workloads" --engines corvus-str,corvus-bytes,v8 --v8 tools/benchmarks/v8/industry.mjs --rounds 1 --seconds 0.01 \
    --passes 1 --out "$work/counts.json" 2> "$work/counts.log" || true
  python3 tools/bench/count-gate.py "$workloads" "$work/counts.json" corvus-str corvus-bytes
  exit $?
fi
python3 tools/dataset.py "$data" "$work/wrong-corvus.tsv" > "$work/compliance-corvus.txt" 2>&1 || true
# V8=0 (the central run, for every image but one): no V8, whose counts the workloads carry (v8Count).
v8=(--v8 tools/benchmarks/v8/industry.mjs)
if [ "${V8:-1}" = 0 ]; then
  v8=()
else
  node tools/benchmarks/v8/dataset.mjs "$data" > "$work/compliance-v8.txt" 2>&1 || true
fi
tail -n 1 "$work"/compliance-*.txt
if [ "${SETTLE:-0}" -gt 0 ]; then
  echo "settling for $SETTLE s"
  sleep "$SETTLE"
fi
export CORVUS_REGEX_TEXTS="$texts"
timed python3 tools/bench/industry.py "$workloads" "${v8[@]}" --rounds "$rounds" \
  --seconds "$seconds" --passes "$passes" --spread "$spread" --out "$work/run.json" 2> "$work/run.log"
grep -E '^(SPREAD|COUNT) ' "$work/run.log" || true
python3 tools/bench/industry-results.py --workloads "$workloads" --run "$work/run.json" --out "$out_file" \
  --compliance-dir "$work" --run-url "${RUN_URL:-}"
if [ -n "${KEEP:-}" ]; then mkdir -p "$KEEP" && cp "$work"/*.json "$work"/*.txt "$work"/*.log "$KEEP"/; fi
