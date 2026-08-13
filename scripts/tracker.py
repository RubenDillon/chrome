#!/usr/bin/env python3
"""
tracker.py
==========
1. Fetches the YouTube playlist video list with yt-dlp.
2. Opens each video in Chrome (kiosk mode via Selenium) and waits for it to finish.
3. After each video completes, writes a timestamped entry to the log file.
4. Loops the playlist indefinitely.

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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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

def get_playlist_videos(playlist_url: str) -> list[dict]:
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
    """Create a headless-looking Chrome driver running on the given Xvfb display."""
    os.environ["DISPLAY"] = display

    options = Options()

    # Kiosk + autoplay
    options.add_argument("--kiosk")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--autoplay-policy=no-user-gesture-required")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--mute-audio")                 # no sound in headless VM
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--start-fullscreen")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument(f"--display={display}")

    # Disable password / save prompts
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    }
    options.add_experimental_option("prefs", prefs)

    service = Service(executable_path="/usr/local/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def wait_for_video_end(driver: webdriver.Chrome, timeout_seconds: int = 3600) -> bool:
    """
    Poll the page's HTML5 video element until it reports ended=true or an error.
    Returns True when ended normally, False on timeout.
    """
    js_ended = """
    var vids = document.querySelectorAll('video');
    if (vids.length === 0) return 'no_video';
    var v = vids[0];
    if (v.error) return 'error';
    if (v.ended)  return 'ended';
    return 'playing';
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            status = driver.execute_script(js_ended)
        except Exception:
            return False

        if status == "ended":
            return True
        if status == "error":
            log.warning("Video element reported an error — skipping.")
            return False

        time.sleep(5)

    log.warning("Timeout waiting for video to end.")
    return False


def append_log(log_file: str, video: dict, status: str) -> None:
    """Append a line to the played log."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {status.upper()} | {video['url']} | {video['title']}\n"
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(line)
        log.info("Logged: %s", line.strip())
    except OSError as exc:
        log.error("Cannot write to log file %s: %s", log_file, exc)


def play_video(driver: webdriver.Chrome, video: dict, log_file: str) -> None:
    """Navigate to the video URL and wait until playback finishes."""
    log.info("Playing: %s  (%s)", video["title"], video["url"])

    # Append autoplay param so YouTube starts automatically
    url = video["url"] + "&autoplay=1"
    driver.get(url)

    # Give the page time to load and start playing
    time.sleep(8)

    # Attempt to dismiss cookie/consent dialogs (best-effort)
    try:
        btn = driver.find_element(By.XPATH, '//button[contains(., "Accept")]')
        btn.click()
        time.sleep(2)
    except Exception:
        pass

    # Click the video player to ensure it starts (YouTube sometimes needs it)
    try:
        player = driver.find_element(By.CSS_SELECTOR, "video")
        driver.execute_script("arguments[0].play();", player)
    except Exception:
        pass

    ended = wait_for_video_end(driver)
    status = "played" if ended else "incomplete"
    append_log(log_file, video, status)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube playlist kiosk tracker")
    parser.add_argument("--playlist", required=True, help="YouTube playlist URL")
    parser.add_argument("--log",      required=True, help="Path to the output log file")
    parser.add_argument("--display",  default=":99",  help="X display to use (e.g. :99)")
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
                # Try to recover by restarting the driver
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

        # Small pause between playlist loops
        time.sleep(5)


if __name__ == "__main__":
    main()
