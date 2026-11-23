# Build from the repository root so the shared package is included.
FROM python:3.12-slim AS runtime
# procps provides ps, which Nextflow needs in the container to collect task metrics.
RUN apt-get update && apt-get install -y --no-install-recommends procps && rm -rf /var/lib/apt/lists/*
COPY shared /opt/rddc-screen-common
RUN pip install --no-cache-dir /opt/rddc-screen-common
WORKDIR /opt/rddc-fhir-screen
COPY containers/rddc-fhir-screen/pyproject.toml ./
COPY containers/rddc-fhir-screen/src ./src
RUN pip install --no-cache-dir . && rddc-fhir-screen --version

FROM runtime AS test
COPY containers/rddc-fhir-screen/tests ./tests
RUN pip install --no-cache-dir ".[test]"
CMD ["pytest", "-q", "tests"]
