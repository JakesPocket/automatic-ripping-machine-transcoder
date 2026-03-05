#!/usr/bin/env bash
# ARM Drive Watcher Setup - Auto-rescan/restart ARM container when optical drive connects
#
# Installs a host-level watcher that detects when an optical drive appears
# (e.g. powered on or plugged in) and either rescans the drive inside the
# running ARM container (default, safe for multi-drive) or restarts the
# entire container (legacy behavior).
#
# Two modes:
#   udev   - udev rule triggers a systemd oneshot (recommended, multi-drive)
#   device - systemd BindsTo= on the device unit (simpler, single device)
#
# Two actions:
#   rescan  - docker exec rescan_drive.sh (default, safe for multi-drive)
#   restart - docker restart (legacy, kills in-progress rips)
#
# Usage:
#   setup-drive-watcher.sh --mode MODE [OPTIONS]
#   setup-drive-watcher.sh --uninstall
#
# Examples:
#   # Recommended: udev mode with rescan (default action)
#   sudo ./setup-drive-watcher.sh --mode udev --container arm-rippers
#
#   # Legacy: udev mode with container restart
#   sudo ./setup-drive-watcher.sh --mode udev --action restart
#
#   # Device mode with explicit container name
#   sudo ./setup-drive-watcher.sh --mode device --container automatic-ripping-machine
#
#   # Docker Compose restart
#   sudo ./setup-drive-watcher.sh --mode udev --action restart --compose-file /opt/arm/docker-compose.yml
#
#   # Remove everything
#   sudo ./setup-drive-watcher.sh --uninstall

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Installed file paths ---
HELPER_SCRIPT="/usr/local/bin/arm-drive-restart.sh"
UDEV_RULE="/etc/udev/rules.d/99-arm-drive-watcher.rules"
UDEV_SERVICE="/etc/systemd/system/arm-drive-watcher@.service"
DEVICE_SERVICE="/etc/systemd/system/arm-drive-watcher.service"
STATE_FILE_PREFIX="/var/run/arm-drive-watcher"

# --- Defaults ---
MODE=""
CONTAINER=""
COMPOSE_FILE=""
DEVICE="sr0"
DEBOUNCE=60
ACTION="rescan"
UNINSTALL=false

# --- Usage ---
usage() {
    cat <<EOF
Usage: $(basename "$0") --mode MODE [OPTIONS]
       $(basename "$0") --uninstall

Install a host-level watcher that rescans or restarts the ARM container when
an optical drive connects.

Modes:
  --mode udev       udev rule + systemd oneshot (recommended)
  --mode device     systemd device-bound service

Options:
  --action ACTION        rescan (default) or restart
                         rescan: docker exec rescan_drive.sh (multi-drive safe)
                         restart: docker restart (legacy, kills other rips)
  --container NAME       ARM container name (default: auto-detect ^arm)
  --compose-file PATH    Path to docker-compose.yml (for compose restart)
  --device NAME          Device name without /dev/ (default: sr0)
  --debounce SECONDS     Min seconds between actions (default: 60, udev only)
  --uninstall            Remove all installed files
  -h, --help             Show this help
EOF
    exit "${1:-0}"
}

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --action)
            ACTION="$2"
            shift 2
            ;;
        --container)
            CONTAINER="$2"
            shift 2
            ;;
        --compose-file)
            COMPOSE_FILE="$2"
            shift 2
            ;;
        --device)
            DEVICE="$2"
            shift 2
            ;;
        --debounce)
            DEBOUNCE="$2"
            shift 2
            ;;
        --uninstall)
            UNINSTALL=true
            shift
            ;;
        -h|--help)
            usage 0
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            usage 1
            ;;
    esac
done

# --- Root check ---
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (sudo)" >&2
    exit 1
fi

