# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into /app/deps
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/app/deps -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Create non-root user for security
RUN addgroup --system appgroup && adduser --system --group appuser

# Copy dependencies from builder
COPY --from=builder /app/deps /usr/local

# Copy application source
COPY app/ ./app/

# Switch to non-root
USER appuser

EXPOSE 8000

# Health check for Docker/orchestrators
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Uvicorn with multiple workers
# In production: use gunicorn with uvicorn workers for better process management
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--loop", "uvloop", \
     "--log-level", "info"]