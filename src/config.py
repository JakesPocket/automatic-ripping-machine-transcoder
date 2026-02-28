"""
Configuration settings for ARM Transcoder
"""

from pydantic_settings import BaseSettings
from pydantic import Field, field_validator

from constants import (
    VALID_VIDEO_ENCODERS,
    VALID_AUDIO_ENCODERS,
    VALID_SUBTITLE_MODES,
)


UPDATABLE_KEYS = {
    # Transcoding
    "video_encoder",
    "video_quality",
    "audio_encoder",
    "subtitle_mode",
    "handbrake_preset",
    "handbrake_preset_4k",
    "handbrake_preset_dvd",
    "handbrake_preset_file",
    # File handling
    "delete_source",
    "output_extension",
    # Organization
    "movies_subdir",
    "tv_subdir",
    "audio_subdir",
    # Concurrency
    "max_concurrent",
    "stabilize_seconds",
    # Operational
    "minimum_free_space_gb",
    "max_retry_count",
    "log_level",
    "log_level_libraries",
}

VALID_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Paths
    raw_path: str = Field("/data/raw", description="Path to raw MKV files from ARM")
    completed_path: str = Field("/data/completed", description="Path for completed transcodes")
    work_path: str = Field("/data/work", description="Temporary working directory")
    db_path: str = Field("/data/db/transcoder.db", description="SQLite database path")
    log_path: str = Field("/data/logs", description="Directory for log files")
    preset_path: str = Field("/config/presets", description="HandBrake presets directory")

    # Authentication
    require_api_auth: bool = Field(
        False,
        description="Require API key authentication for all endpoints"
    )
    api_keys: str = Field(
        "",
        description="Comma-separated API keys. Format: 'key1,key2' or 'admin:key1,readonly:key2'"
    )
    webhook_secret: str = Field(
        "",
        description="Optional secret for webhook authentication (X-Webhook-Secret header)"
    )

    # Transcoding — defaults are software (safe fallback for any hardware).
    # At startup, auto_resolve_gpu_defaults() upgrades these based on detected GPU.
    handbrake_preset: str = Field(
        "H.265 MKV 1080p30",
        description="HandBrake preset name to use"
    )
    handbrake_preset_4k: str = Field(
        "H.265 MKV 2160p60 4K",
        description="HandBrake preset for 4K content"
    )
    handbrake_preset_dvd: str = Field(
        "H.265 MKV 720p30",
        description="HandBrake preset for DVD/low-res sources (<720p). Falls back to handbrake_preset if empty."
    )
    handbrake_preset_file: str = Field(
        "",
        description="Path to custom preset JSON file (overrides preset name)"
    )
    video_encoder: str = Field(
        "x265",
        description=f"Video encoder. Valid: {', '.join(VALID_VIDEO_ENCODERS)}"
    )
    video_quality: int = Field(
        22,
        ge=0,
        le=51,
        description="Video quality (CRF-like, lower is better, 0-51)"
    )
    audio_encoder: str = Field(
        "copy",
        description=f"Audio encoder. Valid: {', '.join(VALID_AUDIO_ENCODERS)}"
    )
    subtitle_mode: str = Field(
        "all",
        description=f"Subtitle handling. Valid: {', '.join(VALID_SUBTITLE_MODES)}"
    )

    # File handling
    delete_source: bool = Field(
        True,
        description="Delete source files after successful transcode"
    )
    output_extension: str = Field("mkv", description="Output file extension")

    # Organization
    movies_subdir: str = Field("movies", description="Subdirectory for movies")
    tv_subdir: str = Field("tv", description="Subdirectory for TV shows")
    audio_subdir: str = Field("audio", description="Subdirectory for audio")

    # Concurrency
    max_concurrent: int = Field(
        1,
        ge=1,
        le=10,
        description="Max concurrent transcodes (1 recommended for single GPU)"
    )
    stabilize_seconds: int = Field(
        60,
        ge=10,
        le=600,
        description="Seconds to wait for source folder to stabilize"
    )

    # Disk space
    minimum_free_space_gb: float = Field(
        10.0,
        ge=1.0,
        description="Minimum free disk space required (GB)"
    )

    # Retry configuration
    max_retry_count: int = Field(
        3,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed jobs"
    )

    # Logging
    log_level: str = Field("INFO", description="Logging level")
    log_level_libraries: str = Field(
        "WARNING",
        description="Logging level for third-party libraries (aiosqlite, httpcore, httpx, uvicorn.access)",
    )

    @field_validator("video_encoder")
    @classmethod
    def validate_video_encoder(cls, v: str) -> str:
        """Validate video encoder."""
        if v not in VALID_VIDEO_ENCODERS:
            raise ValueError(
                f"Invalid video encoder: {v}. "
                f"Valid options: {', '.join(VALID_VIDEO_ENCODERS)}"
            )
        return v

    @field_validator("audio_encoder")
    @classmethod
    def validate_audio_encoder(cls, v: str) -> str:
        """Validate audio encoder."""
        if v not in VALID_AUDIO_ENCODERS:
            raise ValueError(
                f"Invalid audio encoder: {v}. "
                f"Valid options: {', '.join(VALID_AUDIO_ENCODERS)}"
            )
        return v

    @field_validator("subtitle_mode")
    @classmethod
    def validate_subtitle_mode(cls, v: str) -> str:
        """Validate subtitle mode."""
        if v not in VALID_SUBTITLE_MODES:
            raise ValueError(
                f"Invalid subtitle mode: {v}. "
                f"Valid options: {', '.join(VALID_SUBTITLE_MODES)}"
            )
        return v

    @field_validator("log_level", "log_level_libraries")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(
                f"Invalid log level: {v}. "
                f"Valid options: {', '.join(valid_levels)}"
            )
        return v_upper

    class Config:
        env_prefix = ""
        case_sensitive = False


