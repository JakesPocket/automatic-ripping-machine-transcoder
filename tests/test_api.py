"""
Tests for main.py - FastAPI API endpoint integration tests.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ─── App fixture with mocked worker and real DB ─────────────────────────────


@pytest.fixture
def mock_worker():
    """Create a mock TranscodeWorker."""
    worker = MagicMock()
    worker.is_running = True
    worker.queue_size = 0
    worker.current_job = None
    worker.queue_job = AsyncMock(return_value=(1, True))
    worker.shutdown = MagicMock()
    return worker


@pytest_asyncio.fixture
async def client(mock_worker, tmp_path):
    """Create an async test client with initialized test DB."""
    db_path = str(tmp_path / "test.db")

    # Patch database module to use test DB before importing main
    import database as db_module
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from models import Base

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    # Initialize tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def test_get_db():
        async with test_session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    # Patch both the database module and the main module's reference
    with patch.object(db_module, "get_db", test_get_db), \
         patch("main.get_db", test_get_db), \
         patch("main.init_db", AsyncMock()):

        import main as main_module
        main_module.worker = mock_worker

        transport = ASGITransport(app=main_module.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

        main_module.worker = None

    # Cleanup
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


# ─── Health Check ────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    """Tests for GET /health."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Health check should return status."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "healthy"
        assert "worker_running" in data
        assert "queue_size" in data


# ─── Webhook Endpoint ───────────────────────────────────────────────────────


