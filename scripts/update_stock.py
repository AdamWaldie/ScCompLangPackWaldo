#!/usr/bin/env python3
"""
Pull the stock global.ini out of your Star Citizen install and hand it to CI.

Run this after the launcher finishes patching. It:
  1. reads Data/Localization/english/global.ini from <SC>/<CHANNEL>/Data.p4k (pure Python, seconds)
  2. reads the game version from <SC>/<CHANNEL>/build_manifest.id
  3. writes stock/<CHANNEL>/global.ini and stock/<CHANNEL>/version.json
  4. builds and validates locally, prints the change report
  5. (with --push) commits to a new branch update/<channel>-<version> and pushes it;
     GitHub Actions then opens a pull request with the report. Merging it publishes the release.

Usage:
    python scripts/update_stock.py --channel LIVE --push
    python scripts/update_stock.py --channel PTU --sc-path "D:/Games/StarCitizen"
    python scripts/update_stock.py --channel LIVE --local-file path/to/global.ini --version 4.10.1

Requires: pip install zstandard
"""

from __future__ import annotations

import argparse
import configparser
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import REPO_ROOT  # noqa: E402

INI_PATHS = ["Data/Localization/english/global.ini", "Data/Libs/Localization/English/global.ini"]

DEFAULT_SC_BASES = {
    "Windows": [Path(f"{d}:/Program Files/Roberts Space Industries/StarCitizen") for d in "CDEFG"]
    + [Path(f"{d}:/Roberts Space Industries/StarCitizen") for d in "CDEFG"]
    + [Path(f"{d}:/StarCitizen") for d in "CDEFG"],
    "Linux": [Path.home() / "Games/star-citizen/drive_c/Program Files/Roberts Space Industries/StarCitizen"],
}


def find_sc_base(cli_path: Path | None) -> Path | None:
    if cli_path:
        return cli_path
    cfg = configparser.ConfigParser()
    cfg.read(REPO_ROOT / "config.ini")
    override = cfg.get("paths", "sc_base", fallback=None)
    if override:
        return Path(override)
    return next((p for p in DEFAULT_SC_BASES.get(platform.system(), []) if p.exists()), None)


def extract_ini(p4k_path: Path) -> bytes:
    try:
        from p4k_reader import P4KFile
    except ImportError as e:
        sys.exit(f"ERROR: {e}\nInstall the dependency with: pip install zstandard")
    print(f"Reading {p4k_path} (parsing the index takes a few seconds)...")
    p4k = P4KFile(p4k_path)
    for target in INI_PATHS:
        entry = p4k.find(target)
        if entry:
            print(f"Found {entry.filename} ({entry.file_size:,} bytes)")
            return p4k.read(entry)
    sys.exit("ERROR: global.ini not found inside Data.p4k")


def read_build_manifest(channel_dir: Path) -> dict:
    path = channel_dir / "build_manifest.id"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig")).get("Data", {})
    except (json.JSONDecodeError, AttributeError):
        return {}
    text = " ".join(str(data.get(k, "")) for k in ("Version", "Branch", "Tag"))
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", text)
    return {
        "version": m.group(1) if m else "",
        "build": str(data.get("RequestedP4ChangeNum") or data.get("BuildId") or ""),
        "branch": str(data.get("Branch", "")),
    }


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=REPO_ROOT, check=check)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", required=True, help="LIVE, PTU, EPTU, HOTFIX or TECH-PREVIEW")
    parser.add_argument("--sc-path", type=Path, help="StarCitizen folder that contains LIVE/, PTU/ ...")
    parser.add_argument("--local-file", type=Path, help="Use an already-extracted global.ini instead of Data.p4k")
    parser.add_argument("--version", help="Game version, e.g. 4.10.1 (default: read from build_manifest.id)")
    parser.add_argument("--push", action="store_true", help="Commit to update/<channel>-<version> and push")
    args = parser.parse_args()

    channel = args.channel.upper()
    manifest: dict = {}

    if args.local_file:
        data = args.local_file.read_bytes()
    else:
        base = find_sc_base(args.sc_path)
        if base is None:
            sys.exit("ERROR: Star Citizen install not found. Pass --sc-path or set sc_base in config.ini.")
        channel_dir = base / channel
        p4k = channel_dir / "Data.p4k"
        if not p4k.exists():
            sys.exit(f"ERROR: {p4k} does not exist")
        data = extract_ini(p4k)
        manifest = read_build_manifest(channel_dir)

    version = args.version or manifest.get("version")
    if not version:
        sys.exit("ERROR: couldn't read the game version from build_manifest.id; pass --version X.Y.Z")
    if b"Frontend_PU_Version" not in data[:20_000_000]:
        sys.exit("ERROR: extracted file doesn't look like a global.ini (no Frontend_PU_Version key)")

    branch = f"update/{channel.lower()}-{version}" + (f"-{manifest['build']}" if manifest.get("build") else "")
    if args.push:
        # Start from the latest main so the update branch only carries this channel's change.
        run(["git", "fetch", "origin", "main"])
        run(["git", "switch", "-C", branch, "origin/main"])

    stock_dir = REPO_ROOT / "stock" / channel
    stock_dir.mkdir(parents=True, exist_ok=True)
    stock_file = stock_dir / "global.ini"
    if stock_file.exists() and stock_file.read_bytes() == data:
        print(f"stock/{channel}/global.ini is already up to date - nothing to do.")
        return 0
    stock_file.write_bytes(data)
    (stock_dir / "version.json").write_text(json.dumps(
        {"version": version, "build": manifest.get("build", ""), "branch": manifest.get("branch", "")},
        indent=2) + "\n")
    print(f"Wrote stock/{channel}/global.ini for {version}")

    py = sys.executable
    run([py, "scripts/build.py", "--channel", channel])
    run([py, "scripts/report.py", "--channel", channel, "--base-ref", "HEAD"], check=False)
    if run([py, "scripts/validate.py", "--channel", channel], check=False).returncode != 0:
        print("\nValidation failed - fix the items above (usually data/component_overrides.csv), then re-run.")
        if not args.push:
            return 1

    if args.push:
        run(["git", "add", f"stock/{channel}", f"dist/{channel}"])
        run(["git", "commit", "-m", f"Update {channel} stock global.ini to {version}"])
        run(["git", "push", "-u", "origin", branch])
        print(f"\nPushed {branch}. GitHub Actions will open a pull request with the change report.")
    else:
        print("\nDry run done. Re-run with --push to send it to GitHub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
