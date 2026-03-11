"""
Tests for transcoder.py - TranscodeWorker unit tests.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from models import TranscodeJob


# Default GPU support dict for mocking
def _gpu_support_all():
    return {
        "handbrake_nvenc": True,
        "ffmpeg_nvenc_h265": True,
        "ffmpeg_nvenc_h264": True,
        "ffmpeg_vaapi_h265": True,
        "ffmpeg_vaapi_h264": True,
        "ffmpeg_amf_h265": True,
        "ffmpeg_amf_h264": True,
        "ffmpeg_qsv_h265": True,
        "ffmpeg_qsv_h264": True,
        "vaapi_device": True,
    }


def _gpu_support_none():
    return {k: False for k in _gpu_support_all()}


# ─── check_gpu_support ──────────────────────────────────────────────────────


class TestCheckGpuSupport:
    """Tests for check_gpu_support function."""

    def test_all_available(self):
        """Should detect all GPU encoders."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            result.stdout = "nvenc hevc_nvenc h264_nvenc hevc_vaapi h264_vaapi hevc_amf h264_amf hevc_qsv h264_qsv"
            result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=True):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["handbrake_nvenc"] is True
            assert support["ffmpeg_nvenc_h265"] is True
            assert support["ffmpeg_nvenc_h264"] is True
            assert support["ffmpeg_vaapi_h265"] is True
            assert support["ffmpeg_vaapi_h264"] is True
            assert support["ffmpeg_amf_h265"] is True
            assert support["ffmpeg_amf_h264"] is True
            assert support["ffmpeg_qsv_h265"] is True
            assert support["ffmpeg_qsv_h264"] is True
            assert support["vaapi_device"] is True

    def test_nothing_available(self):
        """Should handle no GPU support."""
        def mock_run(cmd, **kwargs):
            raise FileNotFoundError("not found")

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=False):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["handbrake_nvenc"] is False
            assert support["ffmpeg_nvenc_h265"] is False
            assert support["ffmpeg_nvenc_h264"] is False
            assert support["ffmpeg_vaapi_h265"] is False
            assert support["ffmpeg_vaapi_h264"] is False
            assert support["ffmpeg_amf_h265"] is False
            assert support["ffmpeg_amf_h264"] is False
            assert support["ffmpeg_qsv_h265"] is False
            assert support["ffmpeg_qsv_h264"] is False
            assert support["vaapi_device"] is False

    def test_ffmpeg_only_nvenc(self):
        """Should detect FFmpeg NVENC when HandBrake missing."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == "HandBrakeCLI":
                raise FileNotFoundError()
            result.stdout = "hevc_nvenc h264_nvenc"
            result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=False):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["handbrake_nvenc"] is False
            assert support["ffmpeg_nvenc_h265"] is True
            assert support["ffmpeg_nvenc_h264"] is True
            assert support["ffmpeg_vaapi_h265"] is False
            assert support["ffmpeg_vaapi_h264"] is False

    def test_vaapi_only(self):
        """Should detect VAAPI encoders for AMD GPU."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == "HandBrakeCLI":
                raise FileNotFoundError()
            result.stdout = "hevc_vaapi h264_vaapi"
            result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=True):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["handbrake_nvenc"] is False
            assert support["ffmpeg_nvenc_h265"] is False
            assert support["ffmpeg_vaapi_h265"] is True
            assert support["ffmpeg_vaapi_h264"] is True
            assert support["vaapi_device"] is True

    def test_qsv_only(self):
        """Should detect QSV encoders for Intel GPU."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == "HandBrakeCLI":
                raise FileNotFoundError()
            result.stdout = "hevc_qsv h264_qsv"
            result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=True):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["handbrake_nvenc"] is False
            assert support["ffmpeg_nvenc_h265"] is False
            assert support["ffmpeg_qsv_h265"] is True
            assert support["ffmpeg_qsv_h264"] is True
            assert support["vaapi_device"] is True

    def test_handbrake_nvenc_in_stderr(self):
        """HandBrake may report NVENC in stderr."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == "HandBrakeCLI":
                result.stdout = ""
                result.stderr = "NVENC encoder available"
            else:
                result.stdout = ""
                result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=False):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["handbrake_nvenc"] is True

    def test_vaapi_device_not_found(self):
        """Should report no VAAPI device when /dev/dri/renderD128 missing."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == "HandBrakeCLI":
                raise FileNotFoundError()
            result.stdout = "hevc_vaapi h264_vaapi"
            result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=False):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["ffmpeg_vaapi_h265"] is True
            assert support["vaapi_device"] is False

    def test_backward_compat_alias(self):
        """check_nvenc_support should be an alias for check_gpu_support."""
        from transcoder import check_nvenc_support, check_gpu_support
        assert check_nvenc_support is check_gpu_support


# ─── Encoder family detection ────────────────────────────────────────────────


class TestEncoderFamilyDetection:
    """Tests for _detect_encoder_family and _select_backend."""

    def _make_worker(self, gpu_support=None, video_encoder="nvenc_h265"):
        if gpu_support is None:
            gpu_support = _gpu_support_all()
        with patch("transcoder.check_gpu_support", return_value=gpu_support), \
             patch("transcoder.settings") as mock_settings:
            mock_settings.video_encoder = video_encoder
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_nvenc_family(self):
        worker = self._make_worker(video_encoder="nvenc_h265")
        assert worker._encoder_family == "nvenc"

    def test_vaapi_family(self):
        worker = self._make_worker(video_encoder="vaapi_h265")
        assert worker._encoder_family == "vaapi"

    def test_amf_family(self):
        worker = self._make_worker(video_encoder="amf_h265")
        assert worker._encoder_family == "amf"

    def test_qsv_family(self):
        worker = self._make_worker(video_encoder="qsv_h265")
        assert worker._encoder_family == "qsv"

    def test_software_family(self):
        worker = self._make_worker(video_encoder="x265")
        assert worker._encoder_family == "software"

    def test_nvenc_uses_handbrake_when_available(self):
        worker = self._make_worker(video_encoder="nvenc_h265")
        assert worker._encoder_backend == "handbrake"

    def test_nvenc_falls_back_to_ffmpeg(self):
        support = _gpu_support_none()
        support["ffmpeg_nvenc_h265"] = True
        worker = self._make_worker(gpu_support=support, video_encoder="nvenc_h265")
        assert worker._encoder_backend == "ffmpeg"

    def test_vaapi_always_uses_ffmpeg(self):
        worker = self._make_worker(video_encoder="vaapi_h265")
        assert worker._encoder_backend == "ffmpeg"

    def test_amf_always_uses_ffmpeg(self):
        worker = self._make_worker(video_encoder="amf_h265")
        assert worker._encoder_backend == "ffmpeg"

    def test_qsv_uses_ffmpeg(self):
        worker = self._make_worker(video_encoder="qsv_h265")
        assert worker._encoder_backend == "ffmpeg"

    def test_software_uses_ffmpeg(self):
        worker = self._make_worker(video_encoder="x264")
        assert worker._encoder_backend == "ffmpeg"


# ─── FFmpeg command building ─────────────────────────────────────────────────


class TestBuildFfmpegCommand:
    """Tests for _build_ffmpeg_command with different encoder families."""

    def _make_worker(self, video_encoder="nvenc_h265"):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()), \
             patch("transcoder.settings") as mock_settings:
            mock_settings.video_encoder = video_encoder
            mock_settings.video_quality = 22
            mock_settings.audio_encoder = "copy"
            mock_settings.subtitle_mode = "all"
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()
            # Re-patch settings for command building
            with patch("transcoder.settings", mock_settings):
                return worker, mock_settings

    def test_nvenc_h265_command(self):
        worker, settings = self._make_worker("nvenc_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "-hwaccel" in cmd
        assert "cuda" in cmd
        assert "hevc_nvenc" in cmd
        assert "-cq" in cmd
        # Explicit stream mapping
        assert "-map" in cmd
        assert "0:v:0" in cmd
        assert "0:a?" in cmd

    def test_nvenc_h264_command(self):
        worker, settings = self._make_worker("nvenc_h264")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "h264_nvenc" in cmd

    def test_vaapi_h265_command(self):
        worker, settings = self._make_worker("vaapi_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "-hwaccel" in cmd
        assert "vaapi" in cmd
        assert "hevc_vaapi" in cmd
        assert "-rc_mode" in cmd
        assert "CQP" in cmd
        assert "-qp" in cmd

    def test_vaapi_h264_command(self):
        worker, settings = self._make_worker("vaapi_h264")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "h264_vaapi" in cmd

    def test_amf_h265_command(self):
        worker, settings = self._make_worker("amf_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "hevc_amf" in cmd
        assert "-rc" in cmd
        assert "cqp" in cmd
        assert "-qp_i" in cmd

    def test_qsv_h265_command(self):
        worker, settings = self._make_worker("qsv_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "-hwaccel" in cmd
        assert "qsv" in cmd
        assert "hevc_qsv" in cmd
        assert "-global_quality" in cmd

    def test_qsv_h264_command(self):
        worker, settings = self._make_worker("qsv_h264")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "h264_qsv" in cmd
        assert "-global_quality" in cmd

    def test_software_x265_command(self):
        worker, settings = self._make_worker("x265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "libx265" in cmd
        assert "-crf" in cmd
        assert "-hwaccel" not in cmd

    def test_software_x264_command(self):
        worker, settings = self._make_worker("x264")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "libx264" in cmd
        assert "-crf" in cmd
        assert "-hwaccel" not in cmd

    def test_audio_copy(self):
        worker, settings = self._make_worker("nvenc_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        idx = cmd.index("-c:a")
        assert cmd[idx + 1] == "copy"

    def test_subtitle_all(self):
        worker, settings = self._make_worker("nvenc_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        # Should map all subtitles and copy them
        assert "0:s?" in cmd
        idx = cmd.index("-c:s")
        assert cmd[idx + 1] == "copy"

    def test_subtitle_none(self):
        worker, settings = self._make_worker("nvenc_h265")
        settings.subtitle_mode = "none"
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        # Should not map any subtitle streams
        assert "0:s?" not in cmd
        assert "0:s:0?" not in cmd
        assert "-c:s" not in cmd

    def test_subtitle_first(self):
        worker, settings = self._make_worker("nvenc_h265")
        settings.subtitle_mode = "first"
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        # Should map only first subtitle stream
        assert "0:s:0?" in cmd
        idx = cmd.index("-c:s")
        assert cmd[idx + 1] == "copy"

    def test_vaapi_includes_device_path(self):
        worker, settings = self._make_worker("vaapi_h265")
        with patch("transcoder.settings", settings), \
             patch.dict("os.environ", {"VAAPI_DEVICE": "/dev/dri/renderD128"}):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "-hwaccel_device" in cmd
        device_idx = cmd.index("-hwaccel_device")
        assert cmd[device_idx + 1] == "/dev/dri/renderD128"

    def test_nvenc_480p_upscale(self):
        """NVENC FFmpeg should use scale_cuda for DVD upscale."""
        worker, settings = self._make_worker("nvenc_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"), resolution=(720, 480))
        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        assert "scale_cuda=1280:-2" in cmd[vf_idx + 1]

    def test_vaapi_480p_upscale(self):
        """VAAPI FFmpeg should use scale_vaapi for DVD upscale."""
        worker, settings = self._make_worker("vaapi_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"), resolution=(720, 480))
        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        assert "scale_vaapi=w=1280:h=-2" in cmd[vf_idx + 1]

    def test_qsv_480p_upscale(self):
        """QSV FFmpeg should use vpp_qsv for DVD upscale."""
        worker, settings = self._make_worker("qsv_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"), resolution=(720, 480))
        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        assert "vpp_qsv=w=1280:h=-2" in cmd[vf_idx + 1]

    def test_amf_480p_upscale(self):
        """AMF FFmpeg should use software scale for DVD upscale."""
        worker, settings = self._make_worker("amf_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"), resolution=(720, 480))
        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        assert "scale=1280:-2" in cmd[vf_idx + 1]

    def test_software_480p_upscale(self):
        """Software FFmpeg should use software scale for DVD upscale."""
        worker, settings = self._make_worker("x265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"), resolution=(720, 480))
        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        assert "scale=1280:-2" in cmd[vf_idx + 1]

    def test_1080p_no_scale(self):
        """1080p source should not add any scale filter."""
        worker, settings = self._make_worker("nvenc_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"), resolution=(1920, 1080))
        assert "-vf" not in cmd

    def test_4k_no_scale(self):
        """4K source should not add any scale filter."""
        worker, settings = self._make_worker("nvenc_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"), resolution=(3840, 2160))
        assert "-vf" not in cmd

    def test_no_resolution_no_scale(self):
        """No resolution info should not add any scale filter."""
        worker, settings = self._make_worker("nvenc_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"), resolution=None)
        assert "-vf" not in cmd

    def test_576p_pal_dvd_upscale(self):
        """PAL DVD (576p) should also be upscaled."""
        worker, settings = self._make_worker("nvenc_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"), resolution=(720, 576))
        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        assert "scale_cuda=1280:-2" in cmd[vf_idx + 1]


# ─── TranscodeWorker._resolve_source_path ─────────────────────────────────────


class TestResolveSourcePath:
    """Tests for _resolve_source_path method."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_direct_path_with_files(self, tmp_dirs):
        """When direct path exists and has MKV files, return it as-is."""
        movie_dir = tmp_dirs["raw"] / "SERIAL_MOM"
        movie_dir.mkdir()
        (movie_dir / "SERIAL_MOM.mkv").write_bytes(b"\x00" * 100)

        worker = self._make_worker()
        with patch("transcoder.settings") as mock_settings:
            mock_settings.raw_path = str(tmp_dirs["raw"])
            result = worker._resolve_source_path(str(movie_dir))
        assert result == str(movie_dir)

    def test_empty_direct_path_finds_subdirectory(self, tmp_dirs):
        """When direct path is empty, find files in subdirectory matching title."""
        # Direct path exists but is empty
        movie_dir = tmp_dirs["raw"] / "SERIAL_MOM"
        movie_dir.mkdir()

        # ARM moved files here
        actual_dir = tmp_dirs["raw"] / "unidentified" / "SERIAL_MOM_177059407232"
        actual_dir.mkdir(parents=True)
        (actual_dir / "SERIAL_MOM.mkv").write_bytes(b"\x00" * 100)

        worker = self._make_worker()
        with patch("transcoder.settings") as mock_settings:
            mock_settings.raw_path = str(tmp_dirs["raw"])
            result = worker._resolve_source_path(str(movie_dir))
        assert result == str(actual_dir)

    def test_missing_direct_path_finds_subdirectory(self, tmp_dirs):
        """When direct path doesn't exist, find files in subdirectory."""
        movie_dir = tmp_dirs["raw"] / "SERIAL_MOM"
        # Don't create the direct path

        actual_dir = tmp_dirs["raw"] / "unidentified" / "SERIAL_MOM_177059407232"
        actual_dir.mkdir(parents=True)
        (actual_dir / "SERIAL_MOM.mkv").write_bytes(b"\x00" * 100)

        worker = self._make_worker()
        with patch("transcoder.settings") as mock_settings:
            mock_settings.raw_path = str(tmp_dirs["raw"])
            result = worker._resolve_source_path(str(movie_dir))
        assert result == str(actual_dir)

    def test_finds_in_movies_subfolder(self, tmp_dirs):
        """ARM may put identified movies in a 'movies' subfolder."""
        movie_dir = tmp_dirs["raw"] / "THE_MATRIX"
        # No direct path

        actual_dir = tmp_dirs["raw"] / "movies" / "THE_MATRIX"
        actual_dir.mkdir(parents=True)
        (actual_dir / "THE_MATRIX.mkv").write_bytes(b"\x00" * 100)

        worker = self._make_worker()
        with patch("transcoder.settings") as mock_settings:
            mock_settings.raw_path = str(tmp_dirs["raw"])
            result = worker._resolve_source_path(str(movie_dir))
        assert result == str(actual_dir)

    def test_picks_most_recent_candidate(self, tmp_dirs):
        """When multiple matches exist, pick the most recently modified."""
        import time
        movie_dir = tmp_dirs["raw"] / "SERIAL_MOM"

        old_dir = tmp_dirs["raw"] / "unidentified" / "SERIAL_MOM_100"
        old_dir.mkdir(parents=True)
        (old_dir / "SERIAL_MOM.mkv").write_bytes(b"\x00" * 100)

        time.sleep(0.05)  # Ensure different mtime

        new_dir = tmp_dirs["raw"] / "unidentified" / "SERIAL_MOM_200"
        new_dir.mkdir(parents=True)
        (new_dir / "SERIAL_MOM.mkv").write_bytes(b"\x00" * 100)

        worker = self._make_worker()
        with patch("transcoder.settings") as mock_settings:
            mock_settings.raw_path = str(tmp_dirs["raw"])
            result = worker._resolve_source_path(str(movie_dir))
        assert result == str(new_dir)

    def test_no_match_returns_original(self, tmp_dirs):
        """When no matching subdirectory found, return original path."""
        movie_dir = tmp_dirs["raw"] / "NONEXISTENT"

        worker = self._make_worker()
        with patch("transcoder.settings") as mock_settings:
            mock_settings.raw_path = str(tmp_dirs["raw"])
            result = worker._resolve_source_path(str(movie_dir))
        assert result == str(movie_dir)

    def test_audio_files_in_subdirectory(self, tmp_dirs):
        """Resolves when subdirectory contains audio files (CD rip)."""
        cd_dir = tmp_dirs["raw"] / "ALBUM_TITLE"

        actual_dir = tmp_dirs["raw"] / "unidentified" / "ALBUM_TITLE_12345"
        actual_dir.mkdir(parents=True)
        (actual_dir / "track01.flac").write_bytes(b"\x00" * 100)

        worker = self._make_worker()
        with patch("transcoder.settings") as mock_settings:
            mock_settings.raw_path = str(tmp_dirs["raw"])
            result = worker._resolve_source_path(str(cd_dir))
        assert result == str(actual_dir)

    def test_skips_subdirectory_without_media(self, tmp_dirs):
        """Ignores subdirectories that don't contain media files."""
        movie_dir = tmp_dirs["raw"] / "SERIAL_MOM"

        # Directory matches title but has no media files
        no_media_dir = tmp_dirs["raw"] / "unidentified" / "SERIAL_MOM_100"
        no_media_dir.mkdir(parents=True)
        (no_media_dir / "readme.txt").write_text("no media here")

        worker = self._make_worker()
        with patch("transcoder.settings") as mock_settings:
            mock_settings.raw_path = str(tmp_dirs["raw"])
            result = worker._resolve_source_path(str(movie_dir))
        assert result == str(movie_dir)  # Falls back to original


