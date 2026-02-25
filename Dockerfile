FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

LABEL org.opencontainers.image.source="https://github.com/uprightbass360/automatic-ripping-machine-transcoder"
LABEL org.opencontainers.image.license="MIT"
LABEL org.opencontainers.image.description="GPU-accelerated transcoding service for ARM (NVIDIA)"

# Install system dependencies and HandBrake CLI from Ubuntu universe repo
RUN echo "deb http://archive.ubuntu.com/ubuntu jammy universe" >> /etc/apt/sources.list \
    && echo "deb http://archive.ubuntu.com/ubuntu jammy-updates universe" >> /etc/apt/sources.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    mediainfo \
    curl \
    libva2 \
    libva-drm2 \
    libdrm2 \
    handbrake-cli \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -m -s /bin/bash transcoder

# Setup Python environment
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY VERSION /app/
COPY src/ /app/
COPY presets/ /config/presets/

# Create data directories
RUN mkdir -p /data/raw /data/completed /data/work /data/db /data/logs \
    && chown -R transcoder:transcoder /data /app /config

USER transcoder

EXPOSE 5000

CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]
