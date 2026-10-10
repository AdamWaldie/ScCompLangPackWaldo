#!/usr/bin/env python3
"""
Print release metadata for a channel from stock/<CHANNEL>/version.json (used by the workflows).

    python scripts/version_info.py --channel LIVE version   -> 4.10.2
    python scripts/version_info.py --channel LIVE build     -> 12881860
    python scripts/version_info.py --channel LIVE title     -> 4.10.2 LIVE (build 12881860)
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def info(channel: str) -> dict:
    data = json.loads((REPO_ROOT / "stock" / channel / "version.json").read_text(encoding="utf-8"))
    version, build = data.get("version", ""), data.get("build", "")
    title = f"{version} {channel}" + (f" (build {build})" if build else "")
    return {"version": version, "build": build, "branch": data.get("branch", ""), "title": title,
            "source": data.get("source", "")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", required=True)
    parser.add_argument("field", choices=("version", "build", "branch", "title", "source"))
    args = parser.parse_args()
    print(info(args.channel.upper())[args.field])
    return 0


if __name__ == "__main__":
    sys.exit(main())