# --- Uninstall ---
if [[ "$UNINSTALL" == true ]]; then
    echo "=== Uninstalling ARM Drive Watcher ==="
    echo ""

    removed=0
    for f in "$HELPER_SCRIPT" "$UDEV_RULE" "$UDEV_SERVICE" "$DEVICE_SERVICE"; do
        if [[ -f "$f" ]]; then
            rm -f "$f"
            echo "  Removed: $f"
            removed=$((removed + 1))
        fi
    done
    # Remove per-device state files
    for f in "${STATE_FILE_PREFIX}"-*.state; do
        if [[ -f "$f" ]]; then
            rm -f "$f"
            echo "  Removed: $f"
            removed=$((removed + 1))
        fi
    done

    if [[ $removed -eq 0 ]]; then
        echo "  Nothing to remove — no installed files found."
    else
        # Reload systemd and udev
        systemctl daemon-reload 2>/dev/null || true
        udevadm control --reload-rules 2>/dev/null || true
        echo ""
        echo "  Reloaded systemd and udev rules."
    fi

    echo ""
    echo "=== Uninstall complete ==="
    exit 0
fi

# --- Validate inputs ---
if [[ -z "$MODE" ]]; then
    echo "ERROR: --mode is required (udev or device)" >&2
    usage 1
fi

if [[ "$MODE" != "udev" && "$MODE" != "device" ]]; then
    echo "ERROR: --mode must be 'udev' or 'device', got: $MODE" >&2
    usage 1
fi

if [[ "$ACTION" != "rescan" && "$ACTION" != "restart" ]]; then
    echo "ERROR: --action must be 'rescan' or 'restart', got: $ACTION" >&2
    exit 1
fi

# Validate device name
if [[ ! "$DEVICE" =~ ^sr[0-9]+$ ]]; then
    echo "ERROR: --device must match sr[0-9]+ (e.g. sr0, sr1), got: $DEVICE" >&2
    exit 1
fi

