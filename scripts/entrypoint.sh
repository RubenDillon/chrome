#!/bin/bash
# =============================================================================
# entrypoint.sh — Launch the Playwright-based tracker
# Playwright manages its own Chromium — no Xvfb needed
# =============================================================================

set -euo pipefail

LOG_FILE="${LOG_FILE:-/var/log/chrome-kiosk/played.log}"
PLAYLIST_URL="${PLAYLIST_URL:-https://www.youtube.com/playlist?list=PLLeOGPWFDdFk}"

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

echo "[entrypoint] Starting tracker (Playwright/Chromium headless)..." | tee -a "$LOG_FILE"

set +e
python3 /usr/local/bin/tracker.py \
    --playlist "$PLAYLIST_URL" \
    --log      "$LOG_FILE"
EXIT_CODE=$?
set -e

echo "[entrypoint] tracker exited with code ${EXIT_CODE}" | tee -a "$LOG_FILE"
exit "${EXIT_CODE}"
