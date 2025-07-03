# Stage 1: Base image that includes FFmpeg
FROM jrottenberg/ffmpeg:4.4-ubuntu as ffmpeg

# Stage 2: Python runtime
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# Copy FFmpeg from stage 1
COPY --from=ffmpeg /usr/local /usr/local

WORKDIR /app

# Install minimal system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libsm6 libxext6 curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn

# Copy app code
COPY . .

# Create app user
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

# Environment
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV PYTHONPATH=/app

# Healthcheck for Railway
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl --fail http://localhost:5000/ping || exit 1

EXPOSE 5000

CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers=2", \
     "--timeout=120", \
     "--log-level=info", \
     "app:app"]
