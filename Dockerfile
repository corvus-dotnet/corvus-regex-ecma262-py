# The Python benchmark harness as an image: this package built from the repository into a wheel and installed, with the
# regex package at a pinned release, and Node 24 for the V8 rows, with tools/bench/run.sh as the entry point. Built from
# the repository's root:
#
#   docker build -t corvus-regex-ecma262-py .
#   docker run --rm -v <workloads.json>:/workloads.json:ro -v <texts dir>:/texts:ro -v <out dir>:/out <image>
#
# which writes /out/industry.json, the run's data file in the results page's shape. The ECMA-262 test data is cloned
# at depth 1 inside the container unless its data/ directory is mounted at /data. JOB=short, SECONDS_EACH, PASSES,
# CORES, SETTLE and RUN_URL pass through (see tools/bench/run.sh). The central benchmark site runs this image each
# night; .github/workflows/harness-image.yml builds, smoke-runs and publishes it.
FROM node:24.11.0-bookworm-slim AS node

FROM rust:1.98-bookworm AS wheel
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /maturin && /maturin/bin/pip install -q "maturin==1.15.0"
WORKDIR /src
COPY . .
RUN rustup show && /maturin/bin/maturin build --release -j 4 --locked --compatibility linux --out /wheels

FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git util-linux ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=wheel /wheels /wheels
RUN pip install -q --no-cache-dir /wheels/*.whl "regex==2026.9.29"
WORKDIR /harness
COPY tools tools
# The commit the image is built from, for the run's record (the image has no .git).
ARG COMMIT=""
ENV CORVUS_COMMIT=$COMMIT
ENTRYPOINT ["/harness/tools/bench/container-entry.sh"]
