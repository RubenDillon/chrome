FROM almalinux:9

LABEL maintainer="RubenDillon"
LABEL description="Chrome kiosk container - YouTube playlist continuous playback"

# -------------------------------------------------------
# Install EPEL + required packages
# AlmaLinux 9 has full X11/desktop repos without subscription
# -------------------------------------------------------
RUN dnf install -y epel-release \
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
RUN python3 - <<'PYEOF'
import subprocess, urllib.request, json, sys, os, zipfile, io

# Get Chrome major version
out = subprocess.check_output(["google-chrome", "--version"], stderr=subprocess.DEVNULL).decode()
major = out.strip().split()[-1].split(".")[0]
print(f"Chrome major version: {major}")

# Fetch known-good versions JSON
url = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
with urllib.request.urlopen(url) as r:
    data = json.load(r)

# Find latest chromedriver for this major version
versions = [v for v in data["versions"] if v["version"].split(".")[0] == major]
versions.sort(key=lambda x: list(map(int, x["version"].split("."))), reverse=True)

driver_url = None
for v in versions:
    for dl in v["downloads"].get("chromedriver", []):
        if dl["platform"] == "linux64":
            driver_url = dl["url"]
            break
    if driver_url:
        break

if not driver_url:
    print(f"ERROR: no chromedriver found for Chrome {major}", file=sys.stderr)
    sys.exit(1)

print(f"Downloading chromedriver from: {driver_url}")
with urllib.request.urlopen(driver_url) as r:
    zdata = r.read()

with zipfile.ZipFile(io.BytesIO(zdata)) as z:
    for name in z.namelist():
        if name.endswith("chromedriver") and not name.endswith("/"):
            data_bytes = z.read(name)
            out_path = "/usr/local/bin/chromedriver"
            with open(out_path, "wb") as f:
                f.write(data_bytes)
            os.chmod(out_path, 0o755)
            print(f"Installed chromedriver to {out_path}")
            break
PYEOF
RUN chromedriver --version

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
