# ─── Multi-stage Dockerfile for Railway deployment ───
FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .
COPY scrapers/ scrapers/

# Default port
ENV PORT=8000
ENV WEB_CONCURRENCY=1

# Expose port
EXPOSE 8000

# Health check (start-period gives app time to boot before checking)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Run with shell form so environment variables are expanded
CMD python main.py