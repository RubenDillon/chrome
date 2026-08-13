#!/bin/bash
# =============================================================================
# 01_setup_host.sh
# =============================================================================
# Prepares a RHEL 9.6 machine to build and run the Chrome kiosk container.
# Run as root (or with sudo).
#
# What this script does:
#   1. Registers the system / enables required repos (RHEL + EPEL)
#   2. Installs Podman + Buildah
#   3. Installs Git (to clone the repo)
#   4. Creates the log directory on the host
#   5. Configures /etc/subuid + /etc/subgid for rootless Podman (optional)
#   6. Enables and configures the Podman socket (for future management)
#
# Usage:
#   sudo bash 01_setup_host.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# -----------------------------------------------------------------------
# 0. Must run as root
# -----------------------------------------------------------------------
[[ $EUID -eq 0 ]] || error "Please run as root: sudo bash $0"

info "=== Chrome Kiosk — Host Setup (RHEL 9.6) ==="

# -----------------------------------------------------------------------
# 1. Subscription / repo check
# -----------------------------------------------------------------------
info "Checking RHEL subscription status..."
if subscription-manager status &>/dev/null; then
    info "System is registered with Red Hat."
else
    warn "System does not appear to be registered with Red Hat Subscription Manager."
    warn "If you have a subscription, run: subscription-manager register --auto-attach"
    warn "Continuing — assuming repos are available via another mechanism (e.g. CentOS/Rocky mirrors)."
fi

# Enable required repos
info "Enabling BaseOS, AppStream and CRB repos..."
subscription-manager repos \
    --enable=rhel-9-for-x86_64-baseos-rpms \
    --enable=rhel-9-for-x86_64-appstream-rpms \
    --enable=codeready-builder-for-rhel-9-x86_64-rpms 2>/dev/null || \
    warn "Could not enable RHEL repos via subscription-manager (may already be enabled or using alternate repos)."

# -----------------------------------------------------------------------
# 2. Install EPEL 9
# -----------------------------------------------------------------------
if ! rpm -q epel-release &>/dev/null; then
    info "Installing EPEL 9..."
    dnf install -y \
        https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm
else
    info "EPEL already installed."
fi

# -----------------------------------------------------------------------
# 3. Install Podman, Buildah, and Git
# -----------------------------------------------------------------------
info "Installing podman, buildah, git..."
dnf install -y \
    podman \
    buildah \
    git \
    skopeo

# Verify
podman --version
buildah --version
git    --version

# -----------------------------------------------------------------------
# 4. Configure rootless Podman for the current non-root user (if any)
# -----------------------------------------------------------------------
SUDO_USER_NAME="${SUDO_USER:-}"
if [[ -n "$SUDO_USER_NAME" && "$SUDO_USER_NAME" != "root" ]]; then
    info "Configuring rootless Podman for user: $SUDO_USER_NAME"
    USER_UID=$(id -u "$SUDO_USER_NAME")
    USER_GID=$(id -g "$SUDO_USER_NAME")

    # /etc/subuid
    if ! grep -q "^${SUDO_USER_NAME}:" /etc/subuid 2>/dev/null; then
        echo "${SUDO_USER_NAME}:100000:65536" >> /etc/subuid
        info "Added subuid entry for $SUDO_USER_NAME"
    fi

    # /etc/subgid
    if ! grep -q "^${SUDO_USER_NAME}:" /etc/subgid 2>/dev/null; then
        echo "${SUDO_USER_NAME}:100000:65536" >> /etc/subgid
        info "Added subgid entry for $SUDO_USER_NAME"
    fi

    # Initialise the user namespace mapping
    podman system migrate || true
else
    info "Running as root — skipping rootless Podman user configuration."
    info "If you want rootless mode, re-run: sudo bash $0 as a non-root sudoer."
fi

# -----------------------------------------------------------------------
# 5. Create host log directory
# -----------------------------------------------------------------------
LOG_DIR="/var/log/chrome-kiosk"
info "Creating log directory: $LOG_DIR"
mkdir -p "$LOG_DIR"
chmod 777 "$LOG_DIR"      # Writable by container user (kiosk uid may differ on host)
info "Log directory ready: $LOG_DIR"

# -----------------------------------------------------------------------
# 6. SELinux — allow container to write to the bind-mounted log dir
# -----------------------------------------------------------------------
if command -v semanage &>/dev/null && command -v restorecon &>/dev/null; then
    info "Applying SELinux container_file_t context to $LOG_DIR..."
    semanage fcontext -a -t container_file_t "${LOG_DIR}(/.*)?" 2>/dev/null || \
        semanage fcontext -m -t container_file_t "${LOG_DIR}(/.*)?"; true
    restorecon -Rv "$LOG_DIR" || true
else
    warn "semanage/restorecon not found. If SELinux is enforcing, install policycoreutils-python-utils:"
    warn "  dnf install -y policycoreutils-python-utils"
    warn "Then run:"
    warn "  semanage fcontext -a -t container_file_t '${LOG_DIR}(/.*)?'"
    warn "  restorecon -Rv ${LOG_DIR}"
fi

# -----------------------------------------------------------------------
# 7. Firewall — nothing to open (container only needs outbound internet)
# -----------------------------------------------------------------------
info "No inbound firewall rules needed (outbound-only container)."

# -----------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------
info "=== Host setup complete ==="
info ""
info "Next steps:"
info "  1. Clone the repository into this machine:"
info "       git clone https://github.com/RubenDillon/chrome.git"
info "  2. Build the container image:"
info "       bash chrome/02_build.sh"
info "  3. Run the container:"
info "       bash chrome/03_run.sh"
