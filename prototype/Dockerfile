# Container image for the Skill Registry & Graduation service.
#
# Builds the chassis package with its API extra and runs the HTTP service. The
# registry is persisted to a SQLite file under /data (mount a volume to keep it
# across restarts) - swap CHASSIS_DB for a hosted backend later.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install the package (with the API extra) from source.
COPY pyproject.toml README.md ./
COPY chassis ./chassis
RUN pip install --no-cache-dir ".[api]"

# Default runtime configuration (override at `docker run -e ...`).
ENV CHASSIS_HOST=0.0.0.0 \
    CHASSIS_PORT=8000 \
    CHASSIS_DB=sqlite:////data/registry.db

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000

# A tiny entrypoint so env vars drive the CLI flags.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
url='http://127.0.0.1:%s/healthz' % os.environ.get('CHASSIS_PORT','8000'); \
sys.exit(0 if urllib.request.urlopen(url, timeout=2).status==200 else 1)"

ENTRYPOINT ["docker-entrypoint.sh"]
