FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 genealogiste \
    && useradd --uid 10001 --gid 10001 --create-home genealogiste \
    && mkdir -p /data /cache \
    && chown genealogiste:genealogiste /data /cache \
    && chmod 700 /data /cache

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    GENEALOGISTE_DATA_DIR=/data GENEALOGISTE_CACHE=/cache/cache.sqlite

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

ENV UV_CACHE_DIR=/cache/uv
USER 10001:10001

VOLUME ["/data", "/cache"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8765), 3)"
CMD ["uv", "run", "--no-sync", "genealogiste-mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8765"]
