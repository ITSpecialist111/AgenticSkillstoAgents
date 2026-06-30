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

# Copy the server, the chassis it imports, the schemas it validates against,
# and the bundled example manifests (for the default REGISTRY_CATALOG_MODE=local
# until Stage 2 is wired in).
COPY mcp-server/ /app/mcp-server/
COPY prototype-lite/ /app/prototype-lite/
COPY schemas/ /app/schemas/
COPY examples/ /app/examples/

# Parquet ontology drop for ONTOLOGY_BACKEND=local (query_ontology tool).
# Rebuild with: python -m prototype.chassis.fabric_export --out prototype/out/fabric/
COPY prototype/out/fabric/ /app/prototype/out/fabric/

WORKDIR /app/mcp-server
EXPOSE 8000

# Container Apps liveness probe hits /health (see infra/stage-3/main.bicep).
CMD ["python", "-m", "server"]
