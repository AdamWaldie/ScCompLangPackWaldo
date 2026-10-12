#!/usr/bin/env python3
"""
Fetch contract game data and write the compact summary the build uses.

Several public sources, each extracted from the game files every patch, are combined:
  * SCMDB (https://scmdb.net): usually has a new build within a day or two. Career and event
    contracts, keyed by their global.ini keys.
  * StarCitizenWiki's scunpacked-data (extracted with octfx/ScDataDumper): every contract, keyed,
    but often published days or weeks after a patch.
  * FleetYards (https://fleetyards.net), parsed nightly: every contract, but without global.ini keys,
    so its contracts are matched to keys by their exact text in the stock file (text shared by more
    than one key is skipped). Its reputation is used only when a contract pays exactly one, since it
    doesn't say which rewards are the hidden "Affinity" reputation.
Each source can offer its LIVE and its PTU build. PTU is a test build of the coming LIVE patch, so its
contract data usually appears there first: PTU data for the stock file's own patch is used (labelled
as PTU) until LIVE data arrives. Data for a patch newer than the stock file is never used.

The best build wins for every key it has (newest patch, then LIVE over PTU, then newest build, then
SCMDB > scunpacked-data > FleetYards); the others fill the keys it lacks, marked "asof" with their own
patch when that differs. A source that can't be fetched or looks broken is skipped.

Writes data/gamedata/LIVE.json:
    {
      "version": "4.10.2", "build": "12881860", "channel": "LIVE", "format": 4,
      "sources": {"scmdb/LIVE": {"version": ..., "build": ..., "id": ...}, ...},
      "titles":       {"<title key>": {"bp": 3, "total": 4, "rep": [200]}},
      "descriptions": {"<desc key>":  {"bp": 3, "total": 4, "items": ["A", "B", ...], "rep": [200],
                                       "req": [["Sr. Contractor", 5800]], "faction": "Dead Saints",
                                       "scenario": [255], "asof": "4.10.1"}}
      "ui_keys":      ["item_TypeUtilityTurret", ...]
    }
"version"/"build"/"channel" are the best build's. "bp" counts contracts using that key that award
blueprints, "total" all contracts using it, so the build can tell "always awards" from "only some
versions award". "rep" is the distinct reputation amounts a contract pays (hidden "Affinity"
reputation left out), "req" the distinct minimum standings needed to be offered it (entry level left
out), "faction" whose standing that is when every version agrees, and "scenario" the distinct
scenario progress points. Keys with none of these are left out.

"ui_keys" are the global.ini keys the game builds from item data at runtime and shows in its UI
("@item_Type" + item type, "@item_SubType" + subtype, unresolved item port names), from
scunpacked-data's items.json. CIG doesn't always add text for them (4.10.2 shows
"@item_TypeUtilityTurret" on mining ships' turrets), so the build adds the ones the stock file lacks.

Usage:
    python scripts/fetch_gamedata.py                       # fetch every source, update data/gamedata/LIVE.json
    python scripts/fetch_gamedata.py --source-dir <clone>  # use an existing scunpacked-data checkout
    python scripts/fetch_gamedata.py --scmdb-file <json>   # use a downloaded SCMDB merged-*.json
    python scripts/fetch_gamedata.py --no-fleetyards       # skip FleetYards (about 2,000 API calls)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "data" / "gamedata" / "LIVE.json"
STOCK_DIR = REPO_ROOT / "stock" / "LIVE"
SOURCE_REPO = "https://github.com/StarCitizenWiki/scunpacked-data"
SCMDB_DATA = "https://scmdb.net/data"
FLEETYARDS_API = "https://api.fleetyards.net/v1"
USER_AGENT = "ScCompLangPackWaldo (+https://github.com/AdamWaldie/ScCompLangPackWaldo)"
# Bump when the summary gains or changes fields, so the next run rebuilds it from the same data.
FORMAT = 6
# Which source wins between builds of the same patch, channel and build number.
PRIORITY = {"scmdb": 2, "scunpacked": 1, "fleetyards": 0}

SUBJECT_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)[-_ ]?(LIVE|PTU|EPTU|HOTFIX)?[.\-_ ]?(\d{6,9})?", re.IGNORECASE)


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def clone(dest: Path) -> None:
    # Only the contracts folder and the top-level files (items.json) are needed; skip the rest of the
    # (large) dump. A cone-mode sparse checkout always includes the top-level files.
    subprocess.run(["git", "clone", "--quiet", "--depth=1", "--filter=blob:none", "--sparse",
                    SOURCE_REPO, str(dest)], check=True)
    subprocess.run(["git", "sparse-checkout", "set", "--cone", "contracts"], cwd=dest, check=True)


def parse_version(subject: str) -> dict:
    """{"version", "channel" ("LIVE"/"PTU", or "" when the label doesn't say), "build"}, or {}."""
    m = SUBJECT_RE.search(subject)
    if not m:
        return {}
    channel = (m.group(2) or "").upper()
    channel = {"EPTU": "PTU", "HOTFIX": "LIVE"}.get(channel, channel)
    return {"version": m.group(1), "channel": channel, "build": m.group(3) or ""}


def version_tuple(v: str) -> tuple[int, ...]:
    parts = [int(x) for x in re.findall(r"\d+", v or "")]
    return tuple((parts + [0, 0, 0])[:3])


def get_json(url: str, retries: int = 2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError):
            if attempt == retries:
                raise
            time.sleep(2 * (attempt + 1))


class Summary:
    """Per title/description key: blueprint, reputation, standing and scenario information."""

    def __init__(self) -> None:
        def entry() -> dict:
            return {"bp": 0, "total": 0, "items": set(), "rep": set(), "req": set(), "factions": set(),
                    "scenario": set()}
        self.titles: dict[str, dict] = defaultdict(entry)
        self.descs: dict[str, dict] = defaultdict(entry)
        self.awarding = 0
        self.ui_keys: set[str] = set()

    def add(self, title_key: str, desc_key: str, items: list[str], rep: int,
            req: tuple[str, int | None, str] | None, scenario: int, count: int = 1) -> None:
        """One contract (or `count` identical variants of it). req is (standing, reputation it starts
        at, faction); the reputation may be None when the source doesn't state it."""
        items = [i.strip() for i in items if readable(i)]
        awards = bool(items)
        self.awarding += awards * count
        for key, table in ((title_key, self.titles), (desc_key, self.descs)):
            if not key:
                continue
            e = table[key]
            e["total"] += count
            e["bp"] += awards * count
            e["items"].update(items)
            if rep > 0:
                e["rep"].add(rep)
            if req:
                e["req"].add(req[:2])
                e["factions"].add(req[2])
            if scenario > 0:
                e["scenario"].add(int(scenario))

    def result(self) -> tuple[dict, dict]:
        def compact(e: dict, full: bool) -> dict:
            out = {"bp": e["bp"], "total": e["total"]}
            if full and e["bp"]:
                out["items"] = sorted(e["items"])
            if e["rep"]:
                out["rep"] = sorted(e["rep"])
            if full and e["req"]:
                out["req"] = [list(r) for r in sorted(e["req"], key=lambda r: (r[1] or 0, r[0]))]
                if len(e["factions"]) == 1 and readable(next(iter(e["factions"]))):
                    out["faction"] = next(iter(e["factions"]))
            if full and e["scenario"]:
                out["scenario"] = sorted(e["scenario"])
            return out

        def useful(e: dict, full: bool) -> bool:
            return bool(e["bp"] or e["rep"] or (full and (e["req"] or e["scenario"])))

        return ({k: compact(v, False) for k, v in sorted(self.titles.items()) if useful(v, False)},
                {k: compact(v, True) for k, v in sorted(self.descs.items()) if useful(v, True)})


PLACEHOLDER_RE = re.compile(r"PLACEHOLDER|UNINITIALI[SZ]ED|<=|=>|^@|^\[PH\]", re.IGNORECASE)


def readable(name: str | None) -> str:
    """The name, or "" when it is empty or a game-data placeholder (e.g. "<= PLACEHOLDER =>")."""
    name = (name or "").strip()
    return "" if not name or PLACEHOLDER_RE.search(name) else name


def standing(std: dict | None, faction: str) -> tuple[str, int, str] | None:
    """(standing, reputation it starts at, faction) needed to be offered a contract, or None when the
    entry level (Neutral/Applicant, 0 reputation) is enough or the standing has no real name."""
    if not std or not readable(std.get("name")) or (std.get("minReputation") or 0) <= 0:
        return None
    return std["name"].strip(), int(std["minReputation"]), readable(faction)


def candidate(name: str, label: str, ident: str, load) -> dict | None:
    """A build a source offers, from a version label like "4.10.2-live.12881860"."""
    meta = parse_version(label)
    if not meta.get("version") or meta["channel"] not in ("LIVE", "PTU"):
        print(f"note: {name} build {label!r} is not LIVE or PTU; not using it", file=sys.stderr)
        return None
    return {"name": name, "channel": meta["channel"], "version": meta["version"], "build": meta["build"],
            "id": ident, "load": load}


# --- scunpacked-data ---

UI_KEY_RE = re.compile(r"^[A-Za-z_][\w.\-]*$")


def summarise_ui_keys(items_path: Path) -> set[str]:
    """Keys the game looks up for item types, subtypes and item port names (see "ui_keys" above).
    Port names the dumper resolved are plain text; those still "@key" have no text in global.ini.
    Port names written as "@Some text" aren't keys, and "@Placeholder" only marks unused templates."""
    keys: set[str] = set()

    def ports(node) -> None:
        if isinstance(node, dict):
            name = node.get("DisplayName")
            if isinstance(name, str) and name.startswith("@") and UI_KEY_RE.match(name[1:]) \
                    and name[1:].lower() != "placeholder":
                keys.add(name[1:])
            for value in node.values():
                ports(value)
        elif isinstance(node, list):
            for value in node:
                ports(value)

    for item in json.loads(items_path.read_text(encoding="utf-8")):
        for prefix, field in (("item_Type", "type"), ("item_SubType", "subType")):
            value = (item.get(field) or "").strip()
            if value and UI_KEY_RE.match(value):
                keys.add(prefix + value)
        ports((item.get("stdItem") or {}).get("Ports"))
    return keys


def summarise_scunpacked(contracts_dir: Path) -> Summary:
    summary = Summary()
    for path in sorted(contracts_dir.glob("*.json")):
        try:
            c = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if c.get("NotForRelease") or c.get("WorkInProgress"):
            continue
        items = sorted({(e.get("ItemName") or "").strip()
                        for pool in (c.get("Blueprints") or []) for e in (pool.get("PoolContents") or [])})
        # "Affinity" is a hidden per-faction relationship the game doesn't show for contracts.
        rep = max([r.get("Amount") or 0 for r in (c.get("ReputationGained") or [])
                   if r.get("Scope") != "Affinity"], default=0)
        pre = c.get("ReputationPrerequisite") or {}
        std = pre.get("MinStanding") or c.get("MinStanding") or {}
        req = standing({"name": std.get("Name"), "minReputation": std.get("MinReputation")},
                       pre.get("Faction") or (c.get("Faction") or {}).get("Name") or "")
        summary.add(c.get("TitleKey") or "", c.get("DescriptionKey") or "", items, rep, req,
                    c.get("ScenarioProgress") or 0)
    items_path = contracts_dir.parent / "items.json"
    if items_path.exists():
        summary.ui_keys = summarise_ui_keys(items_path)
    else:
        print("note: scunpacked items.json not found; item type names not updated", file=sys.stderr)
    return summary


def fetch_scunpacked(source_dir: Path | None) -> list[dict]:
    """The dump's latest commit, which names its build, e.g. "4.10.1-LIVE.12660092"."""
    src = source_dir
    if src is None:
        src = Path(tempfile.mkdtemp()) / "gamedata"
        clone(src)
    subject = git("log", "-1", "--format=%s", cwd=src).strip()
    meta = parse_version(subject)
    if meta and not meta["channel"]:
        subject += " LIVE"  # older commit subjects name no channel; the dump's default branch is LIVE
    found = candidate("scunpacked", subject, git("rev-parse", "HEAD", cwd=src).strip(),
                      lambda: summarise_scunpacked(src / "contracts"))
    return [found] if found else []


# --- SCMDB ---

def summarise_scmdb(data: dict) -> Summary:
    summary = Summary()
    pools = data.get("blueprintPools") or {}
    rewards = data.get("factionRewardsPools") or []
    scopes = data.get("scopes") or {}
    events = set(data.get("eventScopes") or {})
    factions = data.get("factions") or {}
    for c in (data.get("contracts") or []) + (data.get("legacyContracts") or []):
        items = sorted({(b.get("name") or "").strip()
                        for r in (c.get("blueprintRewards") or [])
                        for b in ((pools.get(r.get("blueprintPool")) or {}).get("blueprints") or [])})
        idx = c.get("factionRewardsIndex")
        pool = rewards[idx] if isinstance(idx, int) and 0 <= idx < len(rewards) else []
        rep = max([r.get("amount") or 0 for r in pool
                   if (scopes.get(r.get("scopeGuid")) or {}).get("scopeName") != "Affinity"], default=0)
        faction = (factions.get(c.get("factionGuid")) or {}).get("name") or c.get("contractorName") or ""
        scenario = max([t.get("count") or 0 for t in (c.get("completionTags") or []) if t.get("tag") in events],
                       default=0)
        summary.add(c.get("titleLocKey") or (c.get("titleKey") or "").lstrip("@"),
                    c.get("descriptionLocKey") or (c.get("descriptionKey") or "").lstrip("@"),
                    items, rep, standing(c.get("minStanding"), faction), scenario,
                    count=len(c.get("contractDefinitionIds") or []) or 1)
    return summary


def fetch_scmdb(scmdb_file: Path | None) -> list[dict]:
    """The newest LIVE and the newest PTU build SCMDB lists."""
    if scmdb_file:
        data = json.loads(scmdb_file.read_text(encoding="utf-8"))
        found = candidate("scmdb", data.get("version") or "", data.get("version") or "", lambda: summarise_scmdb(data))
        return [found] if found else []
    found = {}
    for v in get_json(f"{SCMDB_DATA}/game-versions.json"):
        label, file = v.get("version") or "", v.get("file") or ""
        c = candidate("scmdb", label, label, lambda file=file: summarise_scmdb(get_json(f"{SCMDB_DATA}/{file}")))
        if c and (c["channel"] not in found or _rank(c) > _rank(found[c["channel"]])):
            found[c["channel"]] = c
    return list(found.values())


# --- FleetYards ---

def normalise_text(text: str) -> str:
    """Compare FleetYards text (real line breaks) with global.ini values (literal "\\n" escapes)."""
    return re.sub(r"\s+", " ", (text or "").replace("\\n", "\n")).strip()


def stock_text_index() -> dict[str, str]:
    """Normalised stock text -> its global.ini key, for text only one key has."""
    seen: dict[str, list[str]] = defaultdict(list)
    path = STOCK_DIR / "global.ini"
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep and value.strip():
            seen[normalise_text(value)].append(key.split(",")[0].strip())
    return {text: keys[0] for text, keys in seen.items() if len(keys) == 1}


def summarise_fleetyards(env: str) -> Summary:
    query = "q[released]=true&q[rewardingIn][]=reputation&q[rewardingIn][]=blueprint&perPage=100"
    slugs, page = [], 1
    while True:
        listing = get_json(f"{FLEETYARDS_API}/missions?{query}&source={env}&page={page}")
        slugs += [m["slug"] for m in listing.get("items") or []]
        if page >= ((listing.get("meta") or {}).get("pagination") or {}).get("totalPages", 0):
            break
        page += 1

    def detail(slug: str) -> dict | None:
        try:
            return get_json(f"{FLEETYARDS_API}/missions/{urllib.parse.quote(slug)}?source={env}")
        except (OSError, ValueError):
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        missions = list(pool.map(detail, slugs))
    failed = sum(m is None for m in missions)
    if failed > len(slugs) // 20:
        raise OSError(f"{failed} of {len(slugs)} FleetYards contracts could not be read")

    keys = stock_text_index()
    summary = Summary()
    for m in filter(None, missions):
        title_key = keys.get(normalise_text(m.get("name")), "")
        desc_key = keys.get(normalise_text(m.get("description")), "")
        if not (title_key or desc_key):
            continue
        reps = [r.get("amount") or 0 for r in (m.get("rewards") or [])
                if r.get("kind") == "reputation" and (r.get("amount") or 0) > 0]
        org = (m.get("org") or {}).get("name") or ""
        # The reputation a standing starts at isn't stated; it is filled in from the other sources.
        req = (m["minStanding"], None, readable(org)) if readable(m.get("minStanding")) else None
        summary.add(title_key, desc_key, [b.get("name") or "" for b in (m.get("blueprints") or [])],
                    reps[0] if len(reps) == 1 else 0, req, 0)
    return summary


def fetch_fleetyards(_: object = None) -> list[dict]:
    """Every build FleetYards serves (its `source` parameter picks one, e.g. live or ptu)."""
    found = []
    for s in (get_json(f"{FLEETYARDS_API}/sc-data/sources").get("items") or []):
        env, label = s.get("environment") or "", s.get("version") or ""
        c = candidate("fleetyards", label, label, lambda env=env: summarise_fleetyards(env))
        if c:
            found.append(c)
    return found


# --- merge ---

def _rank(source: dict) -> tuple:
    return (version_tuple(source["version"]), source["channel"] == "LIVE", int(source["build"] or 0),
            PRIORITY[source["name"]])


def label(source: dict) -> str:
    return source["version"] + (" PTU" if source["channel"] == "PTU" else "")


def resolve_standings(descs: dict[str, dict]) -> None:
    """Fill in the reputation a standing starts at where a source didn't state it, from the sources
    that do; standings still unknown, or at entry level, are dropped."""
    known: dict[str, int] = {}
    for info in descs.values():
        for name, rep in info.get("req") or []:
            if rep:
                known.setdefault(name, rep)
    for info in descs.values():
        if not info.get("req") or all(rep for _, rep in info["req"]):
            continue
        req = sorted({(name, rep or known.get(name, 0)) for name, rep in info["req"]}, key=lambda r: (r[1], r[0]))
        req = [list(r) for r in req if r[1] and r[1] > 0 and readable(r[0])]
        if req:
            info["req"] = req
        else:
            info.pop("req")
            info.pop("faction", None)


def stock_version() -> str:
    path = STOCK_DIR / "version.json"
    return json.loads(path.read_text(encoding="utf-8")).get("version", "") if path.exists() else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, help="Existing checkout of scunpacked-data")
    parser.add_argument("--scmdb-file", type=Path, help="Downloaded SCMDB merged-*.json")
    parser.add_argument("--no-fleetyards", action="store_true", help="Skip FleetYards")
    args = parser.parse_args()

    fetchers = [(fetch_scmdb, args.scmdb_file), (fetch_scunpacked, args.source_dir)]
    if not args.no_fleetyards:
        fetchers.append((fetch_fleetyards, None))
    stock = stock_version()
    sources = []
    for fetch, arg in fetchers:
        name = fetch.__name__.removeprefix("fetch_")
        try:
            found = fetch(arg)
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
            print(f"note: {name} unavailable ({e}); not using it", file=sys.stderr)
            continue
        for src in found:
            if stock and version_tuple(src["version"]) > version_tuple(stock):
                print(f"note: {name} {label(src)} is newer than stock {stock}; not using it", file=sys.stderr)
            else:
                sources.append(src)
    if not sources:
        print("ERROR: no game data source available; leaving the current summary unchanged", file=sys.stderr)
        return 1

    def key(src: dict) -> str:
        return f"{src['name']}/{src['channel']}"

    wanted = {key(s): {"version": s["version"], "build": s["build"], "id": s["id"]} for s in sources}
    current = json.loads(OUT.read_text()) if OUT.exists() else {}
    if current.get("format") == FORMAT and current.get("sources") == wanted:
        return 0

    titles: dict[str, dict] = {}
    descs: dict[str, dict] = {}
    ui_keys: set[str] = set()
    used: list[str] = []
    best = None
    for src in sorted(sources, key=_rank, reverse=True):
        try:
            summary = src["load"]()
        except (OSError, ValueError, KeyError) as e:
            print(f"note: {key(src)} could not be read ({e}); not using it", file=sys.stderr)
            continue
        if summary.awarding == 0:
            # Data with no blueprint rewards at all is almost certainly broken.
            print(f"note: {key(src)} has no blueprint rewards; not using it", file=sys.stderr)
            continue
        best = best or src
        same = (src["version"], src["build"], src["channel"]) == (best["version"], best["build"], best["channel"])
        asof = "" if same else label(src)
        ui_keys = ui_keys or summary.ui_keys
        t, d = summary.result()
        for table, new in ((titles, t), (descs, d)):
            # The build matches keys case-insensitively, and the sources don't always agree on case.
            have = {k.lower() for k in table}
            for k, info in new.items():
                if k.lower() not in have:
                    table[k] = {**info, "asof": asof} if asof else info
        used.append(key(src))
    if best is None:
        print("ERROR: game data has no blueprint rewards; refusing to replace the current summary", file=sys.stderr)
        return 1
    resolve_standings(descs)
    if not ui_keys:
        # Only scunpacked-data lists items; keep the last list rather than lose the fixes.
        ui_keys = set(current.get("ui_keys") or [])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "version": best["version"],
        "build": best["build"],
        "channel": best["channel"],
        "format": FORMAT,
        "sources": wanted,
        "titles": dict(sorted(titles.items())),
        "descriptions": dict(sorted(descs.items())),
        "ui_keys": sorted(ui_keys, key=str.lower),
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"version": best["version"], "build": best["build"], "channel": best["channel"],
                      "sources": used, "descriptions": len(descs), "titles": len(titles)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