# ─── TranscodeWorker._discover_source_files ──────────────────────────────────


class TestDiscoverSourceFiles:
    """Tests for _discover_source_files method."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_finds_mkv_files(self, sample_mkv_dir):
        worker = self._make_worker()
        files = worker._discover_source_files(str(sample_mkv_dir["dir"]))
        assert len(files) == 2
        names = {f.name for f in files}
        assert "title_main.mkv" in names
        assert "title_extra.mkv" in names

    def test_sorted_by_size(self, sample_mkv_dir):
        worker = self._make_worker()
        files = worker._discover_source_files(str(sample_mkv_dir["dir"]))
        assert files[0].name == "title_main.mkv"

    def test_single_file(self, tmp_path):
        mkv = tmp_path / "movie.mkv"
        mkv.write_bytes(b"\x00" * 100)
        worker = self._make_worker()
        files = worker._discover_source_files(str(mkv))
        assert len(files) == 1
        assert files[0].name == "movie.mkv"

    def test_no_mkv_files(self, tmp_path):
        (tmp_path / "readme.txt").write_text("not a video")
        worker = self._make_worker()
        files = worker._discover_source_files(str(tmp_path))
        assert len(files) == 0

    def test_non_mkv_single_file(self, tmp_path):
        txt = tmp_path / "readme.txt"
        txt.write_text("not a video")
        worker = self._make_worker()
        files = worker._discover_source_files(str(txt))
        assert len(files) == 0

    def test_ignores_non_mkv_in_dir(self, tmp_path):
        (tmp_path / "movie.mkv").write_bytes(b"\x00" * 100)
        (tmp_path / "cover.jpg").write_bytes(b"\x00" * 50)
        (tmp_path / "subs.srt").write_text("subtitle")
        worker = self._make_worker()
        files = worker._discover_source_files(str(tmp_path))
        assert len(files) == 1
        assert files[0].suffix == ".mkv"


# ─── TranscodeWorker._discover_audio_files ────────────────────────────────────


class TestDiscoverAudioFiles:
    """Tests for _discover_audio_files method."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_finds_flac_files(self, tmp_path):
        (tmp_path / "track01.flac").write_bytes(b"\x00" * 100)
        (tmp_path / "track02.flac").write_bytes(b"\x00" * 200)
        worker = self._make_worker()
        files = worker._discover_audio_files(str(tmp_path))
        assert len(files) == 2
        names = {f.name for f in files}
        assert "track01.flac" in names
        assert "track02.flac" in names

    def test_finds_mixed_audio_formats(self, tmp_path):
        (tmp_path / "track.flac").write_bytes(b"\x00" * 100)
        (tmp_path / "track.mp3").write_bytes(b"\x00" * 100)
        (tmp_path / "track.ogg").write_bytes(b"\x00" * 100)
        (tmp_path / "track.wav").write_bytes(b"\x00" * 100)
        (tmp_path / "track.m4a").write_bytes(b"\x00" * 100)
        worker = self._make_worker()
        files = worker._discover_audio_files(str(tmp_path))
        assert len(files) == 5

    def test_returns_empty_for_mkv_only(self, tmp_path):
        (tmp_path / "movie.mkv").write_bytes(b"\x00" * 100)
        worker = self._make_worker()
        files = worker._discover_audio_files(str(tmp_path))
        assert len(files) == 0

    def test_returns_empty_for_empty_dir(self, tmp_path):
        worker = self._make_worker()
        files = worker._discover_audio_files(str(tmp_path))
        assert len(files) == 0

    def test_ignores_non_audio_files(self, tmp_path):
        (tmp_path / "track.flac").write_bytes(b"\x00" * 100)
        (tmp_path / "cover.jpg").write_bytes(b"\x00" * 50)
        (tmp_path / "playlist.m3u").write_text("list")
        worker = self._make_worker()
        files = worker._discover_audio_files(str(tmp_path))
        assert len(files) == 1
        assert files[0].suffix == ".flac"

    def test_single_audio_file(self, tmp_path):
        flac = tmp_path / "track.flac"
        flac.write_bytes(b"\x00" * 100)
        worker = self._make_worker()
        files = worker._discover_audio_files(str(flac))
        assert len(files) == 1
        assert files[0].name == "track.flac"

    def test_single_non_audio_file(self, tmp_path):
        txt = tmp_path / "readme.txt"
        txt.write_text("not audio")
        worker = self._make_worker()
        files = worker._discover_audio_files(str(txt))
        assert len(files) == 0

    def test_sorted_by_name(self, tmp_path):
        (tmp_path / "track03.flac").write_bytes(b"\x00" * 100)
        (tmp_path / "track01.flac").write_bytes(b"\x00" * 100)
        (tmp_path / "track02.flac").write_bytes(b"\x00" * 100)
        worker = self._make_worker()
        files = worker._discover_audio_files(str(tmp_path))
        assert [f.name for f in files] == ["track01.flac", "track02.flac", "track03.flac"]


