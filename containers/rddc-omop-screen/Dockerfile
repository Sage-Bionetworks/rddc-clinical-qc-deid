# Build from the repository root so the shared package is included.
FROM python:3.12-slim AS runtime
COPY shared /opt/rddc-screen-common
RUN pip install --no-cache-dir /opt/rddc-screen-common
WORKDIR /opt/rddc-omop-screen
COPY containers/rddc-omop-screen/pyproject.toml ./
COPY containers/rddc-omop-screen/src ./src
RUN pip install --no-cache-dir . && rddc-omop-screen --version

FROM runtime AS test
COPY containers/rddc-omop-screen/tests ./tests
RUN pip install --no-cache-dir ".[test]"
CMD ["pytest", "-q", "tests"]
