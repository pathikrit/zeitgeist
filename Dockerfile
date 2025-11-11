# ---------- Stage 1: Builder ----------
FROM python:3.11-slim AS builder

# Install required system dependencies
RUN apt-get update && apt-get install -y git curl && \
    rm -rf /var/lib/apt/lists/*

# Install uv (Python project manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app

# Clone the zeitgeist repo (or copy local if you maintain your own fork)
COPY . .

# Install dependencies and sync virtualenv (isolated in /app/.venv)
RUN uv sync --frozen

# ---------- Stage 2: Runtime ----------
FROM python:3.11-slim

# Copy only what we need from builder stage
WORKDIR /app
COPY --from=builder /app /app

# Add UV to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Default command to generate report
CMD ["uv", "run", "python", "zeitgeist.py"]
