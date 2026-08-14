#!/usr/bin/env python3
"""
tracker.py
==========
Strategy:
  1. Fetch playlist order with yt-dlp (flat, no auth needed).
  2. Open each video in Chrome via undetected-chromedriver (bypasses YouTube bot detection).
  3. Read duration from page DOM (ytInitialPlayerResponse / video.duration / meta tag).
  4. Wait for that duration + buffer, polling currentTime.
  5. Write STARTED / PLAYED to log file.
  6. Loop forever.
"""

import argparse
import datetime
import logging
import os
import re
import subprocess
import sys
import time

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [tracker] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

BUFFER_SECONDS     = 15
FALLBACK_DURATION  = 90    # seconds — conservative average for short clips
HEARTBEAT_INTERVAL = 30
STALL_TIMEOUT      = 60


# ---------------------------------------------------------------------------
# yt-dlp helpers
# ---------------------------------------------------------------------------

def run_ytdlp(args_list: list, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["yt-dlp"] + args_list,
        capture_output=True, text=True, timeout=timeout,
    )


def get_playlist_videos(playlist_url: str) -> list:
    """Return [{id, url, title}] for every video in the playlist."""
    log.info("Fetching playlist: %s", playlist_url)
    result = run_ytdlp([
        "--flat-playlist",
        "--print", "%(id)s\t%(title)s",
        "--no-warnings",
        playlist_url,
    ])
    if result.returncode != 0:
        log.error("yt-dlp playlist error: %s", result.stderr.strip())
        return []

    videos = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) < 2:
            continue
        videos.append({
            "id":    parts[0],
            "url":   "https://www.youtube.com/watch?v=" + parts[0],
            "title": parts[1],
        })
    log.info("Found %d videos in playlist.", len(videos))
    return videos


# ---------------------------------------------------------------------------
# Chrome driver — undetected_chromedriver bypasses YouTube bot detection
# ---------------------------------------------------------------------------

def build_driver(display: str) -> uc.Chrome:
    """
    Build a Chrome driver using undetected-chromedriver.
    uc patches the ChromeDriver binary at runtime to remove WebDriver fingerprints.
    It needs a writable copy of chromedriver — we keep it in /tmp.
    """
    os.environ["DISPLAY"] = display

    # uc needs to write-patch the binary; copy to a writable location once
    import shutil
    uc_driver = "/tmp/chromedriver_uc"
    if not os.path.exists(uc_driver):
        shutil.copy2("/usr/local/bin/chromedriver", uc_driver)
        os.chmod(uc_driver, 0o755)

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-namespace-sandbox")
    # NOTE: do NOT use --single-process or --no-zygote with undetected-chromedriver
    # uc requires Chrome's normal multi-process model to patch and start correctly
    # Software rendering for VM without GPU
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-gpu-compositing")
    options.add_argument("--use-gl=swiftshader")
    options.add_argument("--use-angle=swiftshader-webgl")
    options.add_argument("--disable-vulkan")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--autoplay-policy=no-user-gesture-required")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-crash-reporter")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-sync")

    driver = uc.Chrome(
        options=options,
        driver_executable_path=uc_driver,
        version_main=None,
        headless=True,
    )
    return driver


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

def append_log(log_file: str, video: dict, status: str) -> None:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "[%s] %-10s | %s | %s\n" % (timestamp, status.upper(), video["url"], video["title"])
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
        log.info("Logged: %s", line.strip())
    except OSError as exc:
        log.error("Cannot write to log file %s: %s", log_file, exc)


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------

def dismiss_consent(driver: uc.Chrome) -> None:
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


def force_play(driver: uc.Chrome) -> None:
    """Mute via JS (not via Chrome flag) and force play."""
    try:
        driver.execute_script("""
            var v = document.querySelector('video');
            if (v) { v.muted = true; v.volume = 0; v.play().catch(function(){}); }
        """)
    except Exception:
        pass


def get_current_time(driver: uc.Chrome) -> float:
    try:
        t = driver.execute_script(
            "var v = document.querySelector('video'); return v ? v.currentTime : -1;"
        )
        return float(t) if t is not None else -1.0
    except Exception:
        return -1.0


def get_duration_from_page(driver: uc.Chrome) -> int:
    """
    Read video duration from page DOM. Tries three sources:
      1. video.duration  (HTML5 element)
      2. ytInitialPlayerResponse.videoDetails.lengthSeconds  (YouTube JS object)
      3. <meta itemprop="duration">  (ISO 8601 PT#M#S)
    Returns seconds, or 0 if not found.
    """
    try:
        d = driver.execute_script(
            "var v = document.querySelector('video');"
            "return (v && v.duration && !isNaN(v.duration)) ? v.duration : 0;"
        )
        if d and float(d) > 0:
            return int(float(d))
    except Exception:
        pass

    try:
        d = driver.execute_script(
            "try { return parseInt(ytInitialPlayerResponse.videoDetails.lengthSeconds,10); }"
            "catch(e) { return 0; }"
        )
        if d and int(d) > 0:
            return int(d)
    except Exception:
        pass

    try:
        content = driver.execute_script(
            "var m = document.querySelector('meta[itemprop=\"duration\"]');"
            "return m ? m.getAttribute('content') : '';"
        )
        if content:
            m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', content)
            if m:
                total = int(m.group(1) or 0)*3600 + int(m.group(2) or 0)*60 + int(m.group(3) or 0)
                if total > 0:
                    return total
    except Exception:
        pass

    return 0


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

def play_video(driver: uc.Chrome, video: dict, log_file: str) -> None:
    log.info("Loading: %s  (%s)", video["title"], video["url"])

    driver.get(video["url"] + "?autoplay=1&t=0")
    time.sleep(10)

    dismiss_consent(driver)
    force_play(driver)
    time.sleep(3)

    duration = get_duration_from_page(driver)
    if duration > 0:
        log.info("Duration from page: %ds", duration)
    else:
        duration = FALLBACK_DURATION
        log.warning("Duration unknown — using %ds fallback.", duration)

    total_wait = duration + BUFFER_SECONDS
    log.info("Playing: %s  [duration=%ds wait=%ds]", video["title"], duration, total_wait)

    append_log(log_file, video, "started")

    start_time = time.time()
    last_hb    = start_time
    last_ct    = get_current_time(driver)
    last_moved = start_time

    while True:
        elapsed = time.time() - start_time
        if elapsed >= total_wait:
            break

        time.sleep(5)
        now = time.time()
        ct  = get_current_time(driver)

        if now - last_hb >= HEARTBEAT_INTERVAL:
            log.info("  playing: currentTime=%.1fs / duration=%ds (elapsed=%.0fs)", ct, duration, elapsed)
            last_hb = now
            force_play(driver)

        if ct > 0 and abs(ct - last_ct) > 0.5:
            last_moved = now
        last_ct = ct

        if ct > 3 and (now - last_moved) > STALL_TIMEOUT:
            log.warning("  stalled at %.1fs — skipping.", ct)
            break

        if 0 < ct >= duration - 2:
            log.info("  currentTime=%.1fs reached end — finishing early.", ct)
            time.sleep(3)
            break

    append_log(log_file, video, "played")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
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
            log.info("Initialising Chrome WebDriver (undetected-chromedriver)...")
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
