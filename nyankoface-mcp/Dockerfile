ARG PYTHON_IMAGE=python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7
FROM ${PYTHON_IMAGE} AS builder

ENV SOURCE_DATE_EPOCH=1767225600 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY nyankoface_mcp ./nyankoface_mcp
COPY requirements.lock ./
COPY scripts ./scripts
RUN pip install --no-cache-dir build==1.3.0 packaging==26.2 pyproject-hooks==1.2.0 \
        setuptools==80.9.0 wheel==0.45.1 \
    && python scripts/build_distribution.py --out-dir /dist

FROM ${PYTHON_IMAGE}

ARG NYANKOFACE_MCP_VERSION=0.1.0
ARG VCS_REF=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

LABEL org.opencontainers.image.title="NyankoFace MCP" \
      org.opencontainers.image.version="${NYANKOFACE_MCP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="https://github.com/Sunwood-ai-labs/NyankoFace" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
COPY requirements.lock ./
COPY --from=builder /dist/nyankoface_mcp-*.whl /tmp/
RUN pip install --no-cache-dir -r requirements.lock \
    && pip install --no-cache-dir --no-deps /tmp/nyankoface_mcp-*.whl \
    && rm -f /tmp/nyankoface_mcp-*.whl \
    && pip check \
    && test "$(nyankoface-mcp --version)" = "nyankoface-mcp ${NYANKOFACE_MCP_VERSION}"

RUN useradd --create-home --uid 10001 nyankoface \
    && install -d -o nyankoface -g nyankoface /data
USER nyankoface
EXPOSE 8000
CMD ["nyankoface-mcp-server"]
