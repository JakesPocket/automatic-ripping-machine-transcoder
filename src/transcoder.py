"""
Transcode worker - handles GPU transcoding with HandBrake or FFmpeg
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import structlog
from sqlalchemy import select

from config import settings
from constants import (
    AUDIO_FILE_EXTENSIONS,
    PROGRESS_UPDATE_MIN_INTERVAL,
    PROGRESS_UPDATE_THRESHOLD,
)
from database import get_db
from log_format import json_formatter
from models import TranscodeJobDB, JobStatus, TranscodeJob
from utils import check_sufficient_disk_space, clean_title_for_filesystem, estimate_transcode_size

logger = logging.getLogger(__name__)


def check_gpu_support() -> dict:
    """Check which GPU encoders are available (NVENC, VAAPI, AMF, QSV)."""
    result = {
        "handbrake_nvenc": False,
        "handbrake_qsv": False,
        "ffmpeg_nvenc_h265": False,
        "ffmpeg_nvenc_h264": False,
        "ffmpeg_vaapi_h265": False,
        "ffmpeg_vaapi_h264": False,
        "ffmpeg_amf_h265": False,
        "ffmpeg_amf_h264": False,
        "ffmpeg_qsv_h265": False,
        "ffmpeg_qsv_h264": False,
        "vaapi_device": False,
    }

    # Check HandBrake encoder support (NVENC, QSV)
    try:
        output = subprocess.run(
            ["HandBrakeCLI", "--help"],
            capture_output=True, text=True, timeout=10
        )
        combined = output.stdout.lower() + output.stderr.lower()
        if "nvenc" in combined:
            result["handbrake_nvenc"] = True
        if "qsv" in combined:
            result["handbrake_qsv"] = True
    except Exception:
        pass

    # Check FFmpeg encoders (NVENC, VAAPI, AMF, QSV)
    try:
        output = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True, text=True, timeout=10
        )
        stdout = output.stdout
        # NVENC (NVIDIA)
        if "hevc_nvenc" in stdout:
            result["ffmpeg_nvenc_h265"] = True
        if "h264_nvenc" in stdout:
            result["ffmpeg_nvenc_h264"] = True
        # VAAPI (AMD/Intel on Linux)
        if "hevc_vaapi" in stdout:
            result["ffmpeg_vaapi_h265"] = True
        if "h264_vaapi" in stdout:
            result["ffmpeg_vaapi_h264"] = True
        # AMF (AMD)
        if "hevc_amf" in stdout:
            result["ffmpeg_amf_h265"] = True
        if "h264_amf" in stdout:
            result["ffmpeg_amf_h264"] = True
        # QSV (Intel Quick Sync)
        if "hevc_qsv" in stdout:
            result["ffmpeg_qsv_h265"] = True
        if "h264_qsv" in stdout:
            result["ffmpeg_qsv_h264"] = True
    except Exception:
        pass

    # Check for VAAPI/QSV device (typically /dev/dri/renderD128)
    vaapi_device = os.environ.get("VAAPI_DEVICE", "/dev/dri/renderD128")
    if os.path.exists(vaapi_device):
        result["vaapi_device"] = True

    return result


# Keep backward-compatible alias
check_nvenc_support = check_gpu_support


class TranscodeWorker:
    """Background worker that processes transcode jobs."""

    def __init__(self, gpu_support: dict | None = None):
        self._queue: asyncio.Queue[TranscodeJob] = asyncio.Queue()
        self._running = False
        self._current_job: Optional[str] = None
        self._shutdown_event = asyncio.Event()
        self._gpu_support = gpu_support if gpu_support is not None else check_gpu_support()
        self._last_progress: dict[int, float] = {}
        self._last_progress_time: dict[int, float] = {}
        self._queue_lock = asyncio.Lock()

        logger.info(f"GPU support: {self._gpu_support}")

        # Determine encoder family from settings (read after auto-resolve has run)
        encoder = settings.video_encoder
        self._encoder_family = self._detect_encoder_family(encoder)
        self._encoder_backend = self._select_backend(encoder, self._encoder_family)

        logger.info(f"Encoder family: {self._encoder_family}, backend: {self._encoder_backend}")

    def _effective(self, key: str, overrides: dict | None) -> object:
        """Return per-job override if set, otherwise global setting."""
        if overrides and key in overrides:
            return overrides[key]
        return getattr(settings, key)

    def _detect_encoder_family(self, encoder: str) -> str:
        """Determine encoder family from encoder name."""
        if "vaapi" in encoder:
            return "vaapi"
        if "amf" in encoder:
            return "amf"
        if "nvenc" in encoder:
            return "nvenc"
        if "qsv" in encoder:
            return "qsv"
        if encoder in ("x265", "x264"):
            return "software"
        return "unknown"

    def _select_backend(self, encoder: str, family: str) -> str:
        """Select transcoding backend (handbrake or ffmpeg) based on encoder."""
        if family == "nvenc":
            if self._gpu_support["handbrake_nvenc"]:
                logger.info("Using HandBrake with NVENC")
                return "handbrake"
            elif self._gpu_support["ffmpeg_nvenc_h265"] or self._gpu_support["ffmpeg_nvenc_h264"]:
                logger.info("Using FFmpeg with NVENC")
                return "ffmpeg"
            else:
                logger.warning("NVENC not detected - will attempt FFmpeg anyway")
                return "ffmpeg"
        elif family == "vaapi":
            if not self._gpu_support["vaapi_device"]:
                logger.warning("VAAPI device not found at /dev/dri/renderD128 - encoding may fail")
            logger.info("Using FFmpeg with VAAPI (AMD/Intel)")
            return "ffmpeg"
        elif family == "amf":
            logger.info("Using FFmpeg with AMF (AMD)")
            return "ffmpeg"
        elif family == "qsv":
            if self._gpu_support.get("handbrake_qsv"):
                logger.info("Using HandBrake with QSV")
                return "handbrake"
            logger.info("Using FFmpeg with Quick Sync (Intel)")
            return "ffmpeg"
        elif family == "software":
            logger.info("Using FFmpeg with software encoding")
            return "ffmpeg"
        else:
            logger.info("Using HandBrake (default backend)")
            return "handbrake"

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def current_job(self) -> Optional[str]:
        return self._current_job

    @property
    def gpu_support(self) -> dict:
        return self._gpu_support

    def shutdown(self):
        """Signal worker to shutdown."""
        self._shutdown_event.set()

    async def queue_job(
        self,
        source_path: str,
        title: str,
        arm_job_id: Optional[str] = None,
        existing_job_id: Optional[int] = None,
        video_type: Optional[str] = None,
        year: Optional[str] = None,
        disctype: Optional[str] = None,
        poster_url: Optional[str] = None,
        config_overrides: dict | None = None,
    ) -> tuple[int, bool]:
        """Add a job to the transcode queue.

        Returns (job_id, created) — created is False when an existing
        pending/processing job already covers the same source_path.
        """
        overrides_json = json.dumps(config_overrides) if config_overrides else None
        async with self._queue_lock:
            async with get_db() as db:
                if existing_job_id:
                    # Retry existing job
                    result = await db.execute(
                        select(TranscodeJobDB).where(TranscodeJobDB.id == existing_job_id)
                    )
                    job_db = result.scalar_one()
                else:
                    # Deduplicate: skip if an active job already exists for this source
                    result = await db.execute(
                        select(TranscodeJobDB).where(
                            TranscodeJobDB.source_path == source_path,
                            TranscodeJobDB.status.in_([JobStatus.PENDING, JobStatus.PROCESSING]),
                        )
                    )
                    existing = result.scalar_one_or_none()
                    if existing:
                        logger.info(
                            f"Duplicate webhook — job {existing.id} already "
                            f"{existing.status.value} for {source_path}"
                        )
                        return existing.id, False

                    # Create new job record
                    job_db = TranscodeJobDB(
                        title=title,
                        source_path=source_path,
                        arm_job_id=arm_job_id,
                        video_type=video_type,
                        year=year,
                        disctype=disctype,
                        poster_url=poster_url,
                        config_overrides=overrides_json,
                        status=JobStatus.PENDING,
                    )
                    db.add(job_db)
                    await db.commit()
                    await db.refresh(job_db)

                job = TranscodeJob(
                    id=job_db.id,
                    title=title,
                    source_path=source_path,
                    arm_job_id=arm_job_id,
                )

        await self._queue.put(job)
        logger.info(f"Queued job {job.id}: {title}")
        return job.id, True

    async def _update_job(self, job_id: int, **kwargs):
        """Update job fields using a short-lived DB session."""
        async with get_db() as db:
            result = await db.execute(
                select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
            )
            job_db = result.scalar_one()
            for key, value in kwargs.items():
                setattr(job_db, key, value)
            await db.commit()

    async def _update_progress(self, job_id: int, progress: float):
        """Update job progress with delta and time-based rate limiting."""
        now = asyncio.get_event_loop().time()
        last_progress = self._last_progress.get(job_id, -PROGRESS_UPDATE_THRESHOLD)
        last_time = self._last_progress_time.get(job_id, 0.0)

        delta = progress - last_progress
        elapsed = now - last_time

        if delta >= PROGRESS_UPDATE_THRESHOLD and elapsed >= PROGRESS_UPDATE_MIN_INTERVAL:
            await self._update_job(job_id, progress=progress)
            self._last_progress[job_id] = progress
            self._last_progress_time[job_id] = now

    async def run(self):
        """Main worker loop."""
        self._running = True
        logger.info("Transcode worker started")

        # Load any pending jobs from database on startup
        await self._load_pending_jobs()

        while not self._shutdown_event.is_set():
            try:
                # Wait for a job with timeout to allow shutdown checks
                try:
                    job = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue

                self._current_job = job.title
                await self._process_job(job)
                self._current_job = None
                self._queue.task_done()

            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
                await asyncio.sleep(5)

        self._running = False
        logger.info("Transcode worker stopped")

    async def _load_pending_jobs(self):
        """Load any pending jobs from database on startup."""
        async with get_db() as db:
            result = await db.execute(
                select(TranscodeJobDB)
                .where(TranscodeJobDB.status.in_([JobStatus.PENDING, JobStatus.PROCESSING]))
                .order_by(TranscodeJobDB.created_at)
            )
            jobs = result.scalars().all()

            for job_db in jobs:
                # Reset processing jobs to pending
                if job_db.status == JobStatus.PROCESSING:
                    job_db.status = JobStatus.PENDING
                    await db.commit()

                job = TranscodeJob(
                    id=job_db.id,
                    title=job_db.title,
                    source_path=job_db.source_path,
                    arm_job_id=job_db.arm_job_id,
                )
                await self._queue.put(job)
                logger.info(f"Restored pending job {job.id}: {job.title}")

    async def _process_job(self, job: TranscodeJob):  # noqa: C901
        """Process a single transcode job.

        Uses local scratch storage (work_path) to avoid doing heavy I/O on shared storage:
          1. Copy source from raw → local work dir
          2. Transcode locally
          3. Move output from local → completed
          4. Clean up local work dir (always, even on failure)
          5. Clean up raw source (if delete_source is set)

        Each DB update uses a short-lived session to avoid holding locks during
        long-running I/O (file copies, transcoding).
        """
        logger.info(f"Processing job {job.id}: {job.title}")

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            job_id=job.id,
            label=job.title,
            arm_job_id=job.arm_job_id,
        )

        work_job_dir = Path(settings.work_path) / f"job-{job.id}"
        logfile_name = f"job-{job.id}.log"
        job_handler = None

        try:
            # Attach a per-job log file so each job gets its own clean log.
            # Non-fatal: if the handler can't be created the global
            # transcoder.log still captures everything.
            try:
                log_dir = Path(settings.log_path)
                log_dir.mkdir(parents=True, exist_ok=True)
                job_handler = logging.FileHandler(str(log_dir / logfile_name))
                job_handler.setFormatter(json_formatter())

                _job_id = job.id  # capture for filter closure

                class _JobFilter(logging.Filter):
                    def filter(self, record):
                        ctx = structlog.contextvars.get_contextvars()
                        return ctx.get("job_id") == _job_id

                job_handler.addFilter(_JobFilter())
                logging.getLogger().addHandler(job_handler)
            except Exception:
                logger.warning(f"Could not create per-job log file: {logfile_name}")
                logfile_name = None

            # Update status to processing
            await self._update_job(
                job.id,
                status=JobStatus.PROCESSING,
                started_at=datetime.now(timezone.utc),
                logfile=logfile_name,
            )

            # Load per-job overrides and DB metadata
            overrides = None
            db_video_type = None
            db_year = None
            async with get_db() as db_sess:
                result = await db_sess.execute(
                    select(TranscodeJobDB).where(TranscodeJobDB.id == job.id)
                )
                job_db = result.scalar_one_or_none()
                if job_db:
                    db_video_type = job_db.video_type
                    db_year = job_db.year
                    if job_db.config_overrides:
                        try:
                            overrides = json.loads(job_db.config_overrides)
                        except (json.JSONDecodeError, TypeError):
                            pass
            if overrides:
                logger.info(f"Per-job overrides: {overrides}")

            # Resolve actual source path (ARM may move files to subdirectories)
            resolved_path = self._resolve_source_path(job.source_path)
            if resolved_path != job.source_path:
                await self._update_job(job.id, source_path=resolved_path)
                job.source_path = resolved_path

            # Wait for source to stabilize (files still being written)
            await self._wait_for_stable(job.source_path)

            # Discover source files
            source_files = self._discover_source_files(job.source_path)
            if not source_files:
                # ARM may have moved files during stabilization (race condition)
                resolved_path = self._resolve_source_path(job.source_path)
                if resolved_path != job.source_path:
                    await self._update_job(job.id, source_path=resolved_path)
                    job.source_path = resolved_path
                    await self._wait_for_stable(job.source_path)
                    source_files = self._discover_source_files(job.source_path)

            if not source_files:
                # Check for audio files (audio CD rip)
                audio_files = self._discover_audio_files(job.source_path)
                if audio_files:
                    await self._passthrough_audio(job)
                    return
                raise ValueError(f"No video or audio files found in {job.source_path}")

            await self._update_job(job.id, total_tracks=len(source_files))

            logger.info(f"Found {len(source_files)} MKV files to transcode")

            # Ensure work directory exists for disk space check and copy
            work_job_dir.mkdir(parents=True, exist_ok=True)

            # Check disk space before copying
            source_size = sum(f.stat().st_size for f in source_files)
            estimated_output = estimate_transcode_size(source_size)
            total_needed = source_size + estimated_output  # copy + transcode output
            sufficient, msg = check_sufficient_disk_space(
                settings.work_path, total_needed, settings.minimum_free_space_gb
            )
            if not sufficient:
                raise ValueError(msg)

            # Copy source to local scratch
            work_source_dir = work_job_dir / "source"
            work_output_dir = work_job_dir / "output"
            source = Path(job.source_path)
            work_output_dir.mkdir()

            logger.info(f"Copying source to local scratch: {work_source_dir}")
            if source.is_file():
                work_source_dir.mkdir()
                shutil.copy2(str(source), str(work_source_dir / source.name))
            else:
                shutil.copytree(str(source), str(work_source_dir))

            # Re-discover files from local copy
            local_source_files = self._discover_source_files(str(work_source_dir))

            # Find main feature (largest file) and probe resolution
            main_feature = max(local_source_files, key=lambda f: f.stat().st_size)
            resolution = await self._get_video_resolution(main_feature)
            await self._update_job(job.id, main_feature_file=main_feature.name)

            # Determine final output path (with metadata from resolution)
            output_dir = self._determine_output_path(
                job.title, job.source_path, resolution, overrides,
                db_year=db_year, db_video_type=db_video_type,
            )
            folder_name = output_dir.name
            os.makedirs(output_dir, exist_ok=True)
            await self._update_job(
                job.id,
                video_type=db_video_type or self._detect_video_type(job.title, job.source_path),
                output_path=str(output_dir),
            )

            # Transcode each file locally
            ext = self._effective("output_extension", overrides)
            for i, source_file in enumerate(local_source_files):
                progress = (i / len(local_source_files)) * 100
                await self._update_progress(job.id, progress)

                # Name output files using the metadata-enriched folder name
                is_main = source_file == main_feature
                if is_main or len(local_source_files) == 1:
                    output_file = work_output_dir / f"{folder_name}.{ext}"
                else:
                    output_file = work_output_dir / f"{folder_name} - {source_file.stem}.{ext}"

                logger.info(
                    f"Transcoding [{i+1}/{len(local_source_files)}]: {source_file.name}"
                    f"{' (main feature)' if is_main else ''}"
                )

                if self._encoder_backend == "ffmpeg":
                    await self._transcode_file_ffmpeg(source_file, output_file, job.id, overrides=overrides)
                else:
                    await self._transcode_file_handbrake(source_file, output_file, job.id, overrides=overrides)

            # Move local output → completed
            logger.info(f"Moving output to completed: {output_dir}")
            for f in work_output_dir.iterdir():
                shutil.move(str(f), str(output_dir / f.name))

            # Success
            await self._update_job(
                job.id,
                status=JobStatus.COMPLETED,
                progress=100.0,
                completed_at=datetime.now(timezone.utc),
            )

            # Clean up raw source if configured
            if self._effective("delete_source", overrides):
                try:
                    self._cleanup_source(job.source_path)
                    logger.info(f"Cleaned up source: {job.source_path}")
                except OSError as e:
                    logger.warning(f"Could not clean up source: {e}")

            logger.info(f"Completed job {job.id}: {job.title}")
            await self._notify_arm_callback(job, "completed")

        except Exception as e:
            logger.error(f"Job {job.id} failed: {e}", exc_info=True)
            try:
                await self._update_job(
                    job.id,
                    status=JobStatus.FAILED,
                    error=str(e),
                )
                await self._notify_arm_callback(job, "failed", error=str(e))
            except Exception:
                logger.error(f"Failed to update job {job.id} status to FAILED", exc_info=True)

        finally:
            # Always clean up local scratch
            if work_job_dir.exists():
                shutil.rmtree(work_job_dir)
                logger.info(f"Cleaned up work dir: {work_job_dir}")
            # Remove per-job log handler
            if job_handler:
                logging.getLogger().removeHandler(job_handler)
                job_handler.close()
            # Clean up progress tracking
            self._last_progress.pop(job.id, None)
            self._last_progress_time.pop(job.id, None)
            structlog.contextvars.clear_contextvars()

    def _resolve_source_path(self, source_path: str) -> str:
        """Resolve the actual source path, searching subdirectories if needed.

        ARM may move ripped files from raw/<TITLE>/ to raw/<type>/<TITLE_timestamp>/
        where type is 'unidentified', 'movies', or 'tv'. This method finds the
        actual location when the direct path doesn't exist or is empty.
        """
        path = Path(source_path)

        # If path exists and has media files, use it directly
        if path.exists() and path.is_dir():
            has_files = (
                any(path.glob("*.mkv"))
                or any(
                    f for f in path.iterdir()
                    if f.is_file() and f.suffix.lower() in AUDIO_FILE_EXTENSIONS
                )
            )
            if has_files:
                return source_path

        # Search subdirectories of raw_path for a matching title
        raw_path = Path(settings.raw_path)
        title = path.name  # e.g., "SERIAL_MOM"

        if not raw_path.exists():
            return source_path

        candidates = []
        for subdir in raw_path.iterdir():
            if not subdir.is_dir() or subdir == path:
                continue
            for candidate in subdir.iterdir():
                if not candidate.is_dir():
                    continue
                if not candidate.name.startswith(title):
                    continue
                # Verify it has actual media files
                has_media = (
                    any(candidate.glob("*.mkv"))
                    or any(
                        f for f in candidate.iterdir()
                        if f.is_file() and f.suffix.lower() in AUDIO_FILE_EXTENSIONS
                    )
                )
                if has_media:
                    # Security: ensure resolved path is still within raw_path
                    try:
                        candidate.resolve().relative_to(raw_path.resolve())
                        candidates.append(candidate)
                    except ValueError:
                        logger.warning(f"Skipping candidate outside raw_path: {candidate}")

        if not candidates:
            return source_path

        # Pick the most recently modified candidate
        best = max(candidates, key=lambda d: d.stat().st_mtime)
        logger.info(f"Resolved source path: {source_path} -> {best}")
        return str(best)

    async def _wait_for_stable(self, path: str, timeout: int = 3600):
        """Wait for directory to stop receiving new files."""
        path = Path(path)
        if not path.exists():
            # NFS mounts may lag behind — wait up to 60s for the path to appear
            logger.info(f"Source path not yet visible, waiting for NFS propagation: {path}")
            for _ in range(12):
                await asyncio.sleep(5)
                if path.exists():
                    break
            else:
                raise ValueError(f"Source path does not exist: {path}")

        logger.info(f"Waiting for source to stabilize: {path}")

        last_size = -1
        stable_time = 0
        start_time = asyncio.get_event_loop().time()

        while stable_time < settings.stabilize_seconds:
            current_size = sum(
                f.stat().st_size for f in path.rglob('*') if f.is_file()
            )

            if current_size == last_size:
                stable_time += 5
            else:
                stable_time = 0
                last_size = current_size

            await asyncio.sleep(5)

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                raise TimeoutError(f"Source still changing after {timeout}s")

        logger.info(f"Source stabilized at {last_size} bytes")

    async def _notify_arm_callback(self, job: TranscodeJob, status: str, error: str | None = None):
        """Send transcode result back to ARM so it can update the job status."""
        if not settings.arm_callback_url or not job.arm_job_id:
            return
        url = f"{settings.arm_callback_url.rstrip('/')}/api/v1/jobs/{job.arm_job_id}/transcode-callback"
        payload: dict = {"status": status}
        if error:
            payload["error"] = error[:500]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
            logger.info(f"ARM callback sent ({resp.status_code}): {status} for ARM job {job.arm_job_id}")
        except Exception as e:
            logger.warning(f"Failed to send ARM callback for job {job.arm_job_id}: {e}")

    def _discover_source_files(self, source_path: str) -> list[Path]:
        """Find all MKV files in source directory."""
        path = Path(source_path)

        if path.is_file():
            return [path] if path.suffix.lower() == '.mkv' else []

        # Find all MKV files, sorted by size (largest first)
        mkv_files = list(path.glob("*.mkv"))
        mkv_files.sort(key=lambda f: f.stat().st_size, reverse=True)

        return mkv_files

    def _discover_audio_files(self, source_path: str) -> list[Path]:
        """Find all audio files in source directory."""
        path = Path(source_path)

        if path.is_file():
            return [path] if path.suffix.lower() in AUDIO_FILE_EXTENSIONS else []

        audio_files = [
            f for f in path.iterdir()
            if f.is_file() and f.suffix.lower() in AUDIO_FILE_EXTENSIONS
        ]
        audio_files.sort(key=lambda f: f.name)

        return audio_files

    async def _passthrough_audio(self, job: TranscodeJob):
        """Copy audio files directly to audio output folder (no transcoding)."""
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            job_id=job.id,
            label=job.title,
            arm_job_id=job.arm_job_id,
        )
        clean_title = clean_title_for_filesystem(job.title)
        output_dir = Path(settings.completed_path) / settings.audio_subdir / clean_title
        os.makedirs(output_dir, exist_ok=True)

        audio_files = self._discover_audio_files(job.source_path)

        logger.info(f"Audio passthrough: copying {len(audio_files)} audio files to {output_dir}")

        for f in audio_files:
            shutil.copy2(str(f), str(output_dir / f.name))

        await self._update_job(
            job.id,
            output_path=str(output_dir),
            total_tracks=len(audio_files),
            status=JobStatus.COMPLETED,
            progress=100.0,
            completed_at=datetime.now(timezone.utc),
        )

        logger.info(f"Completed audio passthrough for job {job.id}: {job.title}")
        await self._notify_arm_callback(job, "completed")

        # Clean up source directory if delete_source is set (non-fatal)
        if settings.delete_source:
            try:
                self._cleanup_source(job.source_path)
                logger.info(f"Cleaned up source: {job.source_path}")
            except OSError as e:
                logger.warning(f"Could not clean up source {job.source_path}: {e}")

    def _detect_video_type(self, title: str, source_path: str) -> str:
        """Detect whether content is a TV show or movie based on naming patterns.

        ARM uses patterns like 'Show S01', 'Show S01E01', 'Show_S02E03'
        for TV rips. Returns 'tv' or 'movie'.
        """
        # Check both title and source directory name
        dir_name = Path(source_path).name
        for text in [title, dir_name]:
            if re.search(r'S\d{1,2}(E\d{1,2})?', text, re.IGNORECASE):
                return "tv"
        return "movie"

    @staticmethod
    def _classify_media_type(height: int) -> str:
        """Return media type label from resolution height."""
        if height < 720:
            return "DVD"
        if height <= 1080:
            return "Blu-ray"
        return "UHD Blu-ray"

    @staticmethod
    def _format_resolution(height: int) -> str:
        """Return resolution string from height."""
        if height < 720:
            return "480p"
        if height == 720:
            return "720p"
        if height == 1080:
            return "1080p"
        if height == 2160:
            return "2160p"
        return f"{height}p"

    def _get_codec_name(self, overrides: dict | None = None) -> str:
        """Map settings.video_encoder to a display name."""
        encoder = str(self._effective("video_encoder", overrides)).lower()
        h265_names = {
            "nvenc_h265", "hevc_nvenc", "vaapi_h265", "hevc_vaapi",
            "amf_h265", "hevc_amf", "qsv_h265", "hevc_qsv", "x265",
        }
        h264_names = {
            "nvenc_h264", "h264_nvenc", "vaapi_h264", "h264_vaapi",
            "amf_h264", "h264_amf", "qsv_h264", "h264_qsv", "x264",
        }
        if encoder in h265_names:
            return "HEVC"
        if encoder in h264_names:
            return "H264"
        return encoder.upper()

    def _determine_output_path(
        self, title: str, source_path: str,
        resolution: tuple[int, int] | None = None,
        overrides: dict | None = None,
        *, db_year: str | None = None, db_video_type: str | None = None,
    ) -> Path:
        """Determine the output directory path.

        Builds a metadata-enriched folder name like:
          Serial Mom (1994) 480p DVD HEVC

        Prefers DB values (db_year, db_video_type) from the webhook payload
        over re-detecting from the directory name / title patterns.
        """
        video_type = db_video_type or self._detect_video_type(title, source_path)
        if video_type in ("tv", "series"):
            base = Path(settings.completed_path) / settings.tv_subdir
        else:
            base = Path(settings.completed_path) / settings.movies_subdir

        clean_title = clean_title_for_filesystem(title)

        # Prefer year from DB; fall back to extracting from directory name
        year = db_year if db_year and db_year not in ("", "0000") else None
        if not year:
            dir_name = Path(source_path).name
            year_match = re.search(r'\((\d{4})\)', dir_name)
            year = year_match.group(1) if year_match else None

        # Build metadata suffix if resolution is available
        if resolution:
            height = resolution[1]
            res_str = self._format_resolution(height)
            media_type = self._classify_media_type(height)
            codec = self._get_codec_name(overrides)
            if year:
                folder_name = f"{clean_title} ({year}) {res_str} {media_type} {codec}"
            else:
                folder_name = f"{clean_title} {res_str} {media_type} {codec}"
        else:
            if year:
                folder_name = f"{clean_title} ({year})"
            else:
                folder_name = clean_title

        folder_name = clean_title_for_filesystem(folder_name)
        return base / folder_name

    async def _transcode_file_handbrake(
        self,
        source: Path,
        output: Path,
        job_id: int,
        overrides: dict | None = None,
    ):
        """Transcode a single file using HandBrake."""
        # Resolution-based preset selection
        resolution = await self._get_video_resolution(source)
        extra_args = []
        if resolution and resolution[1] > 1080:
            preset = self._effective("handbrake_preset_4k", overrides)
            logger.info(f"4K source ({resolution[0]}x{resolution[1]}), using preset: {preset}")
        elif resolution and resolution[1] < 720:
            preset = self._effective("handbrake_preset_dvd", overrides) or self._effective("handbrake_preset", overrides)
            extra_args = ["--width", "1280"]
            logger.info(f"Low-res source ({resolution[0]}x{resolution[1]}), using preset: {preset}, upscaling to 720p")
        else:
            preset = self._effective("handbrake_preset", overrides)

        cmd = [
            "HandBrakeCLI",
            "-i", str(source),
            "-o", str(output),
        ]

        # Add encoder
        video_encoder = self._effective("video_encoder", overrides)
        if video_encoder:
            cmd.extend(["--encoder", str(video_encoder)])

        # Add quality
        cmd.extend(["-q", str(self._effective("video_quality", overrides))])

        # Add preset if specified
        preset_file = self._effective("handbrake_preset_file", overrides)
        if preset_file:
            cmd.extend(["--preset-import-file", str(preset_file)])
        if preset:
            cmd.extend(["--preset", str(preset)])

        # Add resolution-based extra args (e.g. upscale for DVD)
        cmd.extend(extra_args)

        # Audio handling
        audio_encoder = self._effective("audio_encoder", overrides)
        if audio_encoder == "copy":
            cmd.extend(["--aencoder", "copy"])
            # Override preset's CopyMask so all common codecs pass through
            cmd.extend(["--audio-copy-mask",
                         "aac,ac3,eac3,dts,dtshd,truehd,flac,mp2,mp3"])
            cmd.extend(["--audio-fallback", "aac"])
        else:
            cmd.extend(["--aencoder", str(audio_encoder)])

        # Subtitle handling
        subtitle_mode = self._effective("subtitle_mode", overrides)
        if subtitle_mode == "all":
            cmd.extend(["--all-subtitles"])
        elif subtitle_mode == "first":
            cmd.extend(["--subtitle", "1"])

        logger.debug(f"HandBrake command: {' '.join(cmd)}")

        # Run HandBrake and parse progress
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Parse output for progress
        async for line in process.stdout:
            line = line.decode('utf-8', errors='replace').strip()

            # Parse HandBrake progress: "Encoding: task 1 of 1, 45.23 %"
            match = re.search(r'(\d+\.?\d*)\s*%', line)
            if match:
                file_progress = float(match.group(1))
                await self._update_progress(job_id, file_progress)

        await process.wait()

        if process.returncode != 0:
            raise RuntimeError(f"HandBrake failed with exit code {process.returncode}")

        # Verify output exists
        if not output.exists():
            raise RuntimeError(f"Output file was not created: {output}")

        logger.info(f"Transcoded: {source.name} -> {output.name}")

    def _build_ffmpeg_command(  # noqa: C901
        self, source: Path, output: Path,
        resolution: Optional[tuple[int, int]] = None,
        overrides: dict | None = None,
    ) -> list[str]:
        """Build FFmpeg command based on encoder family."""
        encoder_name = str(self._effective("video_encoder", overrides))
        family = self._detect_encoder_family(encoder_name) if overrides and "video_encoder" in overrides else self._encoder_family
        quality = self._effective("video_quality", overrides)

        # Determine FFmpeg encoder name
        if family == "nvenc":
            if "h265" in encoder_name or "hevc" in encoder_name:
                ffmpeg_encoder = "hevc_nvenc"
            else:
                ffmpeg_encoder = "h264_nvenc"
        elif family == "vaapi":
            if "h265" in encoder_name or "hevc" in encoder_name:
                ffmpeg_encoder = "hevc_vaapi"
            else:
                ffmpeg_encoder = "h264_vaapi"
        elif family == "amf":
            if "h265" in encoder_name or "hevc" in encoder_name:
                ffmpeg_encoder = "hevc_amf"
            else:
                ffmpeg_encoder = "h264_amf"
        elif family == "qsv":
            if "h265" in encoder_name or "hevc" in encoder_name:
                ffmpeg_encoder = "hevc_qsv"
            else:
                ffmpeg_encoder = "h264_qsv"
        elif family == "software":
            if encoder_name == "x265":
                ffmpeg_encoder = "libx265"
            else:
                ffmpeg_encoder = "libx264"
        else:
            ffmpeg_encoder = encoder_name

        cmd = ["ffmpeg", "-y"]

        # Hardware acceleration input flags (per encoder family)
        if family == "nvenc":
            cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])
        elif family == "vaapi":
            vaapi_device = os.environ.get("VAAPI_DEVICE", "/dev/dri/renderD128")
            cmd.extend([
                "-hwaccel", "vaapi",
                "-hwaccel_device", vaapi_device,
                "-hwaccel_output_format", "vaapi",
            ])
        elif family == "qsv":
            cmd.extend(["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"])

        # Input file
        cmd.extend(["-i", str(source)])

        # Explicit stream mapping to preserve multi-track audio/subtitles
        subtitle_mode = self._effective("subtitle_mode", overrides)
        cmd.extend(["-map", "0:v:0"])   # first video stream
        cmd.extend(["-map", "0:a?"])    # all audio streams (optional)
        if subtitle_mode == "all":
            cmd.extend(["-map", "0:s?"])    # all subtitles (optional)
        elif subtitle_mode == "first":
            cmd.extend(["-map", "0:s:0?"])  # first subtitle only (optional)

        # Video encoder
        cmd.extend(["-c:v", ffmpeg_encoder])

        # Quality settings (per encoder family)
        if family == "nvenc":
            cmd.extend(["-preset", "p4", "-cq", str(quality), "-b:v", "0"])
        elif family == "vaapi":
            cmd.extend(["-rc_mode", "CQP", "-qp", str(quality)])
        elif family == "amf":
            cmd.extend(["-rc", "cqp", "-qp_i", str(quality), "-qp_p", str(quality)])
        elif family == "qsv":
            cmd.extend(["-global_quality", str(quality)])
        elif family == "software":
            cmd.extend(["-crf", str(quality), "-preset", "medium"])

        # Upscale low-res sources (DVD) to 720p
        if resolution and resolution[1] < 720:
            if family == "nvenc":
                cmd.extend(["-vf", "scale_cuda=1280:-2"])
            elif family == "vaapi":
                cmd.extend(["-vf", "scale_vaapi=w=1280:h=-2"])
            elif family == "qsv":
                cmd.extend(["-vf", "vpp_qsv=w=1280:h=-2"])
            else:
                cmd.extend(["-vf", "scale=1280:-2"])
            logger.info(f"Low-res source ({resolution[0]}x{resolution[1]}), upscaling to 720p")

        # Audio handling
        audio_encoder = self._effective("audio_encoder", overrides)
        if audio_encoder == "copy":
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", str(audio_encoder)])

        # Subtitle handling (stream selection handled by -map above)
        if subtitle_mode in ("all", "first"):
            cmd.extend(["-c:s", "copy"])

        # Output
        cmd.append(str(output))

        return cmd

    async def _transcode_file_ffmpeg(
        self,
        source: Path,
        output: Path,
        job_id: int,
        overrides: dict | None = None,
    ):
        """Transcode a single file using FFmpeg."""
        resolution = await self._get_video_resolution(source)
        cmd = self._build_ffmpeg_command(source, output, resolution, overrides)

        logger.debug(f"FFmpeg command: {' '.join(cmd)}")

        # Run FFmpeg and parse progress
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Get duration for progress calculation
        duration = await self._get_video_duration(source)

        async for line in process.stdout:
            line = line.decode('utf-8', errors='replace').strip()

            # Parse FFmpeg progress: "time=00:01:23.45"
            match = re.search(r'time=(\d+):(\d+):(\d+\.?\d*)', line)
            if match and duration:
                hours, mins, secs = match.groups()
                current_secs = int(hours) * 3600 + int(mins) * 60 + float(secs)
                file_progress = min(100, (current_secs / duration) * 100)
                await self._update_progress(job_id, file_progress)

        await process.wait()

        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg failed with exit code {process.returncode}")

        if not output.exists():
            raise RuntimeError(f"Output file was not created: {output}")

        logger.info(f"Transcoded: {source.name} -> {output.name}")

    async def _get_video_resolution(self, path: Path) -> Optional[tuple[int, int]]:
        """Get video resolution (width, height) using ffprobe."""
        try:
            result = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await result.communicate()
            parts = stdout.decode().strip().split("x")
            return (int(parts[0]), int(parts[1]))
        except Exception:
            return None

    async def _get_video_duration(self, path: Path) -> Optional[float]:
        """Get video duration in seconds using ffprobe."""
        try:
            result = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await result.communicate()
            return float(stdout.decode().strip())
        except Exception:
            return None

    def _cleanup_source(self, source_path: str):
        """Remove source files after successful transcode."""
        path = Path(source_path)

        if not path.exists():
            logger.warning(f"Source already removed: {source_path}")
            return

        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
