#!/usr/bin/env python3
"""
Build ScCompLangPackWaldo language packs from a stock Star Citizen global.ini.

Everything needed to classify a component (type, size, grade, class, missile
tracking signal) is read from the stock file's own item descriptions, so no
game install, Data.p4k or DataForge extraction is required. Items whose
descriptions are missing stats can be filled in via data/component_overrides.csv.

Usage:
    python scripts/build.py --channel LIVE
    python scripts/build.py --channel LIVE --variant remix
    python scripts/build.py --stock path/to/global.ini --out-dir /tmp/out
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

VARIANTS = ("remix", "classic")

# Description "Item Type:" values that get a [Class][Size][Grade] tag.
COMPONENT_TYPES = {
    "Cooler",
    "Power Plant",
    "Shield Generator",
    "Quantum Drive",
    "Radar",
}

CLASS_PREFIX = {
    "Military": "M",
    "Industrial": "I",
    "Civilian": "C",
    "Competition": "R",  # R for Racing, so it doesn't clash with Civilian
    "Stealth": "S",
}

TRACKING_FROM_DESC = {
    "infrared": "IR",
    "infared": "IR",  # CIG typo present in some descriptions
    "electromagnetic": "EM",
    "cross section": "CS",
    "crosssection": "CS",
}

NAME_KEY_RE = re.compile(r"^item_?name", re.IGNORECASE)
ORDNANCE_KEY_RE = re.compile(r"^item_?name_?(G?MISL|BOMB)_", re.IGNORECASE)
KEY_TRACKING_RE = re.compile(r"_(IR|EM|CS)_", re.IGNORECASE)
KEY_SIZE_RE = re.compile(r"_S(\d+)_", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# INI handling
# --------------------------------------------------------------------------- #

@dataclass
class IniFile:
    """A global.ini kept line-for-line so untouched entries are written back byte-identical."""

    lines: list[str]
    index: dict[str, int] = field(default_factory=dict)  # bare key -> line number
    raw_keys: dict[str, str] = field(default_factory=dict)  # bare key -> key as written (may carry ",P")

    @classmethod
    def load(cls, path: Path) -> "IniFile":
        # surrogateescape round-trips any stray non-UTF-8 bytes CIG ships, unchanged.
        # newline="" keeps CIG's line endings (CRLF since 4.10) exactly as shipped.
        with path.open(encoding="utf-8-sig", errors="surrogateescape", newline="") as f:
            text = f.read()
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        ini = cls(lines)
        for i, line in enumerate(lines):
            if "=" not in line:
                continue
            raw_key = line.split("=", 1)[0]
            bare = bare_key(raw_key)
            if bare not in ini.index:
                ini.index[bare] = i
                ini.raw_keys[bare] = raw_key
        return ini

    def get(self, key: str) -> str | None:
        i = self.index.get(key)
        if i is None:
            return None
        return self.lines[i].split("=", 1)[1].rstrip("\r")

    def set(self, key: str, value: str) -> None:
        i = self.index[key]
        cr = "\r" if self.lines[i].endswith("\r") else ""
        self.lines[i] = f"{self.raw_keys[key]}={value}{cr}"

    def keys(self):
        return self.index.keys()

    def changes_since(self, stock: "IniFile", skip: set[str] = frozenset()) -> list[str]:
        """Lines whose value differs from stock, in file order (for tools that merge packs)."""
        return [self.lines[i] for key, i in self.index.items()
                if key not in skip and self.lines[i] != stock.lines[stock.index[key]]]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8-sig", errors="surrogateescape", newline="")


def bare_key(raw_key: str) -> str:
    """Strip the ',P' style flag suffix CIG puts on some keys."""
    return raw_key.split(",", 1)[0].strip()


def load_kv(path: Path) -> dict[str, str]:
    """Load a simple key=value file (comments with # or ;)."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith(("#", ";")) or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v
    return out


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #

@dataclass
class Item:
    key: str
    kind: str  # "component", "missile", "bomb"
    item_type: str = ""
    size: str = ""
    grade: str = ""
    cls: str = ""
    tracking: str = ""  # IR / EM / CS
    source: str = "desc"


def parse_desc(desc: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in desc.split("\\n"):
        if ":" not in part:
            continue
        label, value = part.split(":", 1)
        label = label.strip().lower()
        if label in ("item type", "size", "grade", "class", "tracking signal") and label not in fields:
            fields[label] = value.strip()
    return fields


def core_key(key: str) -> str:
    """Reduce item_Name_X / item_DescX / X_SCItem spellings to a shared lookup core."""
    core = re.sub(r"^item_?(name|desc)_?", "", key, flags=re.IGNORECASE).lower()
    return re.sub(r"_scitem$", "", core)


def find_desc_key(name_key: str, lower_keys: dict[str, str], desc_cores: dict[str, list[str]]) -> str | None:
    candidate = re.sub(r"name", "desc", name_key, count=1, flags=re.IGNORECASE).lower()
    if candidate in lower_keys:
        return lower_keys[candidate]
    # CIG is inconsistent with underscores and the _SCItem suffix between name and description keys.
    matches = desc_cores.get(core_key(name_key), [])
    return matches[0] if matches else None


def load_component_overrides() -> dict[str, dict[str, str]]:
    path = DATA_DIR / "component_overrides.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return {row["key"].strip(): {k: (v or "").strip() for k, v in row.items()} for row in rows}


@dataclass
class Classification:
    items: list[Item] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)  # component-like keys with unreadable stats
    bespoke: list[str] = field(default_factory=list)  # ship-specific parts with no grade (left untagged)


def classify(ini: IniFile) -> Classification:
    lower_keys = {k.lower(): k for k in ini.keys()}
    desc_cores: dict[str, list[str]] = {}
    for k in ini.keys():
        if re.match(r"^item_?desc", k, re.IGNORECASE):
            desc_cores.setdefault(core_key(k), []).append(k)
    overrides = load_component_overrides()
    result = Classification()
    items, unresolved = result.items, result.unresolved

    for key in list(ini.keys()):
        if not NAME_KEY_RE.match(key) or key.lower().endswith(("_short", "_controller")):
            continue

        if key in overrides:
            o = overrides[key]
            if o.get("kind", "component") == "skip":
                continue
            items.append(Item(key=key, kind=o.get("kind") or "component", item_type=o.get("type", ""),
                              size=o.get("size", ""), grade=o.get("grade", "").upper(),
                              cls=o.get("class", ""), tracking=o.get("tracking", "").upper(),
                              source="override"))
            continue

        desc_key = find_desc_key(key, lower_keys, desc_cores)
        fields = parse_desc(ini.get(desc_key) or "") if desc_key else {}
        item_type = fields.get("item type", "")

        ordnance = ORDNANCE_KEY_RE.match(key)
        if ordnance:
            family = ordnance.group(1).upper()
            size = re.sub(r"\D.*", "", fields.get("size", "")) or _key_size(key)
            if family == "BOMB" or "bomb" in item_type.lower():
                items.append(Item(key=key, kind="bomb", item_type="Bomb", size=size))
                continue
            m = KEY_TRACKING_RE.search(key)
            tracking = m.group(1).upper() if m else TRACKING_FROM_DESC.get(
                fields.get("tracking signal", "").lower().replace("  ", " "), "")
            if tracking:
                items.append(Item(key=key, kind="missile", item_type="Missile", size=size, tracking=tracking))
            else:
                unresolved.append(key)
            continue

        if item_type in COMPONENT_TYPES:
            size, grade, cls = fields.get("size", ""), fields.get("grade", "").upper(), fields.get("class", "")
            if size.isdigit() and grade in ("A", "B", "C", "D") and cls in CLASS_PREFIX:
                items.append(Item(key=key, kind="component", item_type=item_type, size=size,
                                  grade=grade, cls=cls))
            elif grade in ("", "BESPOKE", "N/A"):
                # Capital-ship and Vanduul parts: fixed to one ship, no grade worth showing.
                result.bespoke.append(key)
            else:
                unresolved.append(key)
        elif desc_key is None and re.match(r"^item_?name_?(COOL|POWR|SHLD|QDRV|QRDV|RADR)_", key, re.IGNORECASE):
            # Looks like a component by key but has no description to read stats from.
            unresolved.append(key)

    return result


def _key_size(key: str) -> str:
    m = KEY_SIZE_RE.search(key)
    return str(int(m.group(1))) if m else ""


# --------------------------------------------------------------------------- #
# Naming
# --------------------------------------------------------------------------- #

def ordnance_tag(item: Item, variant: str) -> str | None:
    if item.kind == "bomb":
        return f"B{item.size}" if variant == "remix" else None
    return item.tracking if variant == "remix" else f"[{item.tracking}]"


def rename(item: Item, name: str, variant: str) -> str | None:
    """Return the tagged name, or None if this variant doesn't tag this kind of item."""
    if item.kind == "component":
        if variant == "remix":
            tagged = f"{CLASS_PREFIX[item.cls]}{item.size}{item.grade} {name}"
            return None if name.startswith(tagged[: tagged.index(" ") + 1]) else tagged
        suffix = f" {item.cls} {item.grade}"
        return None if name.endswith(suffix) else name + suffix
    tag = ordnance_tag(item, variant)
    if tag is None or name.startswith(tag + " "):
        return None
    return f"{tag} {name}"


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #

BRANDING = {"remix": "ScCompLangPackWaldo", "classic": "ScCompLangPackWaldo Classic"}


def build(stock_path: Path, variant: str) -> tuple[IniFile, dict]:
    ini = IniFile.load(stock_path)
    result = classify(ini)
    lower_keys = {k.lower(): k for k in ini.keys()}
    counts = {"component": 0, "missile": 0, "bomb": 0, "short": 0, "override": 0}
    tagged: dict[str, str] = {}

    for item in result.items:
        keys = [item.key]
        if item.kind != "component":
            # Ordnance short names are what the MFDs show.
            short_key = lower_keys.get(item.key.lower() + "_short")
            if short_key:
                keys.append(short_key)
        for key in keys:
            name = ini.get(key)
            new = rename(item, name, variant) if name else None
            if new is None:
                continue
            ini.set(key, new)
            tagged[key] = new
            counts["short" if key != item.key else item.kind] += 1

    # Hand-written fixes: common first, then per-variant.
    for path in (DATA_DIR / "overrides" / "common.ini", DATA_DIR / "overrides" / f"{variant}.ini"):
        for key, value in load_kv(path).items():
            if key in ini.index:
                ini.set(key, value)
                tagged[key] = value
                counts["override"] += 1

    version_key = "Frontend_PU_Version"
    stock_version = ini.get(version_key)
    if stock_version is not None:
        ini.set(version_key, f"{stock_version} - {BRANDING[variant]}")

    stats = {
        "game_version": stock_version or "",
        "counts": counts,
        "unresolved": sorted(result.unresolved),
        "bespoke": sorted(result.bespoke),
        "tagged": dict(sorted(tagged.items())),
    }
    return ini, stats


CHANGES_FILE = "changes.ini"


def write_changes(ini: IniFile, stock: IniFile, path: Path) -> None:
    """Write only the keys this pack changes, so tools like StarMeld can layer it with other packs."""
    lines = ini.changes_since(stock, skip={"Frontend_PU_Version"})
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig", errors="surrogateescape", newline="")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", default="LIVE", help="Channel folder under stock/ (only LIVE is supported)")
    parser.add_argument("--stock", type=Path, help="Explicit stock global.ini path (overrides --channel input)")
    parser.add_argument("--variant", choices=VARIANTS + ("all",), default="all")
    parser.add_argument("--out-dir", type=Path, help="Output root (default: dist/<channel>)")
    parser.add_argument("--stats-json", type=Path, help="Write build stats to this JSON file")
    args = parser.parse_args()

    channel = args.channel.upper()
    stock = args.stock or REPO_ROOT / "stock" / channel / "global.ini"
    if not stock.exists():
        print(f"ERROR: stock file not found: {stock}", file=sys.stderr)
        return 1
    out_root = args.out_dir or REPO_ROOT / "dist" / channel
    variants = VARIANTS if args.variant == "all" else (args.variant,)

    all_stats = {}
    for variant in variants:
        ini, stats = build(stock, variant)
        out = out_root / variant / "data" / "Localization" / "english" / "global.ini"
        ini.save(out)
        (out_root / variant / "user.cfg").write_bytes((REPO_ROOT / "user.cfg").read_bytes())
        write_changes(ini, IniFile.load(stock), out_root / variant / CHANGES_FILE)
        all_stats[variant] = stats
        c = stats["counts"]
        print(f"[{channel}/{variant}] {stats['game_version']!r}: {c['component']} components, "
              f"{c['missile']} missiles, {c['bomb']} bombs, {c['short']} short names, "
              f"{c['override']} overrides, {len(stats['bespoke'])} bespoke left as-is -> {out}")
        if stats["unresolved"]:
            print(f"  WARNING: {len(stats['unresolved'])} unclassified component-like keys "
                  f"(add them to data/component_overrides.csv):")
            for key in stats["unresolved"]:
                print(f"    {key}")

    if args.stats_json:
        args.stats_json.write_text(json.dumps(all_stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
