# ─── Multi-stage Dockerfile for Railway deployment ───
# Base image: official Playwright image bundles Chromium + system deps
# needed for the DraftKings Akamai-bypass session.
FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl is already in the Playwright image; no extra apt packages needed.
# The image ships chromium-1223 matching playwright==1.60.0.

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

# Health check (start-period gives app time to boot + first DK prime ~10s)
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Run with shell form so environment variables are expanded
CMD python main.py
