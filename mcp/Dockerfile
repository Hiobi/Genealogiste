FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    GENEALOGISTE_DATA_DIR=/data GENEALOGISTE_CACHE=/cache/cache.sqlite

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

VOLUME ["/data", "/cache"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8765), 3)"
CMD ["uv", "run", "--no-sync", "genealogiste-mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8765"]
