#!/usr/bin/env python3
"""
Fetch contract game data and write the compact summary the build uses.

Two public sources, both extracted from the game files each patch:
  * SCMDB (https://scmdb.net): usually has the current LIVE build
    within a day or two of a patch. It lists the contractor career and event contracts.
  * StarCitizenWiki's scunpacked-data (extracted with octfx/ScDataDumper): every contract, but often
    published days or weeks after a patch.
The newer source wins for every key it has; the other fills the keys it lacks, marked "asof" with
its own patch when that is older. If one source can't be fetched the other is used alone.

Writes data/gamedata/LIVE.json:
    {
      "version": "4.10.2", "build": "12881860", "format": 3,
      "sources": {"scmdb": {"version": ..., "build": ..., "id": ...}, "scunpacked": {...}},
      "titles":       {"<title key>": {"bp": 3, "total": 4, "rep": [200]}},
      "descriptions": {"<desc key>":  {"bp": 3, "total": 4, "items": ["A", "B", ...], "rep": [200],
                                       "req": [["Sr. Contractor", 5800]], "faction": "Dead Saints",
                                       "scenario": [255], "asof": "4.10.1"}}
    }
"version"/"build" are the newest source's. "bp" counts contracts using that key that award
blueprints, "total" all contracts using it, so the build can tell "always awards" from "only some
versions award". "rep" is the distinct reputation amounts a contract pays (hidden "Affinity"
reputation left out), "req" the distinct minimum standings needed to be offered it (entry level left
out), "faction" whose standing that is when every version agrees, and "scenario" the distinct
scenario progress points. Keys with none of these are left out.

The build only uses this file when its version is not newer than the stock file, and labels older
information "as of <patch>".

Usage:
    python scripts/fetch_gamedata.py                       # fetch both sources, update data/gamedata/LIVE.json
    python scripts/fetch_gamedata.py --source-dir <clone>  # use an existing scunpacked-data checkout
    python scripts/fetch_gamedata.py --scmdb-file <json>   # use a downloaded SCMDB merged-*.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "data" / "gamedata" / "LIVE.json"
SOURCE_REPO = "https://github.com/StarCitizenWiki/scunpacked-data"
SCMDB_DATA = "https://scmdb.net/data"
USER_AGENT = "ScCompLangPackWaldo (+https://github.com/AdamWaldie/ScCompLangPackWaldo)"
# Bump when the summary gains or changes fields, so the next run rebuilds it from the same data.
FORMAT = 3

SUBJECT_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)[-_ ]?(LIVE|PTU|EPTU|HOTFIX)?[.\-_ ]?(\d{6,9})?", re.IGNORECASE)


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def clone(dest: Path) -> None:
    # Only the contracts folder is needed; skip the rest of the (large) dump.
    subprocess.run(["git", "clone", "--quiet", "--depth=1", "--filter=blob:none", "--sparse",
                    SOURCE_REPO, str(dest)], check=True)
    subprocess.run(["git", "sparse-checkout", "set", "contracts"], cwd=dest, check=True)


def parse_version(subject: str) -> dict:
    m = SUBJECT_RE.search(subject)
    if not m:
        return {}
    return {"version": m.group(1), "channel": (m.group(2) or "").upper(), "build": m.group(3) or ""}


class Summary:
    """Per title/description key: blueprint, reputation, standing and scenario information."""

    def __init__(self) -> None:
        def entry() -> dict:
            return {"bp": 0, "total": 0, "items": set(), "rep": set(), "req": set(), "factions": set(),
                    "scenario": set()}
        self.titles: dict[str, dict] = defaultdict(entry)
        self.descs: dict[str, dict] = defaultdict(entry)
        self.awarding = 0

    def add(self, title_key: str, desc_key: str, items: list[str], rep: int,
            req: tuple[str, int, str] | None, scenario: int, count: int = 1) -> None:
        """One contract (or `count` identical variants of it). req is (standing, reputation, faction)."""
        items = [i for i in items if i and not i.startswith("@") and "PLACEHOLDER" not in i]
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
                out["req"] = [list(r) for r in sorted(e["req"], key=lambda r: (r[1], r[0]))]
                if len(e["factions"]) == 1 and next(iter(e["factions"])):
                    out["faction"] = next(iter(e["factions"]))
            if full and e["scenario"]:
                out["scenario"] = sorted(e["scenario"])
            return out

        def useful(e: dict, full: bool) -> bool:
            return bool(e["bp"] or e["rep"] or (full and (e["req"] or e["scenario"])))

        return ({k: compact(v, False) for k, v in sorted(self.titles.items()) if useful(v, False)},
                {k: compact(v, True) for k, v in sorted(self.descs.items()) if useful(v, True)})


def standing(std: dict | None, faction: str) -> tuple[str, int, str] | None:
    """(standing, reputation it starts at, faction) needed to be offered a contract, or None when the
    entry level (Neutral/Applicant, 0 reputation) is enough."""
    if not std or not std.get("name") or not std.get("minReputation"):
        return None
    return std["name"], int(std["minReputation"]), faction


# --- scunpacked-data ---

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
    return summary


def fetch_scunpacked(source_dir: Path | None) -> dict | None:
    src = source_dir
    if src is None:
        src = Path(tempfile.mkdtemp()) / "gamedata"
        clone(src)
    subject = git("log", "-1", "--format=%s", cwd=src).strip()
    meta = parse_version(subject)
    if not meta.get("version") or meta.get("channel") not in ("", "LIVE"):
        print(f"note: scunpacked-data is not a LIVE build ({subject!r}); not using it", file=sys.stderr)
        return None
    return {"name": "scunpacked", "version": meta["version"], "build": meta["build"],
            "id": git("rev-parse", "HEAD", cwd=src).strip(), "load": lambda: summarise_scunpacked(src / "contracts")}


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


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_scmdb(scmdb_file: Path | None) -> dict | None:
    try:
        if scmdb_file:
            data = json.loads(scmdb_file.read_text(encoding="utf-8"))
            name = scmdb_file.name
        else:
            versions = get_json(f"{SCMDB_DATA}/game-versions.json")
            live = [v for v in versions if "-live." in (v.get("version") or "").lower()]
            if not live:
                print("note: SCMDB lists no LIVE build; not using it", file=sys.stderr)
                return None
            name = live[0]["file"]
            data = None
    except (OSError, ValueError, KeyError) as e:
        print(f"note: SCMDB unavailable ({e}); not using it", file=sys.stderr)
        return None
    if data is not None:
        label = data.get("version") or ""
    else:
        label = live[0]["version"]
    meta = parse_version(label)
    if not meta.get("version") or meta.get("channel") not in ("", "LIVE"):
        print(f"note: SCMDB data is not a LIVE build ({label!r}); not using it", file=sys.stderr)
        return None

    def load() -> Summary:
        return summarise_scmdb(data if data is not None else get_json(f"{SCMDB_DATA}/{name}"))
    return {"name": "scmdb", "version": meta["version"], "build": meta["build"], "id": label, "load": load}


# --- merge ---

def _version_key(source: dict) -> tuple:
    return (tuple(int(p) for p in source["version"].split(".")), int(source["build"] or 0),
            source["name"] == "scmdb")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, help="Existing checkout of scunpacked-data")
    parser.add_argument("--scmdb-file", type=Path, help="Downloaded SCMDB merged-*.json")
    args = parser.parse_args()

    sources = []
    for fetch, arg in ((fetch_scmdb, args.scmdb_file), (fetch_scunpacked, args.source_dir)):
        try:
            src = fetch(arg)
        except (OSError, subprocess.CalledProcessError) as e:
            print(f"note: {fetch.__name__[6:]} unavailable ({e}); not using it", file=sys.stderr)
            src = None
        if src:
            sources.append(src)
    if not sources:
        print("ERROR: no game data source available; leaving the current summary unchanged", file=sys.stderr)
        return 1

    current = json.loads(OUT.read_text()) if OUT.exists() else {}
    wanted = {s["name"]: {"version": s["version"], "build": s["build"], "id": s["id"]} for s in sources}
    if current.get("format") == FORMAT and current.get("sources") == wanted:
        return 0

    titles: dict[str, dict] = {}
    descs: dict[str, dict] = {}
    used = {}
    sources.sort(key=_version_key, reverse=True)
    newest = sources[0]  # the newest source that turns out usable
    for src in sources:
        try:
            summary = src["load"]()
        except (OSError, ValueError) as e:
            print(f"note: {src['name']} could not be read ({e}); not using it", file=sys.stderr)
            continue
        if summary.awarding == 0:
            # A dump with no blueprint rewards at all is almost certainly broken.
            print(f"note: {src['name']} has no blueprint rewards; not using it", file=sys.stderr)
            continue
        if not used:
            newest = src
        asof = "" if (src["version"], src["build"]) == (newest["version"], newest["build"]) else src["version"]
        t, d = summary.result()
        for table, new in ((titles, t), (descs, d)):
            # The build matches keys case-insensitively, and the sources don't always agree on case.
            have = {k.lower() for k in table}
            for key, info in new.items():
                if key.lower() not in have:
                    table[key] = {**info, "asof": asof} if asof else info
        used[src["name"]] = wanted[src["name"]]
    if not used:
        print("ERROR: game data has no blueprint rewards; refusing to replace the current summary", file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "version": newest["version"],
        "build": newest["build"],
        "format": FORMAT,
        "sources": wanted,
        "titles": dict(sorted(titles.items())),
        "descriptions": dict(sorted(descs.items())),
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"version": newest["version"], "build": newest["build"], "sources": list(used),
                      "descriptions": len(descs), "titles": len(titles)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
