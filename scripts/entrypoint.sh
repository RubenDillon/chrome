#!/bin/bash
# =============================================================================
# entrypoint.sh — Start Xvfb, launch tracker (Chrome kiosk + video logging)
# =============================================================================

set -euo pipefail

DISPLAY_NUM=":99"
LOG_FILE="${LOG_FILE:-/var/log/chrome-kiosk/played.log}"
PLAYLIST_URL="${PLAYLIST_URL:-https://www.youtube.com/playlist?list=PLLeOGPWFDdFk}"
SCREEN_RES="${SCREEN_RES:-1920x1080x24}"

# -------------------------------------------------------
# Ensure log directory exists
# -------------------------------------------------------
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

echo "[entrypoint] Starting Xvfb on display ${DISPLAY_NUM} (${SCREEN_RES})" | tee -a "$LOG_FILE"

# Start Xvfb
Xvfb "${DISPLAY_NUM}" -screen 0 "${SCREEN_RES}" -ac +extension GLX +render -noreset &
XVFB_PID=$!

sleep 2

export DISPLAY="${DISPLAY_NUM}"

echo "[entrypoint] Xvfb running (PID ${XVFB_PID}), launching tracker..." | tee -a "$LOG_FILE"

# Launch tracker — capture exit code so we can dump the chromedriver log on crash
set +e
python3 /usr/local/bin/tracker.py \
    --playlist   "$PLAYLIST_URL" \
    --log        "$LOG_FILE" \
    --display    "$DISPLAY_NUM"
EXIT_CODE=$?
set -e

echo "[entrypoint] tracker exited with code ${EXIT_CODE}" | tee -a "$LOG_FILE"

# Dump ChromeDriver log if it exists — critical for diagnosing crashes
if [[ -f /tmp/chromedriver.log ]]; then
    echo "[entrypoint] === chromedriver.log ===" | tee -a "$LOG_FILE"
    tail -50 /tmp/chromedriver.log | tee -a "$LOG_FILE"
fi

exit "${EXIT_CODE}"
