FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    android-tools-adb \
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
    Pillow

# Copy app code
COPY app/ ./app/
COPY config.yaml ./

# Data + screenshots + downloads volumes
RUN mkdir -p /data /app/screenshots /app/static/downloads

# Copy helper APK if available
COPY android-helper/app/build/outputs/apk/debug/app-debug.apk /app/static/downloads/ac-helper.apk

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
