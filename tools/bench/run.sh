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
python3 tools/dataset.py "$data" "$work/wrong-corvus.tsv" > "$work/compliance-corvus.txt" 2>&1 || true
node tools/benchmarks/v8/dataset.mjs "$data" > "$work/compliance-v8.txt" 2>&1 || true
tail -n 1 "$work"/compliance-*.txt
if [ "${SETTLE:-0}" -gt 0 ]; then
  echo "settling for $SETTLE s"
  sleep "$SETTLE"
fi
export CORVUS_REGEX_TEXTS="$texts"
timed python3 tools/bench/industry.py "$workloads" --v8 tools/benchmarks/v8/industry.mjs --rounds "$rounds" \
  --seconds "$seconds" --passes "$passes" --spread "$spread" --out "$work/run.json" 2> "$work/run.log"
grep -E '^(SPREAD|COUNT) ' "$work/run.log" || true
python3 tools/bench/industry-results.py --workloads "$workloads" --run "$work/run.json" --out "$out_file" \
  --compliance-dir "$work" --run-url "${RUN_URL:-}"
if [ -n "${KEEP:-}" ]; then mkdir -p "$KEEP" && cp "$work"/*.json "$work"/*.txt "$work"/*.log "$KEEP"/; fi
