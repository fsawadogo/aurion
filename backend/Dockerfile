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
# `ffmpeg` — clip-to-still fallback + video-import audio/frame extraction.
# `libglib2.0-0` — runtime dep of opencv-python-headless (VID-04 masking).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Verify ffmpeg is reachable on PATH. Fails the build early if a
# future Debian base image ever drops the package — better than
# discovering it via a 500 in production.
RUN ffmpeg -version

# Download the res10 SSD face-detector weights for server-side masking
# (VID-07). BEST-EFFORT: if the download fails (network/URL drift) the build
# still succeeds and runtime falls back to the bundled Haar cascade — a
# masking-quality improvement must never break the deploy. FACE_DETECTOR_MODEL_DIR
# defaults to /app/models (see app/modules/video_import/masking.py).
RUN mkdir -p /app/models && \
    curl -fsSL -o /app/models/res10_deploy.prototxt \
      https://raw.githubusercontent.com/opencv/opencv/4.x/samples/dnn/face_detector/deploy.prototxt \
      || echo "WARN: res10 prototxt download failed — runtime falls back to Haar" && \
    curl -fsSL -o /app/models/res10.caffemodel \
      https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel \
      || echo "WARN: res10 caffemodel download failed — runtime falls back to Haar"

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
