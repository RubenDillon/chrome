#!/usr/bin/env python3
"""
tracker.py
==========
Strategy:
  1. Fetch playlist with yt-dlp (flat, fast).
  2. For each video, get its duration with yt-dlp.
  3. Open the video in Chrome (Selenium) and force play via JS.
  4. Sleep for the video duration + a small buffer.
  5. Write STARTED at the beginning, PLAYED at the end.
  6. Loop forever.

Using duration-based waiting avoids relying on the HTML5 video.ended
event, which YouTube's SPA often fires late or never when running under
Selenium with --mute-audio.
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

# How many extra seconds to wait after the expected duration ends
BUFFER_SECONDS = 15
# Fallback duration if yt-dlp cannot determine it (seconds)
FALLBACK_DURATION = 600
# How often to log a "still playing" heartbeat (seconds)
HEARTBEAT_INTERVAL = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_ytdlp(args_list: list, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["yt-dlp"] + args_list,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def get_playlist_videos(playlist_url: str) -> list:
    """Return ordered list of {id, url, title, duration} dicts."""
    log.info("Fetching playlist: %s", playlist_url)
    result = run_ytdlp([
        "--flat-playlist",
        "--print", "%(id)s\t%(title)s\t%(duration)s",
        "--no-warnings",
        playlist_url,
    ])
    if result.returncode != 0:
        log.error("yt-dlp playlist error: %s", result.stderr.strip())
        return []

    videos = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        vid_id = parts[0]
        title  = parts[1] if len(parts) > 1 else vid_id
        try:
            duration = int(float(parts[2])) if len(parts) > 2 and parts[2] not in ("", "NA", "None") else None
        except (ValueError, TypeError):
            duration = None
        videos.append({
            "id":       vid_id,
            "url":      f"https://www.youtube.com/watch?v={vid_id}",
            "title":    title,
            "duration": duration,
        })

    log.info("Found %d videos in playlist.", len(videos))
    return videos


def get_video_duration(video_url: str) -> int:
    """Return video duration in seconds via yt-dlp, or FALLBACK_DURATION."""
    result = run_ytdlp([
        "--no-playlist",
        "--print", "%(duration)s",
        "--no-warnings",
        video_url,
    ], timeout=30)
    if result.returncode == 0:
        raw = result.stdout.strip()
        try:
            return int(float(raw))
        except (ValueError, TypeError):
            pass
    log.warning("Could not get duration for %s — using %ds fallback.", video_url, FALLBACK_DURATION)
    return FALLBACK_DURATION


def build_driver(display: str) -> webdriver.Chrome:
    """Build a Chrome WebDriver on the given Xvfb display."""
    os.environ["DISPLAY"] = display

    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--autoplay-policy=no-user-gesture-required")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--mute-audio")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-blink-features=AutomationControlled")
    # Exclude automation flags that trigger YouTube bot detection
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    })

    service = Service(executable_path="/usr/local/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)
    # Hide webdriver flag from JS
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


def append_log(log_file: str, video: dict, status: str) -> None:
    """Write a timestamped entry to the log file."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {status.upper():10s} | {video['url']} | {video['title']}\n"
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
        log.info("Logged: %s", line.strip())
    except OSError as exc:
        log.error("Cannot write to log file %s: %s", log_file, exc)


def dismiss_consent(driver: webdriver.Chrome) -> None:
    """Dismiss YouTube cookie/consent dialogs if present."""
    xpaths = [
        '//button[@aria-label="Accept all"]',
        '//button[contains(., "Accept all")]',
        '//button[contains(., "Accept")]',
        '//button[contains(., "Agree")]',
        '//tp-yt-paper-button[contains(., "AGREE")]',
    ]
    for xp in xpaths:
        try:
            driver.find_element(By.XPATH, xp).click()
            log.info("Dismissed consent dialog.")
            time.sleep(2)
            return
        except Exception:
            pass


def force_play(driver: webdriver.Chrome) -> None:
    """Force the HTML5 video to play and unmute via JavaScript."""
    try:
        driver.execute_script("""
            var v = document.querySelector('video');
            if (v) {
                v.muted = false;
                v.volume = 0.5;
                v.play().catch(function(){});
            }
        """)
    except Exception:
        pass


def get_current_time(driver: webdriver.Chrome) -> float:
    """Return video.currentTime or -1 on error."""
    try:
        t = driver.execute_script(
            "var v = document.querySelector('video'); return v ? v.currentTime : -1;"
        )
        return float(t) if t is not None else -1.0
    except Exception:
        return -1.0


def play_video(driver: webdriver.Chrome, video: dict, log_file: str) -> None:
    """Navigate to the video and wait for it to finish by duration."""

    # Get duration (use cached value from playlist if available)
    duration = video.get("duration")
    if not duration:
        duration = get_video_duration(video["url"])
    total_wait = duration + BUFFER_SECONDS
    log.info(
        "Playing: %s  (%s)  [duration=%ds, waiting=%ds]",
        video["title"], video["url"], duration, total_wait,
    )

    url = video["url"] + "?autoplay=1&t=0"
    driver.get(url)
    time.sleep(8)

    dismiss_consent(driver)
    force_play(driver)

    append_log(log_file, video, "started")

    # Wait for the video duration, polling to log heartbeats and re-force play
    start_time   = time.time()
    last_hb      = start_time
    last_ct      = get_current_time(driver)
    stall_since  = start_time

    while True:
        elapsed = time.time() - start_time
        if elapsed >= total_wait:
            break

        time.sleep(5)
        now = time.time()

        # Heartbeat log every HEARTBEAT_INTERVAL seconds
        if now - last_hb >= HEARTBEAT_INTERVAL:
            ct = get_current_time(driver)
            log.info(
                "  still playing: currentTime=%.1fs / expected=%.0fs (elapsed=%.0fs)",
                ct, duration, elapsed,
            )
            last_hb = now

            # Detect stall: if currentTime hasn't moved in 30s, force play again
            if ct > 0 and abs(ct - last_ct) < 1.0:
                log.warning("  video appears stalled — forcing play()")
                force_play(driver)
            elif ct > 0:
                stall_since = now
            last_ct = ct

        # If currentTime is near the end, break early
        ct = get_current_time(driver)
        if 0 < ct >= duration - 2:
            log.info("  currentTime=%.1fs reached end — finishing early.", ct)
            time.sleep(3)
            break

    append_log(log_file, video, "played")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube playlist kiosk tracker")
    parser.add_argument("--playlist", required=True)
    parser.add_argument("--log",      required=True)
    parser.add_argument("--display",  default=":99")
    args = parser.parse_args()

    iteration = 0
    driver    = None

    while True:
        iteration += 1
        log.info("=== Playlist loop iteration %d ===", iteration)

        videos = get_playlist_videos(args.playlist)
        if not videos:
            log.error("No videos found — retrying in 60s.")
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

        time.sleep(3)


if __name__ == "__main__":
    main()
