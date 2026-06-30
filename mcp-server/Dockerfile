# Slim Python image. The MCP server is tiny (only depends on the chassis
# in ../prototype-lite plus the mcp + uvicorn + starlette stacks), so we
# don't need a multi-stage build for the spike.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8000 \
    TELEMETRY_BACKEND=stdout

WORKDIR /app

# ODBC Driver 18 for SQL Server — required by the Fabric ontology backend
# (ONTOLOGY_BACKEND=fabric). Local DuckDB backend doesn't need it but installing
# unconditionally keeps the image self-contained and avoids a runtime "missing
# driver" surprise when the env var is flipped.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates apt-transport-https \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
    && rm -rf /var/lib/apt/lists/*

# Install deps first for layer caching.
COPY mcp-server/requirements.txt /app/mcp-server/requirements.txt
RUN pip install --no-cache-dir -r /app/mcp-server/requirements.txt

# Copy the server, the chassis it imports, the schemas it validates against.
# (examples/ is replaced by a build-time synth catalog — see the RUN below.)
COPY mcp-server/ /app/mcp-server/
COPY prototype-lite/ /app/prototype-lite/
COPY schemas/ /app/schemas/

# Parquet ontology drop for ONTOLOGY_BACKEND=local (query_ontology tool) +
# manifests for REGISTRY_CATALOG_MODE=local (find_skill_by_capability tool).
# Stage F Phase 1 + scale bump (image :v7, 2026-06-30):
#   - Generate the 1000-skill synth catalog (seed=42, deterministic).
#   - Generate the 500-person org alongside (seed=42).
#   - Project both into parquet (2 348 nodes / 20 440 edges).
#   - The synth catalog becomes /app/examples so the registry tool surface
#     sees the same 1000 skills the ontology graph indexes.
COPY prototype/ /app/prototype/
RUN python -m prototype.chassis.synth_skills --count 1000 \
        --out /app/examples --seed 42 \
    && python -m prototype.chassis.synth_org \
        --count-people 500 --count-projects 200 \
        --count-training 150 --count-certs 60 \
        --out /app/prototype/out/synth/org \
        --skills-dir /app/examples --seed 42 \
    && python -m prototype.chassis.fabric_export \
        --out /app/prototype/out/fabric/ \
        --examples /app/examples \
        --org-dir /app/prototype/out/synth/org

WORKDIR /app/mcp-server
EXPOSE 8000

# Container Apps liveness probe hits /health (see infra/stage-3/main.bicep).
CMD ["python", "-m", "server"]
