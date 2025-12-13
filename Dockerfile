FROM python:3.14-slim

# Install system dependencies
RUN apt-get update && apt-get install -y libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Copy project files
COPY --chown=appuser:appuser pyproject.toml uv.lock ./

# Install dependencies as ROOT (важно!)
RUN --mount=from=ghcr.io/astral-sh/uv,source=/uv,target=/bin/uv \
    uv --no-cache sync --no-dev

# Copy application code
COPY --chown=appuser:appuser . /app/

# Switch to non-root user
USER appuser

CMD [".venv/bin/python", "main.py"]