FROM almalinux:9

LABEL maintainer="RubenDillon"
LABEL description="Chrome kiosk container - YouTube playlist continuous playback"

# -------------------------------------------------------
# Install EPEL + required packages
# AlmaLinux 9 has full X11/desktop repos without subscription
# -------------------------------------------------------
RUN dnf install -y epel-release \
    && dnf install -y --allowerasing \
        xorg-x11-server-Xvfb \
        xorg-x11-utils \
        xdotool \
        python3 \
        python3-pip \
        wget \
        curl \
        unzip \
        jq \
        procps-ng \
        dbus-glib \
        dbus-daemon \
        liberation-fonts \
        nss \
        alsa-lib \
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
        ca-certificates \
        fontconfig \
        freetype \
    && dnf clean all

# -------------------------------------------------------
# Install Google Chrome 120 (last version fully supported by uc 3.5.5)
# -------------------------------------------------------
RUN CHROME_URL="https://dl.google.com/linux/chrome/rpm/stable/x86_64/google-chrome-stable-120.0.6099.224-1.x86_64.rpm" \
    && wget -q -O /tmp/google-chrome.rpm "${CHROME_URL}" \
    && dnf install -y /tmp/google-chrome.rpm \
    && rm -f /tmp/google-chrome.rpm \
    && dnf clean all \
    && google-chrome --version

# -------------------------------------------------------
# Install Python dependencies for video tracker
# -------------------------------------------------------
RUN pip3 install --no-cache-dir \
        selenium \
        undetected-chromedriver \
        yt-dlp \
        requests

# -------------------------------------------------------
# Install ChromeDriver 120 matching Chrome 120
# -------------------------------------------------------
RUN DRIVER_URL="https://storage.googleapis.com/chrome-for-testing-public/120.0.6099.224/linux64/chromedriver-linux64.zip" \
    && curl -sL "${DRIVER_URL}" -o /tmp/chromedriver.zip \
    && unzip -p /tmp/chromedriver.zip chromedriver-linux64/chromedriver \
         > /usr/local/bin/chromedriver \
    && chmod +x /usr/local/bin/chromedriver \
    && rm -f /tmp/chromedriver.zip \
    && chromedriver --version

# -------------------------------------------------------
# Create non-root user for Chrome
# -------------------------------------------------------
RUN useradd -m -s /bin/bash kiosk

# -------------------------------------------------------
# Copy application scripts
# -------------------------------------------------------
COPY scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY scripts/tracker.py    /usr/local/bin/tracker.py

RUN chmod +x /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/tracker.py

# -------------------------------------------------------
# X11 socket directory — must exist before Xvfb runs as non-root
# -------------------------------------------------------
RUN mkdir -p /tmp/.X11-unix \
    && chmod 1777 /tmp/.X11-unix

# -------------------------------------------------------
# machine-id — Chrome requires a valid 32-char ID
# -------------------------------------------------------
RUN printf '%032x' "$(date +%s%N)" > /etc/machine-id

# -------------------------------------------------------
# Log directory (will be overridden by bind-mount)
# -------------------------------------------------------
RUN mkdir -p /var/log/chrome-kiosk \
    && chown kiosk:kiosk /var/log/chrome-kiosk

USER kiosk
WORKDIR /home/kiosk

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
