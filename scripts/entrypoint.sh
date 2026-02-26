#!/bin/sh
# Entrypoint: optionally remap the transcoder user's UID/GID to match the
# host or NFS ownership, fix data-dir permissions, then drop privileges.
#
# Environment variables (all optional):
#   TRANSCODER_UID  — desired UID for the transcoder user  (default: keep image default)
#   TRANSCODER_GID  — desired GID for the transcoder group (default: keep image default)
#
# If the container is already running as non-root (e.g. --user or Kubernetes
# securityContext), the UID/GID remap and chown are skipped.

set -e

# Directories the app needs to write to (bind-mounted from host).
# /data/raw and /config/presets are read-only mounts — skip them.
WRITABLE_DIRS="/data/work /data/db /data/logs /data/completed"

if [ "$(id -u)" = "0" ]; then
    # ── Remap UID/GID if requested ────────────────────────────────────
    CURRENT_UID=$(id -u transcoder)
    CURRENT_GID=$(id -g transcoder)
    TARGET_UID=${TRANSCODER_UID:-$CURRENT_UID}
    TARGET_GID=${TRANSCODER_GID:-$CURRENT_GID}

    if [ "$TARGET_GID" != "$CURRENT_GID" ]; then
        groupmod -o -g "$TARGET_GID" transcoder
        # Fix ownership on app dirs that were created at build time
        find /app /config -group "$CURRENT_GID" -exec chgrp transcoder {} + 2>/dev/null || true
    fi

    if [ "$TARGET_UID" != "$CURRENT_UID" ]; then
        usermod -o -u "$TARGET_UID" transcoder
        # Fix ownership on app dirs that were created at build time
        find /app /config -user "$CURRENT_UID" -exec chown transcoder {} + 2>/dev/null || true
    fi

    # ── Fix ownership on writable bind-mounted dirs ───────────────────
    # Shallow chown (maxdepth 1) to avoid slow recursion on large media trees.
    for dir in $WRITABLE_DIRS; do
        if [ -d "$dir" ]; then
            chown transcoder:transcoder "$dir"
            find "$dir" -maxdepth 1 ! -type d -exec chown transcoder:transcoder {} + 2>/dev/null || true
        fi
    done

    exec gosu transcoder "$@"
else
    exec "$@"
fi
