FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
#
# `ffmpeg` is required by `app/modules/providers/vision/_clip_to_still.py`
# (P1-2 still-fallback). When `vision_clip` is routed to a non-native
# provider (OpenAI, Anthropic — neither accepts MP4 directly), the
# helper shells out to `ffmpeg` to extract a midpoint JPEG. Without
# this binary the fallback chain crashes at runtime — surfaced live
# against `api-dev.aurionclinical.com` (P1-FU-FFMPEG).
#
# Image-size cost: ~70 MB. Acceptable for an API container that
# already carries Python + torch transitive deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Verify ffmpeg is reachable on PATH. Fails the build early if a
# future Debian base image ever drops the package — better than
# discovering it via a 500 in production.
RUN ffmpeg -version

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code, alembic config, migrations, and entrypoint
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
