FROM almalinux:9

LABEL maintainer="RubenDillon"
LABEL description="Chrome kiosk container - YouTube playlist continuous playback"

# -------------------------------------------------------
# System packages required by Playwright's Chromium
# (equivalent to what playwright install-deps installs on Ubuntu)
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
        nss-util \
        nspr \
        atk \
        at-spi2-atk \
        cups-libs \
        gtk3 \
        libXcomposite \
        libXcursor \
        libXdamage \
        libXext \
        libXi \
        libXrandr \
        libXtst \
        libXScrnSaver \
        pango \
        alsa-lib \
        liberation-fonts \
        freetype \
        harfbuzz \
        dbus-glib \
        dbus-libs \
        mesa-libgbm \
        libdrm \
        libxkbcommon \
    && dnf clean all

# -------------------------------------------------------
# Python dependencies
# -------------------------------------------------------
RUN pip3 install --no-cache-dir \
        playwright \
        yt-dlp

# -------------------------------------------------------
# Download Playwright's Chromium browser
# Run as root so it goes to /root/.cache, then we'll make it world-readable
# -------------------------------------------------------
RUN playwright install chromium \
    && chmod -R a+rX /root/.cache/ms-playwright

# -------------------------------------------------------
# machine-id
# -------------------------------------------------------
RUN printf '%032x' "$(date +%s%N)" > /etc/machine-id

# -------------------------------------------------------
# Create non-root user
# -------------------------------------------------------
RUN useradd -m -s /bin/bash kiosk

# -------------------------------------------------------
# Make Playwright cache accessible to kiosk user
# -------------------------------------------------------
RUN mkdir -p /home/kiosk/.cache \
    && cp -r /root/.cache/ms-playwright /home/kiosk/.cache/ms-playwright \
    && chown -R kiosk:kiosk /home/kiosk/.cache

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
