FROM python:3.12-bookworm

ENV DEBIAN_FRONTEND="noninteractive" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Create directories for config and downloads
RUN mkdir -p /config /downloads

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .
COPY sync_runner.py .
COPY templates templates/

# Expose the web interface port
EXPOSE 5000

# Use single worker gunicorn to preserve global state
# --threads 4 allows concurrent requests while sharing global state
# --timeout 0 disables worker timeout for long-running sync jobs
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "0", "app:app"]
