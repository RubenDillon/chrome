# chrome-kiosk

Containerised Chrome kiosk that plays a YouTube playlist in a loop inside a **Podman** container on **RHEL 9.6**, logging every completed video to a file on the host.

---

## Architecture overview

```
RHEL 9.6 host
│
├── /var/log/chrome-kiosk/played.log  ← bind-mounted log (readable on host)
│
└── Podman container: chrome-kiosk
    ├── Xvfb  (virtual display :99)
    ├── Google Chrome  (kiosk mode)
    ├── ChromeDriver
    └── tracker.py  (Selenium + yt-dlp)
         • fetches playlist order via yt-dlp
         • plays each video with Chrome
         • waits for video to end
         • writes entry to /var/log/chrome-kiosk/played.log
         • loops forever
```

---

## Repository layout

```
chrome/
├── Dockerfile
├── scripts/
│   ├── entrypoint.sh     # container entry point (starts Xvfb → tracker.py)
│   └── tracker.py        # playlist player + logger
├── 01_setup_host.sh      # STEP 1 — install dependencies on the RHEL 9.6 host
├── 02_build.sh           # STEP 2 — build the Podman image
├── 03_run.sh             # STEP 3 — run the container
└── README.md             # this file
```

---

## Quick start

### 1 — Prepare the host (run once, as root)

```bash
sudo bash 01_setup_host.sh
```

What it does:
- Enables RHEL BaseOS / AppStream / CRB repos
- Installs EPEL 9
- Installs **Podman**, **Buildah**, **Git**, **skopeo**
- Creates `/var/log/chrome-kiosk/` with correct SELinux context (`container_file_t`)
- Configures `/etc/subuid` / `/etc/subgid` for rootless Podman (if running as a non-root sudoer)

### 2 — Clone the repository on the host

```bash
git clone https://github.com/RubenDillon/chrome.git
cd chrome
```

### 3 — Build the container image

```bash
bash 02_build.sh
```

This builds the image locally (no registry push needed). The first build downloads
Chrome, ChromeDriver and Python packages — expect **5–10 minutes** depending on bandwidth.

### 4 — Run the container

```bash
bash 03_run.sh
```

The container starts in the background (`--detach`). It will **restart automatically**
unless explicitly stopped.

---

## Watching the log

```bash
# Follow in real time
tail -f /var/log/chrome-kiosk/played.log

# Show last 20 entries
tail -20 /var/log/chrome-kiosk/played.log
```

### Log format

```
[2025-07-11 14:03:22] PLAYED     | https://www.youtube.com/watch?v=XXXXXXXXXXX | Video title here
[2025-07-11 14:07:55] PLAYED     | https://www.youtube.com/watch?v=YYYYYYYYYYY | Another video
[2025-07-11 14:09:01] INCOMPLETE | https://www.youtube.com/watch?v=ZZZZZZZZZZZ | Skipped (error)
```

- `PLAYED`     — video played to completion
- `INCOMPLETE` — video was skipped due to an error or timeout

---

## Configuration

You can override defaults by exporting variables **before** calling `03_run.sh`:

| Variable       | Default                                                        | Description                          |
|----------------|----------------------------------------------------------------|--------------------------------------|
| `PLAYLIST_URL` | `https://www.youtube.com/playlist?list=PLLeOGPWFDdFk`         | YouTube playlist to play             |
| `HOST_LOG_DIR` | `/var/log/chrome-kiosk`                                        | Host directory for the log file      |
| `LOG_FILE`     | `/var/log/chrome-kiosk/played.log`                             | Full path inside the container       |
| `SCREEN_RES`   | `1920x1080x24`                                                 | Xvfb virtual display resolution      |

Example — use a different playlist:

```bash
export PLAYLIST_URL="https://www.youtube.com/playlist?list=YOUR_LIST_ID"
bash 03_run.sh
```

---

## Container management

```bash
# View live container output
podman logs -f chrome-kiosk

# Stop the container
podman stop chrome-kiosk

# Restart the container
podman restart chrome-kiosk

# Remove the container (keeps the image)
podman rm -f chrome-kiosk

# Remove image (forces a full rebuild next time)
podman rmi chrome-kiosk:latest
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Container exits immediately | Chrome/ChromeDriver version mismatch | Rebuild the image: `bash 02_build.sh` |
| Log file empty | SELinux blocking write | `semanage fcontext -m -t container_file_t '/var/log/chrome-kiosk(/.*)?' && restorecon -Rv /var/log/chrome-kiosk` |
| `yt-dlp` returns no videos | YouTube anti-bot / network | Check internet access from inside: `podman exec chrome-kiosk curl -s https://youtube.com` |
| Chrome crashes in loop | Insufficient `/dev/shm` | Increase `--shm-size` in `03_run.sh` (default 256 m) |
| `RHSM` repos not available | Unregistered VM | Use a CentOS Stream 9 / Rocky 9 mirror, or register: `subscription-manager register` |

---

## Requirements

- RHEL 9.6 (or compatible: Rocky Linux 9, AlmaLinux 9)
- x86_64 architecture
- Internet access (to download Chrome RPM, ChromeDriver, Python packages during build)
- ~2 GB disk space for the container image
- ≥ 1 GB RAM recommended for Chrome

---

## License

MIT
