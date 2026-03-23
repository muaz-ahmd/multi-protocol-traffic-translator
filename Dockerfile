# Multi-Protocol Traffic Translator Dockerfile

FROM python:3.9-slim

# Install system dependencies for various adapters
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY traffic_translator/ ./traffic_translator/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Default configuration volume
VOLUME ["/config"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import traffic_translator.main; print('OK')" || exit 1

# Default command
CMD ["python", "-m", "traffic_translator.main", "-c", "/config/traffic_controller.yaml"]

# Labels
LABEL maintainer="Traffic Translator Team"
LABEL description="Multi-protocol traffic signal controller translator"
LABEL version="1.0.0"