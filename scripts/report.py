#!/usr/bin/env python3
"""
Compare two stock global.ini files and report what a new patch changed for the pack:
new tagged items, items whose size/grade/class/tracking changed, removed items, and
component-like keys that need a manual entry in data/component_overrides.csv.

Usage:
    # Compare the working-tree stock file against the one in the previous commit
    python scripts/report.py --channel LIVE --base-ref HEAD~1

    # Compare two explicit files
    python scripts/report.py --old old.ini --new new.ini

Output is Markdown (suitable for a PR body or GitHub job summary).
Exit code is 2 when items need attention and --fail-on-unresolved is set.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import REPO_ROOT, IniFile, build, classify, rename  # noqa: E402


def describe(ini: IniFile) -> tuple[dict[str, tuple[str, str]], list[str], list[str]]:
    """Return {key: (stock name, remix-tagged name)}, unresolved keys, bespoke keys."""
    result = classify(ini)
    out = {}
    for item in result.items:
        name = ini.get(item.key) or ""
        out[item.key] = (name, rename(item, name, "remix") or name)
    return out, result.unresolved, result.bespoke


def stock_at_ref(channel: str, ref: str) -> Path | None:
    rel = f"stock/{channel}/global.ini"
    proc = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"{ref}:{rel}"], capture_output=True)
    if proc.returncode != 0:
        return None
    tmp = Path(tempfile.mkdtemp()) / "global.ini"
    tmp.write_bytes(proc.stdout)
    return tmp


def table(rows: list[tuple[str, ...]], headers: tuple[str, ...]) -> str:
    if not rows:
        return "_None._\n"
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(c.replace("|", "\\|") for c in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", default="LIVE")
    parser.add_argument("--base-ref", default="HEAD~1", help="Git ref holding the previous stock file")
    parser.add_argument("--old", type=Path, help="Previous stock global.ini (overrides --base-ref)")
    parser.add_argument("--new", type=Path, help="New stock global.ini (default: stock/<channel>/global.ini)")
    parser.add_argument("--fail-on-unresolved", action="store_true")
    args = parser.parse_args()

    channel = args.channel.upper()
    new_path = args.new or REPO_ROOT / "stock" / channel / "global.ini"
    old_path = args.old or stock_at_ref(channel, args.base_ref)

    new_ini = IniFile.load(new_path)
    new_items, unresolved, bespoke = describe(new_ini)
    version = new_ini.get("Frontend_PU_Version") or "unknown"

    print(f"## {channel}: {version}\n")
    print(f"**{len(new_items)}** items tagged, **{len(bespoke)}** bespoke parts left as-is, "
          f"**{len(unresolved)}** need attention.\n")
    if new_path.parent.name == channel:
        _, built = build(new_path, "remix")
        c = built["counts"]
        print(f"Contract info (blueprints, reputation, standing, scenario progress): **{c['contract_title']}** "
              f"titles and **{c['contract_desc']}** descriptions "
              f"annotated ({built['gamedata']}). CIG text fixes: **{c['cig_fix']}**.\n")

    if old_path is None:
        print("_No previous stock file to compare against (first build for this channel)._\n")
    else:
        old_ini = IniFile.load(old_path)
        old_items, _, _ = describe(old_ini)
        print(f"Compared with previous stock: `{old_ini.get('Frontend_PU_Version') or 'unknown'}`\n")

        added = [(k, new_items[k][1]) for k in sorted(new_items) if k not in old_items]
        removed = [(k, old_items[k][1]) for k in sorted(old_items) if k not in new_items]
        changed = [(k, old_items[k][1], new_items[k][1]) for k in sorted(new_items)
                   if k in old_items and old_items[k][1] != new_items[k][1]]

        print(f"### New items ({len(added)})\n")
        print(table(added, ("Key", "Tagged name")))
        print(f"### Changed items ({len(changed)})\n")
        print(table(changed, ("Key", "Before", "After")))
        print(f"### Removed items ({len(removed)})\n")
        print(table(removed, ("Key", "Was")))

    no_desc = classify(new_ini).no_description
    if no_desc:
        print(f"### Left with stock names ({len(no_desc)})\n")
        print("Component-like keys with no description to read stats from (usually a typo in CIG's key). "
              "Their stock name is kept; nothing to do.\n")
        print(table([(k, new_ini.get(k) or "") for k in no_desc], ("Key", "Stock name")))

    print(f"### Needs attention ({len(unresolved)})\n")
    if unresolved:
        print("These look like ship components but their stats couldn't be read from the description. "
              "Add a row to `data/component_overrides.csv` (stats, or `skip`).\n")
    print(table([(k, new_ini.get(k) or "") for k in unresolved], ("Key", "Stock name")))

    return 2 if unresolved and args.fail_on_unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
