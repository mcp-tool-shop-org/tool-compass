# Tool Compass - Semantic MCP Tool Discovery
# Multi-stage build for minimal production image

# =============================================================================
# Stage 1: Builder
# =============================================================================
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .

# Create virtualenv and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir uvicorn

# =============================================================================
# Stage 2: Production
# =============================================================================
FROM python:3.11-slim as production

LABEL maintainer="Tool Compass <github.com/mcp-tool-shop-org/tool-compass>"
LABEL description="Semantic search gateway for MCP tools"
# Keep in sync with pyproject.toml [project] version
LABEL version="2.0.3"

# Security: Run as non-root user
RUN groupadd -r compass && useradd -r -g compass compass

WORKDIR /app/tool_compass

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY --chown=compass:compass . .

# Create data directory for indexes
RUN mkdir -p /app/tool_compass/db && \
    chown -R compass:compass /app/tool_compass/db

# Environment configuration
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    # Tool Compass settings
    TOOL_COMPASS_BASE_PATH=/app \
    OLLAMA_URL=http://host.docker.internal:11434 \
    # Gradio settings
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860

# Expose Gradio UI port
EXPOSE 7860

# Switch to non-root user
USER compass

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from indexer import CompassIndex; idx = CompassIndex(); print('healthy' if idx.load_index() else 'no index')" || exit 1

# Default command: Run Gradio UI
CMD ["python", "ui.py"]

# =============================================================================
# Stage 3: MCP Gateway (alternative entrypoint)
# =============================================================================
FROM production as mcp-gateway

# Override for HTTP mode (Fly.io / Smithery)
ENV PORT=8080

# Expose MCP HTTP port
EXPOSE 8080

# Health check via /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8080/health'); r.raise_for_status()" || exit 1

CMD ["python", "gateway.py"]