# ─── TranscodeWorker._detect_video_type ───────────────────────────────────────


class TestDetectVideoType:
    """Tests for _detect_video_type method."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_movie_title_with_year(self):
        worker = self._make_worker()
        assert worker._detect_video_type("The Matrix (1999)", "/data/raw/The Matrix (1999)") == "movie"

    def test_movie_plain_title(self):
        worker = self._make_worker()
        assert worker._detect_video_type("Inception", "/data/raw/Inception") == "movie"

    def test_tv_season_and_episode(self):
        worker = self._make_worker()
        assert worker._detect_video_type("Breaking Bad S01E01", "/data/raw/Breaking Bad S01E01") == "tv"

    def test_tv_season_only(self):
        worker = self._make_worker()
        assert worker._detect_video_type("The Office S02", "/data/raw/The Office S02") == "tv"

    def test_tv_detected_from_source_path(self):
        worker = self._make_worker()
        assert worker._detect_video_type("ARM notification", "/data/raw/Seinfeld S05E03") == "tv"

    def test_tv_case_insensitive(self):
        worker = self._make_worker()
        assert worker._detect_video_type("show s01e01", "/data/raw/show") == "tv"

    def test_tv_underscore_separator(self):
        worker = self._make_worker()
        assert worker._detect_video_type("Show_S03E12", "/data/raw/Show_S03E12") == "tv"

    def test_movie_with_s_in_title(self):
        """Title containing 'S' followed by non-season digits should be movie."""
        worker = self._make_worker()
        assert worker._detect_video_type("Spider-Man", "/data/raw/Spider-Man") == "movie"


# ─── TranscodeWorker._determine_output_path ──────────────────────────────────


class TestDetermineOutputPath:
    """Tests for _determine_output_path method."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_normal_title(self):
        worker = self._make_worker()
        result = worker._determine_output_path("The Matrix", "/data/raw/matrix")
        assert "The Matrix" in str(result)
        assert str(result).startswith(str(Path(settings.completed_path)))

    def test_title_with_special_chars(self):
        worker = self._make_worker()
        result = worker._determine_output_path('Movie: "Title"', "/data/raw/movie")
        path_str = str(result)
        assert ":" not in Path(path_str).name
        assert '"' not in Path(path_str).name

    def test_movie_uses_movies_subdir(self):
        worker = self._make_worker()
        result = worker._determine_output_path("Test Movie (2024)", "/data/raw/test")
        assert settings.movies_subdir in str(result)

    def test_tv_uses_tv_subdir(self):
        worker = self._make_worker()
        result = worker._determine_output_path("Show S01E05", "/data/raw/Show S01E05")
        assert settings.tv_subdir in str(result)


