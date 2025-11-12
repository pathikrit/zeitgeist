# ---------- Stage 1: Builder ----------
FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .

# Install dependencies with pip
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# ---------- Stage 2: Runtime ----------
FROM python:3.13-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Default command: run zeitgeist
CMD ["python3", "zeitgeist.py"]
