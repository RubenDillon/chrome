#!/usr/bin/env python3
"""
tracker.py
==========
1. Fetches the YouTube playlist video list with yt-dlp.
2. Opens each video in Chrome (kiosk mode via Selenium) and waits for it to finish.
3. Writes a timestamped STARTED entry when playback begins.
4. Writes a timestamped PLAYED/INCOMPLETE entry when playback ends.
5. Loops the playlist indefinitely.

Usage (called by entrypoint.sh):
    python3 tracker.py --playlist <url> --log <path> --display <:N>
"""

import argparse
import datetime
import logging
import os
import subprocess
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [tracker] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_playlist_videos(playlist_url: str) -> list:
    """Return ordered list of {id, url, title} dicts for every video in the playlist."""
    log.info("Fetching playlist: %s", playlist_url)
    result = subprocess.run(
        [
            "yt-dlp",
            "--flat-playlist",
            "--print", "%(id)s\t%(title)s",
            "--no-warnings",
            playlist_url,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        log.error("yt-dlp error: %s", result.stderr.strip())
        return []

    videos = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            vid_id, title = parts
            videos.append(
                {
                    "id":    vid_id,
                    "url":   f"https://www.youtube.com/watch?v={vid_id}",
                    "title": title,
                }
            )
    log.info("Found %d videos in playlist.", len(videos))
    return videos


def build_driver(display: str) -> webdriver.Chrome:
    """Create a Chrome driver running on the given Xvfb display."""
    os.environ["DISPLAY"] = display

    options = Options()
    options.add_argument("--kiosk")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--autoplay-policy=no-user-gesture-required")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--mute-audio")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--start-fullscreen")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-blink-features=AutomationControlled")

    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    }
    options.add_experimental_option("prefs", prefs)

    service = Service(executable_path="/usr/local/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def append_log(log_file: str, video: dict, status: str) -> None:
    """Append a timestamped line to the played log."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {status.upper()} | {video['url']} | {video['title']}\n"
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
        log.info("Logged: %s", line.strip())
    except OSError as exc:
        log.error("Cannot write to log file %s: %s", log_file, exc)


def dismiss_consent(driver: webdriver.Chrome) -> None:
    """Best-effort dismiss of YouTube cookie/consent dialogs."""
    selectors = [
        '//button[contains(., "Accept all")]',
        '//button[contains(., "Accept")]',
        '//button[contains(., "Agree")]',
        '//button[@aria-label="Accept all"]',
    ]
    for sel in selectors:
        try:
            btn = driver.find_element(By.XPATH, sel)
            btn.click()
            log.info("Dismissed consent dialog.")
            time.sleep(2)
            return
        except Exception:
            pass


def wait_for_video_end(driver: webdriver.Chrome, video: dict, log_file: str) -> bool:
    """
    Poll the HTML5 video element until:
      - ended=true  → return True
      - error       → return False
      - no_video for more than NO_VIDEO_TIMEOUT → log INCOMPLETE and return False
      - global timeout (video length + buffer) → log INCOMPLETE and return False

    Also logs a STARTED entry on first confirmed playback.
    """
    NO_VIDEO_TIMEOUT = 60       # seconds to wait for <video> to appear
    GLOBAL_TIMEOUT   = 4 * 3600 # 4 hours max per video (covers long streams)
    POLL_INTERVAL    = 5

    js = """
    var vids = document.querySelectorAll('video');
    if (vids.length === 0) return 'no_video';
    var v = vids[0];
    if (v.error)  return 'error';
    if (v.ended)  return 'ended';
    if (v.paused) return 'paused';
    if (v.currentTime > 0) return 'playing';
    return 'loading';
    """

    started_logged = False
    no_video_since = time.time()
    deadline = time.time() + GLOBAL_TIMEOUT

    while time.time() < deadline:
        try:
            status = driver.execute_script(js)
        except Exception as exc:
            log.warning("JS execution error: %s", exc)
            return False

        log.debug("Video status: %s", status)

        if status == "no_video":
            if time.time() - no_video_since > NO_VIDEO_TIMEOUT:
                log.warning("No <video> element found after %ds — skipping.", NO_VIDEO_TIMEOUT)
                return False
        else:
            # Reset the no_video timer whenever we see any video element
            no_video_since = time.time()

        if status in ("playing", "loading", "paused") and not started_logged:
            append_log(log_file, video, "started")
            started_logged = True

        if status == "ended":
            return True

        if status == "error":
            log.warning("Video element reported an error — skipping.")
            return False

        # If paused for too long, try to resume
        if status == "paused" and started_logged:
            try:
                driver.execute_script(
                    "document.querySelector('video').play();"
                )
            except Exception:
                pass

        time.sleep(POLL_INTERVAL)

    log.warning("Global timeout reached — skipping video.")
    return False


def play_video(driver: webdriver.Chrome, video: dict, log_file: str) -> None:
    """Navigate to the video URL and wait until playback finishes."""
    log.info("Playing: %s  (%s)", video["title"], video["url"])

    # autoplay=1 + start from beginning
    url = video["url"] + "&autoplay=1&t=0"
    driver.get(url)

    # Give the page time to load
    time.sleep(10)

    # Dismiss consent dialogs
    dismiss_consent(driver)

    # Force play via JS in case autoplay was blocked
    try:
        driver.execute_script(
            "var v = document.querySelector('video'); if(v) v.play();"
        )
    except Exception:
        pass

    ended = wait_for_video_end(driver, video, log_file)
    status = "played" if ended else "incomplete"
    append_log(log_file, video, status)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube playlist kiosk tracker")
    parser.add_argument("--playlist", required=True, help="YouTube playlist URL")
    parser.add_argument("--log",      required=True, help="Path to the output log file")
    parser.add_argument("--display",  default=":99",  help="X display (e.g. :99)")
    args = parser.parse_args()

    iteration = 0
    driver = None

    while True:
        iteration += 1
        log.info("=== Playlist loop iteration %d ===", iteration)

        videos = get_playlist_videos(args.playlist)
        if not videos:
            log.error("No videos found. Retrying in 60 s...")
            time.sleep(60)
            continue

        if driver is None:
            log.info("Initialising Chrome WebDriver...")
            try:
                driver = build_driver(args.display)
            except Exception as exc:
                log.error("Failed to create WebDriver: %s", exc)
                time.sleep(30)
                continue

        for video in videos:
            try:
                play_video(driver, video, args.log)
            except Exception as exc:
                log.error("Error playing %s: %s", video["url"], exc)
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = None
                time.sleep(10)
                try:
                    driver = build_driver(args.display)
                except Exception as exc2:
                    log.error("Failed to restart WebDriver: %s", exc2)
                    time.sleep(30)
                break

        time.sleep(5)


if __name__ == "__main__":
    main()
