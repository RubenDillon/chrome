#!/usr/bin/env python3
"""
get_chromedriver.py
Reads CHROME_MAJOR from environment, finds the matching ChromeDriver
download URL from the Chrome for Testing JSON, and prints it to stdout.
Called during Docker build — output is captured as $DRIVER_URL.
"""
import json
import os
import sys
import urllib.request

major = os.environ.get("CHROME_MAJOR", "").strip()
if not major:
    print("ERROR: CHROME_MAJOR env var is not set", file=sys.stderr)
    sys.exit(1)

url = (
    "https://googlechromelabs.github.io/chrome-for-testing/"
    "known-good-versions-with-downloads.json"
)

with urllib.request.urlopen(url) as r:
    data = json.load(r)

versions = [
    v for v in data["versions"]
    if v["version"].split(".")[0] == major
]
versions.sort(
    key=lambda x: list(map(int, x["version"].split("."))),
    reverse=True,
)

for v in versions:
    for dl in v["downloads"].get("chromedriver", []):
        if dl["platform"] == "linux64":
            print(dl["url"])
            sys.exit(0)

print(f"ERROR: no chromedriver found for Chrome major {major}", file=sys.stderr)
sys.exit(1)
