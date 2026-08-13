#!/bin/bash
# =============================================================================
# 02_build.sh
# =============================================================================
# Builds the Chrome kiosk Podman image from the local Dockerfile.
#
# Usage:
#   bash 02_build.sh              # from inside the chrome/ directory
#   bash chrome/02_build.sh       # from the parent directory
#
# The image is stored locally (no registry push required).
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# -----------------------------------------------------------------------
# Resolve the directory where this script lives (= repo root)
# -----------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -----------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------
IMAGE_NAME="chrome-kiosk"
IMAGE_TAG="latest"
FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"

info "=== Chrome Kiosk — Build Image ==="
info "Image: ${FULL_IMAGE}"
info "Context: ${SCRIPT_DIR}"

# -----------------------------------------------------------------------
# Pre-flight checks
# -----------------------------------------------------------------------
command -v podman &>/dev/null || error "Podman not found. Run 01_setup_host.sh first."
[[ -f "Dockerfile" ]]              || error "Dockerfile not found in ${SCRIPT_DIR}"
[[ -f "scripts/entrypoint.sh" ]]   || error "scripts/entrypoint.sh not found"
[[ -f "scripts/tracker.py" ]]      || error "scripts/tracker.py not found"

# -----------------------------------------------------------------------
# Remove old image if it exists (optional — comment out to use layer cache)
# -----------------------------------------------------------------------
if podman image exists "${FULL_IMAGE}" 2>/dev/null; then
    warn "Removing existing image ${FULL_IMAGE}..."
    podman rmi -f "${FULL_IMAGE}" || true
fi

# -----------------------------------------------------------------------
# Build
# -----------------------------------------------------------------------
info "Starting Podman build (this may take several minutes the first time)..."

podman build \
    --tag   "${FULL_IMAGE}" \
    --file  "Dockerfile" \
    --layers \
    .

info "=== Build complete ==="
podman images "${IMAGE_NAME}"

info ""
info "To run the container:"
info "  bash 03_run.sh"
