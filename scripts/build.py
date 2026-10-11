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
    "Computer",
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
    # Component-like keys with no description at all (usually a CIG typo in the key). Nothing to read
    # stats from, so the stock name is kept; reported for information, never blocks a release.
    no_description: list[str] = field(default_factory=list)


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
        elif desc_key is None and re.match(r"^item_?name_?(COOL|POWR|SHLD|QDRV|QRDV|RADR|COMP)_", key, re.IGNORECASE):
            result.no_description.append(key)

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

    counts["cig_fix"] = fix_literal_at_values(ini, tagged)
    text_fixed: set[str] = set()
    counts["stock_text"], left_blank = fix_stock_text(ini, tagged, text_fixed)

    gamedata, gamedata_status, asof = load_matching_gamedata(stock_path)
    counts["contract_title"], counts["contract_desc"] = (apply_contract_info(ini, gamedata, tagged, asof)
                                                         if gamedata else (0, 0))

    version_key = "Frontend_PU_Version"
    stock_version = ini.get(version_key)
    if stock_version is not None:
        ini.set(version_key, f"{stock_version} - {BRANDING[variant]}")

    stats = {
        "game_version": stock_version or "",
        "counts": counts,
        "unresolved": sorted(result.unresolved),
        "bespoke": sorted(result.bespoke),
        "no_description": sorted(result.no_description),
        "left_blank": left_blank,
        "text_fixed": sorted(text_fixed),
        "tagged": dict(sorted(tagged.items())),
        "gamedata": gamedata_status,
    }
    return ini, stats


# --------------------------------------------------------------------------- #
# Game-data layers: CIG text fixes and blueprint rewards
# --------------------------------------------------------------------------- #

LITERAL_AT_RE = re.compile(r"^@([A-Za-z0-9].*\s.*)$")
KEY_REF_RE = re.compile(r"^@([A-Za-z_][\w.\-]*)$")


def readable_key_name(key: str) -> str:
    """'item_NameClothingCabinet' -> 'Clothing Cabinet', 'item_NameSCAR' -> 'SCAR'."""
    name = re.sub(r"^item_?(name|desc)_?", "", key, flags=re.IGNORECASE)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    return re.sub(r"[_\s]+", " ", name).strip() or key


def fix_literal_at_values(ini: IniFile, tagged: dict[str, str]) -> int:
    """CIG sometimes writes plain text as '@Navigation light', which the game shows with the '@'.
    Drop the '@' when what follows is readable text (has a space) rather than a key reference.
    A key reference to a key that doesn't exist ('@mp_eFlashlightNova') would also show raw, so it
    becomes a readable name made from the referring key ('Clothing Cabinet')."""
    fixed = 0
    lower = {k.lower() for k in ini.index}
    for key in list(ini.keys()):
        value = (ini.get(key) or "").strip()
        m = LITERAL_AT_RE.match(value)
        new = None
        if m and m.group(1) not in ini.index:
            new = m.group(1)
        else:
            ref = KEY_REF_RE.match(value)
            if ref and ref.group(1).lower() not in lower:
                new = readable_key_name(key)
        if new:
            ini.set(key, new)
            tagged[key] = new
            fixed += 1
    return fixed


PH_PREFIX_RE = re.compile(r"^\s*\[PH\]\s*", re.IGNORECASE)
PH_ANYWHERE_RE = re.compile(r"[ \t]*\[PH\][ \t]*", re.IGNORECASE)
PLACEHOLDER_PREFIX_RE = re.compile(r"^\s*(?:<\s*)?placeholder\s*(?:>\s*)?(?:[-:]\s*)?", re.IGNORECASE)
IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+$")
# Identifier-looking text that is meant to look that way: chat emote commands players type, in-fiction
# usernames, e-mail handles and file names, and developer-only beacons.
KEEP_IDENTIFIER_KEY_RE = re.compile(
    r"^(chat_emote_|datapad_|ea_ui_player_|FW2022_|FW22_|MissionManager_|QT_Beacon|PBay_|BBT_|storm_datafac)",
    re.IGNORECASE)
ITEM_NAME_KEY_RE = re.compile(r"^item_?name", re.IGNORECASE)
ITEM_DESC_KEY_RE = re.compile(r"^item_?desc", re.IGNORECASE)


def humanise(text: str, codes: bool = False) -> str:
    """'Armor_Shop' -> 'Armor Shop'; with codes=True a key like 'dmc_frontier_gloves_01_02_11'
    -> 'DMC Frontier Gloves' (bare numbers dropped, a short leading maker code upper-cased)."""
    if codes:
        text = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    words = [w for w in re.split(r"[_\s]+", text) if w]
    if codes:
        words = [w for w in words if not re.fullmatch(r"\d+\w{0,8}", w)] or words
    out = []
    for i, w in enumerate(words):
        if codes and i == 0 and w.islower() and len(w) <= 4 and len(words) > 1:
            out.append(w.upper())
        else:
            out.append(w[:1].upper() + w[1:] if w.islower() else w)
    return " ".join(out)


