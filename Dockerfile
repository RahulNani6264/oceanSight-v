# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libnetcdf-dev \
    libhdf5-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY *.py ./
COPY data/ ./data/
COPY raw/ ./raw/
COPY processed/ ./processed/
COPY metadata/ ./metadata/
COPY logs/ ./logs/

# Create non-root user
RUN groupadd -r oceansight && useradd -r -g oceansight oceansight && \
    chown -R oceansight:oceansight /app

USER oceansight

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-of-period=60s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Run the application
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "4"]