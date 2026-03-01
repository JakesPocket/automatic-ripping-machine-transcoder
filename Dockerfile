# ── Stage 1: Compile HandBrake CLI with all GPU encoders ──────────────
# Use CUDA devel image so HandBrake's bundled FFmpeg can compile with
# NVENC/NVDEC support (requires cuda_llvm / nvcc headers).
# This stage is discarded — only the HandBrakeCLI binary is copied out.
FROM nvidia/cuda:12.8.1-devel-ubuntu24.04 AS handbrake-builder
ARG HANDBRAKE_VERSION=1.10.2
RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf automake build-essential ca-certificates clang cmake git \
    libtool libtool-bin \
    libass-dev libbz2-dev libfontconfig-dev libfreetype-dev \
    libfribidi-dev libharfbuzz-dev libjansson-dev liblzma-dev \
    libmp3lame-dev libnuma-dev libogg-dev libopus-dev \
    libsamplerate0-dev libspeex-dev libssl-dev libtheora-dev \
    libturbojpeg0-dev libva-dev libvpl-dev libdrm-dev libvorbis-dev \
    libvpx-dev libx264-dev libxml2-dev m4 make meson nasm \
    ninja-build patch pkg-config python3 tar zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN git clone https://github.com/HandBrake/HandBrake.git \
        --branch ${HANDBRAKE_VERSION} --depth 1 \
    && cd HandBrake \
    && ./configure --prefix=/usr/local \
                   --disable-gtk \
                   --enable-nvenc \
                   --enable-nvdec \
                   --enable-qsv \
                   --enable-numa \
                   --launch-jobs=$(nproc) \
                   --launch \
    && make -j$(nproc) --directory=build install

# ── Stage 2: Base runtime ──────────────────────────────────────────────
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

COPY --from=handbrake-builder /usr/local/bin/HandBrakeCLI /usr/local/bin/

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
