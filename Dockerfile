# ---------- Stage 1: Builder ----------
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app
COPY . .

RUN uv sync --frozen

# ---------- Stage 2: Runtime ----------
FROM python:3.11-slim

WORKDIR /app

# Copy uv + app
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

# Either:
# CMD ["uv", "run", "python", "zeitgeist.py"]
# Or the simpler venv Python version:
CMD ["/app/.venv/bin/python", "zeitgeist.py"]
