"""
Tests for models.py - Pydantic validation and data models.
"""

import pytest
from pydantic import ValidationError

from models import WebhookPayload, JobStatus, TranscodeJob


# ─── WebhookPayload Validation ──────────────────────────────────────────────


class TestWebhookPayload:
    """Tests for WebhookPayload Pydantic model validation."""

    def test_valid_minimal_payload(self):
        """Minimal valid payload with only title."""
        payload = WebhookPayload(title="Movie Rip Complete")
        assert payload.title == "Movie Rip Complete"
        assert payload.body is None
        assert payload.path is None

    def test_valid_full_payload(self):
        """Full payload with all fields."""
        payload = WebhookPayload(
            title="Movie Title",
            body="Rip of Movie Title (2024) complete",
            path="Movie Title (2024)",
            job_id="job-123",
            status="success",
            type="info",
        )
        assert payload.title == "Movie Title"
        assert payload.job_id == "job-123"
        assert payload.status == "success"

    def test_empty_title_rejected(self):
        """Empty title must be rejected."""
        with pytest.raises(ValidationError):
            WebhookPayload(title="")

    def test_whitespace_only_title_rejected(self):
        """Whitespace-only title must be rejected."""
        with pytest.raises(ValidationError):
            WebhookPayload(title="   ")

    def test_title_max_length(self):
        """Title over 500 chars must be rejected."""
        with pytest.raises(ValidationError):
            WebhookPayload(title="A" * 501)

    def test_title_at_max_length(self):
        """Title at exactly 500 chars should be accepted."""
        payload = WebhookPayload(title="A" * 500)
        assert len(payload.title) == 500

    def test_title_control_characters_stripped(self):
        """Control characters should be removed from title."""
        payload = WebhookPayload(title="Movie\x01\x02\x03Title")
        assert payload.title == "MovieTitle"

    def test_body_max_length(self):
        """Body over 2000 chars must be rejected."""
        with pytest.raises(ValidationError):
            WebhookPayload(title="Test", body="B" * 2001)

    def test_body_preserves_newlines(self):
        """Newlines in body should be preserved."""
        payload = WebhookPayload(title="Test", body="Line 1\nLine 2\n")
        assert "\n" in payload.body

    def test_body_preserves_tabs(self):
        """Tabs in body should be preserved."""
        payload = WebhookPayload(title="Test", body="Col1\tCol2")
        assert "\t" in payload.body

    def test_body_control_chars_stripped(self):
        """Control characters (except newline/tab) should be removed from body."""
        payload = WebhookPayload(title="Test", body="Clean\x01\x02text")
        assert "\x01" not in payload.body
        assert "\x02" not in payload.body

    def test_path_max_length(self):
        """Path over 1000 chars must be rejected."""
        with pytest.raises(ValidationError):
            WebhookPayload(title="Test", path="p" * 1001)

    def test_path_null_bytes_stripped(self):
        """Null bytes should be removed from path."""
        payload = WebhookPayload(title="Test", path="movie\x00title")
        assert "\x00" not in payload.path

    def test_path_control_chars_stripped(self):
        """Control characters should be removed from path."""
        payload = WebhookPayload(title="Test", path="movie\x01title")
        assert "\x01" not in payload.path

    def test_job_id_max_length(self):
        """Job ID over 50 chars must be rejected."""
        with pytest.raises(ValidationError):
            WebhookPayload(title="Test", job_id="j" * 51)

    def test_job_id_valid_characters(self):
        """Job ID with valid characters should be accepted."""
        payload = WebhookPayload(title="Test", job_id="job-123_abc")
        assert payload.job_id == "job-123_abc"

    def test_job_id_invalid_characters_rejected(self):
        """Job ID with special characters must be rejected."""
        with pytest.raises(ValidationError, match="invalid characters"):
            WebhookPayload(title="Test", job_id="job;rm -rf /")

    def test_job_id_spaces_rejected(self):
        """Job ID with spaces must be rejected."""
        with pytest.raises(ValidationError):
            WebhookPayload(title="Test", job_id="job 123")

    def test_job_id_dots_rejected(self):
        """Job ID with dots must be rejected (not in allowed regex)."""
        with pytest.raises(ValidationError):
            WebhookPayload(title="Test", job_id="job.123")

    def test_status_max_length(self):
        """Status over 50 chars must be rejected."""
        with pytest.raises(ValidationError):
            WebhookPayload(title="Test", status="s" * 51)

    def test_type_max_length(self):
        """Type over 50 chars must be rejected."""
        with pytest.raises(ValidationError):
            WebhookPayload(title="Test", type="t" * 51)

    def test_none_optional_fields(self):
        """All optional fields should accept None."""
        payload = WebhookPayload(
            title="Test",
            body=None,
            message=None,
            path=None,
            job_id=None,
            status=None,
            type=None,
        )
        assert payload.body is None
        assert payload.message is None
        assert payload.path is None
        assert payload.job_id is None

    # ─── Multi-title disc fields ────────────────────────────────────────────

    def test_multi_title_default_none(self):
        """multi_title should default to None when not provided."""
        payload = WebhookPayload(title="Test")
        assert payload.multi_title is None

    def test_multi_title_true(self):
        """multi_title=True should be accepted."""
        payload = WebhookPayload(title="Test", multi_title=True)
        assert payload.multi_title is True

    def test_multi_title_false(self):
        """multi_title=False should be accepted."""
        payload = WebhookPayload(title="Test", multi_title=False)
        assert payload.multi_title is False

    def test_tracks_default_none(self):
        """tracks should default to None when not provided."""
        payload = WebhookPayload(title="Test")
        assert payload.tracks is None

    def test_tracks_empty_list(self):
        """tracks=[] should be accepted."""
        payload = WebhookPayload(title="Test", tracks=[])
        assert payload.tracks == []

    def test_tracks_with_metadata(self):
        """tracks with per-track metadata dicts should be accepted."""
        tracks = [
            {"track_number": 1, "filename": "t01.mkv", "title": "Episode 1", "year": "2024"},
            {"track_number": 2, "filename": "t02.mkv", "title": "Episode 2", "year": "2024"},
        ]
        payload = WebhookPayload(title="Test", multi_title=True, tracks=tracks)
        assert payload.multi_title is True
        assert len(payload.tracks) == 2
        assert payload.tracks[0]["filename"] == "t01.mkv"
        assert payload.tracks[1]["track_number"] == 2

    def test_multi_title_full_payload(self):
        """Full payload with multi_title and tracks alongside standard fields."""
        tracks = [
            {"track_number": 1, "filename": "main.mkv", "title": "Movie", "video_type": "movie"},
        ]
        payload = WebhookPayload(
            title="ARM notification",
            body="Rip of Movie (2024) complete",
            path="Movie (2024)",
            job_id="42",
            status="success",
            type="info",
            multi_title=True,
            tracks=tracks,
        )
        assert payload.multi_title is True
        assert len(payload.tracks) == 1
        assert payload.title == "ARM notification"
        assert payload.job_id == "42"

    # ─── Apprise message field support ──────────────────────────────────────

    def test_apprise_message_field_accepted(self):
        """Apprise json:// sends 'message' instead of 'body'."""
        payload = WebhookPayload(
            title="ARM notification",
            message="Movie Title (2024) rip complete. Starting transcode.",
            type="info",
        )
        assert payload.message == "Movie Title (2024) rip complete. Starting transcode."
        assert payload.body is None

    def test_effective_body_prefers_body(self):
        """effective_body should prefer 'body' over 'message' when both present."""
        payload = WebhookPayload(
            title="Test",
            body="from body",
            message="from message",
        )
        assert payload.effective_body == "from body"

    def test_effective_body_falls_back_to_message(self):
        """effective_body should return 'message' when 'body' is None."""
        payload = WebhookPayload(
            title="Test",
            message="from message",
        )
        assert payload.effective_body == "from message"

    def test_effective_body_none_when_both_empty(self):
        """effective_body should return None when both fields are empty."""
        payload = WebhookPayload(title="Test")
        assert payload.effective_body is None

    def test_apprise_full_payload(self):
        """Apprise json:// sends version, title, message, type."""
        payload = WebhookPayload(
            title="ARM notification",
            message="Movie (2024) rip complete. Starting transcode.",
            type="info",
        )
        assert payload.effective_body == "Movie (2024) rip complete. Starting transcode."

    def test_message_max_length(self):
        """Message over 2000 chars must be rejected."""
        with pytest.raises(ValidationError):
            WebhookPayload(title="Test", message="M" * 2001)

    def test_message_control_chars_stripped(self):
        """Control characters should be stripped from message field."""
        payload = WebhookPayload(title="Test", message="Clean\x01\x02text")
        assert "\x01" not in payload.message
        assert "\x02" not in payload.message


