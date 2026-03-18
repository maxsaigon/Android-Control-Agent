FROM python:3.11-slim

# System deps for ADB
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

# Bundle helper APK for auto-install on devices
# NOTE: Uncomment when building from a machine with Android Studio APK output
# COPY android-helper/app/build/outputs/apk/debug/app-debug.apk ./ac-helper.apk

# Data + screenshots volumes
RUN mkdir -p /app/data /app/screenshots

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