# ─── TranscodeWorker._classify_media_type ─────────────────────────────────────


class TestClassifyMediaType:
    """Tests for _classify_media_type static method."""

    def test_dvd_480p(self):
        from transcoder import TranscodeWorker
        assert TranscodeWorker._classify_media_type(480) == "DVD"

    def test_dvd_576p_pal(self):
        from transcoder import TranscodeWorker
        assert TranscodeWorker._classify_media_type(576) == "DVD"

    def test_bluray_720p(self):
        from transcoder import TranscodeWorker
        assert TranscodeWorker._classify_media_type(720) == "Blu-ray"

    def test_bluray_1080p(self):
        from transcoder import TranscodeWorker
        assert TranscodeWorker._classify_media_type(1080) == "Blu-ray"

    def test_uhd_2160p(self):
        from transcoder import TranscodeWorker
        assert TranscodeWorker._classify_media_type(2160) == "UHD Blu-ray"

    def test_uhd_4320p(self):
        from transcoder import TranscodeWorker
        assert TranscodeWorker._classify_media_type(4320) == "UHD Blu-ray"


# ─── TranscodeWorker._format_resolution ──────────────────────────────────────


class TestFormatResolution:
    """Tests for _format_resolution static method."""

    def test_480p(self):
        from transcoder import TranscodeWorker
        assert TranscodeWorker._format_resolution(480) == "480p"

    def test_576p_still_480p_label(self):
        from transcoder import TranscodeWorker
        assert TranscodeWorker._format_resolution(576) == "480p"

    def test_720p(self):
        from transcoder import TranscodeWorker
        assert TranscodeWorker._format_resolution(720) == "720p"

    def test_1080p(self):
        from transcoder import TranscodeWorker
        assert TranscodeWorker._format_resolution(1080) == "1080p"

    def test_2160p(self):
        from transcoder import TranscodeWorker
        assert TranscodeWorker._format_resolution(2160) == "2160p"

    def test_unusual_resolution(self):
        from transcoder import TranscodeWorker
        assert TranscodeWorker._format_resolution(900) == "900p"


# ─── TranscodeWorker._get_codec_name ─────────────────────────────────────────