# ─── JobStatus Enum ──────────────────────────────────────────────────────────


class TestJobStatus:
    """Tests for JobStatus enum."""

    def test_all_statuses_exist(self):
        """All expected statuses should exist."""
        assert JobStatus.PENDING == "pending"
        assert JobStatus.PROCESSING == "processing"
        assert JobStatus.COMPLETED == "completed"
        assert JobStatus.FAILED == "failed"
        assert JobStatus.CANCELLED == "cancelled"

    def test_status_is_string(self):
        """JobStatus values should be strings."""
        for status in JobStatus:
            assert isinstance(status.value, str)


# ─── TranscodeJob Model ─────────────────────────────────────────────────────


class TestTranscodeJob:
    """Tests for TranscodeJob Pydantic model."""

    def test_create_job(self):
        """Should create a job with required fields."""
        job = TranscodeJob(title="Movie", source_path="/data/raw/movie")
        assert job.title == "Movie"
        assert job.source_path == "/data/raw/movie"
        assert job.id is None
        assert job.arm_job_id is None

    def test_create_job_with_all_fields(self):
        """Should create a job with all fields."""
        job = TranscodeJob(
            id=1,
            title="Movie",
            source_path="/data/raw/movie",
            arm_job_id="job-42",
        )
        assert job.id == 1
        assert job.arm_job_id == "job-42"

    def test_from_attributes_config(self):
        """Should support from_attributes for ORM integration."""
        assert TranscodeJob.model_config.get("from_attributes") is True