def is_placeholder(value: str) -> bool:
    return bool(PH_PREFIX_RE.match(value) or PLACEHOLDER_PREFIX_RE.match(value))


def fix_stock_text(ini: IniFile, tagged: dict[str, str], text_fixed: set[str]) -> tuple[int, list[str]]:
    """Text CIG left unfinished, which players would see as-is. Applied every build, so new strings
    of the same kinds are covered automatically:
      * item names that are blank or placeholders get a readable name from the remaining text or the
        key ('PLACEHOLDER - dmc_frontier_gloves_01_02_11' -> 'DMC Frontier Gloves');
      * item descriptions that are blank or placeholders keep any real text after the placeholder,
        otherwise get the item's name;
      * a '[PH]' marker anywhere in any text is dropped;
      * labels written as identifiers ('Armor_Shop') get spaces, except where that is intended.
    Other blank values (ship screen slots, engine sentinels like LOC_EMPTY) are deliberate and kept.
    Returns (values fixed, item descriptions still blank)."""
    fixed = 0
    lower = {k.lower(): k for k in ini.keys()}

    def put(key: str, value: str) -> None:
        nonlocal fixed
        if value and value != ini.get(key):
            ini.set(key, value)
            tagged[key] = value
            text_fixed.add(key)
            fixed += 1

    def readable_name(key: str, value: str) -> str:
        rest = PLACEHOLDER_PREFIX_RE.sub("", PH_PREFIX_RE.sub("", value)).strip()
        if rest and not IDENTIFIER_RE.match(rest):
            return rest
        return humanise(rest or re.sub(r"^item_?name_?", "", key, flags=re.IGNORECASE), codes=True)

    for key in list(ini.keys()):
        value = ini.get(key) or ""
        if ITEM_NAME_KEY_RE.match(key) and re.sub(r"^item_?name", "", key, flags=re.IGNORECASE).strip("_"):
            if not value.strip() or is_placeholder(value):
                put(key, readable_name(key, value))
                continue
        if ITEM_DESC_KEY_RE.match(key) and (not value.strip() or is_placeholder(value)):
            continue  # descriptions are handled below, once every name is fixed
        new = value
        if PH_ANYWHERE_RE.search(value):
            new = PH_ANYWHERE_RE.sub(" ", value)
            new = re.sub(r"(?<=>) +| +(?=<)", "", new)  # no stray space inside markup like <span> Hey</span>
            new = re.sub(r"\s+(Name|Desc|Description)$", "", re.sub(r" {2,}", " ", new).strip())
        if IDENTIFIER_RE.match(new.strip()) and not KEEP_IDENTIFIER_KEY_RE.match(key) \
                and new.strip().lower() not in lower:
            new = humanise(new.strip())
        put(key, new)

    left_blank = []
    for key in list(ini.keys()):
        value = ini.get(key) or ""
        if not ITEM_DESC_KEY_RE.match(key) or not (not value.strip() or is_placeholder(value)):
            continue
        # Keep real text after the placeholder line, e.g. 'Placeholder - CBD Jacket Desc\n\nCarrying ...'.
        lines = value.split("\\n")
        rest = "\\n".join(lines[1:]).strip("\\n ").replace("\\n\\n\\n", "\\n\\n") if is_placeholder(value) else ""
        if not rest:
            name_key = lower.get(re.sub(r"desc", "name", key, count=1, flags=re.IGNORECASE).lower())
            rest = (ini.get(name_key) or "").strip() if name_key else ""
        if not rest or is_placeholder(rest):
            rest = humanise(re.sub(r"^item_?desc_?", "", key, flags=re.IGNORECASE), codes=True)
        if rest:
            put(key, rest)
        else:
            left_blank.append(key)
    return fixed, sorted(left_blank)


def _version_tuple(v: str) -> tuple[int, ...]:
    parts = [int(x) for x in re.findall(r"\d+", v or "")]
    return tuple((parts + [0, 0, 0])[:3])


def gamedata_match(gd: dict, meta: dict) -> str:
    """'matched' (same patch, and same build when both are known), 'newer' or 'older' than the stock file.
    PTU data is never 'matched': it stands in for the patch's LIVE data until that arrives."""
    gd_version, stock_version = _version_tuple(gd.get("version", "")), _version_tuple(meta.get("version", ""))
    builds_known = gd.get("build") and meta.get("build")
    if (gd_version == stock_version and gd.get("channel", "LIVE") != "PTU"
            and not (builds_known and gd["build"] != meta["build"])):
        return "matched"
    return "newer" if gd_version > stock_version else "older"


