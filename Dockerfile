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
RUN CHROME_MAJOR=$(google-chrome --version 2>/dev/null | grep -oP '\d+' | head -1) \
    && echo "Chrome major: ${CHROME_MAJOR}" \
    && DRIVER_URL=$(CHROME_MAJOR="${CHROME_MAJOR}" python3 -c "
import sys, json, os, urllib.request
major = os.environ['CHROME_MAJOR']
url = 'https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json'
with urllib.request.urlopen(url) as r:
    data = json.load(r)
versions = [v for v in data['versions'] if v['version'].split('.')[0] == major]
versions.sort(key=lambda x: list(map(int, x['version'].split('.'))), reverse=True)
for v in versions:
    for dl in v['downloads'].get('chromedriver', []):
        if dl['platform'] == 'linux64':
            print(dl['url'])
            sys.exit(0)
sys.exit(1)
") \
    && echo "ChromeDriver URL: ${DRIVER_URL}" \
    && curl -sL "${DRIVER_URL}" -o /tmp/chromedriver.zip \
    && unzip -p /tmp/chromedriver.zip "chromedriver-linux64/chromedriver" \
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
# Log directory (will be overridden by bind-mount)
# -------------------------------------------------------
RUN mkdir -p /var/log/chrome-kiosk \
    && chown kiosk:kiosk /var/log/chrome-kiosk

USER kiosk
WORKDIR /home/kiosk

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
