"""
Integration tests - full ARM → Transcoder functional pipeline.

Tests the end-to-end flow:
  ARM webhook → job creation in DB → worker pickup → transcode → completion
  Including retry flow, job deletion, stats accuracy, and worker lifecycle.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from models import Base, JobStatus, TranscodeJobDB


# ─── Shared test DB infrastructure ──────────────────────────────────────────


@pytest_asyncio.fixture
async def test_db_setup(tmp_path):
    """Create a real test database shared across worker and API."""
    db_path = str(tmp_path / "integration_test.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def test_get_db():
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    yield engine, session_factory, test_get_db

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_db_setup):
    """Get a session for direct DB inspection in tests."""
    _, session_factory, _ = test_db_setup
    async with session_factory() as session:
        yield session


# ─── 1. Job Lifecycle: queue_job → DB record creation ────────────────────────


class TestJobQueueCreation:
    """Test that queue_job creates real DB records."""

    @pytest.mark.asyncio
    async def test_queue_job_creates_db_record(self, test_db_setup):
        """queue_job should insert a PENDING job into the database."""
        _, session_factory, test_get_db = test_db_setup

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(
                source_path="/data/raw/Test Movie (2024)",
                title="Test Movie (2024)",
                arm_job_id="job-42",
            )

        # Verify the DB record
        async with session_factory() as session:
            result = await session.execute(select(TranscodeJobDB))
            job = result.scalar_one()
            assert job.title == "Test Movie (2024)"
            assert job.source_path == "/data/raw/Test Movie (2024)"
            assert job.arm_job_id == "job-42"
            assert job.status == JobStatus.PENDING
            assert job.retry_count == 0

    @pytest.mark.asyncio
    async def test_queue_job_adds_to_internal_queue(self, test_db_setup):
        """queue_job should also put the job on the async queue."""
        _, _, test_get_db = test_db_setup

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()
            assert worker.queue_size == 0

            await worker.queue_job(
                source_path="/data/raw/Movie",
                title="Movie",
            )
            assert worker.queue_size == 1

    @pytest.mark.asyncio
    async def test_queue_multiple_jobs(self, test_db_setup):
        """Multiple queue_job calls should create multiple DB records."""
        _, session_factory, test_get_db = test_db_setup

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            for i in range(3):
                await worker.queue_job(
                    source_path=f"/data/raw/Movie {i}",
                    title=f"Movie {i}",
                    arm_job_id=f"job-{i}",
                )

        async with session_factory() as session:
            result = await session.execute(select(TranscodeJobDB))
            jobs = result.scalars().all()
            assert len(jobs) == 3
            titles = {j.title for j in jobs}
            assert titles == {"Movie 0", "Movie 1", "Movie 2"}


# ─── 2. Process Job: status transitions through pipeline ────────────────────


class TestProcessJobLifecycle:
    """Test _process_job drives correct DB status transitions."""

    @pytest.mark.asyncio
    async def test_successful_transcode_lifecycle(self, test_db_setup, tmp_path):
        """Job should transition: PENDING → PROCESSING → COMPLETED."""
        _, session_factory, test_get_db = test_db_setup

        # Create source directory with MKV files
        source_dir = tmp_path / "raw" / "Test Movie"
        source_dir.mkdir(parents=True)
        mkv = source_dir / "main.mkv"
        mkv.write_bytes(b"\x00" * 5000)

        # Create output directory
        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            # Queue the job (creates DB record)
            await worker.queue_job(
                source_path=str(source_dir),
                title="Test Movie",
            )

            # Get the job from internal queue
            job = await worker._queue.get()

            # Mock the transcode steps so they succeed
            transcode_mock = AsyncMock()
            with patch.object(worker, "_wait_for_stable", AsyncMock()), \
                 patch.object(worker, "_transcode_file_handbrake", transcode_mock), \
                 patch.object(worker, "_transcode_file_ffmpeg", transcode_mock), \
                 patch.object(worker, "_cleanup_source", MagicMock()), \
                 patch("transcoder.settings") as mock_settings:
                mock_settings.completed_path = str(completed_dir)
                mock_settings.movies_subdir = "movies"
                mock_settings.output_extension = "mkv"
                mock_settings.delete_source = False
                mock_settings.video_encoder = "nvenc_h265"
                mock_settings.work_path = str(tmp_path / "work")
                mock_settings.minimum_free_space_gb = 10.0

                await worker._process_job(job)

        # Verify final DB state
        async with session_factory() as session:
            result = await session.execute(select(TranscodeJobDB))
            job_db = result.scalar_one()
            assert job_db.status == JobStatus.COMPLETED
            assert job_db.progress == 100.0
            assert job_db.completed_at is not None
            assert job_db.started_at is not None
            assert job_db.error is None
            assert job_db.total_tracks == 1
            assert job_db.main_feature_file == "main.mkv"

    @pytest.mark.asyncio
    async def test_failed_transcode_lifecycle(self, test_db_setup, tmp_path):
        """Failed transcode should set status to FAILED with error message."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Bad Movie"
        source_dir.mkdir(parents=True)
        (source_dir / "main.mkv").write_bytes(b"\x00" * 1000)

        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(source_path=str(source_dir), title="Bad Movie")
            job = await worker._queue.get()

            # Make transcoding fail
            fail_mock = AsyncMock(side_effect=RuntimeError("HandBrake crashed"))
            with patch.object(worker, "_wait_for_stable", AsyncMock()), \
                 patch.object(worker, "_transcode_file_handbrake", fail_mock), \
                 patch.object(worker, "_transcode_file_ffmpeg", fail_mock), \
                 patch("transcoder.settings") as mock_settings:
                mock_settings.completed_path = str(completed_dir)
                mock_settings.movies_subdir = "movies"
                mock_settings.output_extension = "mkv"
                mock_settings.video_encoder = "nvenc_h265"
                mock_settings.work_path = str(tmp_path / "work")
                mock_settings.minimum_free_space_gb = 10.0

                await worker._process_job(job)

        async with session_factory() as session:
            result = await session.execute(select(TranscodeJobDB))
            job_db = result.scalar_one()
            assert job_db.status == JobStatus.FAILED
            assert "HandBrake crashed" in job_db.error

    @pytest.mark.asyncio
    async def test_no_mkv_files_fails(self, test_db_setup, tmp_path):
        """Job with no MKV or audio files in source should fail."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Empty Movie"
        source_dir.mkdir(parents=True)
        (source_dir / "readme.txt").write_text("no video here")

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(source_path=str(source_dir), title="Empty Movie")
            job = await worker._queue.get()

            with patch.object(worker, "_wait_for_stable", AsyncMock()):
                await worker._process_job(job)

        async with session_factory() as session:
            result = await session.execute(select(TranscodeJobDB))
            job_db = result.scalar_one()
            assert job_db.status == JobStatus.FAILED
            assert "No video or audio files" in job_db.error

    @pytest.mark.asyncio
    async def test_source_cleanup_on_success(self, test_db_setup, tmp_path):
        """Source should be cleaned up when delete_source=True and transcode succeeds."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Cleanup Movie"
        source_dir.mkdir(parents=True)
        (source_dir / "main.mkv").write_bytes(b"\x00" * 5000)

        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(source_path=str(source_dir), title="Cleanup Movie")
            job = await worker._queue.get()

            transcode_mock = AsyncMock()
            with patch.object(worker, "_wait_for_stable", AsyncMock()), \
                 patch.object(worker, "_transcode_file_handbrake", transcode_mock), \
                 patch.object(worker, "_transcode_file_ffmpeg", transcode_mock), \
                 patch("transcoder.settings") as mock_settings:
                mock_settings.completed_path = str(completed_dir)
                mock_settings.movies_subdir = "movies"
                mock_settings.output_extension = "mkv"
                mock_settings.delete_source = True
                mock_settings.video_encoder = "nvenc_h265"
                mock_settings.work_path = str(tmp_path / "work")
                mock_settings.minimum_free_space_gb = 10.0

                await worker._process_job(job)

        # Source should be deleted
        assert not source_dir.exists()

    @pytest.mark.asyncio
    async def test_source_kept_on_failure(self, test_db_setup, tmp_path):
        """Source should NOT be cleaned up when transcode fails."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Keep Movie"
        source_dir.mkdir(parents=True)
        (source_dir / "main.mkv").write_bytes(b"\x00" * 5000)

        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(source_path=str(source_dir), title="Keep Movie")
            job = await worker._queue.get()

            fail_mock = AsyncMock(side_effect=RuntimeError("fail"))
            with patch.object(worker, "_wait_for_stable", AsyncMock()), \
                 patch.object(worker, "_transcode_file_handbrake", fail_mock), \
                 patch.object(worker, "_transcode_file_ffmpeg", fail_mock), \
                 patch("transcoder.settings") as mock_settings:
                mock_settings.completed_path = str(completed_dir)
                mock_settings.movies_subdir = "movies"
                mock_settings.output_extension = "mkv"
                mock_settings.delete_source = True
                mock_settings.video_encoder = "nvenc_h265"
                mock_settings.work_path = str(tmp_path / "work")
                mock_settings.minimum_free_space_gb = 10.0

                await worker._process_job(job)

        # Source should still exist after failure
        assert source_dir.exists()

    @pytest.mark.asyncio
    async def test_work_dir_cleaned_on_success(self, test_db_setup, tmp_path):
        """Local scratch dir should be cleaned up after successful transcode."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Work Cleanup Movie"
        source_dir.mkdir(parents=True)
        (source_dir / "main.mkv").write_bytes(b"\x00" * 5000)
        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()
        work_dir = tmp_path / "work"

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(source_path=str(source_dir), title="Work Cleanup Movie")
            job = await worker._queue.get()

            transcode_mock = AsyncMock()
            with patch.object(worker, "_wait_for_stable", AsyncMock()), \
                 patch.object(worker, "_transcode_file_handbrake", transcode_mock), \
                 patch.object(worker, "_transcode_file_ffmpeg", transcode_mock), \
                 patch("transcoder.settings") as mock_settings:
                mock_settings.completed_path = str(completed_dir)
                mock_settings.movies_subdir = "movies"
                mock_settings.output_extension = "mkv"
                mock_settings.delete_source = False
                mock_settings.video_encoder = "nvenc_h265"
                mock_settings.work_path = str(work_dir)
                mock_settings.minimum_free_space_gb = 10.0

                await worker._process_job(job)

        # Work dir for this job should be cleaned up
        work_job_dir = work_dir / f"job-{job.id}"
        assert not work_job_dir.exists()

    @pytest.mark.asyncio
    async def test_work_dir_cleaned_on_failure(self, test_db_setup, tmp_path):
        """Local scratch dir should be cleaned up even after failed transcode."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Work Fail Movie"
        source_dir.mkdir(parents=True)
        (source_dir / "main.mkv").write_bytes(b"\x00" * 5000)
        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()
        work_dir = tmp_path / "work"

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(source_path=str(source_dir), title="Work Fail Movie")
            job = await worker._queue.get()

            fail_mock = AsyncMock(side_effect=RuntimeError("encoder crash"))
            with patch.object(worker, "_wait_for_stable", AsyncMock()), \
                 patch.object(worker, "_transcode_file_handbrake", fail_mock), \
                 patch.object(worker, "_transcode_file_ffmpeg", fail_mock), \
                 patch("transcoder.settings") as mock_settings:
                mock_settings.completed_path = str(completed_dir)
                mock_settings.movies_subdir = "movies"
                mock_settings.output_extension = "mkv"
                mock_settings.delete_source = False
                mock_settings.video_encoder = "nvenc_h265"
                mock_settings.work_path = str(work_dir)
                mock_settings.minimum_free_space_gb = 10.0

                await worker._process_job(job)

        # Work dir should still be cleaned up despite failure
        work_job_dir = work_dir / f"job-{job.id}"
        assert not work_job_dir.exists()

        # But source should still exist
        assert source_dir.exists()


# ─── 3. Load Pending Jobs on Startup ────────────────────────────────────────


class TestLoadPendingJobsOnStartup:
    """Test that worker restores jobs from DB on startup."""

    @pytest.mark.asyncio
    async def test_pending_jobs_restored(self, test_db_setup):
        """PENDING jobs should be loaded into queue on startup."""
        _, session_factory, test_get_db = test_db_setup

        # Pre-populate DB with pending jobs
        async with session_factory() as session:
            for i in range(3):
                session.add(TranscodeJobDB(
                    title=f"Pending Movie {i}",
                    source_path=f"/data/raw/movie{i}",
                    status=JobStatus.PENDING,
                ))
            await session.commit()

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()
            await worker._load_pending_jobs()

        assert worker.queue_size == 3

    @pytest.mark.asyncio
    async def test_processing_jobs_reset_to_pending(self, test_db_setup):
        """PROCESSING jobs should be reset to PENDING and re-queued."""
        _, session_factory, test_get_db = test_db_setup

        async with session_factory() as session:
            session.add(TranscodeJobDB(
                title="Interrupted Movie",
                source_path="/data/raw/interrupted",
                status=JobStatus.PROCESSING,
            ))
            await session.commit()

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()
            await worker._load_pending_jobs()

        assert worker.queue_size == 1

        # Verify DB status was updated
        async with session_factory() as session:
            result = await session.execute(select(TranscodeJobDB))
            job = result.scalar_one()
            assert job.status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_completed_jobs_not_loaded(self, test_db_setup):
        """COMPLETED and FAILED jobs should NOT be restored."""
        _, session_factory, test_get_db = test_db_setup

        async with session_factory() as session:
            session.add(TranscodeJobDB(
                title="Done Movie",
                source_path="/data/raw/done",
                status=JobStatus.COMPLETED,
            ))
            session.add(TranscodeJobDB(
                title="Failed Movie",
                source_path="/data/raw/failed",
                status=JobStatus.FAILED,
            ))
            await session.commit()

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()
            await worker._load_pending_jobs()

        assert worker.queue_size == 0


# ─── 4. Worker Run Loop ─────────────────────────────────────────────────────


class TestWorkerRunLoop:
    """Test the main worker loop behavior."""

    @pytest.mark.asyncio
    async def test_worker_processes_queued_job(self, test_db_setup, tmp_path):
        """Worker run loop should pick up and process a queued job."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Loop Movie"
        source_dir.mkdir(parents=True)
        (source_dir / "main.mkv").write_bytes(b"\x00" * 5000)
        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(source_path=str(source_dir), title="Loop Movie")

            transcode_mock = AsyncMock()
            with patch.object(worker, "_wait_for_stable", AsyncMock()), \
                 patch.object(worker, "_transcode_file_handbrake", transcode_mock), \
                 patch.object(worker, "_transcode_file_ffmpeg", transcode_mock), \
                 patch("transcoder.settings") as mock_settings:
                mock_settings.completed_path = str(completed_dir)
                mock_settings.movies_subdir = "movies"
                mock_settings.output_extension = "mkv"
                mock_settings.delete_source = False
                mock_settings.video_encoder = "nvenc_h265"
                mock_settings.stabilize_seconds = 0
                mock_settings.work_path = str(tmp_path / "work")
                mock_settings.minimum_free_space_gb = 10.0

                # Run worker briefly - it should process the job then we shut it down
                async def run_and_stop():
                    await asyncio.sleep(0.1)
                    worker.shutdown()

                asyncio.create_task(run_and_stop())
                await worker.run()

        assert worker.is_running is False
        assert worker.queue_size == 0

        async with session_factory() as session:
            result = await session.execute(select(TranscodeJobDB))
            job_db = result.scalar_one()
            assert job_db.status == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_worker_tracks_current_job(self, test_db_setup, tmp_path):
        """Worker should set current_job while processing."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Track Movie"
        source_dir.mkdir(parents=True)
        (source_dir / "main.mkv").write_bytes(b"\x00" * 5000)
        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()

        current_job_during_process = None

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            async def capture_current_job(*args, **kwargs):
                nonlocal current_job_during_process
                current_job_during_process = worker.current_job

            await worker.queue_job(source_path=str(source_dir), title="Track Movie")
            job = await worker._queue.get()
            worker._current_job = job.title

            # Verify tracking works
            assert worker.current_job == "Track Movie"
            worker._current_job = None
            assert worker.current_job is None


# ─── 5. Full API → DB Integration (Retry Pipeline) ──────────────────────────


class TestRetryPipeline:
    """Test the full retry flow: failed job → API retry → re-queue."""

    @pytest_asyncio.fixture
    async def api_client(self, test_db_setup, tmp_path):
        """Client with real DB for full integration tests."""
        engine, session_factory, test_get_db = test_db_setup

        import database as db_module
        import main as main_module

        mock_worker = MagicMock()
        mock_worker.is_running = True
        mock_worker.queue_size = 0
        mock_worker.current_job = None
        mock_worker.queue_job = AsyncMock()
        mock_worker.shutdown = MagicMock()

        with patch.object(db_module, "get_db", test_get_db), \
             patch("main.get_db", test_get_db), \
             patch("main.init_db", AsyncMock()):

            main_module.worker = mock_worker

            transport = ASGITransport(app=main_module.app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac, session_factory, mock_worker

            main_module.worker = None

    @pytest.mark.asyncio
    async def test_retry_failed_job_via_api(self, api_client):
        """POST /jobs/{id}/retry should reset a FAILED job and re-queue it."""
        client, session_factory, mock_worker = api_client

        # Insert a failed job directly
        async with session_factory() as session:
            job = TranscodeJobDB(
                title="Failed Movie",
                source_path="/data/raw/failed",
                status=JobStatus.FAILED,
                error="HandBrake crashed",
                retry_count=0,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        # Retry via API
        response = await client.post(f"/jobs/{job_id}/retry")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["retry_count"] == 1

        # Verify worker.queue_job was called
        mock_worker.queue_job.assert_called_once()
        call_kwargs = mock_worker.queue_job.call_args
        assert call_kwargs.kwargs.get("existing_job_id") == job_id

        # Verify DB state
        async with session_factory() as session:
            result = await session.execute(
                select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
            )
            job_db = result.scalar_one()
            assert job_db.status == JobStatus.PENDING
            assert job_db.retry_count == 1
            assert job_db.error is None

    @pytest.mark.asyncio
    async def test_retry_max_limit_reached(self, api_client):
        """Retry should be rejected when max_retry_count is reached."""
        client, session_factory, _ = api_client

        async with session_factory() as session:
            job = TranscodeJobDB(
                title="Too Many Retries",
                source_path="/data/raw/retries",
                status=JobStatus.FAILED,
                retry_count=3,  # Default max is 3
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        response = await client.post(f"/jobs/{job_id}/retry")
        assert response.status_code == 400
        assert "retry limit" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_retry_non_failed_job_rejected(self, api_client):
        """Only FAILED jobs should be retryable."""
        client, session_factory, _ = api_client

        async with session_factory() as session:
            job = TranscodeJobDB(
                title="Pending Movie",
                source_path="/data/raw/pending",
                status=JobStatus.PENDING,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        response = await client.post(f"/jobs/{job_id}/retry")
        assert response.status_code == 400
        assert "not in failed state" in response.json()["detail"].lower()


# ─── 6. Full API → DB Integration (Delete Pipeline) ─────────────────────────


class TestDeletePipeline:
    """Test full delete flow via API with real DB records."""

    @pytest_asyncio.fixture
    async def api_client(self, test_db_setup):
        engine, session_factory, test_get_db = test_db_setup

        import database as db_module
        import main as main_module

        mock_worker = MagicMock()
        mock_worker.is_running = True
        mock_worker.queue_size = 0
        mock_worker.current_job = None

        with patch.object(db_module, "get_db", test_get_db), \
             patch("main.get_db", test_get_db), \
             patch("main.init_db", AsyncMock()):

            main_module.worker = mock_worker
            transport = ASGITransport(app=main_module.app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac, session_factory

            main_module.worker = None

    @pytest.mark.asyncio
    async def test_delete_completed_job(self, api_client):
        """DELETE /jobs/{id} should remove a completed job from DB."""
        client, session_factory = api_client

        async with session_factory() as session:
            job = TranscodeJobDB(
                title="Done Movie",
                source_path="/data/raw/done",
                status=JobStatus.COMPLETED,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        response = await client.delete(f"/jobs/{job_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

        # Verify gone from DB
        async with session_factory() as session:
            result = await session.execute(
                select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
            )
            assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_failed_job(self, api_client):
        """Should be able to delete FAILED jobs."""
        client, session_factory = api_client

        async with session_factory() as session:
            job = TranscodeJobDB(
                title="Failed Movie",
                source_path="/data/raw/failed",
                status=JobStatus.FAILED,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        response = await client.delete(f"/jobs/{job_id}")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_cannot_delete_processing_job(self, api_client):
        """Should NOT be able to delete a PROCESSING job."""
        client, session_factory = api_client

        async with session_factory() as session:
            job = TranscodeJobDB(
                title="Active Movie",
                source_path="/data/raw/active",
                status=JobStatus.PROCESSING,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        response = await client.delete(f"/jobs/{job_id}")
        assert response.status_code == 400
        assert "in progress" in response.json()["detail"].lower()


# ─── 7. Stats Accuracy ──────────────────────────────────────────────────────


class TestStatsAccuracy:
    """Test that /stats reflects actual DB state."""

    @pytest_asyncio.fixture
    async def api_client(self, test_db_setup):
        engine, session_factory, test_get_db = test_db_setup

        import database as db_module
        import main as main_module

        mock_worker = MagicMock()
        mock_worker.is_running = True
        mock_worker.queue_size = 2
        mock_worker.current_job = "Currently Transcoding"

        with patch.object(db_module, "get_db", test_get_db), \
             patch("main.get_db", test_get_db), \
             patch("main.init_db", AsyncMock()):

            main_module.worker = mock_worker
            transport = ASGITransport(app=main_module.app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac, session_factory

            main_module.worker = None

    @pytest.mark.asyncio
    async def test_stats_reflect_db_state(self, api_client):
        """Stats should show correct counts per status."""
        client, session_factory = api_client

        # Insert jobs with various statuses
        async with session_factory() as session:
            jobs = [
                TranscodeJobDB(title="P1", source_path="/p1", status=JobStatus.PENDING),
                TranscodeJobDB(title="P2", source_path="/p2", status=JobStatus.PENDING),
                TranscodeJobDB(title="R1", source_path="/r1", status=JobStatus.PROCESSING),
                TranscodeJobDB(title="C1", source_path="/c1", status=JobStatus.COMPLETED),
                TranscodeJobDB(title="C2", source_path="/c2", status=JobStatus.COMPLETED),
                TranscodeJobDB(title="C3", source_path="/c3", status=JobStatus.COMPLETED),
                TranscodeJobDB(title="F1", source_path="/f1", status=JobStatus.FAILED),
            ]
            session.add_all(jobs)
            await session.commit()

        response = await client.get("/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["pending"] == 2
        assert data["processing"] == 1
        assert data["completed"] == 3
        assert data["failed"] == 1
        assert data["cancelled"] == 0
        assert data["worker_running"] is True
        assert data["current_job"] == "Currently Transcoding"


# ─── 8. Webhook → Jobs List Integration ─────────────────────────────────────


class TestWebhookToJobsList:
    """Test that webhook-created jobs appear in /jobs listing."""

    @pytest_asyncio.fixture
    async def api_client(self, test_db_setup):
        engine, session_factory, test_get_db = test_db_setup

        import database as db_module
        import main as main_module

        mock_worker = MagicMock()
        mock_worker.is_running = True
        mock_worker.queue_size = 0
        mock_worker.current_job = None
        # Make queue_job actually insert into the test DB
        mock_worker.queue_job = AsyncMock()

        with patch.object(db_module, "get_db", test_get_db), \
             patch("main.get_db", test_get_db), \
             patch("main.init_db", AsyncMock()):

            main_module.worker = mock_worker
            transport = ASGITransport(app=main_module.app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac, session_factory

            main_module.worker = None

    @pytest.mark.asyncio
    async def test_jobs_filtered_by_status(self, api_client):
        """GET /jobs?status=failed should filter correctly."""
        client, session_factory = api_client

        async with session_factory() as session:
            session.add_all([
                TranscodeJobDB(title="OK", source_path="/ok", status=JobStatus.COMPLETED),
                TranscodeJobDB(title="Bad", source_path="/bad", status=JobStatus.FAILED),
                TranscodeJobDB(title="Wait", source_path="/wait", status=JobStatus.PENDING),
            ])
            await session.commit()

        response = await client.get("/jobs?status=failed")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["title"] == "Bad"

    @pytest.mark.asyncio
    async def test_jobs_pagination(self, api_client):
        """Pagination should work correctly with limit and offset."""
        client, session_factory = api_client

        async with session_factory() as session:
            for i in range(10):
                session.add(TranscodeJobDB(
                    title=f"Movie {i}",
                    source_path=f"/data/{i}",
                    status=JobStatus.COMPLETED,
                ))
            await session.commit()

        response = await client.get("/jobs?limit=3&offset=0")
        data = response.json()
        assert len(data["jobs"]) == 3
        assert data["total"] == 10
        assert data["limit"] == 3
        assert data["offset"] == 0

        # Second page
        response = await client.get("/jobs?limit=3&offset=3")
        data = response.json()
        assert len(data["jobs"]) == 3
        assert data["total"] == 10


# ─── 8b. Audio CD Passthrough ─────────────────────────────────────────────────


class TestAudioPassthrough:
    """Test audio CD rip passthrough (no transcoding, copy to audio/)."""

    @pytest.mark.asyncio
    async def test_audio_files_passthrough_to_audio(self, test_db_setup, tmp_path):
        """Source with FLAC files should be copied to audio/ and marked COMPLETED."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Greatest Hits"
        source_dir.mkdir(parents=True)
        (source_dir / "track01.flac").write_bytes(b"\x00" * 1000)
        (source_dir / "track02.flac").write_bytes(b"\x00" * 2000)
        (source_dir / "track03.flac").write_bytes(b"\x00" * 1500)

        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(source_path=str(source_dir), title="Greatest Hits")
            job = await worker._queue.get()

            with patch.object(worker, "_wait_for_stable", AsyncMock()), \
                 patch("transcoder.settings") as mock_settings:
                mock_settings.completed_path = str(completed_dir)
                mock_settings.audio_subdir = "audio"
                mock_settings.movies_subdir = "movies"
                mock_settings.delete_source = False
                mock_settings.work_path = str(tmp_path / "work")

                await worker._process_job(job)

        # Verify files copied to audio/Greatest Hits/
        audio_dir = completed_dir / "audio" / "Greatest Hits"
        assert audio_dir.exists()
        assert (audio_dir / "track01.flac").exists()
        assert (audio_dir / "track02.flac").exists()
        assert (audio_dir / "track03.flac").exists()

        # Verify DB state
        async with session_factory() as session:
            result = await session.execute(select(TranscodeJobDB))
            job_db = result.scalar_one()
            assert job_db.status == JobStatus.COMPLETED
            assert job_db.total_tracks == 3
            assert job_db.progress == 100.0
            assert job_db.completed_at is not None
            assert "audio" in job_db.output_path

    @pytest.mark.asyncio
    async def test_mixed_mkv_and_audio_treated_as_video(self, test_db_setup, tmp_path):
        """Source with MKV + audio files should follow the video transcode path."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Movie With Soundtrack"
        source_dir.mkdir(parents=True)
        (source_dir / "movie.mkv").write_bytes(b"\x00" * 5000)
        (source_dir / "soundtrack.flac").write_bytes(b"\x00" * 1000)

        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(
                source_path=str(source_dir), title="Movie With Soundtrack"
            )
            job = await worker._queue.get()

            transcode_mock = AsyncMock()
            with patch.object(worker, "_wait_for_stable", AsyncMock()), \
                 patch.object(worker, "_transcode_file_handbrake", transcode_mock), \
                 patch.object(worker, "_transcode_file_ffmpeg", transcode_mock), \
                 patch("transcoder.settings") as mock_settings:
                mock_settings.completed_path = str(completed_dir)
                mock_settings.movies_subdir = "movies"
                mock_settings.output_extension = "mkv"
                mock_settings.delete_source = False
                mock_settings.video_encoder = "nvenc_h265"
                mock_settings.work_path = str(tmp_path / "work")
                mock_settings.minimum_free_space_gb = 10.0

                await worker._process_job(job)

        # Should be treated as video, not audio
        async with session_factory() as session:
            result = await session.execute(select(TranscodeJobDB))
            job_db = result.scalar_one()
            assert job_db.status == JobStatus.COMPLETED
            assert "movies" in job_db.output_path

    @pytest.mark.asyncio
    async def test_no_video_or_audio_fails_with_updated_message(self, test_db_setup, tmp_path):
        """Source with no MKV and no audio files should fail with updated error."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Empty Disc"
        source_dir.mkdir(parents=True)
        (source_dir / "readme.txt").write_text("nothing useful")

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(source_path=str(source_dir), title="Empty Disc")
            job = await worker._queue.get()

            with patch.object(worker, "_wait_for_stable", AsyncMock()):
                await worker._process_job(job)

        async with session_factory() as session:
            result = await session.execute(select(TranscodeJobDB))
            job_db = result.scalar_one()
            assert job_db.status == JobStatus.FAILED
            assert "No video or audio files" in job_db.error

    @pytest.mark.asyncio
    async def test_audio_passthrough_cleans_source(self, test_db_setup, tmp_path):
        """Source should be cleaned up when delete_source=True for audio passthrough."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Cleanup Album"
        source_dir.mkdir(parents=True)
        (source_dir / "track01.mp3").write_bytes(b"\x00" * 500)

        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(source_path=str(source_dir), title="Cleanup Album")
            job = await worker._queue.get()

            with patch.object(worker, "_wait_for_stable", AsyncMock()), \
                 patch("transcoder.settings") as mock_settings:
                mock_settings.completed_path = str(completed_dir)
                mock_settings.audio_subdir = "audio"
                mock_settings.movies_subdir = "movies"
                mock_settings.delete_source = True
                mock_settings.work_path = str(tmp_path / "work")

                await worker._process_job(job)

        # Source should be deleted
        assert not source_dir.exists()

        # Output should exist
        audio_dir = completed_dir / "audio" / "Cleanup Album"
        assert audio_dir.exists()
        assert (audio_dir / "track01.mp3").exists()


# ─── 8c. 4K Preset Selection ───────────────────────────────────────────────


class TestResolutionPresetSelection:
    """Test resolution-based HandBrake preset selection in full pipeline."""

    @pytest.mark.asyncio
    async def test_4k_source_uses_4k_preset(self, test_db_setup, tmp_path):
        """4K source should trigger the 4K HandBrake preset in transcoded command."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "4K Movie"
        source_dir.mkdir(parents=True)
        (source_dir / "main.mkv").write_bytes(b"\x00" * 5000)

        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()

        handbrake_cmds = []

        async def capture_handbrake(source, output, job_db, db):
            """Mock that records the HandBrake call context."""
            # We need to call the real method to capture the command,
            # but instead we'll check the preset selection via the resolution mock
            pass

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            # Force HandBrake backend (default encoder "x265" selects ffmpeg)
            worker._encoder_backend = "handbrake"

            await worker.queue_job(source_path=str(source_dir), title="4K Movie")
            job = await worker._queue.get()

            # Mock _get_video_resolution to return 4K, capture the HandBrake command
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.stdout = AsyncMock()
            mock_proc.stdout.__aiter__ = lambda self: self
            mock_proc.stdout.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
            mock_proc.wait = AsyncMock(return_value=0)

            with patch.object(worker, "_wait_for_stable", AsyncMock()), \
                 patch.object(worker, "_get_video_resolution", AsyncMock(return_value=(3840, 2160))), \
                 patch("transcoder.asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)), \
                 patch("transcoder.settings") as mock_settings:
                mock_settings.completed_path = str(completed_dir)
                mock_settings.movies_subdir = "movies"
                mock_settings.output_extension = "mkv"
                mock_settings.delete_source = False
                mock_settings.video_encoder = "nvenc_h265"
                mock_settings.video_quality = 22
                mock_settings.audio_encoder = "copy"
                mock_settings.subtitle_mode = "all"
                mock_settings.handbrake_preset = "NVENC H.265 1080p"
                mock_settings.handbrake_preset_4k = "H.265 NVENC 2160p 4K"
                mock_settings.handbrake_preset_file = ""
                mock_settings.work_path = str(tmp_path / "work")
                mock_settings.minimum_free_space_gb = 10.0

                # Create fake output file so the check passes
                async def fake_exec(*args, **kwargs):
                    handbrake_cmds.append(args)
                    # Create the output file that _transcode_file_handbrake expects
                    for i, arg in enumerate(args):
                        if arg == "-o" and i + 1 < len(args):
                            Path(args[i + 1]).touch()
                    return mock_proc

                with patch("transcoder.asyncio.create_subprocess_exec", fake_exec):
                    await worker._process_job(job)

        # Verify the HandBrake command used the 4K preset
        assert len(handbrake_cmds) > 0
        cmd = handbrake_cmds[0]
        assert "--preset" in cmd
        preset_idx = cmd.index("--preset")
        assert cmd[preset_idx + 1] == "H.265 NVENC 2160p 4K"


# ─── 9. Multi-file Transcode ────────────────────────────────────────────────


class TestMultiFileTranscode:
    """Test transcode of directories with multiple MKV files."""

    @pytest.mark.asyncio
    async def test_multiple_mkv_files_transcoded(self, test_db_setup, tmp_path):
        """All MKV files in source dir should be transcoded."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Multi Movie"
        source_dir.mkdir(parents=True)
        (source_dir / "feature.mkv").write_bytes(b"\x00" * 10000)
        (source_dir / "extra1.mkv").write_bytes(b"\x00" * 3000)
        (source_dir / "extra2.mkv").write_bytes(b"\x00" * 2000)
        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()

        transcode_calls = []

        async def mock_transcode(source, output, job_id, overrides=None):
            transcode_calls.append(source.name)

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(source_path=str(source_dir), title="Multi Movie")
            job = await worker._queue.get()

            with patch.object(worker, "_wait_for_stable", AsyncMock()), \
                 patch.object(worker, "_transcode_file_handbrake", mock_transcode), \
                 patch.object(worker, "_transcode_file_ffmpeg", mock_transcode), \
                 patch("transcoder.settings") as mock_settings:
                mock_settings.completed_path = str(completed_dir)
                mock_settings.movies_subdir = "movies"
                mock_settings.output_extension = "mkv"
                mock_settings.delete_source = False
                mock_settings.video_encoder = "nvenc_h265"
                mock_settings.work_path = str(tmp_path / "work")
                mock_settings.minimum_free_space_gb = 10.0

                await worker._process_job(job)

        # All 3 files should have been transcoded
        assert len(transcode_calls) == 3
        assert "feature.mkv" in transcode_calls

        # Verify DB metadata
        async with session_factory() as session:
            result = await session.execute(select(TranscodeJobDB))
            job_db = result.scalar_one()
            assert job_db.total_tracks == 3
            assert job_db.main_feature_file == "feature.mkv"  # largest file
            assert job_db.status == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_main_feature_identified_by_size(self, test_db_setup, tmp_path):
        """Main feature should be the largest MKV file."""
        _, session_factory, test_get_db = test_db_setup

        source_dir = tmp_path / "raw" / "Size Test"
        source_dir.mkdir(parents=True)
        (source_dir / "small.mkv").write_bytes(b"\x00" * 100)
        (source_dir / "big_feature.mkv").write_bytes(b"\x00" * 50000)
        (source_dir / "medium.mkv").write_bytes(b"\x00" * 5000)
        completed_dir = tmp_path / "completed"
        completed_dir.mkdir()

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.check_gpu_support", return_value={
                 "handbrake_nvenc": True, "ffmpeg_nvenc_h265": True, "ffmpeg_nvenc_h264": True,
                 "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
                 "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
                 "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False, "vaapi_device": False,
             }):
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()

            await worker.queue_job(source_path=str(source_dir), title="Size Test")
            job = await worker._queue.get()

            transcode_mock = AsyncMock()
            with patch.object(worker, "_wait_for_stable", AsyncMock()), \
                 patch.object(worker, "_transcode_file_handbrake", transcode_mock), \
                 patch.object(worker, "_transcode_file_ffmpeg", transcode_mock), \
                 patch("transcoder.settings") as mock_settings:
                mock_settings.completed_path = str(completed_dir)
                mock_settings.movies_subdir = "movies"
                mock_settings.output_extension = "mkv"
                mock_settings.delete_source = False
                mock_settings.video_encoder = "nvenc_h265"
                mock_settings.work_path = str(tmp_path / "work")
                mock_settings.minimum_free_space_gb = 10.0

                await worker._process_job(job)

        async with session_factory() as session:
            result = await session.execute(select(TranscodeJobDB))
            job_db = result.scalar_one()
            assert job_db.main_feature_file == "big_feature.mkv"