class TestGetCodecName:
    """Tests for _get_codec_name method."""

    def _make_worker(self, video_encoder="nvenc_h265"):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()), \
             patch("transcoder.settings") as mock_settings:
            mock_settings.video_encoder = video_encoder
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_nvenc_h265(self):
        worker = self._make_worker("nvenc_h265")
        with patch("transcoder.settings") as s:
            s.video_encoder = "nvenc_h265"
            assert worker._get_codec_name() == "HEVC"

    def test_hevc_nvenc(self):
        worker = self._make_worker("nvenc_h265")
        with patch("transcoder.settings") as s:
            s.video_encoder = "hevc_nvenc"
            assert worker._get_codec_name() == "HEVC"

    def test_x265(self):
        worker = self._make_worker("x265")
        with patch("transcoder.settings") as s:
            s.video_encoder = "x265"
            assert worker._get_codec_name() == "HEVC"

    def test_nvenc_h264(self):
        worker = self._make_worker("nvenc_h264")
        with patch("transcoder.settings") as s:
            s.video_encoder = "nvenc_h264"
            assert worker._get_codec_name() == "H264"

    def test_x264(self):
        worker = self._make_worker("x264")
        with patch("transcoder.settings") as s:
            s.video_encoder = "x264"
            assert worker._get_codec_name() == "H264"

    def test_vaapi_h265(self):
        worker = self._make_worker("vaapi_h265")
        with patch("transcoder.settings") as s:
            s.video_encoder = "vaapi_h265"
            assert worker._get_codec_name() == "HEVC"

    def test_qsv_h264(self):
        worker = self._make_worker("qsv_h264")
        with patch("transcoder.settings") as s:
            s.video_encoder = "qsv_h264"
            assert worker._get_codec_name() == "H264"

    def test_amf_h265(self):
        worker = self._make_worker("amf_h265")
        with patch("transcoder.settings") as s:
            s.video_encoder = "amf_h265"
            assert worker._get_codec_name() == "HEVC"


# ─── TranscodeWorker._determine_output_path with resolution ──────────────────


class TestDetermineOutputPathWithMetadata:
    """Tests for _determine_output_path with resolution metadata."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_dvd_with_year(self):
        worker = self._make_worker()
        with patch("transcoder.settings") as s:
            s.completed_path = "/data/completed"
            s.movies_subdir = "movies"
            s.video_encoder = "nvenc_h265"
            result = worker._determine_output_path(
                "Serial-Mom", "/data/raw/Serial-Mom (1994)", resolution=(720, 480)
            )
        assert result.name == "Serial-Mom (1994) 480p DVD HEVC"

    def test_bluray_1080p_with_year(self):
        worker = self._make_worker()
        with patch("transcoder.settings") as s:
            s.completed_path = "/data/completed"
            s.movies_subdir = "movies"
            s.video_encoder = "nvenc_h265"
            result = worker._determine_output_path(
                "Some Movie", "/data/raw/Some Movie (2020)", resolution=(1920, 1080)
            )
        assert result.name == "Some Movie (2020) 1080p Blu-ray HEVC"

    def test_uhd_2160p_with_year(self):
        worker = self._make_worker()
        with patch("transcoder.settings") as s:
            s.completed_path = "/data/completed"
            s.movies_subdir = "movies"
            s.video_encoder = "nvenc_h265"
            result = worker._determine_output_path(
                "Big Film", "/data/raw/Big Film (2023)", resolution=(3840, 2160)
            )
        assert result.name == "Big Film (2023) 2160p UHD Blu-ray HEVC"

    def test_no_year_in_source(self):
        worker = self._make_worker()
        with patch("transcoder.settings") as s:
            s.completed_path = "/data/completed"
            s.movies_subdir = "movies"
            s.video_encoder = "nvenc_h265"
            result = worker._determine_output_path(
                "Unknown Movie", "/data/raw/Unknown Movie", resolution=(1920, 1080)
            )
        assert result.name == "Unknown Movie 1080p Blu-ray HEVC"

    def test_no_resolution_with_year(self):
        worker = self._make_worker()
        with patch("transcoder.settings") as s:
            s.completed_path = "/data/completed"
            s.movies_subdir = "movies"
            s.video_encoder = "nvenc_h265"
            result = worker._determine_output_path(
                "Fallback Movie", "/data/raw/Fallback Movie (2021)", resolution=None
            )
        assert result.name == "Fallback Movie (2021)"

    def test_no_resolution_no_year(self):
        worker = self._make_worker()
        with patch("transcoder.settings") as s:
            s.completed_path = "/data/completed"
            s.movies_subdir = "movies"
            s.video_encoder = "nvenc_h265"
            result = worker._determine_output_path(
                "Plain Movie", "/data/raw/Plain Movie", resolution=None
            )
        assert result.name == "Plain Movie"

    def test_h264_codec(self):
        worker = self._make_worker()
        with patch("transcoder.settings") as s:
            s.completed_path = "/data/completed"
            s.movies_subdir = "movies"
            s.video_encoder = "nvenc_h264"
            result = worker._determine_output_path(
                "H264 Movie", "/data/raw/H264 Movie (2022)", resolution=(1920, 1080)
            )
        assert result.name == "H264 Movie (2022) 1080p Blu-ray H264"

    def test_tv_show_with_resolution(self):
        worker = self._make_worker()
        with patch("transcoder.settings") as s:
            s.completed_path = "/data/completed"
            s.tv_subdir = "tv"
            s.video_encoder = "nvenc_h265"
            result = worker._determine_output_path(
                "Show S01E05", "/data/raw/Show S01E05 (2023)", resolution=(1920, 1080)
            )
        assert "tv" in str(result)
        assert result.name == "Show S01E05 (2023) 1080p Blu-ray HEVC"

    def test_720p_resolution(self):
        worker = self._make_worker()
        with patch("transcoder.settings") as s:
            s.completed_path = "/data/completed"
            s.movies_subdir = "movies"
            s.video_encoder = "x265"
            result = worker._determine_output_path(
                "HD Movie", "/data/raw/HD Movie (2019)", resolution=(1280, 720)
            )
        assert result.name == "HD Movie (2019) 720p Blu-ray HEVC"


# ─── TranscodeWorker._cleanup_source ─────────────────────────────────────────


class TestCleanupSource:
    """Tests for _cleanup_source method."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_cleanup_directory(self, tmp_path):
        target = tmp_path / "movie_dir"
        target.mkdir()
        (target / "file.mkv").write_bytes(b"\x00" * 100)
        worker = self._make_worker()
        worker._cleanup_source(str(target))
        assert not target.exists()

    def test_cleanup_single_file(self, tmp_path):
        target = tmp_path / "movie.mkv"
        target.write_bytes(b"\x00" * 100)
        worker = self._make_worker()
        worker._cleanup_source(str(target))
        assert not target.exists()

    def test_cleanup_nonexistent(self, tmp_path):
        worker = self._make_worker()
        path = str(tmp_path / "nonexistent")
        worker._cleanup_source(path)  # Should not raise


# ─── TranscodeWorker properties ──────────────────────────────────────────────


