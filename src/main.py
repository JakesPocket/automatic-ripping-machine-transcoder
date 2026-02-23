"""
ARM Transcoder - Webhook receiver and transcode orchestrator
"""

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import platform
import re
from contextlib import asynccontextmanager
from pathlib import Path

import psutil

from fastapi import FastAPI, Depends, HTTPException, Query, Request
from sqlalchemy import select, delete, func

from auth import get_current_user, require_admin, verify_webhook_secret
from config import (
    settings, UPDATABLE_KEYS, VALID_LOG_LEVELS, get_available_presets,
    get_preset_files, get_presets_by_file, load_config_overrides,
    auto_resolve_gpu_defaults,
)
from constants import SHUTDOWN_TIMEOUT, VALID_VIDEO_ENCODERS, VALID_AUDIO_ENCODERS, VALID_SUBTITLE_MODES
from database import init_db, get_db
from models import WebhookPayload, JobStatus, TranscodeJobDB, ConfigOverrideDB
from transcoder import TranscodeWorker


def _configure_logging():
    log_level = getattr(logging, settings.log_level)
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    root = logging.getLogger()
    root.setLevel(log_level)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    log_dir = Path(settings.log_path)
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        log_dir / "transcoder.log", maxBytes=10_485_760, backupCount=5
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)


_configure_logging()
logger = logging.getLogger(__name__)

