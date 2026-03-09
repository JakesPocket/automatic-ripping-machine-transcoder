[![CI](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/actions/workflows/test.yml/badge.svg)](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/uprightbass360/automatic-ripping-machine-transcoder/graph/badge.svg)](https://codecov.io/gh/uprightbass360/automatic-ripping-machine-transcoder)
[![GitHub release](https://img.shields.io/github/v/release/uprightbass360/automatic-ripping-machine-transcoder)](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/releases/latest)
[![NVIDIA](https://img.shields.io/docker/v/uprightbass360/arm-transcoder?label=nvidia)](https://hub.docker.com/r/uprightbass360/arm-transcoder)
[![AMD](https://img.shields.io/docker/v/uprightbass360/arm-transcoder?tag=latest-amd&label=amd)](https://hub.docker.com/r/uprightbass360/arm-transcoder)
[![Intel](https://img.shields.io/docker/v/uprightbass360/arm-transcoder?tag=latest-intel&label=intel)](https://hub.docker.com/r/uprightbass360/arm-transcoder)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

# ARM Transcoder

Part of the [Automatic Ripping Machine ecosystem](#related-projects). Hardware-accelerated transcoding service that offloads encoding from your ARM ripper to a dedicated transcode server. Supports NVIDIA, AMD, and Intel GPUs, or CPU-only software encoding.

## Related Projects

Part of the Automatic Ripping Machine ecosystem:

| Project | Description |
|---------|-------------|
| [automatic-ripping-machine-neu](https://github.com/uprightbass360/automatic-ripping-machine-neu) | Fork of the original ARM with bug fixes and improvements |
| [automatic-ripping-machine-ui](https://github.com/uprightbass360/automatic-ripping-machine-ui) | Modern replacement dashboard (SvelteKit + FastAPI) |
| **automatic-ripping-machine-transcoder** | GPU-accelerated transcoding service (this project) |

The original upstream project: [automatic-ripping-machine/automatic-ripping-machine](https://github.com/automatic-ripping-machine/automatic-ripping-machine)

## Architecture

```mermaid
flowchart TB
    subgraph ripper["ARM Ripper Machine"]
        ARM["ARM Container<br/>(MakeMKV only)"]
    end

    subgraph transcoder["Transcode Machine"]
        TC["arm-transcoder<br/>(FFmpeg / HandBrake)"]
    end

    subgraph storage["Shared Storage"]
        RAW["/raw/ — MakeMKV output"]
        DONE["/completed/movies/ — Transcoded video"]
        AUDIO["/completed/audio/ — Audio CD rips"]
    end

    ARM -- "webhook" --> TC
    ARM -- "writes" --> RAW
    RAW -- "reads" --> TC
    TC -- "transcodes" --> DONE
    TC -- "copies" --> AUDIO
```

## Features

- Webhook receiver for ARM job completion notifications
- Hardware-accelerated transcoding via FFmpeg (with HandBrake fallback for NVIDIA)
- Resolution-based encoding — 4K preserved, Blu-ray at 1080p, DVDs upscaled to 720p
- Multi-GPU support: NVIDIA NVENC, AMD VAAPI/AMF, Intel Quick Sync, software fallback
- Queue management with SQLite persistence
- REST API for job monitoring and management
- API key authentication with role-based access (admin/readonly)
- Input validation and path traversal protection
- Audio CD passthrough — detects audio rips (FLAC/MP3/etc.) and copies them to an audio folder without transcoding
- Local scratch storage to avoid heavy I/O on network shares (copy→transcode→move)
- Automatic source cleanup after successful transcode
- Pagination support on job listings
- Retry limits with tracking
- Disk space pre-checks

## Docker Images

Pre-built images are published to Docker Hub on every release:

```bash
docker pull uprightbass360/arm-transcoder:latest            # NVIDIA (default)
docker pull uprightbass360/arm-transcoder:latest-nvidia     # NVIDIA (explicit)
docker pull uprightbass360/arm-transcoder:latest-amd        # AMD Radeon
docker pull uprightbass360/arm-transcoder:latest-intel      # Intel QSV
```

For the full ecosystem quick start (ARM + UI + Transcoder), see the [ARM-neu README](https://github.com/uprightbass360/automatic-ripping-machine-neu#quick-start).

## Requirements

- Docker
- Shared storage between machines (NFS, SMB/CIFS, or any network/local mount)
- ARM configured to skip transcoding (`SKIP_TRANSCODE: true`)
- One of the following for encoding:

| Hardware | Requirements | Compose File | Encoder |
|----------|-------------|--------------|---------|
| **AMD Radeon** | `/dev/dri` device + mesa-va-drivers | `docker-compose.amd.yml` | `vaapi_h265` |
| **Intel** | `/dev/dri` device + intel-media-driver | `docker-compose.intel.yml` | `qsv_h265` |
| **NVIDIA** | NVIDIA Container Toolkit | `docker-compose.yml` | `nvenc_h265` |
| **No GPU** | None | `docker-compose.dev.yml` | `x265` |

## Setting Up with ARM

Step-by-step guide for a typical two-machine setup: an ARM ripper that rips discs and a separate transcode server with a GPU, connected by shared storage.

For Proxmox LXC deployment, see [docs/proxmox-lxc-setup.md](docs/proxmox-lxc-setup.md).

### 1. Set up shared storage

Both machines need access to the same directories via NFS, SMB/CIFS, or any network mount:

```
/mnt/media/raw         ← ARM writes raw MKV files here
/mnt/media/completed   ← Transcoder writes finished files here
```

ARM writes to `raw/`. The transcoder reads from `raw/` and writes to `completed/movies/`, `completed/tv/`, and `completed/audio/`.

### 2. Start the transcoder

On your transcode server:

```bash
git clone https://github.com/uprightbass360/automatic-ripping-machine-transcoder.git
cd automatic-ripping-machine-transcoder
cp .env.example .env
```

Edit `.env` with your shared storage paths:

```bash
HOST_RAW_PATH=/mnt/media/raw
HOST_COMPLETED_PATH=/mnt/media/completed
```

Start the container for your GPU:

```bash
docker compose up -d                                  # NVIDIA
docker compose -f docker-compose.amd.yml up -d        # AMD Radeon
docker compose -f docker-compose.intel.yml up -d       # Intel Quick Sync
docker compose -f docker-compose.dev.yml up -d         # No GPU (software)
```

Verify it's running:

```bash
curl http://localhost:5000/health
```

### 3. Configure ARM

On your ARM ripper, disable built-in transcoding and point webhooks at the transcoder.

**Option A: Automated setup (recommended)**

Copy the setup script to your ARM machine and run it:

```bash
# Simple webhook (no auth)
./scripts/setup-arm.sh \
  --url http://TRANSCODER_IP:5000/webhook/arm \
  --config /etc/arm/config

# With webhook authentication
./scripts/setup-arm.sh \
  --url http://TRANSCODER_IP:5000/webhook/arm \
  --config /etc/arm/config \
  --secret your-webhook-secret \
  --restart
```

The script patches `arm.yaml`, deploys the notification script (when using `--secret`), and optionally restarts ARM.

**Option B: Manual setup**

Edit your ARM `arm.yaml`:

```yaml
# Disable ARM's built-in transcoding
SKIP_TRANSCODE: true
RIPMETHOD: "mkv"
DELRAWFILES: false
MAX_CONCURRENT_TRANSCODES: 0

# Send webhook when rip completes
JSON_URL: "http://TRANSCODER_IP:5000/webhook/arm"
NOTIFY_RIP: true
NOTIFY_TRANSCODE: false
```

Replace `TRANSCODER_IP` with the IP or hostname of your transcode server. For authenticated webhooks, use the `notify_transcoder.sh` script instead of `JSON_URL` — see [config/arm/arm.yaml](config/arm/arm.yaml) for both options.

### 4. Test the pipeline

Send a test webhook to verify connectivity:

```bash
curl -s -X POST http://TRANSCODER_IP:5000/webhook/arm \
  -H "Content-Type: application/json" \
  -d '{"title": "ARM notification", "body": "Test Movie (2024) rip complete. Starting transcode.", "type": "info"}'
```

A `200` response means the transcoder received the webhook. Check job status:

```bash
curl http://TRANSCODER_IP:5000/jobs
curl http://TRANSCODER_IP:5000/stats
```

### 5. Rip a disc

Insert a disc into your ARM ripper and let it rip. When the rip completes:

1. ARM sends a webhook to the transcoder
2. The transcoder finds the raw MKV files on shared storage
3. Files are transcoded with your GPU (resolution-aware — 4K preserved, DVDs upscaled to 720p)
4. Output is written to `completed/movies/` or `completed/tv/` (auto-detected)
5. Audio CD rips are copied to `completed/audio/` without transcoding
6. Source files are cleaned up (if `DELETE_SOURCE=true`)

### Optional: Drive auto-restart

If your Blu-ray drive isn't powered on 24/7, install a watcher on the ARM host
to automatically restart the container when the drive connects:

```bash
sudo ./scripts/setup-drive-watcher.sh --mode udev

# Monitor restart events
journalctl -t arm-drive-watcher -f
```

See `./scripts/setup-drive-watcher.sh --help` for all options including
docker-compose support and device-bound mode.

### Optional: Stable drive naming

If your optical drive changes device names between reboots (e.g., `/dev/sr0`
becomes `/dev/sr1`), create stable symlinks:

```bash
# List detected drives
./scripts/setup-optical-symlinks.sh --list

# Auto-create /dev/optical0, /dev/optical1, ...
sudo ./scripts/setup-optical-symlinks.sh --auto
```

Then use `/dev/optical0` in your Docker device mapping instead of `/dev/sr0`.
See `./scripts/setup-optical-symlinks.sh --help` for all options.

## Configuration

### Docker Environment Variables (.env)

These variables are used across all `docker-compose*.yml` files:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST_RAW_PATH` | *(required)* | Host path to ARM's raw output (shared storage mount) |
| `HOST_COMPLETED_PATH` | *(required)* | Host path for completed transcodes |
| `VIDEO_ENCODER` | *(per compose file)* | Video encoder (see [Encoder Options](#encoder-options)) |
| `WEBHOOK_PORT` | 5000 | Port exposed on host |
| `WEBHOOK_SECRET` | *(empty)* | Secret for webhook authentication (see [Authentication](docs/AUTHENTICATION.md)) |
| `LOG_LEVEL` | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `TZ` | America/New_York | Container timezone |

### Application Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `RAW_PATH` | /data/raw | Path to raw MKV files inside container |
| `COMPLETED_PATH` | /data/completed | Path for completed transcodes inside container |
| `VIDEO_QUALITY` | 22 | Quality (0-51, lower = better). Maps to CQ (NVENC), QP (VAAPI), global_quality (QSV), or CRF (software) |
| `AUDIO_ENCODER` | copy | Audio handling (`copy`, `aac`, `ac3`, `eac3`, `flac`, `mp3`) |
| `SUBTITLE_MODE` | all | Subtitle handling (`all`, `none`, `first`) |
| `MOVIES_SUBDIR` | movies | Subdirectory under COMPLETED_PATH for movies |
| `TV_SUBDIR` | tv | Subdirectory under COMPLETED_PATH for TV shows |
| `AUDIO_SUBDIR` | audio | Subdirectory under COMPLETED_PATH for audio CD rips |
| `DELETE_SOURCE` | true | Remove source after successful transcode |
| `MAX_CONCURRENT` | 1 | Max concurrent transcodes (1 recommended for single GPU) |
| `STABILIZE_SECONDS` | 60 | Seconds to wait for source files to stop changing |
| `MAX_RETRY_COUNT` | 3 | Maximum retry attempts for failed jobs (0-10) |
| `MINIMUM_FREE_SPACE_GB` | 10 | Minimum free disk space required (GB) |
| `REQUIRE_API_AUTH` | false | Require API key for endpoints |
| `API_KEYS` | *(empty)* | Comma-separated API keys (see [Authentication](docs/AUTHENTICATION.md)) |
| `HANDBRAKE_PRESET` | H.265 NVENC 1080p | HandBrake preset for standard content |
| `HANDBRAKE_PRESET_4K` | H.265 NVENC 2160p 4K | HandBrake preset for 4K content (source > 1080p) |
| `VAAPI_DEVICE` | /dev/dri/renderD128 | VAAPI/QSV render device path (AMD and Intel only) |

See `.env.example` for the full template.

### Encoder Options

| Hardware | Encoder | Description |
|----------|---------|-------------|
| AMD | `vaapi_h265` / `hevc_vaapi` | VAAPI H.265 (recommended for Radeon on Linux) |
| AMD | `vaapi_h264` / `h264_vaapi` | VAAPI H.264 |
| AMD | `amf_h265` / `hevc_amf` | AMF H.265 |
| AMD | `amf_h264` / `h264_amf` | AMF H.264 |
| Intel | `qsv_h265` / `hevc_qsv` | Quick Sync H.265 |
| Intel | `qsv_h264` / `h264_qsv` | Quick Sync H.264 |
| NVIDIA | `nvenc_h265` / `hevc_nvenc` | NVENC H.265 |
| NVIDIA | `nvenc_h264` / `h264_nvenc` | NVENC H.264 |
| None | `x265` | Software H.265 (no GPU required, slower) |
| None | `x264` | Software H.264 (no GPU required, slower) |

Each compose file sets a sensible default encoder for its GPU type. Override with `VIDEO_ENCODER` in your `.env`.

### HandBrake Presets

HandBrake is used as the transcoding backend when NVIDIA NVENC is selected and HandBrake is available. For all other encoder families, FFmpeg is used directly.

The default preset is HandBrake's built-in **H.265 NVENC 1080p**. Custom presets are available in `presets/nvenc_presets.json` — to use them, set `HANDBRAKE_PRESET_FILE=/config/presets/nvenc_presets.json`:

- **NVENC H.265 1080p** - Best compression, decomb deinterlacing, all audio/subtitle tracks
- **NVENC H.265 4K** - For 4K/UHD content
- **NVENC H.264 1080p** - Broader device compatibility

### Resolution-Based Encoding

The transcoder automatically detects source resolution and adjusts encoding:

| Source | HandBrake | FFmpeg |
|--------|-----------|--------|
| **4K UHD** (> 1080p) | Uses `HANDBRAKE_PRESET_4K` | Preserves native resolution |
| **Blu-ray** (720p–1080p) | Uses `HANDBRAKE_PRESET` | Preserves native resolution |
| **DVD** (< 720p) | Uses `HANDBRAKE_PRESET` + upscale to 720p | Upscales to 720p via GPU-native filter |

FFmpeg upscaling uses the appropriate hardware filter per GPU: `scale_cuda` (NVIDIA), `scale_vaapi` (AMD), `vpp_qsv` (Intel), or software `scale` fallback.

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | None | Health check |
| `/webhook/arm` | POST | Webhook secret | Receive ARM notifications |
| `/jobs` | GET | API key | List jobs (supports `?status=` filter, `?limit=`, `?offset=`) |
| `/jobs/{id}/retry` | POST | Admin API key | Retry a failed job |
| `/jobs/{id}` | DELETE | Admin API key | Delete a job |
| `/stats` | GET | API key | Transcoding statistics |

When `REQUIRE_API_AUTH=false` (default), API key auth is bypassed. See [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md) for details.

## Monitoring

```bash
# View logs (use the compose file matching your GPU)
docker compose -f docker-compose.amd.yml logs -f arm-transcoder

# Check queue and stats
curl http://localhost:5000/stats

# List jobs (with optional filters)
curl http://localhost:5000/jobs
curl http://localhost:5000/jobs?status=failed
curl http://localhost:5000/jobs?limit=10&offset=0
```

## Troubleshooting

### GPU Not Detected

**AMD Radeon** - Verify VAAPI device and drivers:
```bash
# Check device exists on host
ls -la /dev/dri/renderD128

# Test inside container
docker compose -f docker-compose.amd.yml exec arm-transcoder vainfo
```

**Intel Quick Sync** - Verify QSV device:
```bash
ls -la /dev/dri/renderD128
docker compose -f docker-compose.intel.yml exec arm-transcoder vainfo
```

**NVIDIA** - Verify container toolkit:
```bash
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

### Webhook Not Receiving

1. Check ARM logs for notification attempts
2. Verify network connectivity between machines
3. Check `JSON_URL` in ARM config matches transcoder address
4. If using `WEBHOOK_SECRET`, ensure ARM sends `X-Webhook-Secret` header

The transcoder accepts two webhook formats:

**Apprise format** (default ARM notifications):
```json
{
  "title": "ARM notification",
  "body": "Rip of Movie Title (2024) complete",
  "type": "info"
}
```

**Custom format** (via ARM's `BASH_SCRIPT`):
```json
{
  "title": "Movie Title",
  "path": "Movie Title (2024)",
  "job_id": "123",
  "status": "success"
}
```

The transcoder extracts the title and looks for files in `RAW_PATH/<directory name>/`.

### Transcode Fails

1. Check job error: `curl http://localhost:5000/jobs?status=failed`
2. Verify source files exist in `RAW_PATH`
3. Verify sufficient disk space (default minimum: 10GB free)
4. Check container logs for FFmpeg/HandBrake error output

### Authentication Errors

See [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md) for setup and troubleshooting.

## Testing

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run all tests
python -m pytest tests/ -v
```

## License

[MIT License](LICENSE)
