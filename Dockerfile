# ── HandBrake CLI — pre-compiled, published by publish-handbrake.yml ──
ARG HANDBRAKE_TAG=latest
FROM uprightbass360/arm-handbrake:${HANDBRAKE_TAG} AS handbrake

# ── Base runtime ──────────────────────────────────────────────────────
# Shared base with HandBrake + deps + app code.
# Add a GPU layer (Dockerfile.nvidia/intel/amd) for hardware encoding,
# or use this image directly for CPU-only (x265/x264) transcoding.
FROM ubuntu:24.04
LABEL org.opencontainers.image.source="https://github.com/uprightbass360/automatic-ripping-machine-transcoder"
LABEL org.opencontainers.image.license="MIT"
LABEL org.opencontainers.image.description="ARM Transcoder base — add a GPU layer (Dockerfile.nvidia/intel/amd) for hardware encoding"

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ffmpeg mediainfo curl vainfo gosu \
    libva2 libva-drm2 libdrm2 \
    libass9 libbz2-1.0 libfontconfig1 libfreetype6 libfribidi0 \
    libharfbuzz0b libjansson4 liblzma5 libmp3lame0 libnuma1 \
    libogg0 libopus0 libsamplerate0 libspeex1 libtheora0 \
    libturbojpeg libvorbis0a libvorbisenc2 libxml2 zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=handbrake /HandBrakeCLI /usr/local/bin/HandBrakeCLI

# App user — UID 1001 / GID 1000 to match ARM's runtime identity.
# ARM writes NFS files as 1001:1000 (ARM_UID=1001, ARM_GID=1000),
# so the transcoder must use the same UID to read/write shared storage.
# ubuntu:24.04 ships a default 'ubuntu' user at 1000:1000 which we
# remove first so our UID/GID assignments are clean.
ARG TRANSCODER_UID=1001
ARG TRANSCODER_GID=1000
RUN (userdel -r ubuntu 2>/dev/null; groupdel ubuntu 2>/dev/null; true) \
    && groupadd -g ${TRANSCODER_GID} transcoder \
    && groupadd -f render \
    && useradd -m -s /bin/bash -u ${TRANSCODER_UID} -g transcoder transcoder \
    && usermod -aG video transcoder \
    && usermod -aG render transcoder

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt
COPY VERSION /app/
COPY src/ /app/
COPY presets/ /config/presets/
RUN mkdir -p /data/raw /data/completed /data/work /data/db /data/logs \
    && chown -R transcoder:transcoder /data /app /config

COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]
