FROM registry.access.redhat.com/ubi9/ubi:latest

LABEL maintainer="RubenDillon"
LABEL description="Chrome kiosk container - YouTube playlist continuous playback"

# -------------------------------------------------------
# Install EPEL + required packages
# -------------------------------------------------------
RUN dnf install -y \
        https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm \
    && dnf install -y \
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
# Install Google Chrome (stable)
# -------------------------------------------------------
RUN wget -q -O /tmp/google-chrome.rpm \
        https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm \
    && dnf install -y /tmp/google-chrome.rpm \
    && rm -f /tmp/google-chrome.rpm \
    && dnf clean all

# -------------------------------------------------------
# Install Python dependencies for video tracker
# -------------------------------------------------------
RUN pip3 install --no-cache-dir \
        selenium \
        yt-dlp \
        requests

# -------------------------------------------------------
# Install ChromeDriver matching installed Chrome version
# -------------------------------------------------------
RUN CHROME_VERSION=$(google-chrome --version | awk '{print $3}' | cut -d. -f1) \
    && DRIVER_URL="https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json" \
    && DRIVER_VER=$(curl -s "$DRIVER_URL" \
        | python3 -c "
import sys, json
data = json.load(sys.stdin)
major = '${CHROME_VERSION}'
versions = [v for v in data['versions'] if v['version'].startswith(major + '.')]
versions.sort(key=lambda x: x['version'], reverse=True)
if versions:
    for dl in versions[0]['downloads'].get('chromedriver', []):
        if dl['platform'] == 'linux64':
            print(dl['url'])
            break
") \
    && wget -q -O /tmp/chromedriver.zip "$DRIVER_VER" \
    && unzip -j /tmp/chromedriver.zip '*/chromedriver' -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/chromedriver \
    && rm -f /tmp/chromedriver.zip

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
# Log directory (will be overridden by bind-mount)
# -------------------------------------------------------
RUN mkdir -p /var/log/chrome-kiosk \
    && chown kiosk:kiosk /var/log/chrome-kiosk

USER kiosk
WORKDIR /home/kiosk

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
