#!/usr/bin/env python3
"""
Sanity-check built packs against their stock file before anything is released.

Checks, per channel and variant:
  * output exists, starts with a UTF-8 BOM and isn't truncated
  * same keys, in the same order, as the stock file, plus the UI keys the build adds at the end
  * every item type/subtype/port name, ship name and contract title/description the game looks up
    has text
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
from build import CHANGES_FILE, REPO_ROOT, VARIANTS, IniFile, build, is_placeholder, load_ui_keys  # noqa: E402

REMIX_COMPONENT_TAG = re.compile(r"^[MICRS]\d{1,2}[A-D] \S")


# 4.10.2 lists ~1,400 (item types, subtypes, ship and contract names); far fewer means the list broke.
MIN_UI_KEYS = 500
PLACEHOLDER_TEXT = re.compile(r"PLACEHOLDER|UNINITIALI[SZ]ED|<=\s*\w|\[PH\]", re.IGNORECASE)


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
        expected, stats = build(stock_path, variant)
        if list(out.index) != list(stock.index) + stats["added"]:
            errors.append(f"{where}: key list differs from stock plus added UI keys ({len(out.index)} vs "
                          f"{len(stock.index)} + {len(stats['added'])} keys) - truncated or stale build")
            continue

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
                   if "_short" not in k.lower() and k not in stats["text_fixed"] and re.match(r"^item_?name_?(COOL|POWR|SHLD|QDRV|RADR|COMP)", k, re.I)
                   and not REMIX_COMPONENT_TAG.match(v)]
            if bad:
                errors.append(f"{where}: malformed component tags: {bad[:5]}")

        # Nothing we write may break the file or show raw keys in game.
        broken = [k for k, v in stats["tagged"].items()
                  if "\n" in v or "\r" in v or v.startswith("@") or v.startswith("[BP][BP]")
                  or (not v.strip() and (stock.get(k) or "").strip())]
        if broken:
            errors.append(f"{where}: {len(broken)} changed values would be broken in game, e.g. {broken[:5]}")

        # Placeholder text from game data must never reach the player.
        placeholder = [k for k, v in stats["tagged"].items()
                       if PLACEHOLDER_TEXT.search(v) and not PLACEHOLDER_TEXT.search(stock.get(k) or "")]
        if placeholder:
            errors.append(f"{where}: {len(placeholder)} values gained placeholder text, e.g. {placeholder[:5]}")

        # A value that only references a key that doesn't exist shows the raw "@key" in game.
        lower = {k.lower() for k in out.index}
        dangling = [k for k in out.keys() if (m := re.match(r"^@([A-Za-z_][\w.\-]*)$", (out.get(k) or "").strip()))
                    and m.group(1).lower() not in lower]
        if dangling:
            errors.append(f"{where}: {len(dangling)} values reference keys that don't exist, e.g. {dangling[:5]}")

        # Keys the game builds from item data (e.g. "@item_TypeUtilityTurret") show raw without text.
        names, descs = load_ui_keys(stock_path)
        if (REPO_ROOT / "data" / "gamedata" / f"{channel}.json").exists() and len(names) < MIN_UI_KEYS:
            # An empty or tiny list would silently switch this check off (e.g. a game-data format change).
            errors.append(f"{where}: game data lists only {len(names)} UI keys (expected {MIN_UI_KEYS}+); "
                          f"check scripts/fetch_gamedata.py against the scunpacked-data layout")
        missing = [k for k in [*names, *descs] if k.lower() not in lower]
        missing += [k for k in stats["added"] if not (out.get(k) or "").strip()]
        if missing:
            errors.append(f"{where}: {len(missing)} names/descriptions the game looks up have no text, "
                          f"e.g. {missing[:5]}")

        # Item names and descriptions must never be blank, placeholders or raw identifiers, and no text
        # may start with a [PH] marker (fix_stock_text handles these; this catches anything new).
        unfinished = [k for k in out.keys()
                      if re.match(r"^item_?(name|desc)_?\w", k, re.I) and k.lower() not in {"item_name", "item_desc"}
                      and (not (out.get(k) or "").strip() or is_placeholder(out.get(k) or ""))]
        unfinished += [k for k in out.keys() if re.search(r"\[PH\]", out.get(k) or "", re.I)]
        if unfinished:
            errors.append(f"{where}: {len(unfinished)} values are blank or placeholders, e.g. {unfinished[:5]}")

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
