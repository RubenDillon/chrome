FROM almalinux:9

LABEL maintainer="RubenDillon"
LABEL description="Chrome kiosk container - YouTube playlist continuous playback"

# -------------------------------------------------------
# System packages
# -------------------------------------------------------
RUN dnf install -y epel-release \
    && dnf install -y --allowerasing \
        python3 \
        python3-pip \
        wget \
        curl \
        unzip \
        jq \
        procps-ng \
        ca-certificates \
        fontconfig \
        nss \
        atk \
        cups-libs \
        gtk3 \
        libXcomposite \
        libXcursor \
        libXdamage \
        libXext \
        libXi \
        libXrandr \
        libXtst \
        pango \
        alsa-lib \
        liberation-fonts \
        freetype \
        dbus-glib \
    && dnf clean all

# -------------------------------------------------------
# Python dependencies
# Playwright manages its own browser binaries — no separate Chrome install needed
# -------------------------------------------------------
RUN pip3 install --no-cache-dir \
        playwright \
        yt-dlp

# -------------------------------------------------------
# Install Playwright's bundled Chromium + its system dependencies
# -------------------------------------------------------
RUN playwright install chromium \
    && playwright install-deps chromium

# -------------------------------------------------------
# machine-id — required by some system libs
# -------------------------------------------------------
RUN printf '%032x' "$(date +%s%N)" > /etc/machine-id

# -------------------------------------------------------
# Create non-root user
# -------------------------------------------------------
RUN useradd -m -s /bin/bash kiosk

# -------------------------------------------------------
# X11 socket directory (kept for Xvfb fallback if needed)
# -------------------------------------------------------
RUN mkdir -p /tmp/.X11-unix \
    && chmod 1777 /tmp/.X11-unix

# -------------------------------------------------------
# Log directory (overridden by bind-mount at runtime)
# -------------------------------------------------------
RUN mkdir -p /var/log/chrome-kiosk \
    && chown kiosk:kiosk /var/log/chrome-kiosk

# -------------------------------------------------------
# Copy application scripts
# -------------------------------------------------------
COPY scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY scripts/tracker.py    /usr/local/bin/tracker.py

RUN chmod +x /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/tracker.py

USER kiosk
WORKDIR /home/kiosk

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
