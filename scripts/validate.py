#!/usr/bin/env python3
"""
Sanity-check built packs against their stock file before anything is released.

Checks, per channel and variant:
  * output exists, starts with a UTF-8 BOM and isn't truncated
  * same keys, in the same order, as the stock file
  * only keys the build meant to change differ from stock
  * remix component tags are well-formed ([MICRS][0-9][A-D])
  * no component-like keys were left unclassified

Usage:
    python scripts/validate.py              # every channel that has a stock file
    python scripts/validate.py --channel LIVE
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import CHANGES_FILE, REPO_ROOT, VARIANTS, IniFile, build  # noqa: E402

REMIX_COMPONENT_TAG = re.compile(r"^[MICRS]\d{1,2}[A-D] \S")


def validate(channel: str) -> list[str]:
    errors: list[str] = []
    stock_path = REPO_ROOT / "stock" / channel / "global.ini"
    stock = IniFile.load(stock_path)

    for variant in VARIANTS:
        out_path = REPO_ROOT / "dist" / channel / variant / "data" / "Localization" / "english" / "global.ini"
        where = f"{channel}/{variant}"
        if not out_path.exists():
            errors.append(f"{where}: missing {out_path.relative_to(REPO_ROOT)} (run scripts/build.py)")
            continue
        if not out_path.read_bytes().startswith(b"\xef\xbb\xbf"):
            errors.append(f"{where}: output has no UTF-8 BOM")
        if not (REPO_ROOT / "dist" / channel / variant / "user.cfg").exists():
            errors.append(f"{where}: missing user.cfg")

        out = IniFile.load(out_path)
        if list(out.index) != list(stock.index):
            errors.append(f"{where}: key list differs from stock ({len(out.index)} vs {len(stock.index)} keys) "
                          f"- truncated or stale build")
            continue

        expected, stats = build(stock_path, variant)
        if out.lines != expected.lines:
            errors.append(f"{where}: committed output is out of date with stock/data/scripts "
                          f"(run scripts/build.py --channel {channel})")

        changes_path = out_path.parents[3] / CHANGES_FILE
        expected_changes = expected.changes_since(stock, skip={"Frontend_PU_Version"})
        if not changes_path.exists() or IniFile.load(changes_path).lines != expected_changes:
            errors.append(f"{where}: {CHANGES_FILE} is missing or out of date (run scripts/build.py --channel {channel})")

        allowed = set(stats["tagged"]) | {"Frontend_PU_Version"}
        unexpected = [k for k in stock.keys() if out.get(k) != stock.get(k) and k not in allowed]
        if unexpected:
            errors.append(f"{where}: {len(unexpected)} keys changed that the build doesn't own, e.g. {unexpected[:5]}")

        if variant == "remix":
            bad = [k for k, v in stats["tagged"].items()
                   if "_short" not in k.lower() and re.match(r"^item_?name_?(COOL|POWR|SHLD|QDRV|RADR)", k, re.I)
                   and not REMIX_COMPONENT_TAG.match(v)]
            if bad:
                errors.append(f"{where}: malformed component tags: {bad[:5]}")

        if stats["unresolved"]:
            errors.append(f"{where}: {len(stats['unresolved'])} unclassified component keys "
                          f"(add to data/component_overrides.csv): {stats['unresolved'][:10]}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", help="Only validate this channel")
    args = parser.parse_args()

    channels = [args.channel.upper()] if args.channel else sorted(
        p.parent.name for p in (REPO_ROOT / "stock").glob("*/global.ini"))
    errors = [e for ch in channels for e in validate(ch)]
    for e in errors:
        print(f"ERROR: {e}")
    print(f"Validated {', '.join(channels)}: {'FAILED' if errors else 'OK'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
