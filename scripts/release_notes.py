#!/usr/bin/env python3
"""
Write the Markdown release notes for a channel's current stock file (as of the checked-out commit).

Used by the Release workflow when publishing, and by the Refresh release notes workflow to
regenerate the notes of an existing release (check out the release's tag first).

    python scripts/release_notes.py --channel LIVE > notes.md
"""

import argparse
import io
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report  # noqa: E402
from build import REPO_ROOT  # noqa: E402
from version_info import info  # noqa: E402


def previous_stock_ref(channel: str) -> str:
    """The commit holding the previous version of this channel's stock file ('' if none)."""
    log = subprocess.run(["git", "-C", str(REPO_ROOT), "log", "--format=%H", "-2", "--",
                          f"stock/{channel}/global.ini"], capture_output=True, text=True).stdout.split()
    return log[1] if len(log) > 1 else ""


def change_report(channel: str, base: str) -> str:
    argv = ["report.py", "--channel", channel] + (["--base-ref", base] if base else ["--base-ref", "none"])
    buf = io.StringIO()
    old_argv, sys.argv = sys.argv, argv
    try:
        with redirect_stdout(buf):
            report.main()
    finally:
        sys.argv = old_argv
    return buf.getvalue()


def notes(channel: str) -> str:
    meta = info(channel)
    version, title = meta["version"], meta["title"]
    lines = [f"Star Citizen **{title}** language pack."]
    if meta["branch"]:
        lines.append(f"CIG build: `{meta['branch']}`")
    lines += [
        "",
        "| Download | Format |",
        "|---|---|",
        f"| `ScCompLangPackWaldo-{version}-{channel}.zip` | Remix: `M2A XL-1`, `EM Dominator II Missile`, `B5 Stormburst Bomb` |",
        f"| `ScCompLangPackWaldo-Classic-{version}-{channel}.zip` | Classic: `XL-1 Military A`, `[EM] Dominator II Missile` |",
        "",
        f"**Install:** extract, then copy `data` and `user.cfg` into your `StarCitizen/{channel}` folder.",
        "If you already have a `user.cfg`, add `g_language = english` to it instead of overwriting.",
        "",
        "The `*-changes.ini` files contain only the lines this pack changes, for merging with other packs "
        "(e.g. in the [Pack Merger](https://adamwaldie.github.io/ScCompLangPackWaldo/)).",
        "",
        change_report(channel, previous_stock_ref(channel)).rstrip(),
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", default="LIVE", type=str.upper)
    args = parser.parse_args()
    sys.stdout.write(notes(args.channel))
    return 0


if __name__ == "__main__":
    sys.exit(main())