# Validate container name if provided
if [[ -n "$CONTAINER" && ! "$CONTAINER" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
    echo "ERROR: --container name must be alphanumeric with hyphens/dots/underscores, got: $CONTAINER" >&2
    exit 1
fi

# --compose-file is only valid with --action restart
if [[ -n "$COMPOSE_FILE" && "$ACTION" == "rescan" ]]; then
    echo "ERROR: --compose-file is only valid with --action restart (rescan targets a container directly)" >&2
    exit 1
fi

# Validate compose file if provided
if [[ -n "$COMPOSE_FILE" && ! -f "$COMPOSE_FILE" ]]; then
    echo "ERROR: --compose-file not found: $COMPOSE_FILE" >&2
    exit 1
fi

# Validate debounce is a positive integer
if [[ ! "$DEBOUNCE" =~ ^[0-9]+$ ]] || [[ "$DEBOUNCE" -lt 1 ]]; then
    echo "ERROR: --debounce must be a positive integer, got: $DEBOUNCE" >&2
    exit 1
fi

echo "=== ARM Drive Watcher Setup ==="
echo "  Mode:      $MODE"
echo "  Action:    $ACTION"
echo "  Device:    /dev/$DEVICE"
if [[ -n "$COMPOSE_FILE" ]]; then
    echo "  Compose:   $COMPOSE_FILE"
elif [[ -n "$CONTAINER" ]]; then
    echo "  Container: $CONTAINER"
else
    echo "  Container: (auto-detect ^arm)"
fi
if [[ "$MODE" == "udev" ]]; then
    echo "  Debounce:  ${DEBOUNCE}s"
fi
echo ""

# --- Generate helper script ---
echo "Installing helper script..."

if [[ "$ACTION" == "rescan" ]]; then
    # =====================================================================
    # RESCAN MODE — docker exec rescan_drive.sh (multi-drive safe)
    # =====================================================================
    # No uptime check needed (we're not restarting, so no restart loop risk).
    # Debounce still applies to avoid hammering the same device.

    # Determine the container to exec into
    RESOLVE_CONTAINER=""
    if [[ -n "$CONTAINER" ]]; then
        RESOLVE_CONTAINER="CONTAINER=\"$CONTAINER\""
    else
        # Auto-detect
        RESOLVE_CONTAINER='CONTAINER=$(docker ps --format "{{.Names}}" 2>/dev/null | grep "^arm" | head -1)
if [[ -z "$CONTAINER" ]]; then
    logger -t arm-drive-watcher "ERROR: No running ARM container found (matching ^arm)"
    exit 1
fi'
    fi

    # Build debounce block
    DEBOUNCE_BLOCK=""
    if [[ "$MODE" == "udev" ]]; then
        DEBOUNCE_BLOCK="
# --- Per-device debounce ---
# Device name passed as \$1 by systemd %i substitution
DEBOUNCE_DEVICE=\"\${1:-unknown}\"
STATE_FILE=\"${STATE_FILE_PREFIX}-\${DEBOUNCE_DEVICE}.state\"
NOW=\$(date +%s)
if [[ -f \"\$STATE_FILE\" ]]; then
    LAST=\$(cat \"\$STATE_FILE\" 2>/dev/null || echo 0)
    ELAPSED=\$((NOW - LAST))
    if [[ \$ELAPSED -lt $DEBOUNCE ]]; then
        logger -t arm-drive-watcher \"Debounce [\$DEBOUNCE_DEVICE]: skipping rescan (\${ELAPSED}s < ${DEBOUNCE}s since last)\"
        exit 0
    fi
fi
echo \"\$NOW\" > \"\$STATE_FILE\"
"
    else
        # Device mode — hardcode the device name (no $1 from systemd)
        DEBOUNCE_BLOCK="
DEBOUNCE_DEVICE=\"$DEVICE\"
"
    fi

    # Write the helper script
    cat > "$HELPER_SCRIPT" <<HELPEREOF
#!/usr/bin/env bash
# ARM Drive Watcher - Rescan helper (multi-drive safe)
# Generated by setup-drive-watcher.sh — do not edit manually
set -euo pipefail

logger -t arm-drive-watcher "Drive event detected, checking rescan..."
${DEBOUNCE_BLOCK}
# --- Resolve container ---
${RESOLVE_CONTAINER}

# --- Rescan drive ---
logger -t arm-drive-watcher "Rescanning \$DEBOUNCE_DEVICE in container \$CONTAINER..."
RESCAN_OUTPUT=\$(docker exec "\$CONTAINER" /opt/arm/scripts/docker/rescan_drive.sh "\$DEBOUNCE_DEVICE" 2>&1) && RESCAN_RC=0 || RESCAN_RC=\$?
[[ -n "\$RESCAN_OUTPUT" ]] && echo "\$RESCAN_OUTPUT" | logger -t arm-drive-watcher
if [[ \$RESCAN_RC -eq 0 ]]; then
    logger -t arm-drive-watcher "Rescan complete for \$DEBOUNCE_DEVICE"
elif [[ \$RESCAN_RC -eq 126 || \$RESCAN_RC -eq 127 ]]; then
    # Script not found or not executable (old image without rescan support)
    logger -t arm-drive-watcher "WARNING: rescan_drive.sh not found (rc=\$RESCAN_RC), falling back to container restart"
    docker restart "\$CONTAINER"
    logger -t arm-drive-watcher "Restarted container \$CONTAINER (fallback)"
else
    logger -t arm-drive-watcher "Rescan exited with rc=\$RESCAN_RC for \$DEBOUNCE_DEVICE (no restart needed)"
fi
HELPEREOF

else
    # =====================================================================
    # RESTART MODE — docker restart (legacy behavior)
    # =====================================================================

    # Build container uptime check
    # If the container was recently restarted (by us), skip — the udev events
    # are from the restart itself, not a genuine drive reconnect.
    # This prevents restart loops without relying on stale device nodes.
    UPTIME_CHECK=""
    if [[ -n "$COMPOSE_FILE" ]]; then
        UPTIME_CHECK="
# --- Check if container was recently restarted ---
COMPOSE_CONTAINER=\$(docker compose -f \"$COMPOSE_FILE\" ps -q 2>/dev/null | head -1)
if [[ -n \"\$COMPOSE_CONTAINER\" ]]; then
    STARTED=\$(docker inspect --format '{{.State.StartedAt}}' \"\$COMPOSE_CONTAINER\" 2>/dev/null)
    STARTED_EPOCH=\$(date -d \"\$STARTED\" +%s 2>/dev/null || echo 0)
    NOW_EPOCH=\$(date +%s)
    UPTIME=\$((NOW_EPOCH - STARTED_EPOCH))
    if [[ \$UPTIME -lt $DEBOUNCE ]]; then
        logger -t arm-drive-watcher \"Container restarted \${UPTIME}s ago, skipping\"
        exit 0
    fi
fi"
    elif [[ -n "$CONTAINER" ]]; then
        UPTIME_CHECK="
# --- Check if container was recently restarted ---
STARTED=\$(docker inspect --format '{{.State.StartedAt}}' \"$CONTAINER\" 2>/dev/null)
STARTED_EPOCH=\$(date -d \"\$STARTED\" +%s 2>/dev/null || echo 0)
NOW_EPOCH=\$(date +%s)
UPTIME=\$((NOW_EPOCH - STARTED_EPOCH))
if [[ \$UPTIME -lt $DEBOUNCE ]]; then
    logger -t arm-drive-watcher \"Container restarted \${UPTIME}s ago, skipping\"
    exit 0
fi"
    fi

    # Build restart command logic
    RESTART_LOGIC=""
    if [[ -n "$COMPOSE_FILE" ]]; then
        RESTART_LOGIC="docker compose -f \"$COMPOSE_FILE\" restart"
    elif [[ -n "$CONTAINER" ]]; then
        RESTART_LOGIC="docker restart \"$CONTAINER\""
    else
        # Auto-detect: find container matching ^arm, fall back to systemd
        RESTART_LOGIC='CONTAINER=$(docker ps -a --format "{{.Names}}" 2>/dev/null | grep "^arm" | head -1)
if [[ -n "$CONTAINER" ]]; then
    # Check if container was recently restarted
    STARTED=$(docker inspect --format '"'"'{{.State.StartedAt}}'"'"' "$CONTAINER" 2>/dev/null)
    STARTED_EPOCH=$(date -d "$STARTED" +%s 2>/dev/null || echo 0)
    NOW_EPOCH=$(date +%s)
    UPTIME=$((NOW_EPOCH - STARTED_EPOCH))
    if [[ $UPTIME -lt '"$DEBOUNCE"' ]]; then
        logger -t arm-drive-watcher "Container restarted ${UPTIME}s ago, skipping"
        exit 0
    fi
    docker restart "$CONTAINER"
    logger -t arm-drive-watcher "Restarted Docker container: $CONTAINER"
elif systemctl is-active --quiet armui 2>/dev/null; then
    systemctl restart armui
    logger -t arm-drive-watcher "Restarted systemd service: armui"
else
    logger -t arm-drive-watcher "ERROR: No ARM container or service found"
    exit 1
fi
exit 0'
    fi

    # Build debounce logic (udev mode only, per-device state file)
    DEBOUNCE_BLOCK=""
    if [[ "$MODE" == "udev" ]]; then
        DEBOUNCE_BLOCK="
# --- Per-device debounce ---
# Device name passed as \$1 by systemd %i substitution
DEBOUNCE_DEVICE=\"\${1:-unknown}\"
STATE_FILE=\"${STATE_FILE_PREFIX}-\${DEBOUNCE_DEVICE}.state\"
NOW=\$(date +%s)
if [[ -f \"\$STATE_FILE\" ]]; then
    LAST=\$(cat \"\$STATE_FILE\" 2>/dev/null || echo 0)
    ELAPSED=\$((NOW - LAST))
    if [[ \$ELAPSED -lt $DEBOUNCE ]]; then
        logger -t arm-drive-watcher \"Debounce [\$DEBOUNCE_DEVICE]: skipping restart (\${ELAPSED}s < ${DEBOUNCE}s since last)\"
        exit 0
    fi
fi
echo \"\$NOW\" > \"\$STATE_FILE\"
"
    fi

    # Write the helper script
    cat > "$HELPER_SCRIPT" <<HELPEREOF
#!/usr/bin/env bash
# ARM Drive Watcher - Restart helper (legacy)
# Generated by setup-drive-watcher.sh — do not edit manually
set -euo pipefail

logger -t arm-drive-watcher "Drive event detected, checking restart..."
${UPTIME_CHECK}
${DEBOUNCE_BLOCK}
# --- Restart ARM ---
logger -t arm-drive-watcher "Restarting ARM..."
${RESTART_LOGIC}
HELPEREOF

    # For non-auto-detect modes, add logging after the restart command
    if [[ -n "$COMPOSE_FILE" ]]; then
        cat >> "$HELPER_SCRIPT" <<'LOGEOF'
logger -t arm-drive-watcher "Restarted ARM via docker compose"
LOGEOF
    elif [[ -n "$CONTAINER" ]]; then
        cat >> "$HELPER_SCRIPT" <<LOGEOF
logger -t arm-drive-watcher "Restarted Docker container: $CONTAINER"
LOGEOF
    fi
fi

chmod +x "$HELPER_SCRIPT"
echo "  Installed: $HELPER_SCRIPT"

# --- Generate systemd / udev files based on mode ---
if [[ "$MODE" == "udev" ]]; then
    echo ""
    echo "Installing udev rule..."

    cat > "$UDEV_RULE" <<UDEVEOF
# ARM Drive Watcher - rescan/restart ARM container when optical drive connects
# Generated by setup-drive-watcher.sh — do not edit manually
ACTION=="add", SUBSYSTEM=="block", KERNEL=="sr*", TAG+="systemd", ENV{SYSTEMD_WANTS}="arm-drive-watcher@%k.service"
UDEVEOF
    echo "  Installed: $UDEV_RULE"

    echo ""
    echo "Installing systemd template service..."

    ACTION_LABEL="Rescan"
    [[ "$ACTION" == "restart" ]] && ACTION_LABEL="Restart"

    cat > "$UDEV_SERVICE" <<SVCEOF
# ARM Drive Watcher - oneshot service triggered by udev
# Generated by setup-drive-watcher.sh — do not edit manually
[Unit]
Description=ARM Drive Watcher - ${ACTION_LABEL} ARM container for %i
After=docker.service
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=oneshot
RemainAfterExit=no
ExecStart=$HELPER_SCRIPT %i
StandardOutput=journal
StandardError=journal
SVCEOF
    echo "  Installed: $UDEV_SERVICE"

    # Reload
    udevadm control --reload-rules
    systemctl daemon-reload
    echo ""
    echo "  Reloaded udev rules and systemd."

elif [[ "$MODE" == "device" ]]; then
    DEVICE_UNIT="dev-${DEVICE}.device"

    echo ""
    echo "Installing systemd device-bound service..."

    ACTION_LABEL="Rescan"
    [[ "$ACTION" == "restart" ]] && ACTION_LABEL="Restart"

    cat > "$DEVICE_SERVICE" <<SVCEOF
# ARM Drive Watcher - device-bound service
# Generated by setup-drive-watcher.sh — do not edit manually
[Unit]
Description=ARM Drive Watcher - ${ACTION_LABEL} ARM on drive connection
BindsTo=${DEVICE_UNIT}
After=${DEVICE_UNIT} docker.service
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=$HELPER_SCRIPT
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF
    echo "  Installed: $DEVICE_SERVICE"

    systemctl daemon-reload
    systemctl enable arm-drive-watcher.service
    echo "  Enabled: arm-drive-watcher.service"
    echo ""
    echo "  Reloaded systemd."
fi

# --- Summary ---
ACTION_VERB="rescan"
[[ "$ACTION" == "restart" ]] && ACTION_VERB="restart"

echo ""
echo "=== Setup complete ==="
echo ""
echo "The ARM container will ${ACTION_VERB} automatically when /dev/$DEVICE connects."
echo ""
echo "Monitor events:"
echo "  journalctl -t arm-drive-watcher -f"
echo ""
if [[ "$MODE" == "udev" ]]; then
    echo "Test manually:"
    echo "  sudo systemctl start arm-drive-watcher@${DEVICE}.service"
elif [[ "$MODE" == "device" ]]; then
    echo "Test manually:"
    echo "  sudo systemctl start arm-drive-watcher.service"
fi
echo ""
echo "Uninstall:"
echo "  sudo $(basename "$0") --uninstall"
echo ""
