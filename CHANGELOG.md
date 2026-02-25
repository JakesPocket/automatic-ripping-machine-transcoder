# Changelog

## [10.1.0-alpha.1](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/compare/v10.0.0-alpha.1...v10.1.0-alpha.1) (2026-02-25)


### Features

* add /system/stats endpoint for live CPU, temp, and memory metrics ([9f4326c](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/9f4326c5bf4cf0fa0276cd73a37acd82450b7645))
* Add ARM setup automation script ([c00d34c](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/c00d34c38e8848a3724c9c99ec7a5b2c28fa597d))
* Add audio CD passthrough to music folder ([ee49572](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/ee49572c0ef44c4aacf39c786e8f32ecff27cdf3))
* Add authentication and security improvements ([12f8a35](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/12f8a35ad7839812d639a85e40cd2b3118c520eb))
* Add comprehensive test suite and fix documentation ([e6c9b7a](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/e6c9b7ace7711908242b3bab8601d0a1ba070276))
* add config persistence model and psutil dependency ([39aefd7](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/39aefd7c923cfb7cf412c93d7f7824d80f97f978))
* add GPU auto-detection, config management, and system monitoring ([94db4fa](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/94db4fa42df444f8e71c26a351c390d097461e1d))
* Add media metadata to output folder and file names ([6b1fb39](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/6b1fb39bd00ce4424a29d5fd91dd0cf707e53531))
* Add multi-GPU support (AMD VAAPI/AMF, Intel QSV, software) ([6964d2a](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/6964d2ad440d92f92f7786ce0bb43ee0ed179552))
* Add optical drive watcher for ARM container auto-restart ([27bde1f](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/27bde1f5a59b5e41423e09666220e47ebf4c694c))
* Add resolution-based preset selection for all GPU backends ([717cb67](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/717cb67ad869b75a60d0fbbc5f60b2e0387054dc))
* add rotating file logging and log viewer API ([84f8c5e](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/84f8c5e4460aac9e00a941142698f45eb9aa433a))
* Add security infrastructure and validation (Phase 1) ([76f93a5](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/76f93a54dd5a8ba733ba2b266488d6698f73c452))
* Add stable optical drive symlink script ([6334854](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/63348548fb8c363de888b8c7181281537c13403f))
* add storage disk usage to /system/stats endpoint ([0b50d57](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/0b50d57555a9650c55c96dc5bc5122f006dc7280))
* enhance ARM notification script with raw path support ([98188ef](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/98188ef18d21a8cf7e40b6bba70a90c3e20d71f3))
* expose version from VERSION file in API and health endpoint ([703465e](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/703465e6cf7c8380ee909c02b02e17f7202215c4))
* forward ARM metadata through webhook to transcoder ([affa688](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/affa688e903400ea8564ce3133be58f7b5c80c0f))
* notify ARM-neu to update submodule on release ([c63ae6c](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/c63ae6cd39924c9c9e51a7ed45135238dc61b1d6))
* Use local scratch storage to avoid heavy I/O on NFS ([09c2954](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/09c29540cc6ee687bae61b7ea4c98f7ff0b10918))


### Bug Fixes

