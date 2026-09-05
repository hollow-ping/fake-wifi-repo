#!/bin/bash
# Set the Pi wall clock. Called via sudo -n from burnernet-api (www-data).
# Arg is local time: YYYY-MM-DDTHH:MM:SS or "YYYY-MM-DD HH:MM:SS"
set -e
STAMP="${1-}"
STAMP="${STAMP/T/ }"
if ! echo "$STAMP" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$'; then
    echo "invalid timestamp (want YYYY-MM-DD HH:MM:SS)" >&2
    exit 1
fi
/usr/bin/timedatectl set-ntp false
/usr/bin/timedatectl set-time "$STAMP"
# Leave NTP on so home Wi-Fi can correct later; off-grid it stays at this stamp.
/usr/bin/timedatectl set-ntp true || true
if command -v fake-hwclock >/dev/null 2>&1; then
    fake-hwclock save 2>/dev/null || true
fi
date --iso-8601=seconds
