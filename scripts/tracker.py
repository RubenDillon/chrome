#!/usr/bin/env python3
"""
tracker.py — YouTube playlist kiosk tracker using Playwright
=============================================================
1. Fetch playlist order with yt-dlp (flat, no auth needed).
2. Open each video URL in Playwright's Chromium (headless).
   Playwright uses a real browser with no WebDriver signals —
   YouTube loads the player normally.
3. Read duration from ytInitialPlayerResponse or video.duration.
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

from playwright.sync_api import sync_playwright, Page, Browser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [tracker] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

BUFFER_SECONDS     = 15
FALLBACK_DURATION  = 90
HEARTBEAT_INTERVAL = 30
STALL_TIMEOUT      = 60


# ---------------------------------------------------------------------------
# yt-dlp — playlist fetch only (no auth needed for flat playlist)
# ---------------------------------------------------------------------------

def get_playlist_videos(playlist_url: str) -> list:
    log.info("Fetching playlist: %s", playlist_url)
    result = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--print", "%(id)s\t%(title)s",
         "--no-warnings", playlist_url],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        log.error("yt-dlp error: %s", result.stderr.strip())
        return []

    videos = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            videos.append({
                "id":    parts[0],
                "url":   "https://www.youtube.com/watch?v=" + parts[0],
                "title": parts[1],
            })
    log.info("Found %d videos in playlist.", len(videos))
    return videos


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------

def build_browser(playwright) -> Browser:
    """Launch Playwright Chromium — no WebDriver signals, passes YouTube checks."""
    return playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--use-gl=swiftshader",
            "--disable-vulkan",
            "--autoplay-policy=no-user-gesture-required",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-crash-reporter",
        ],
    )


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

def dismiss_consent(page: Page) -> None:
    """Dismiss YouTube cookie consent dialogs."""
    selectors = [
        'button[aria-label="Accept all"]',
        'button:has-text("Accept all")',
        'button:has-text("Accept")',
        'button:has-text("Agree")',
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                log.info("Dismissed consent dialog.")
                page.wait_for_timeout(2000)
                return
        except Exception:
            pass


def get_duration_from_page(page: Page) -> int:
    """
    Read video duration from page. Tries:
      1. ytInitialPlayerResponse.videoDetails.lengthSeconds
      2. video.duration (HTML5 element)
      3. <meta itemprop="duration"> (PT#M#S)
    Returns seconds, or 0 if not found.
    """
    try:
        d = page.evaluate(
            "() => { try { return parseInt(ytInitialPlayerResponse.videoDetails.lengthSeconds,10); }"
            " catch(e) { return 0; } }"
        )
        if d and int(d) > 0:
            return int(d)
    except Exception:
        pass

    try:
        d = page.evaluate(
            "() => { var v = document.querySelector('video');"
            " return (v && v.duration && !isNaN(v.duration)) ? v.duration : 0; }"
        )
        if d and float(d) > 0:
            return int(float(d))
    except Exception:
        pass

    try:
        content = page.evaluate(
            "() => { var m = document.querySelector('meta[itemprop=\"duration\"]');"
            " return m ? m.getAttribute('content') : ''; }"
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


def get_current_time(page: Page) -> float:
    try:
        t = page.evaluate(
            "() => { var v = document.querySelector('video'); return v ? v.currentTime : -1; }"
        )
        return float(t) if t is not None else -1.0
    except Exception:
        return -1.0


def force_play(page: Page) -> None:
    try:
        page.evaluate(
            "() => { var v = document.querySelector('video');"
            " if(v) { v.muted=true; v.volume=0; v.play().catch(()=>{}); } }"
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

def play_video(browser: Browser, video: dict, log_file: str) -> None:
    log.info("Loading: %s  (%s)", video["title"], video["url"])

    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    try:
        page.goto(video["url"] + "?autoplay=1&t=0", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(8000)

        dismiss_consent(page)
        force_play(page)
        page.wait_for_timeout(3000)

        duration = get_duration_from_page(page)
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
        last_ct    = get_current_time(page)
        last_moved = start_time

        while True:
            elapsed = time.time() - start_time
            if elapsed >= total_wait:
                break

            time.sleep(5)
            now = time.time()
            ct  = get_current_time(page)

            if now - last_hb >= HEARTBEAT_INTERVAL:
                log.info("  playing: currentTime=%.1fs / duration=%ds (elapsed=%.0fs)",
                         ct, duration, elapsed)
                last_hb = now
                force_play(page)

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

    finally:
        append_log(log_file, video, "played")
        try:
            context.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--playlist", required=True)
    parser.add_argument("--log",      required=True)
    parser.add_argument("--display",  default=":99")  # kept for compat, not used by Playwright
    args = parser.parse_args()

    iteration = 0

    with sync_playwright() as pw:
        log.info("Launching Playwright Chromium browser...")
        browser = build_browser(pw)

        while True:
            iteration += 1
            log.info("=== Playlist loop iteration %d ===", iteration)

            videos = get_playlist_videos(args.playlist)
            if not videos:
                log.error("No videos found — retrying in 60s.")
                time.sleep(60)
                continue

            for video in videos:
                try:
                    play_video(browser, video, args.log)
                except Exception as exc:
                    log.error("Error playing %s: %s", video["url"], exc)
                    time.sleep(5)

            time.sleep(3)


if __name__ == "__main__":
    main()