* add audio-copy-mask to preserve all audio codecs in passthrough ([cc21c29](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/cc21c29b546e61901fda55129c2d29e86a334c1d))
* add LOG_PATH env var to test conftest to prevent CI failure ([221ef88](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/221ef88130919237475a81e7f7a29c13d5db17d3))
* Add worker 503 guards, graceful shutdown, and import cleanup ([f06e1b9](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/f06e1b97ce7a51b767b468870bcca7b6eb196b72))
* Apprise webhook compatibility and ARM integration config ([83a6b49](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/83a6b495cae5be9b100623c9f61cb135c1780597))
* configure release-please to update VERSION file ([61a132f](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/61a132f88fe3ef029fe4633f3042f2b0d14019d3))
* Correct HandBrake preset name to match built-in presets ([eba50a2](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/eba50a21d6bca3a7c0e264a1fabe73e2398bd62a))
* Create render group in Intel and AMD Dockerfiles ([b089af6](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/b089af6b5eaa56609efef80d8302c75d7be3d1b7))
* Increase drive watcher debounce default to 60s ([9520288](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/95202881ce91ceb4cab763cc1757d58b8e9fa14c))
* Install HandBrake from PPA instead of Alpine multi-stage copy ([d3f3322](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/d3f33224af53c63fa9691af021d05c02338c6ab9))
* line too long in /system/stats endpoint ([02423b3](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/02423b37a88065bd606cc6e8eb5613223df9cf8b))
* Make audio passthrough source cleanup non-fatal ([a43383e](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/a43383e8fbdacb9b1e628b037193705f280f6c97))
* Pass all application settings through Docker compose environment ([0dbb17f](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/0dbb17f1936fffe763526b7e0d3c90f548a16a97))
* Prevent restart loop by checking device visibility in container ([0d76b52](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/0d76b522010109900ea1b9a109a0d147dc9636be))
* Re-resolve source path after stabilization when no files found ([2f50791](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/2f50791c6db9e6ce04c7b5f3c9af8fab1f4e8319))
* remove invalid opus from audio-copy-mask, add mp2 and aac fallback ([757f1ee](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/757f1eebc3e55a27c84560c74b79294f926b197a))
* Replace device visibility check with container uptime check ([4023f52](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/4023f52789ca37d559193a8259cedff100db8064))
* resolve 9 pre-existing test failures in CI ([a061809](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/a0618099743ea8d282c6b9650828c5e86488ded6))
* Resolve ARM subdirectory paths for ripped media ([a28403f](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/a28403f10c1d156cbe70bd89a066b510ab6aa3f7))
* resolve flake8 lint errors ([29489ae](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/29489aefa837ba4a5df2dacb156ddc507e065b4a))
* Short-lived DB sessions, progress rate limiting, stream mapping, and disk space checks ([c0e200b](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/c0e200b593721a92fb104f14f4aa8f1f31fd1df5))
* Update Intel Dockerfile for Debian Trixie package names ([50bccb6](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/50bccb6c6b616784a43a8b39ccdab22251d7b6f1))
* Use copy instead of move for audio passthrough ([d5302e5](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/d5302e5af3ffcb8dcc81ecbe29a3728f84b7f880))
* use DOCKERHUB_USERNAME secret for image name ([8f01c7c](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/8f01c7c5c11624596ea368dd15d1032305af4c43))
* Use extracted media title for job naming and graceful cleanup ([5f44c76](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/5f44c76776908ceb8449db007a2c97009f659ae2))
* use final path from ARM webhook instead of parsing body text ([5b48982](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/5b489829ac4d0cc2d331cb4e8fe74ba0be1dc86d))
* use PAT for release-please so releases trigger publish workflow ([fd72f4b](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/fd72f4b516c2a58c99d47d2932f6e93081fcf535))
* use RELEASE_PAT for parent repo dispatch ([5d16cda](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/5d16cda1160f4c554a7f64459ebce9f89261936b))
* Use Ubuntu universe repo for HandBrake instead of PPA ([912bcef](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/912bcef1b06f178d6d459e251abab503cc0d64c5))

## [0.5.0](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/compare/v0.4.1...v0.5.0) (2026-02-20)


### Features

* forward ARM metadata through webhook to transcoder ([affa688](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/affa688e903400ea8564ce3133be58f7b5c80c0f))

## [0.4.1](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/compare/v0.4.0...v0.4.1) (2026-02-16)


### Bug Fixes

* configure release-please to update VERSION file ([61a132f](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/61a132f88fe3ef029fe4633f3042f2b0d14019d3))

## [0.4.0](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/compare/v0.3.0...v0.4.0) (2026-02-16)


### Features

* notify ARM-neu to update submodule on release ([c63ae6c](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/c63ae6cd39924c9c9e51a7ed45135238dc61b1d6))


### Bug Fixes

* use PAT for release-please so releases trigger publish workflow ([fd72f4b](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/fd72f4b516c2a58c99d47d2932f6e93081fcf535))
* use RELEASE_PAT for parent repo dispatch ([5d16cda](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/5d16cda1160f4c554a7f64459ebce9f89261936b))

## [0.3.0](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/compare/v0.2.1...v0.3.0) (2026-02-16)


### Features

* add /system/stats endpoint for live CPU, temp, and memory metrics ([9f4326c](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/9f4326c5bf4cf0fa0276cd73a37acd82450b7645))
* add storage disk usage to /system/stats endpoint ([0b50d57](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/0b50d57555a9650c55c96dc5bc5122f006dc7280))


### Bug Fixes

* line too long in /system/stats endpoint ([02423b3](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/02423b37a88065bd606cc6e8eb5613223df9cf8b))
* resolve flake8 lint errors ([29489ae](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/29489aefa837ba4a5df2dacb156ddc507e065b4a))

## [0.2.1](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/compare/v0.2.0...v0.2.1) (2026-02-16)


### Bug Fixes

* add LOG_PATH env var to test conftest to prevent CI failure ([221ef88](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/221ef88130919237475a81e7f7a29c13d5db17d3))
* resolve 9 pre-existing test failures in CI ([a061809](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/a0618099743ea8d282c6b9650828c5e86488ded6))
* use DOCKERHUB_USERNAME secret for image name ([8f01c7c](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/8f01c7c5c11624596ea368dd15d1032305af4c43))

## [0.2.0](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/compare/v0.1.0...v0.2.0) (2026-02-15)