class TestWebhookEndpoint:
    """Tests for POST /webhook/arm."""

    @pytest.mark.asyncio
    async def test_valid_completion_webhook(self, client, mock_worker):
        """Valid completion webhook should queue a job."""
        payload = {
            "title": "ARM notification",
            "body": "Rip of Test Movie (2024) complete",
            "type": "info",
        }
        response = await client.post("/webhook/arm", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        mock_worker.queue_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_with_path(self, client, mock_worker):
        """Webhook with explicit path should use it."""
        payload = {
            "title": "Rip complete",
            "path": "Movie Title (2024)",
            "status": "success",
        }
        response = await client.post("/webhook/arm", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        mock_worker.queue_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_title_fallback_body(self, client, mock_worker):
        """When body has no parseable pattern, use body text as media title."""
        payload = {
            "title": "Rip complete",
            "path": "Movie Title (2024)",
            "body": "some unrecognized format",
            "status": "success",
        }
        response = await client.post("/webhook/arm", json=payload)
        assert response.status_code == 200
        call_kwargs = mock_worker.queue_job.call_args
        assert call_kwargs.kwargs["title"] == "some unrecognized format"

    @pytest.mark.asyncio
    async def test_apprise_message_field(self, client, mock_worker):
        """Apprise json:// sends 'message' instead of 'body' - should still work."""
        payload = {
            "version": "1.0",
            "title": "ARM notification",
            "message": "Test Movie (2024) rip complete. Starting transcode.",
            "type": "info",
        }
        response = await client.post("/webhook/arm", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        mock_worker.queue_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_arm_rip_notification_format(self, client, mock_worker):
        """ARM's actual NOTIFY_RIP format: '{title} rip complete. Starting transcode.'"""
        payload = {
            "title": "ARM notification",
            "body": "Movie Title (2024) rip complete. Starting transcode.",
            "type": "info",
        }
        response = await client.post("/webhook/arm", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["path"] == "Movie Title (2024)"
        mock_worker.queue_job.assert_called_once()
        # Job title should be the extracted media title, not "ARM notification"
        call_kwargs = mock_worker.queue_job.call_args
        assert call_kwargs.kwargs["title"] == "Movie Title (2024)"

    @pytest.mark.asyncio
    async def test_arm_processing_complete_format(self, client, mock_worker):
        """ARM's NOTIFY_TRANSCODE format: '{title} processing complete.'"""
        payload = {
            "title": "ARM notification",
            "body": "Movie Title (2024) processing complete.",
            "type": "info",
        }
        response = await client.post("/webhook/arm", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["path"] == "Movie Title (2024)"

    @pytest.mark.asyncio
    async def test_webhook_returns_503_when_worker_not_ready(self, client):
        """Webhook should return 503 when worker is None or not running."""
        import main as main_module
        saved_worker = main_module.worker
        main_module.worker = None
        try:
            payload = {
                "title": "ARM notification",
                "body": "Rip of Test Movie (2024) complete",
                "type": "info",
            }
            response = await client.post("/webhook/arm", json=payload)
            assert response.status_code == 503
            assert "not ready" in response.json()["detail"].lower()
        finally:
            main_module.worker = saved_worker

    @pytest.mark.asyncio
    async def test_non_completion_ignored(self, client):
        """Non-completion webhooks should be ignored."""
        payload = {
            "title": "ARM notification",
            "body": "Rip started for some movie",
            "type": "info",
        }
        response = await client.post("/webhook/arm", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    @pytest.mark.asyncio
    async def test_non_completion_apprise_ignored(self, client):
        """Non-completion Apprise notifications should be ignored."""
        payload = {
            "version": "1.0",
            "title": "ARM notification",
            "message": "Found data disc. Copying data.",
            "type": "info",
        }
        response = await client.post("/webhook/arm", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    @pytest.mark.asyncio
    async def test_webhook_no_path_no_body(self, client):
        """Webhook with no determinable path should return error."""
        payload = {
            "title": "Something complete",
        }
        response = await client.post("/webhook/arm", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "error"

    @pytest.mark.asyncio
    async def test_webhook_invalid_payload(self, client):
        """Invalid payload (missing title) should return 400."""
        response = await client.post("/webhook/arm", json={"body": "no title"})
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_webhook_path_traversal_rejected(self, client):
        """Path with traversal characters should be rejected."""
        payload = {
            "title": "Rip complete",
            "path": "../../../etc/passwd",
            "status": "success",
        }
        response = await client.post("/webhook/arm", json=payload)
        data = response.json()
        assert data.get("status") == "error" or response.status_code == 400

    @pytest.mark.asyncio
    async def test_webhook_path_with_subdirectory_accepted(self, client):
        """Relative subdirectory paths should be accepted (e.g. movies/Title (Year))."""
        payload = {
            "title": "Rip complete",
            "path": "movies/The Babysitter (1969)",
            "status": "success",
        }
        response = await client.post("/webhook/arm", json=payload)
        data = response.json()
        assert data.get("status") in ("queued", "error")
        # Should not be rejected for path validation reasons
        assert data.get("reason") != "invalid path"

    @pytest.mark.asyncio
    async def test_webhook_path_with_backslash_rejected(self, client):
        """Paths with backslashes should be rejected."""
        payload = {
            "title": "Rip complete",
            "path": "some\\nested\\path",
            "status": "success",
        }
        response = await client.post("/webhook/arm", json=payload)
        data = response.json()
        assert data.get("status") == "error"


# ─── Jobs Endpoint ──────────────────────────────────────────────────────────


class TestJobsEndpoint:
    """Tests for GET /jobs."""

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, client):
        """Should return empty job list."""
        response = await client.get("/jobs")
        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data
        assert data["jobs"] == []
        assert "total" in data
        assert "limit" in data
        assert "offset" in data

    @pytest.mark.asyncio
    async def test_list_jobs_pagination_defaults(self, client):
        """Default pagination should be limit=50, offset=0."""
        response = await client.get("/jobs")
        data = response.json()
        assert data["limit"] == 50
        assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_list_jobs_limit_capped(self, client):
        """Limit should be capped at 500."""
        response = await client.get("/jobs?limit=1000")
        data = response.json()
        assert data["limit"] == 500

    @pytest.mark.asyncio
    async def test_list_jobs_negative_offset_clamped(self, client):
        """Negative offset should be clamped to 0."""
        response = await client.get("/jobs?offset=-5")
        data = response.json()
        assert data["offset"] == 0


# ─── Retry Endpoint ─────────────────────────────────────────────────────────


class TestRetryEndpoint:
    """Tests for POST /jobs/{id}/retry."""

    @pytest.mark.asyncio
    async def test_retry_returns_503_when_worker_not_ready(self, client):
        """Retry should return 503 when worker is None."""
        import main as main_module

        saved_worker = main_module.worker
        main_module.worker = None
        try:
            response = await client.post("/jobs/1/retry")
            assert response.status_code == 503
            assert "not ready" in response.json()["detail"].lower()
        finally:
            main_module.worker = saved_worker

    @pytest.mark.asyncio
    async def test_retry_nonexistent_job(self, client):
        """Retrying non-existent job should return 404."""
        response = await client.post("/jobs/99999/retry")
        assert response.status_code == 404


# ─── Delete Endpoint ────────────────────────────────────────────────────────


class TestDeleteEndpoint:
    """Tests for DELETE /jobs/{id}."""

    @pytest.mark.asyncio
    async def test_delete_nonexistent_job(self, client):
        """Deleting non-existent job should return 404."""
        response = await client.delete("/jobs/99999")
        assert response.status_code == 404


# ─── Stats Endpoint ─────────────────────────────────────────────────────────


class TestStatsEndpoint:
    """Tests for GET /stats."""

    @pytest.mark.asyncio
    async def test_get_stats(self, client):
        """Stats endpoint should return status counts."""
        response = await client.get("/stats")
        assert response.status_code == 200
        data = response.json()
        assert "pending" in data
        assert "processing" in data
        assert "completed" in data
        assert "failed" in data
        assert "cancelled" in data
        assert "worker_running" in data
