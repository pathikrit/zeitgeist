# ---------- Stage 1: Builder ----------
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app
COPY . .

# Install all dependencies (cached into .venv but not required later)
RUN uv sync --frozen

# ---------- Stage 2: Runtime ----------
FROM python:3.11-slim

WORKDIR /app

# Copy uv and project
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder /app /app

# Default command: run zeitgeist
CMD ["uv", "run", "python", "zeitgeist.py"]