### Features

* Add ARM setup automation script ([c00d34c](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/c00d34c38e8848a3724c9c99ec7a5b2c28fa597d))
* Add audio CD passthrough to music folder ([ee49572](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/ee49572c0ef44c4aacf39c786e8f32ecff27cdf3))
* Add authentication and security improvements ([12f8a35](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/12f8a35ad7839812d639a85e40cd2b3118c520eb))
* Add comprehensive test suite and fix documentation ([e6c9b7a](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/e6c9b7ace7711908242b3bab8601d0a1ba070276))
* add config persistence model and psutil dependency ([39aefd7](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/39aefd7c923cfb7cf412c93d7f7824d80f97f978))
* add GPU auto-detection, config management, and system monitoring ([94db4fa](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/94db4fa42df444f8e71c26a351c390d097461e1d))
* Add media metadata to output folder and file names ([6b1fb39](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/6b1fb39bd00ce4424a29d5fd91dd0cf707e53531))
* Add multi-GPU support (AMD VAAPI/AMF, Intel QSV, software) ([6964d2a](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/6964d2ad440d92f92f7786ce0bb43ee0ed179552))
* Add optical drive watcher for ARM container auto-restart ([27bde1f](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/27bde1f5a59b5e41423e09666220e47ebf4c694c))
* Add resolution-based preset selection for all GPU backends ([717cb67](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/717cb67ad869b75a60d0fbbc5f60b2e0387054dc))
* add rotating file logging and log viewer API ([84f8c5e](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/84f8c5e4460aac9e00a941142698f45eb9aa433a))
* Add security infrastructure and validation (Phase 1) ([76f93a5](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/76f93a54dd5a8ba733ba2b266488d6698f73c452))
* Add stable optical drive symlink script ([6334854](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/63348548fb8c363de888b8c7181281537c13403f))
* enhance ARM notification script with raw path support ([98188ef](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/98188ef18d21a8cf7e40b6bba70a90c3e20d71f3))
* Use local scratch storage to avoid heavy I/O on NFS ([09c2954](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/09c29540cc6ee687bae61b7ea4c98f7ff0b10918))


### Bug Fixes

* Add worker 503 guards, graceful shutdown, and import cleanup ([f06e1b9](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/f06e1b97ce7a51b767b468870bcca7b6eb196b72))
* Apprise webhook compatibility and ARM integration config ([83a6b49](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/83a6b495cae5be9b100623c9f61cb135c1780597))
* Correct HandBrake preset name to match built-in presets ([eba50a2](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/eba50a21d6bca3a7c0e264a1fabe73e2398bd62a))
* Create render group in Intel and AMD Dockerfiles ([b089af6](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/b089af6b5eaa56609efef80d8302c75d7be3d1b7))
* Increase drive watcher debounce default to 60s ([9520288](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/95202881ce91ceb4cab763cc1757d58b8e9fa14c))
* Install HandBrake from PPA instead of Alpine multi-stage copy ([d3f3322](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/d3f33224af53c63fa9691af021d05c02338c6ab9))
* Make audio passthrough source cleanup non-fatal ([a43383e](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/a43383e8fbdacb9b1e628b037193705f280f6c97))
* Pass all application settings through Docker compose environment ([0dbb17f](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/0dbb17f1936fffe763526b7e0d3c90f548a16a97))
* Prevent restart loop by checking device visibility in container ([0d76b52](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/0d76b522010109900ea1b9a109a0d147dc9636be))
* Re-resolve source path after stabilization when no files found ([2f50791](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/2f50791c6db9e6ce04c7b5f3c9af8fab1f4e8319))
* Replace device visibility check with container uptime check ([4023f52](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/4023f52789ca37d559193a8259cedff100db8064))
* Resolve ARM subdirectory paths for ripped media ([a28403f](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/a28403f10c1d156cbe70bd89a066b510ab6aa3f7))
* Short-lived DB sessions, progress rate limiting, stream mapping, and disk space checks ([c0e200b](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/c0e200b593721a92fb104f14f4aa8f1f31fd1df5))
* Update Intel Dockerfile for Debian Trixie package names ([50bccb6](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/50bccb6c6b616784a43a8b39ccdab22251d7b6f1))
* Use copy instead of move for audio passthrough ([d5302e5](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/d5302e5af3ffcb8dcc81ecbe29a3728f84b7f880))
* Use extracted media title for job naming and graceful cleanup ([5f44c76](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/5f44c76776908ceb8449db007a2c97009f659ae2))
* Use Ubuntu universe repo for HandBrake instead of PPA ([912bcef](https://github.com/uprightbass360/automatic-ripping-machine-transcoder/commit/912bcef1b06f178d6d459e251abab503cc0d64c5))

## Changelog
