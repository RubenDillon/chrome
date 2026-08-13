#!/bin/bash
# =============================================================================
# 03_run.sh
# =============================================================================
# Runs (or restarts) the Chrome kiosk container.
#
# Usage:
#   bash 03_run.sh              # from inside the chrome/ directory
#   bash chrome/03_run.sh       # from the parent directory
#
# Environment variables you can override before calling:
#   PLAYLIST_URL  - YouTube playlist URL (default: the original playlist)
#   LOG_FILE      - Path inside container for the log (default: /var/log/chrome-kiosk/played.log)
#   HOST_LOG_DIR  - Directory on the host to bind-mount (default: /var/log/chrome-kiosk)
#   SCREEN_RES    - Xvfb resolution (default: 1920x1080x24)
#
# The log file is accessible on the host at:
#   ${HOST_LOG_DIR}/played.log
#
# To follow the log in real time:
#   tail -f /var/log/chrome-kiosk/played.log
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# -----------------------------------------------------------------------
# Configuration (can be overridden via environment)
# -----------------------------------------------------------------------
CONTAINER_NAME="${CONTAINER_NAME:-chrome-kiosk}"
IMAGE_NAME="chrome-kiosk:latest"
PLAYLIST_URL="${PLAYLIST_URL:-https://www.youtube.com/playlist?list=PLLeOGPWFDdFk}"
HOST_LOG_DIR="${HOST_LOG_DIR:-/var/log/chrome-kiosk}"
LOG_FILE="${LOG_FILE:-/var/log/chrome-kiosk/played.log}"
SCREEN_RES="${SCREEN_RES:-1920x1080x24}"

info "=== Chrome Kiosk — Run Container ==="

# -----------------------------------------------------------------------
# Pre-flight checks
# -----------------------------------------------------------------------
command -v podman &>/dev/null || error "Podman not found. Run 01_setup_host.sh first."

if ! podman image exists "${IMAGE_NAME}" 2>/dev/null; then
    error "Image ${IMAGE_NAME} not found. Run 02_build.sh first."
fi

# -----------------------------------------------------------------------
# Ensure host log directory exists and is writable
# -----------------------------------------------------------------------
if [[ ! -d "$HOST_LOG_DIR" ]]; then
    info "Creating host log directory: $HOST_LOG_DIR"
    mkdir -p "$HOST_LOG_DIR"
    chmod 777 "$HOST_LOG_DIR"
fi

# -----------------------------------------------------------------------
# Stop and remove any previous instance
# -----------------------------------------------------------------------
if podman container exists "${CONTAINER_NAME}" 2>/dev/null; then
    warn "Stopping and removing existing container '${CONTAINER_NAME}'..."
    podman stop  "${CONTAINER_NAME}" 2>/dev/null || true
    podman rm -f "${CONTAINER_NAME}" 2>/dev/null || true
fi

# -----------------------------------------------------------------------
# Run the container
# -----------------------------------------------------------------------
info "Starting container '${CONTAINER_NAME}'..."
info "  Playlist  : ${PLAYLIST_URL}"
info "  Host logs : ${HOST_LOG_DIR}/played.log"

podman run \
    --detach \
    --name  "${CONTAINER_NAME}" \
    --restart unless-stopped \
    \
    --volume "${HOST_LOG_DIR}:/var/log/chrome-kiosk:z" \
    \
    --env "PLAYLIST_URL=${PLAYLIST_URL}" \
    --env "LOG_FILE=${LOG_FILE}" \
    --env "SCREEN_RES=${SCREEN_RES}" \
    \
    --shm-size=256m \
    --security-opt seccomp=unconfined \
    --security-opt label=disable \
    \
    "${IMAGE_NAME}"

# -----------------------------------------------------------------------
# Verify
# -----------------------------------------------------------------------
sleep 3
STATUS=$(podman inspect "${CONTAINER_NAME}" --format '{{.State.Status}}' 2>/dev/null || echo "unknown")
info "Container status: ${STATUS}"

if [[ "$STATUS" == "running" ]]; then
    info "=== Container is running ==="
    info ""
    info "Useful commands:"
    info "  View live log   : tail -f ${HOST_LOG_DIR}/played.log"
    info "  Container logs  : podman logs -f ${CONTAINER_NAME}"
    info "  Stop container  : podman stop ${CONTAINER_NAME}"
    info "  Restart         : podman restart ${CONTAINER_NAME}"
else
    warn "Container is not in 'running' state (status=${STATUS}). Check logs:"
    warn "  podman logs ${CONTAINER_NAME}"
    exit 1
fi
