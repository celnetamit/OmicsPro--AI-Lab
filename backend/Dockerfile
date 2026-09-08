# The API image. The scientific runtimes (Scanpy, leidenalg, GSEApy) are a
# separate build argument: they roughly triple the image size, and a deployment
# that only serves the Foundation track does not need them.
FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build tools are needed to compile the scientific wheels that have no
# manylinux build, and are dropped from the final layer.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements-science.txt ./
ARG INCLUDE_SCIENCE=false
RUN pip install -r requirements.txt \
 && if [ "$INCLUDE_SCIENCE" = "true" ]; then pip install -r requirements-science.txt; fi \
 && apt-get purge -y build-essential && apt-get autoremove -y

COPY backend/ /app/
COPY scripts/ /app/scripts/
COPY docker/api-entrypoint.sh /usr/local/bin/api-entrypoint.sh
RUN chmod +x /usr/local/bin/api-entrypoint.sh

# Runs as an unprivileged user; the data directory is the only writable path.
RUN useradd --system --create-home --uid 10001 omicslab \
 && mkdir -p /data && chown -R omicslab:omicslab /data /app
USER omicslab

ENV PYTHONPATH=/app \
    OMICSLAB_DATA_DIR=/data \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

ENTRYPOINT ["api-entrypoint.sh"]
