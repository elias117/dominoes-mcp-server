# syntax=docker/dockerfile:1
# Multi-platform build: supports linux/arm64 (Mac mini M-series) and linux/amd64
FROM python:3.12-slim-bookworm

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Install dependencies first (layer caching)
COPY pyproject.toml ./
RUN uv sync --frozen --no-dev --no-install-project 2>/dev/null || uv pip install --system -r <(uv pip compile pyproject.toml)

# Copy source
COPY src/ ./src/

# Install the project itself
RUN uv pip install --system --no-deps .

# Create data directory for order logs
RUN mkdir -p /data && chmod 777 /data

# Expose MCP HTTP port
EXPOSE 8000

# Config is mounted at runtime — never baked in
ENV CONFIG_PATH=/config/config.json
ENV LOG_PATH=/data/orders.log
ENV HOST=0.0.0.0
ENV PORT=8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run the MCP server
CMD ["python", "-m", "dominos_mcp.server"]