settings = Settings()


def get_presets_by_file() -> dict[str, list[str]]:
    """Return a mapping of preset file path → list of preset names."""
    import json
    from pathlib import Path

    result: dict[str, list[str]] = {}
    preset_dir = Path(settings.preset_path)
    if not preset_dir.is_dir():
        return result
    for f in sorted(preset_dir.glob("*.json")):
        names: list[str] = []
        try:
            data = json.loads(f.read_text())
            for preset in data.get("PresetList", []):
                name = preset.get("PresetName", "")
                if name:
                    names.append(name)
        except (json.JSONDecodeError, OSError):
            pass
        if names:
            result[str(f)] = names
    return result


def get_available_presets() -> list[str]:
    """Scan preset JSON files and return all preset names (flat list)."""
    names: list[str] = []
    for file_names in get_presets_by_file().values():
        names.extend(file_names)
    return names


def get_preset_files() -> list[str]:
    """Return absolute paths of preset JSON files in the preset directory."""
    return list(get_presets_by_file().keys())


async def load_config_overrides():
    """Load persisted config overrides from DB and patch the settings singleton."""
    from database import get_db
    from models import ConfigOverrideDB
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(select(ConfigOverrideDB))
        overrides = result.scalars().all()

    for override in overrides:
        if override.key not in UPDATABLE_KEYS:
            continue
        field_info = Settings.model_fields.get(override.key)
        if not field_info:
            continue
        # Coerce value based on Pydantic field annotation
        annotation = field_info.annotation
        try:
            if annotation is bool:
                coerced = override.value.lower() in ("true", "1", "yes")
            elif annotation is int:
                coerced = int(override.value)
            elif annotation is float:
                coerced = float(override.value)
            else:
                coerced = override.value
            setattr(settings, override.key, coerced)
        except (ValueError, TypeError):
            pass  # skip invalid overrides


# --- GPU-aware preset auto-resolution ---
# Maps detected GPU family → default encoder + HandBrake preset names.
# Priority: NVENC (Nvidia) > QSV (Intel) > VCN (AMD) > software.

GPU_PRESET_DEFAULTS: dict[str, dict[str, str]] = {
    "nvenc": {
        "video_encoder": "nvenc_h265",
        "handbrake_preset": "H.265 NVENC 1080p",
        "handbrake_preset_4k": "H.265 NVENC 2160p 4K",
        "handbrake_preset_dvd": "H.265 NVENC 1080p",
    },
    "qsv": {
        "video_encoder": "qsv_h265",
        "handbrake_preset": "H.265 QSV 1080p",
        "handbrake_preset_4k": "H.265 QSV 2160p 4K",
        "handbrake_preset_dvd": "H.265 QSV 1080p",
    },
    "vcn": {
        "video_encoder": "vaapi_h265",
        "handbrake_preset": "H.265 VCN 1080p",
        "handbrake_preset_4k": "H.265 VCN 2160p 4K",
        "handbrake_preset_dvd": "H.265 VCN 1080p",
    },
    "software": {
        "video_encoder": "x265",
        "handbrake_preset": "H.265 MKV 1080p30",
        "handbrake_preset_4k": "H.265 MKV 2160p60 4K",
        "handbrake_preset_dvd": "H.265 MKV 720p30",
    },
}


def detect_best_gpu(gpu_support: dict) -> str:
    """Determine the best available GPU family from probe results."""
    if gpu_support.get("handbrake_nvenc") or gpu_support.get("ffmpeg_nvenc_h265"):
        return "nvenc"
    if gpu_support.get("ffmpeg_qsv_h265"):
        return "qsv"
    if gpu_support.get("ffmpeg_amf_h265") or gpu_support.get("ffmpeg_vaapi_h265"):
        return "vcn"
    return "software"


async def auto_resolve_gpu_defaults(gpu_support: dict):
    """Set encoder and preset defaults based on detected GPU.

    Only applies to keys that have no user override in the DB.
    This runs after load_config_overrides() so user choices always win.
    """
    import logging
    from database import get_db
    from models import ConfigOverrideDB
    from sqlalchemy import select

    logger = logging.getLogger(__name__)
    family = detect_best_gpu(gpu_support)
    defaults = GPU_PRESET_DEFAULTS[family]

    # Find which keys the user has explicitly overridden
    async with get_db() as db:
        result = await db.execute(select(ConfigOverrideDB.key))
        overridden_keys = {row[0] for row in result.all()}

    applied = {}
    for key, value in defaults.items():
        if key not in overridden_keys:
            setattr(settings, key, value)
            applied[key] = value

    if applied:
        logger.info(f"GPU auto-resolve ({family}): {applied}")
    else:
        logger.info(f"GPU detected: {family} (all keys have user overrides, skipping auto-resolve)")
