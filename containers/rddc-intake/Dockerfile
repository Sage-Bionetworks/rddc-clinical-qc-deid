# Shared checksum tools. Build from the repository root.
FROM debian:bookworm-slim
# procps provides ps, which Nextflow needs in the container to collect task metrics
# (-with-trace, reports).
RUN apt-get update && apt-get install -y --no-install-recommends procps && rm -rf /var/lib/apt/lists/*
RUN command -v md5sum && command -v sha256sum && command -v ps