def load_matching_gamedata(stock_path: Path) -> tuple[dict | None, str, str]:
    """Game data for the stock file's patch, or failing that older or PTU data: blueprint pools
    rarely change between patches, so it is used and labelled 'as of <version>' (or '<version> PTU').
    Returns (game data, status, as-of version or '' when it matches)."""
    gd_path = DATA_DIR / "gamedata" / f"{stock_path.parent.name}.json"
    meta_path = stock_path.parent / "version.json"
    if not gd_path.exists() or not meta_path.exists():
        return None, "no game data", ""
    gd = json.loads(gd_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    match = gamedata_match(gd, meta)
    if match == "matched":
        return gd, f"matched {gd.get('version')}" + (f" build {gd['build']}" if gd.get("build") else ""), ""
    if match == "newer":
        return None, f"game data is newer ({gd.get('version')}) than stock {meta.get('version')}", ""
    asof = gd.get("version", "")
    if gd.get("channel") == "PTU":
        asof += " PTU"
    elif _version_tuple(asof) == _version_tuple(meta.get("version", "")) and gd.get("build"):
        asof += f" build {gd['build']}"
    return gd, f"as of {asof}; stock is {meta.get('version')}", asof


BP_TITLE = "[BP] "
BP_TITLE_SOME = "[BP]* "
BP_HEADER = "Blueprints this contract can award"
BP_HEADER_SOME = "Blueprints (only some versions of this contract award these"
REP_LABEL = "Reputation awarded"
REQ_LABEL = "Requires"
SCENARIO_LABEL = "Scenario progress"
VARIES = " (depends on the version offered)"


def bp_header(some: bool, asof: str = "") -> str:
    if some:
        return BP_HEADER_SOME + (f", as of {asof}" if asof else "") + "):"
    return BP_HEADER + (f" (as of {asof})" if asof else "") + ":"


def rep_tag(amounts: list[int]) -> str:
    """Title suffix: " [200 Rep]", " [200/400/800 Rep]", or a range when a key covers many versions."""
    if len(amounts) > 3:
        return f" [{amounts[0]}-{amounts[-1]} Rep]"
    return " [" + "/".join(str(a) for a in amounts) + " Rep]"


def contract_info_lines(info: dict, asof: str = "") -> list[str]:
    """Reputation, standing and scenario lines for a description. The first label says which patch
    the numbers are from when the game data is older than the stock file."""
    lines = []
    if info.get("rep"):
        rep = info["rep"]
        lines.append([REP_LABEL, " / ".join(f"{a:,}" for a in rep) + (VARIES if len(rep) > 1 else "")])
    if info.get("req"):
        req = info["req"]
        text = " / ".join(name for name, _ in req) + " standing"
        if info.get("faction"):
            text += f" with {info['faction']}"
        lines.append([REQ_LABEL, text + (VARIES if len(req) > 1 else "")])
    if info.get("scenario"):
        pts = info["scenario"]
        lines.append([SCENARIO_LABEL, " / ".join(f"{p:,}" for p in pts) + " points"
                      + (VARIES if len(pts) > 1 else "")])
    if lines and asof:
        lines[0][0] += f" (as of {asof})"
    return [f"{label}: {text}" for label, text in lines]


def apply_contract_info(ini: IniFile, gamedata: dict, tagged: dict[str, str], asof: str = "") -> tuple[int, int]:
    """Mark contract titles with blueprint rewards ([BP] prefix) and reputation ([200 Rep] suffix), and
    add reputation, required standing, scenario progress and possible blueprints to descriptions.
    With older game data (or an entry only an older source has) the description says which patch
    the information is from."""
    lower = {k.lower(): k for k in ini.keys()}
    titles = descs = 0
    for key, info in gamedata.get("titles", {}).items():
        real = lower.get(key.lower())
        value = ini.get(real) if real else None
        if not value:
            continue
        new = value
        if info.get("bp") and not new.startswith(("[BP]", "[BP]*")):
            new = (BP_TITLE if info["bp"] >= info["total"] else BP_TITLE_SOME) + new
        if info.get("rep") and not new.endswith(" Rep]"):
            new = new.rstrip() + rep_tag(info["rep"])
        if new != value:
            ini.set(real, new)
            tagged[real] = new
            titles += 1
    for key, info in gamedata.get("descriptions", {}).items():
        real = lower.get(key.lower())
        value = ini.get(real) if real else None
        if not value:
            continue
        # Values use literal "\n" escapes, like the rest of global.ini.
        new = value.rstrip()
        # Keys only the older source has carry their own patch.
        entry_asof = info.get("asof") or asof
        lines = contract_info_lines(info, entry_asof)
        if lines and not any(f"\\n\\n{label}" in new for label in (REP_LABEL, REQ_LABEL, SCENARIO_LABEL)):
            new += "\\n\\n" + "\\n".join(lines)
        items = info.get("items") or []
        if items and BP_HEADER not in new and BP_HEADER_SOME not in new:
            header = bp_header(info["bp"] < info["total"], entry_asof)
            new += "\\n\\n" + header + "".join("\\n- " + i for i in items)
        if new != value.rstrip():
            ini.set(real, new)
            tagged[real] = new
            descs += 1
    return titles, descs


CHANGES_FILE = "changes.ini"


def write_changes(ini: IniFile, stock: IniFile, path: Path) -> None:
    """Write only the keys this pack changes, so merge tools can layer it with other packs."""
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
              f"{c['override']} overrides, {c['cig_fix'] + c['stock_text']} CIG text fixes, "
              f"{c['contract_title']}/{c['contract_desc']} contract titles/descriptions ({stats['gamedata']}), "
              f"{len(stats['bespoke'])} bespoke left as-is -> {out}")
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
