FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    android-tools-adb \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "droidrun[openai]" \
    "fastapi[standard]" \
    sqlmodel \
    python-dotenv \
    pydantic-settings \
    websockets \
    Pillow \
    itsdangerous \
    "livekit-api>=1.0,<2"

# Copy app code
COPY app/ ./app/
COPY config.yaml ./

# Data + screenshots + downloads volumes
RUN mkdir -p /data /app/screenshots /app/static/downloads

# Copy pre-built helper APK for download page
COPY app/static/downloads/ /app/static/downloads/

ENV PYTHONUNBUFFERED=1
ENV RUNTIME_DATA_DIR=/app

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--ws-ping-interval", "25", "--ws-ping-timeout", "30"]
