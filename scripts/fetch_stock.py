#!/usr/bin/env python3
"""
Fetch the newest stock LIVE English global.ini without a game install.

Source: Dymerz/StarCitizen-Localization (MIT), whose data/Localization/english/global.ini is
"imported from game files" and updated on patch day. Each commit message names the patch,
e.g. "English + Brazilian 4.10.1-live.12660092" or "4.9.0-ptu.12206539 (EN)", which tells us the
channel and build; PTU commits are ignored (only LIVE is supported). (Their 4.8.0 LIVE file was checked against an extraction from Data.p4k: every
value identical.)

The newest LIVE commit wins. A file is only accepted if it passes sanity
checks (looks like a full global.ini, didn't lose a big chunk of keys, still carries component stats).

Usage:
    python scripts/fetch_stock.py                 # update stock/LIVE/ if newer, print JSON summary
    python scripts/fetch_stock.py --dry-run       # only report what would change

Prints one JSON line when LIVE was updated: {"channel", "version", "build", "source"}.
Exit code 0 even when nothing changed; 1 on errors.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import REPO_ROOT, IniFile, classify  # noqa: E402

SOURCE_REPO = "https://github.com/Dymerz/StarCitizen-Localization"
SOURCE_NAME = "Dymerz/StarCitizen-Localization"
SOURCE_PATH = "data/Localization/english/global.ini"
CHANNELS = ("LIVE",)  # only LIVE is supported

# Lookarounds instead of \b so "4.10.1-live.12660092" splits cleanly into its parts.
VERSION_RE = re.compile(r"(?<![\d.])(\d+\.\d+(?:\.\d+)?)(?![\d])")
CHANNEL_RE = re.compile(r"(?<![a-z])(live|eptu|ptu|hotfix)(?![a-z])", re.IGNORECASE)
BUILD_RE = re.compile(r"(?<!\d)(\d{7,9})(?!\d)")

MIN_KEYS = 50_000          # a real global.ini has ~90k keys
MAX_KEY_LOSS = 0.05        # refuse a file that drops >5% of the keys we currently have
MIN_COMPONENTS = 200       # descriptions must still carry stats for at least this many items


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def parse_message(message: str) -> dict | None:
    """'English + Brazilian 4.10.1-live.12660092' -> {channel: LIVE, version: 4.10.1, build: 12660092}."""
    text = message.splitlines()[0] if message else ""
    channel = CHANNEL_RE.search(text)
    version = VERSION_RE.search(text)
    if not channel or not version:
        return None
    build = BUILD_RE.search(text)
    return {"channel": channel.group(1).upper(), "version": version.group(1),
            "build": build.group(1) if build else ""}


def version_key(version: str) -> tuple[int, ...]:
    parts = [int(x) for x in re.findall(r"\d+", version or "")]
    return tuple((parts + [0, 0, 0])[:3])


def sanity_check(new_path: Path, current_path: Path) -> str | None:
    """Return a reason to reject the file, or None if it looks like a genuine stock global.ini."""
    try:
        new = IniFile.load(new_path)
    except Exception as e:
        return f"unreadable: {e}"
    if new.get("Frontend_PU_Version") is None:
        return "no Frontend_PU_Version key"
    if len(new.index) < MIN_KEYS:
        return f"only {len(new.index)} keys"
    if current_path.exists():
        current = IniFile.load(current_path)
        lost = len(set(current.index) - set(new.index))
        if lost > MAX_KEY_LOSS * len(current.index):
            return f"would drop {lost} of {len(current.index)} existing keys"
    found = classify(new)
    components = sum(1 for i in found.items if i.kind == "component")
    if components < MIN_COMPONENTS:
        return f"only {components} components classifiable (descriptions changed format?)"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, help="Existing clone of the source repo (default: clone to temp)")
    parser.add_argument("--depth", type=int, default=60, help="How many source commits to look back through")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    src = args.source_dir
    if src is None:
        src = Path(tempfile.mkdtemp()) / "src"
        subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout",
                        f"--depth={args.depth}", SOURCE_REPO, str(src)], check=True)

    log = git("log", "--format=%H%x1f%cs%x1f%s", f"-{args.depth}", "HEAD", "--", SOURCE_PATH, cwd=src)
    newest: dict[str, dict] = {}
    for line in log.splitlines():
        sha, date, subject = line.split("\x1f", 2)
        meta = parse_message(subject)
        if meta is None:
            print(f"note: skipping unclassifiable commit {sha[:8]} {subject!r}", file=sys.stderr)
            continue
        if meta["channel"] in CHANNELS and meta["channel"] not in newest:
            newest[meta["channel"]] = {**meta, "sha": sha, "date": date, "subject": subject}

    errors = 0
    for channel in CHANNELS:
        meta = newest.get(channel)
        if meta is None:
            print(f"note: no {channel} commit in the last {args.depth} source commits", file=sys.stderr)
            continue
        stock_dir = REPO_ROOT / "stock" / channel
        version_file = stock_dir / "version.json"
        current = json.loads(version_file.read_text()) if version_file.exists() else {}
        if current.get("source_sha") == meta["sha"]:
            continue  # already have exactly this one

        data = subprocess.run(["git", "show", f"{meta['sha']}:{SOURCE_PATH}"], cwd=src,
                              check=True, capture_output=True).stdout
        stock_file = stock_dir / "global.ini"
        if stock_file.exists() and stock_file.read_bytes() == data:
            continue

        with tempfile.NamedTemporaryFile(suffix=".ini", delete=False) as tmp:
            tmp.write(data)
        reason = sanity_check(Path(tmp.name), stock_file)
        if reason:
            print(f"ERROR: rejected {channel} file from {meta['sha'][:8]} ({meta['subject']!r}): {reason}",
                  file=sys.stderr)
            errors += 1
            continue

        # Never go backwards, e.g. behind a newer manual extraction made with update.bat.
        if version_key(meta["version"]) < version_key(current.get("version", "")) or (
                current.get("build", "").isdigit() and meta["build"].isdigit()
                and int(meta["build"]) < int(current["build"])):
            print(f"note: {channel} source {meta['version']} {meta['build']} is older than ours "
                  f"({current.get('version')} {current.get('build')})", file=sys.stderr)
            continue

        summary = {"channel": channel, "version": meta["version"], "build": meta["build"],
                   "source": f"{SOURCE_NAME}@{meta['sha'][:12]}"}
        if not args.dry_run:
            stock_dir.mkdir(parents=True, exist_ok=True)
            stock_file.write_bytes(data)
            version_file.write_text(json.dumps({
                "version": meta["version"],
                "build": meta["build"],
                "branch": f"sc-alpha-{meta['version']}-{channel.lower()}" + (f".{meta['build']}" if meta["build"] else ""),
                "source": SOURCE_NAME,
                "source_sha": meta["sha"],
            }, indent=2) + "\n")
        print(json.dumps(summary))

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
