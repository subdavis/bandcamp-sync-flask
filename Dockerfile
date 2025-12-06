# Build stage: use full image with git to install dependencies
FROM python:3.12-bookworm AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --target=/build/deps -r requirements.txt

# Runtime stage: slim image without git
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND="noninteractive" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Create directories for config and downloads
RUN mkdir -p /config /downloads

# Copy installed dependencies from builder
COPY --from=builder /build/deps /usr/local/lib/python3.12/site-packages/

# Copy application code
COPY app.py .
COPY sync_runner.py .
COPY templates templates/

# Expose the web interface port
EXPOSE 5000

# Use waitress for lower memory footprint
# Single-threaded async server, lighter than gunicorn for simple apps
CMD ["python", "-m", "waitress", "--host", "0.0.0.0", "--port", "5000", "--threads", "2", "app:app"]
