#!/usr/bin/env python3
"""
Print release metadata for a channel from stock/<CHANNEL>/version.json (used by the workflows).

    python scripts/version_info.py --channel LIVE version   -> 4.10.2
    python scripts/version_info.py --channel LIVE build     -> 12881860
    python scripts/version_info.py --channel LIVE title     -> 4.10.2 LIVE (build 12881860)
    python scripts/version_info.py --channel LIVE blueprints [--ref TAG]
        -> matched / older / newer / none: how the game data compares with the stock file
           (at a commit or tag with --ref, otherwise in the working tree)
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def info(channel: str) -> dict:
    data = json.loads((REPO_ROOT / "stock" / channel / "version.json").read_text(encoding="utf-8"))
    version, build = data.get("version", ""), data.get("build", "")
    title = f"{version} {channel}" + (f" (build {build})" if build else "")
    return {"version": version, "build": build, "branch": data.get("branch", ""), "title": title,
            "source": data.get("source", "")}


def blueprints(channel: str, ref: str = "") -> str:
    from build import gamedata_match

    def read(path: str) -> dict | None:
        if not ref:
            f = REPO_ROOT / path
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"{ref}:{path}"], capture_output=True, text=True)
        return json.loads(out.stdout) if out.returncode == 0 else None

    gd, meta = read(f"data/gamedata/{channel}.json"), read(f"stock/{channel}/version.json")
    return gamedata_match(gd, meta) if gd and meta else "none"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", required=True)
    parser.add_argument("field", choices=("version", "build", "branch", "title", "source", "blueprints"))
    parser.add_argument("--ref", default="", help="blueprints only: commit or tag to check instead of the working tree")
    args = parser.parse_args()
    channel = args.channel.upper()
    print(blueprints(channel, args.ref) if args.field == "blueprints" else info(channel)[args.field])
    return 0


if __name__ == "__main__":
    sys.exit(main())
