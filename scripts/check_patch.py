#!/usr/bin/env python3
"""
Detect a new Star Citizen patch without a game install, so the maintainer gets a reminder to run update.bat.

MrKraken's StarStrings README records the exact CIG build it was made from, e.g.
"[Build: sc-alpha-4.10.2_live_12881860]", and is usually updated within a day of each patch.
This compares that build with stock/<CHANNEL>/version.json. Only the build string is used,
none of StarStrings' content.

Prints one JSON object per line for each channel that looks out of date:
    {"channel": "LIVE", "version": "4.10.2", "build": "12881860", "branch": "sc-alpha-4.10.2_live_12881860"}
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES = [
    "https://raw.githubusercontent.com/MrKraken/StarStrings/master/readme.md",
    "https://raw.githubusercontent.com/MrKraken/StarStrings/sc-ptu/readme.md",
]
BUILD_RE = re.compile(r"sc-alpha-(\d+\.\d+(?:\.\d+)?)[-_]([a-z]+)[-_](\d+)", re.IGNORECASE)


def fetch(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:  # a missing branch or network blip shouldn't fail the whole check
        print(f"warning: couldn't fetch {url}: {e}", file=sys.stderr)
        return ""


def ours(channel: str) -> dict:
    path = REPO_ROOT / "stock" / channel / "version.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def is_newer(theirs: dict, mine: dict) -> bool:
    if mine.get("build", "").isdigit():
        return int(theirs["build"]) > int(mine["build"])
    # No build number recorded yet (e.g. seed data): fall back to comparing versions.
    as_tuple = lambda v: tuple(int(x) for x in re.findall(r"\d+", v or "0"))  # noqa: E731
    return as_tuple(theirs["version"]) > as_tuple(mine.get("version", ""))


def main() -> int:
    latest: dict[str, dict] = {}
    for url in SOURCES:
        for version, env, build in BUILD_RE.findall(fetch(url)):
            channel = env.upper()
            found = {"channel": channel, "version": version, "build": build,
                     "branch": f"sc-alpha-{version}_{env.lower()}_{build}"}
            if channel not in latest or int(build) > int(latest[channel]["build"]):
                latest[channel] = found

    for channel, theirs in sorted(latest.items()):
        if is_newer(theirs, ours(channel)):
            print(json.dumps(theirs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