# Global worker instance
worker: TranscodeWorker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    global worker

    # Initialize database
    await init_db()

    # Apply any persisted config overrides
    await load_config_overrides()

    # Probe GPU, auto-resolve defaults, then start worker with resolved settings
    from transcoder import check_gpu_support
    gpu_support = check_gpu_support()
    await auto_resolve_gpu_defaults(gpu_support)

    worker = TranscodeWorker(gpu_support=gpu_support)
    worker_task = asyncio.create_task(worker.run())

    logger.info("ARM Transcoder started")

    yield

    # Shutdown: signal worker to stop, then wait for current job to finish
    if worker:
        worker.shutdown()
        try:
            await asyncio.wait_for(worker_task, timeout=SHUTDOWN_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(f"Worker did not finish within {SHUTDOWN_TIMEOUT}s, cancelling")
            worker_task.cancel()
        except asyncio.CancelledError:
            pass
    else:
        worker_task.cancel()

    logger.info("ARM Transcoder stopped")


app = FastAPI(
    title="ARM Transcoder",
    description="GPU-accelerated transcoding service for Automatic Ripping Machine",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Health check endpoint with GPU support and active configuration."""
    gpu_support = worker.gpu_support if worker else {}
    return {
        "status": "healthy",
        "worker_running": worker is not None and worker.is_running,
        "queue_size": worker.queue_size if worker else 0,
        "gpu_support": gpu_support,
        "config": {
            "video_encoder": settings.video_encoder,
            "video_quality": settings.video_quality,
            "audio_encoder": settings.audio_encoder,
            "subtitle_mode": settings.subtitle_mode,
            "delete_source": settings.delete_source,
            "output_extension": settings.output_extension,
            "max_concurrent": settings.max_concurrent,
            "stabilize_seconds": settings.stabilize_seconds,
        },
        "require_api_auth": settings.require_api_auth,
        "webhook_secret_configured": bool(settings.webhook_secret),
    }


def _detect_cpu() -> str:
    """Detect CPU model name from /proc/cpuinfo (Linux) or platform fallback."""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "Unknown"


@app.get("/system/info")
async def get_system_info():
    """Return static hardware identity (CPU, RAM, GPU). No auth required."""
    mem = psutil.virtual_memory()
    return {
        "cpu": _detect_cpu(),
        "memory_total_gb": round(mem.total / 1073741824, 1),
        "gpu_support": worker.gpu_support if worker else {},
    }


@app.get("/system/stats")
async def get_system_stats():
    """Return live system metrics: CPU, memory, temperature. No auth required."""
    cpu_percent = psutil.cpu_percent()
    cpu_temp = 0.0
    try:
        temps = psutil.sensors_temperatures()
        for key in ('coretemp', 'cpu_thermal', 'k10temp', 'zenpower'):
            if temps.get(key):
                cpu_temp = temps[key][0].current
                break
    except (AttributeError, OSError):
        pass

    mem = psutil.virtual_memory()

    storage = []
    media_paths = [
        ("Raw", settings.raw_path),
        ("Completed", settings.completed_path),
        ("Work", settings.work_path),
    ]
    for name, path in media_paths:
        try:
            usage = psutil.disk_usage(path)
            storage.append({
                "name": name,
                "path": path,
                "total_gb": round(usage.total / 1073741824, 1),
                "used_gb": round(usage.used / 1073741824, 1),
                "free_gb": round(usage.free / 1073741824, 1),
                "percent": usage.percent,
            })
        except (FileNotFoundError, OSError):
            continue

    return {
        "cpu_percent": cpu_percent,
        "cpu_temp": cpu_temp,
        "memory": {
            "total_gb": round(mem.total / 1073741824, 1),
            "used_gb": round(mem.used / 1073741824, 1),
            "free_gb": round(mem.available / 1073741824, 1),
            "percent": mem.percent,
        },
        "storage": storage,
    }


@app.get("/config")
async def get_config(_role: str = Depends(get_current_user)):
    """Return current updatable settings and valid option lists."""
    config = {key: getattr(settings, key) for key in UPDATABLE_KEYS}
    return {
        "config": config,
        "updatable_keys": sorted(UPDATABLE_KEYS),
        "paths": {
            "raw_path": settings.raw_path,
            "completed_path": settings.completed_path,
            "work_path": settings.work_path,
        },
        "valid_video_encoders": VALID_VIDEO_ENCODERS,
        "valid_audio_encoders": VALID_AUDIO_ENCODERS,
        "valid_subtitle_modes": VALID_SUBTITLE_MODES,
        "valid_log_levels": VALID_LOG_LEVELS,
        "valid_handbrake_presets": get_available_presets(),
        "valid_preset_files": get_preset_files(),
        "presets_by_file": get_presets_by_file(),
    }


@app.patch("/config")
async def update_config(
    request: Request,
    _role: str = Depends(require_admin),
):
    """Update runtime settings. Validates, persists to DB, patches singleton."""
    data = await request.json()
    if not isinstance(data, dict) or not data:
        raise HTTPException(status_code=400, detail="Request body must be a non-empty JSON object")

    # Reject unknown keys
    invalid_keys = set(data.keys()) - UPDATABLE_KEYS
    if invalid_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Non-updatable keys: {', '.join(sorted(invalid_keys))}",
        )

    # Validate values by building a partial Settings with overrides
    current_vals = {key: getattr(settings, key) for key in UPDATABLE_KEYS}
    current_vals.update(data)
    try:
        from config import Settings as SettingsClass
        validated = SettingsClass.model_validate({**settings.model_dump(), **current_vals})
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Persist to DB and update in-memory singleton
    from datetime import datetime, timezone
    async with get_db() as db:
        for key, value in data.items():
            coerced = getattr(validated, key)
            override = await db.get(ConfigOverrideDB, key)
            if override:
                override.value = str(coerced)
                override.updated_at = datetime.now(timezone.utc)
            else:
                db.add(ConfigOverrideDB(key=key, value=str(coerced)))
            setattr(settings, key, coerced)
        await db.commit()

    return {
        "success": True,
        "applied": {key: getattr(settings, key) for key in data},
    }


@app.post("/webhook/arm")
async def arm_webhook(
    request: Request,
    _verified: bool = Depends(verify_webhook_secret),
):
    """
    Receive webhook from ARM's JSON_URL or BASH_SCRIPT curl.

    Expected payload formats:

    1. Apprise JSON format:
    {
        "title": "ARM notification",
        "body": "Rip of Movie Title (2024) complete",
        "type": "info"
    }

    2. Custom format from BASH_SCRIPT:
    {
        "title": "Movie Title",
        "path": "/home/arm/media/raw/Movie Title (2024)",
        "job_id": "123",
        "status": "success"
    }
    """
    # Validate request size (10KB limit)
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 10240:  # 10KB
        raise HTTPException(status_code=413, detail="Payload too large (max 10KB)")

    try:
        payload_dict = await request.json()
        # Validate with Pydantic model
        payload = WebhookPayload(**payload_dict)
    except Exception as e:
        logger.warning(f"Invalid webhook payload: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    # Use effective_body which handles both 'body' (curl) and 'message' (Apprise) fields
    body = payload.effective_body
    logger.info(f"Received webhook: {payload.title} (body={'present' if body else 'empty'})")

    # Check if this is a completion notification
    is_complete = (
        "complete" in payload.title.lower() or
        (body and "complete" in body.lower()) or
        payload.status == "success"
    )

    if not is_complete:
        logger.debug(f"Ignoring non-completion webhook: {payload.title}")
        return {"status": "ignored", "reason": "not a completion event"}

    # Determine source path
    source_path = payload.path

    # Extract media title from body
    # ARM notification formats:
    #   "{title} rip complete. Starting transcode."  (NOTIFY_RIP)
    #   "{title} processing complete."               (NOTIFY_TRANSCODE)
    #   "Rip of {title} complete"                    (legacy/custom)
    title_from_body = None
    if body:
        for pattern in [
            r"^(.+?)\s+rip complete",           # ARM rip notification
            r"^(.+?)\s+processing complete",     # ARM transcode notification
            r"Rip of (.+?) complete",            # legacy format
        ]:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                title_from_body = match.group(1).strip()
                break

    # Use extracted title as source path if no explicit path provided
    if not source_path and title_from_body:
        safe_title = Path(title_from_body).name
        source_path = safe_title

    if not source_path:
        logger.warning(f"Could not determine path from webhook: {payload.title}")
        return {"status": "error", "reason": "could not determine source path"}

    # Security: reject traversal attempts but allow relative subdirectories
    # (e.g. "movies/Title (Year)" is valid, ".." and "\" are not)
    if "\\" in source_path or ".." in source_path:
        logger.warning(f"Rejected path with traversal attempt: {source_path}")
        return {"status": "error", "reason": "invalid path"}

    # Construct full path within RAW_PATH
    full_path = str(Path(settings.raw_path) / source_path)

    # Guard against worker not being ready
    if worker is None or not worker.is_running:
        raise HTTPException(status_code=503, detail="Transcoder not ready")

    # Queue the transcode job — use extracted media title for output naming
    job_title = title_from_body or payload.title
    await worker.queue_job(
        source_path=full_path,
        title=job_title,
        arm_job_id=payload.job_id,
        video_type=payload.video_type,
        year=payload.year,
        disctype=payload.disctype,
    )

    return {
        "status": "queued",
        "path": source_path,
        "queue_size": worker.queue_size,
    }


@app.get("/jobs")
async def list_jobs(
    status: JobStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    _role: str = Depends(get_current_user),
):
    """List all transcode jobs, optionally filtered by status."""
    # Validate pagination
    if limit > 500:
        limit = 500
    if limit < 1:
        limit = 1
    if offset < 0:
        offset = 0

    async with get_db() as db:
        query = select(TranscodeJobDB)
        if status:
            query = query.where(TranscodeJobDB.status == status)
        query = query.order_by(TranscodeJobDB.created_at.desc())

        # Get total count
        count_query = select(func.count()).select_from(TranscodeJobDB)
        if status:
            count_query = count_query.where(TranscodeJobDB.status == status)
        total_result = await db.execute(count_query)
        total = total_result.scalar()

        # Apply pagination
        query = query.limit(limit).offset(offset)

        result = await db.execute(query)
        jobs = result.scalars().all()

        return {
            "jobs": [
                {
                    "id": job.id,
                    "title": job.title,
                    "source_path": job.source_path,
                    "status": job.status,
                    "progress": job.progress,
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                    "error": job.error,
                }
                for job in jobs
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@app.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: int,
    _role: str = Depends(require_admin),
):
    """Retry a failed job (admin only)."""
    if worker is None or not worker.is_running:
        raise HTTPException(status_code=503, detail="Transcoder not ready")

    async with get_db() as db:
        result = await db.execute(
            select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        if job.status != JobStatus.FAILED:
            raise HTTPException(status_code=400, detail="Job is not in failed state")

        # Check retry limit
        if job.retry_count >= settings.max_retry_count:
            raise HTTPException(
                status_code=400,
                detail=f"Maximum retry limit reached ({settings.max_retry_count})"
            )

        # Reset job status
        job.status = JobStatus.PENDING
        job.error = None
        job.progress = 0
        job.retry_count += 1
        await db.commit()

        # Re-queue
        await worker.queue_job(
            source_path=job.source_path,
            title=job.title,
            arm_job_id=job.arm_job_id,
            existing_job_id=job.id,
        )

        return {"status": "queued", "job_id": job.id, "retry_count": job.retry_count}


@app.delete("/jobs/{job_id}")
async def delete_job(
    job_id: int,
    _role: str = Depends(require_admin),
):
    """Delete a job from the database (admin only)."""
    async with get_db() as db:
        result = await db.execute(
            select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        if job.status == JobStatus.PROCESSING:
            raise HTTPException(status_code=400, detail="Cannot delete job in progress")

        await db.execute(delete(TranscodeJobDB).where(TranscodeJobDB.id == job_id))
        await db.commit()

        return {"status": "deleted", "job_id": job_id}


@app.get("/stats")
async def get_stats(_role: str = Depends(get_current_user)):
    """Get transcoding statistics."""
    async with get_db() as db:
        # Count by status
        result = await db.execute(
            select(TranscodeJobDB.status, func.count(TranscodeJobDB.id))
            .group_by(TranscodeJobDB.status)
        )
        status_counts = dict(result.all())

        return {
            "pending": status_counts.get(JobStatus.PENDING, 0),
            "processing": status_counts.get(JobStatus.PROCESSING, 0),
            "completed": status_counts.get(JobStatus.COMPLETED, 0),
            "failed": status_counts.get(JobStatus.FAILED, 0),
            "cancelled": status_counts.get(JobStatus.CANCELLED, 0),
            "worker_running": worker is not None and worker.is_running,
            "current_job": worker.current_job if worker else None,
        }


@app.get("/logs")
async def list_logs(_role: str = Depends(get_current_user)):
    """List available log files."""
    from log_reader import list_logs as _list_logs
    return _list_logs()


@app.get("/logs/{filename}")
async def get_log(
    filename: str,
    mode: str = Query("tail", pattern="^(tail|full)$"),
    lines: int = Query(100, ge=1, le=10000),
    _role: str = Depends(get_current_user),
):
    """Read a log file's content."""
    from log_reader import read_log
    result = read_log(filename, mode=mode, lines=lines)
    if result is None:
        raise HTTPException(status_code=404, detail="Log file not found")
    return result