class TestWorkerProperties:
    """Tests for TranscodeWorker properties."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_initial_state(self):
        worker = self._make_worker()
        assert worker.is_running is False
        assert worker.queue_size == 0
        assert worker.current_job is None

    def test_shutdown_sets_event(self):
        worker = self._make_worker()
        assert not worker._shutdown_event.is_set()
        worker.shutdown()
        assert worker._shutdown_event.is_set()


# ─── TranscodeWorker._get_video_resolution ────────────────────────────────


class TestGetVideoResolution:
    """Tests for _get_video_resolution method."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    @pytest.mark.asyncio
    async def test_valid_output_parsed(self):
        """Should parse ffprobe output into (width, height) tuple."""
        worker = self._make_worker()
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"1920x1080\n", b""))

        with patch("transcoder.asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await worker._get_video_resolution(Path("/fake/video.mkv"))

        assert result == (1920, 1080)

    @pytest.mark.asyncio
    async def test_4k_resolution(self):
        """Should parse 4K resolution correctly."""
        worker = self._make_worker()
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"3840x2160\n", b""))

        with patch("transcoder.asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await worker._get_video_resolution(Path("/fake/video.mkv"))

        assert result == (3840, 2160)

    @pytest.mark.asyncio
    async def test_dvd_resolution(self):
        """Should parse DVD resolution correctly."""
        worker = self._make_worker()
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"720x480\n", b""))

        with patch("transcoder.asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await worker._get_video_resolution(Path("/fake/video.mkv"))

        assert result == (720, 480)

    @pytest.mark.asyncio
    async def test_ffprobe_failure_returns_none(self):
        """Should return None when ffprobe fails."""
        worker = self._make_worker()

        with patch("transcoder.asyncio.create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError)):
            result = await worker._get_video_resolution(Path("/fake/video.mkv"))

        assert result is None

    @pytest.mark.asyncio
    async def test_malformed_output_returns_none(self):
        """Should return None when ffprobe output is malformed."""
        worker = self._make_worker()
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"garbage\n", b""))

        with patch("transcoder.asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await worker._get_video_resolution(Path("/fake/video.mkv"))

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_output_returns_none(self):
        """Should return None when ffprobe returns empty output."""
        worker = self._make_worker()
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("transcoder.asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await worker._get_video_resolution(Path("/fake/video.mkv"))

        assert result is None


# ─── HandBrake preset selection by resolution ─────────────────────────────


class TestHandBrakePresetSelection:
    """Tests for resolution-based preset selection in _transcode_file_handbrake."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def _run_handbrake_test(self, resolution, tmp_path):
        """Helper: run _transcode_file_handbrake with mocked resolution, return captured cmd."""
        worker = self._make_worker()
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.__aiter__ = lambda self: self
        mock_proc.stdout.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
        mock_proc.wait = AsyncMock(return_value=0)

        output = tmp_path / "test_out.mkv"

        async def fake_exec(*args, **kwargs):
            output.touch()
            return mock_proc

        return worker, resolution, fake_exec, output

    @pytest.mark.asyncio
    async def test_4k_source_uses_4k_preset(self, tmp_path):
        """4K source (>1080p) should use handbrake_preset_4k."""
        worker, resolution, fake_exec, output = self._run_handbrake_test((3840, 2160), tmp_path)

        captured = []

        async def capturing_exec(*args, **kwargs):
            captured.append(args)
            output.touch()
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.stdout = AsyncMock()
            mock_proc.stdout.__aiter__ = lambda self: self
            mock_proc.stdout.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
            mock_proc.wait = AsyncMock(return_value=0)
            return mock_proc

        with patch.object(worker, "_get_video_resolution", AsyncMock(return_value=resolution)), \
             patch("transcoder.asyncio.create_subprocess_exec", capturing_exec), \
             patch("transcoder.settings") as mock_settings:
            mock_settings.handbrake_preset = "NVENC H.265 1080p"
            mock_settings.handbrake_preset_4k = "H.265 NVENC 2160p 4K"
            mock_settings.handbrake_preset_file = ""
            mock_settings.video_encoder = "nvenc_h265"
            mock_settings.video_quality = 22
            mock_settings.audio_encoder = "copy"
            mock_settings.subtitle_mode = "all"

            await worker._transcode_file_handbrake(
                Path("/fake/video.mkv"), output, 1
            )

        cmd = captured[0]
        preset_idx = cmd.index("--preset")
        assert cmd[preset_idx + 1] == "H.265 NVENC 2160p 4K"
        assert "--width" not in cmd

    @pytest.mark.asyncio
    async def test_1080p_source_uses_standard_preset(self, tmp_path):
        """1080p source should use standard handbrake_preset."""
        worker = self._make_worker()
        output = tmp_path / "test_out.mkv"
        captured = []

        async def capturing_exec(*args, **kwargs):
            captured.append(args)
            output.touch()
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.stdout = AsyncMock()
            mock_proc.stdout.__aiter__ = lambda self: self
            mock_proc.stdout.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
            mock_proc.wait = AsyncMock(return_value=0)
            return mock_proc

        with patch.object(worker, "_get_video_resolution", AsyncMock(return_value=(1920, 1080))), \
             patch("transcoder.asyncio.create_subprocess_exec", capturing_exec), \
             patch("transcoder.settings") as mock_settings:
            mock_settings.handbrake_preset = "NVENC H.265 1080p"
            mock_settings.handbrake_preset_4k = "H.265 NVENC 2160p 4K"
            mock_settings.handbrake_preset_file = ""
            mock_settings.video_encoder = "nvenc_h265"
            mock_settings.video_quality = 22
            mock_settings.audio_encoder = "copy"
            mock_settings.subtitle_mode = "all"

            await worker._transcode_file_handbrake(
                Path("/fake/video.mkv"), output, 1
            )

        cmd = captured[0]
        preset_idx = cmd.index("--preset")
        assert cmd[preset_idx + 1] == "NVENC H.265 1080p"
        assert "--width" not in cmd

    @pytest.mark.asyncio
    async def test_480p_source_adds_upscale(self, tmp_path):
        """DVD source (<720p) should use standard preset with --width 1280."""
        worker = self._make_worker()
        output = tmp_path / "test_out.mkv"
        captured = []

        async def capturing_exec(*args, **kwargs):
            captured.append(args)
            output.touch()
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.stdout = AsyncMock()
            mock_proc.stdout.__aiter__ = lambda self: self
            mock_proc.stdout.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
            mock_proc.wait = AsyncMock(return_value=0)
            return mock_proc

        with patch.object(worker, "_get_video_resolution", AsyncMock(return_value=(720, 480))), \
             patch("transcoder.asyncio.create_subprocess_exec", capturing_exec), \
             patch("transcoder.settings") as mock_settings:
            mock_settings.handbrake_preset = "NVENC H.265 1080p"
            mock_settings.handbrake_preset_4k = "H.265 NVENC 2160p 4K"
            mock_settings.handbrake_preset_dvd = ""
            mock_settings.handbrake_preset_file = ""
            mock_settings.video_encoder = "nvenc_h265"
            mock_settings.video_quality = 22
            mock_settings.audio_encoder = "copy"
            mock_settings.subtitle_mode = "all"

            await worker._transcode_file_handbrake(
                Path("/fake/video.mkv"), output, 1
            )

        cmd = captured[0]
        preset_idx = cmd.index("--preset")
        assert cmd[preset_idx + 1] == "NVENC H.265 1080p"
        assert "--width" in cmd
        width_idx = cmd.index("--width")
        assert cmd[width_idx + 1] == "1280"

    @pytest.mark.asyncio
    async def test_ffprobe_failure_uses_standard_preset(self, tmp_path):
        """When resolution detection fails, should fall back to standard preset."""
        worker = self._make_worker()
        output = tmp_path / "test_out.mkv"
        captured = []

        async def capturing_exec(*args, **kwargs):
            captured.append(args)
            output.touch()
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.stdout = AsyncMock()
            mock_proc.stdout.__aiter__ = lambda self: self
            mock_proc.stdout.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
            mock_proc.wait = AsyncMock(return_value=0)
            return mock_proc

        with patch.object(worker, "_get_video_resolution", AsyncMock(return_value=None)), \
             patch("transcoder.asyncio.create_subprocess_exec", capturing_exec), \
             patch("transcoder.settings") as mock_settings:
            mock_settings.handbrake_preset = "NVENC H.265 1080p"
            mock_settings.handbrake_preset_4k = "H.265 NVENC 2160p 4K"
            mock_settings.handbrake_preset_file = ""
            mock_settings.video_encoder = "nvenc_h265"
            mock_settings.video_quality = 22
            mock_settings.audio_encoder = "copy"
            mock_settings.subtitle_mode = "all"

            await worker._transcode_file_handbrake(
                Path("/fake/video.mkv"), output, 1
            )

        cmd = captured[0]
        preset_idx = cmd.index("--preset")
        assert cmd[preset_idx + 1] == "NVENC H.265 1080p"
        assert "--width" not in cmd

    @pytest.mark.asyncio
    async def test_720p_source_uses_standard_preset(self, tmp_path):
        """720p source (boundary) should use standard preset without upscale."""
        worker = self._make_worker()
        output = tmp_path / "test_out.mkv"
        captured = []

        async def capturing_exec(*args, **kwargs):
            captured.append(args)
            output.touch()
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.stdout = AsyncMock()
            mock_proc.stdout.__aiter__ = lambda self: self
            mock_proc.stdout.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
            mock_proc.wait = AsyncMock(return_value=0)
            return mock_proc

        with patch.object(worker, "_get_video_resolution", AsyncMock(return_value=(1280, 720))), \
             patch("transcoder.asyncio.create_subprocess_exec", capturing_exec), \
             patch("transcoder.settings") as mock_settings:
            mock_settings.handbrake_preset = "NVENC H.265 1080p"
            mock_settings.handbrake_preset_4k = "H.265 NVENC 2160p 4K"
            mock_settings.handbrake_preset_file = ""
            mock_settings.video_encoder = "nvenc_h265"
            mock_settings.video_quality = 22
            mock_settings.audio_encoder = "copy"
            mock_settings.subtitle_mode = "all"

            await worker._transcode_file_handbrake(
                Path("/fake/video.mkv"), output, 1
            )

        cmd = captured[0]
        preset_idx = cmd.index("--preset")
        assert cmd[preset_idx + 1] == "NVENC H.265 1080p"
        assert "--width" not in cmd


# ─── Disk space pre-check in _process_job ──────────────────────────────────


class TestDiskSpacePreCheck:
    """Tests for disk space pre-check in _process_job."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    @pytest.mark.asyncio
    async def test_insufficient_disk_space_fails_job(self, tmp_dirs):
        """Job should fail with disk space error when space is insufficient."""
        from contextlib import asynccontextmanager
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from models import Base, TranscodeJobDB

        # Set up test DB
        db_path = str(tmp_dirs["db_dir"] / "disktest.db")
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

        # Create source directory with MKV file
        source_dir = tmp_dirs["raw"] / "TestMovie"
        source_dir.mkdir()
        (source_dir / "movie.mkv").write_bytes(b"\x00" * 10000)

        # Create job in DB
        async with session_factory() as session:
            from models import JobStatus
            job_db = TranscodeJobDB(
                title="TestMovie",
                source_path=str(source_dir),
                status=JobStatus.PENDING,
            )
            session.add(job_db)
            await session.commit()
            await session.refresh(job_db)
            job_id = job_db.id

        job = TranscodeJob(
            id=job_id,
            title="TestMovie",
            source_path=str(source_dir),
        )

        worker = self._make_worker()

        # Mock disk_usage to return very low free space
        mock_disk = MagicMock()
        mock_disk.total = 20 * 1024**3
        mock_disk.used = 19.5 * 1024**3
        mock_disk.free = 0.5 * 1024**3  # Only 0.5GB free

        with patch("transcoder.get_db", test_get_db), \
             patch("transcoder.settings") as mock_settings, \
             patch("utils.shutil.disk_usage", return_value=mock_disk):
            mock_settings.work_path = str(tmp_dirs["work"])
            mock_settings.raw_path = str(tmp_dirs["raw"])
            mock_settings.completed_path = str(tmp_dirs["completed"])
            mock_settings.delete_source = False
            mock_settings.stabilize_seconds = 0
            mock_settings.minimum_free_space_gb = 10.0

            await worker._process_job(job)

        # Verify job was marked as failed with disk space error
        async with session_factory() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
            )
            job_db = result.scalar_one()
            assert job_db.status == JobStatus.FAILED
            assert "disk space" in job_db.error.lower()

        await engine.dispose()


# ─── _load_track_metadata ──────────────────────────────────────────────────


class TestLoadTrackMetadata:
    """Tests for TranscodeWorker._load_track_metadata."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    async def _setup_db(self, tmp_path):
        """Create a test DB engine and session factory."""
        from contextlib import asynccontextmanager
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from models import Base

        db_path = str(tmp_path / "track_meta_test.db")
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

        return engine, session_factory, test_get_db

    @pytest.mark.asyncio
    async def test_returns_none_when_not_multi_title(self, tmp_path):
        """Should return None when multi_title is 0 (not a multi-title disc)."""
        import json
        from models import TranscodeJobDB, JobStatus

        engine, session_factory, test_get_db = await self._setup_db(tmp_path)

        # Create a job with multi_title=0
        async with session_factory() as session:
            job_db = TranscodeJobDB(
                title="SingleTitle",
                source_path="/data/raw/movie",
                status=JobStatus.PENDING,
                multi_title=0,
                track_metadata=json.dumps([{"track_number": 1, "filename": "t01.mkv"}]),
            )
            session.add(job_db)
            await session.commit()
            await session.refresh(job_db)
            job_id = job_db.id

        worker = self._make_worker()
        with patch("transcoder.get_db", test_get_db):
            result = await worker._load_track_metadata(job_id)

        assert result is None
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_returns_none_when_no_track_metadata(self, tmp_path):
        """Should return None when track_metadata is NULL."""
        from models import TranscodeJobDB, JobStatus

        engine, session_factory, test_get_db = await self._setup_db(tmp_path)

        async with session_factory() as session:
            job_db = TranscodeJobDB(
                title="NoMetadata",
                source_path="/data/raw/movie",
                status=JobStatus.PENDING,
                multi_title=1,
                track_metadata=None,
            )
            session.add(job_db)
            await session.commit()
            await session.refresh(job_db)
            job_id = job_db.id

        worker = self._make_worker()
        with patch("transcoder.get_db", test_get_db):
            result = await worker._load_track_metadata(job_id)

        assert result is None
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_job(self, tmp_path):
        """Should return None when the job ID does not exist."""
        engine, _session_factory, test_get_db = await self._setup_db(tmp_path)

        worker = self._make_worker()
        with patch("transcoder.get_db", test_get_db):
            result = await worker._load_track_metadata(99999)

        assert result is None
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_returns_none_for_invalid_json(self, tmp_path):
        """Should return None when track_metadata contains invalid JSON."""
        from models import TranscodeJobDB, JobStatus

        engine, session_factory, test_get_db = await self._setup_db(tmp_path)

        async with session_factory() as session:
            job_db = TranscodeJobDB(
                title="BadJSON",
                source_path="/data/raw/movie",
                status=JobStatus.PENDING,
                multi_title=1,
                track_metadata="not-valid-json{{{",
            )
            session.add(job_db)
            await session.commit()
            await session.refresh(job_db)
            job_id = job_db.id

        worker = self._make_worker()
        with patch("transcoder.get_db", test_get_db):
            result = await worker._load_track_metadata(job_id)

        assert result is None
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_returns_map_keyed_by_filename_stem(self, tmp_path):
        """Should return metadata map keyed by filename stem."""
        import json
        from models import TranscodeJobDB, JobStatus

        engine, session_factory, test_get_db = await self._setup_db(tmp_path)

        tracks = [
            {"track_number": 1, "filename": "title_t01.mkv", "title": "Episode 1"},
            {"track_number": 2, "filename": "title_t02.mkv", "title": "Episode 2"},
        ]
        async with session_factory() as session:
            job_db = TranscodeJobDB(
                title="MultiTitle",
                source_path="/data/raw/series",
                status=JobStatus.PENDING,
                multi_title=1,
                track_metadata=json.dumps(tracks),
            )
            session.add(job_db)
            await session.commit()
            await session.refresh(job_db)
            job_id = job_db.id

        worker = self._make_worker()
        with patch("transcoder.get_db", test_get_db):
            result = await worker._load_track_metadata(job_id)

        assert result is not None
        # Keyed by filename stem (without extension)
        assert "title_t01" in result
        assert "title_t02" in result
        assert result["title_t01"]["title"] == "Episode 1"
        assert result["title_t02"]["title"] == "Episode 2"
        # Also keyed by track number
        assert "_track_1" in result
        assert "_track_2" in result
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_tracks_list(self, tmp_path):
        """Should return None when tracks list is empty (no entries produce keys)."""
        import json
        from models import TranscodeJobDB, JobStatus

        engine, session_factory, test_get_db = await self._setup_db(tmp_path)

        async with session_factory() as session:
            job_db = TranscodeJobDB(
                title="EmptyTracks",
                source_path="/data/raw/movie",
                status=JobStatus.PENDING,
                multi_title=1,
                track_metadata=json.dumps([]),
            )
            session.add(job_db)
            await session.commit()
            await session.refresh(job_db)
            job_id = job_db.id

        worker = self._make_worker()
        with patch("transcoder.get_db", test_get_db):
            result = await worker._load_track_metadata(job_id)

        assert result is None
        await engine.dispose()


# ─── queue_job multi-title support ─────────────────────────────────────────


class TestQueueJobMultiTitle:
    """Tests for queue_job() storing multi_title and track_metadata in DB."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    async def _setup_db(self, tmp_path):
        """Create a test DB engine and session factory."""
        from contextlib import asynccontextmanager
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from models import Base

        db_path = str(tmp_path / "queue_job_test.db")
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

        return engine, session_factory, test_get_db

    @pytest.mark.asyncio
    async def test_stores_multi_title_true(self, tmp_path):
        """queue_job with multi_title=True should store multi_title=1 in DB."""
        import json
        from sqlalchemy import select
        from models import TranscodeJobDB

        engine, session_factory, test_get_db = await self._setup_db(tmp_path)
        worker = self._make_worker()

        tracks = [
            {"track_number": 1, "filename": "t01.mkv", "title": "Ep 1"},
            {"track_number": 2, "filename": "t02.mkv", "title": "Ep 2"},
        ]

        with patch("transcoder.get_db", test_get_db):
            job_id, created = await worker.queue_job(
                source_path="/data/raw/series",
                title="Series",
                multi_title=True,
                tracks=tracks,
            )

        assert created is True

        async with session_factory() as session:
            result = await session.execute(
                select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
            )
            job_db = result.scalar_one()
            assert job_db.multi_title == 1
            assert job_db.track_metadata is not None
            stored_tracks = json.loads(job_db.track_metadata)
            assert len(stored_tracks) == 2
            assert stored_tracks[0]["filename"] == "t01.mkv"
            assert stored_tracks[1]["title"] == "Ep 2"

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_stores_multi_title_false(self, tmp_path):
        """queue_job with multi_title=False should store multi_title=0 in DB."""
        from sqlalchemy import select
        from models import TranscodeJobDB

        engine, session_factory, test_get_db = await self._setup_db(tmp_path)
        worker = self._make_worker()

        with patch("transcoder.get_db", test_get_db):
            job_id, created = await worker.queue_job(
                source_path="/data/raw/movie",
                title="Movie",
                multi_title=False,
                tracks=None,
            )

        assert created is True

        async with session_factory() as session:
            result = await session.execute(
                select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
            )
            job_db = result.scalar_one()
            assert job_db.multi_title == 0
            assert job_db.track_metadata is None

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_default_multi_title_is_zero(self, tmp_path):
        """queue_job without multi_title arg should default to multi_title=0."""
        from sqlalchemy import select
        from models import TranscodeJobDB

        engine, session_factory, test_get_db = await self._setup_db(tmp_path)
        worker = self._make_worker()

        with patch("transcoder.get_db", test_get_db):
            job_id, created = await worker.queue_job(
                source_path="/data/raw/movie",
                title="Movie",
            )

        assert created is True

        async with session_factory() as session:
            result = await session.execute(
                select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
            )
            job_db = result.scalar_one()
            assert job_db.multi_title == 0
            assert job_db.track_metadata is None

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_tracks_without_multi_title_still_stored(self, tmp_path):
        """Tracks should be stored even if multi_title defaults to False."""
        import json
        from sqlalchemy import select
        from models import TranscodeJobDB

        engine, session_factory, test_get_db = await self._setup_db(tmp_path)
        worker = self._make_worker()

        tracks = [{"track_number": 1, "filename": "t01.mkv"}]

        with patch("transcoder.get_db", test_get_db):
            job_id, created = await worker.queue_job(
                source_path="/data/raw/movie",
                title="Movie",
                tracks=tracks,
            )

        assert created is True

        async with session_factory() as session:
            result = await session.execute(
                select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
            )
            job_db = result.scalar_one()
            # multi_title defaults to 0 since not passed
            assert job_db.multi_title == 0
            # But tracks are still serialized
            assert job_db.track_metadata is not None
            stored = json.loads(job_db.track_metadata)
            assert len(stored) == 1

        await engine.dispose()


# Import settings for use in output path tests
from config import settings  # noqa: E402
