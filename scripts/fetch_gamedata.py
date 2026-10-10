#!/usr/bin/env python3
"""
Fetch contract/blueprint game data and write the compact summary the build uses.

Source: a public per-patch dump of Star Citizen game data (contracts/*.json). Each contract
names the global.ini keys of its title and description (TitleKey / DescriptionKey) and lists
the blueprint reward pools it can pay out. The dump's commit message names the exact patch,
e.g. "4.10.1-LIVE.12660092".

Writes data/gamedata/LIVE.json:
    {
      "version": "4.10.1", "build": "12660092", "source_sha": "...",
      "titles":       {"<title key>": {"bp": 3, "total": 4}},
      "descriptions": {"<desc key>":  {"bp": 3, "total": 4, "items": ["A", "B", ...]}}
    }
"bp" counts contracts using that key that award blueprints, "total" all contracts using it, so
the build can tell "always awards" from "only some versions award".

The build only uses this file when its version matches the stock file, so blueprint lists are
never shown for the wrong patch.

Usage:
    python scripts/fetch_gamedata.py                       # clone the source, update data/gamedata/LIVE.json
    python scripts/fetch_gamedata.py --source-dir <clone>  # use an existing checkout
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "data" / "gamedata" / "LIVE.json"
SOURCE_REPO = "https://github.com/StarCitizenWiki/scunpacked-data"

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


def summarise(contracts_dir: Path) -> tuple[dict, dict, int]:
    titles: dict[str, dict] = defaultdict(lambda: {"bp": 0, "total": 0})
    descs: dict[str, dict] = defaultdict(lambda: {"bp": 0, "total": 0, "items": set()})
    awarding = 0
    for path in sorted(contracts_dir.glob("*.json")):
        try:
            c = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if c.get("NotForRelease") or c.get("WorkInProgress"):
            continue
        items = sorted({(e.get("ItemName") or "").strip()
                        for pool in (c.get("Blueprints") or []) for e in (pool.get("PoolContents") or [])}
                       - {""})
        items = [i for i in items if not i.startswith("@") and "PLACEHOLDER" not in i]
        awards = bool(items)
        awarding += awards
        if c.get("TitleKey"):
            t = titles[c["TitleKey"]]
            t["total"] += 1
            t["bp"] += awards
        if c.get("DescriptionKey"):
            d = descs[c["DescriptionKey"]]
            d["total"] += 1
            d["bp"] += awards
            d["items"].update(items)
    titles_out = {k: v for k, v in sorted(titles.items()) if v["bp"]}
    descs_out = {k: {"bp": v["bp"], "total": v["total"], "items": sorted(v["items"])}
                 for k, v in sorted(descs.items()) if v["bp"]}
    return titles_out, descs_out, awarding


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, help="Existing checkout of the game-data repo")
    args = parser.parse_args()

    src = args.source_dir
    if src is None:
        src = Path(tempfile.mkdtemp()) / "gamedata"
        clone(src)

    subject = git("log", "-1", "--format=%s", cwd=src).strip()
    sha = git("rev-parse", "HEAD", cwd=src).strip()
    meta = parse_version(subject)
    if not meta.get("version") or meta.get("channel") not in ("", "LIVE"):
        print(f"note: game data is not a LIVE build ({subject!r}); leaving {OUT.name} unchanged", file=sys.stderr)
        return 0

    current = json.loads(OUT.read_text()) if OUT.exists() else {}
    if current.get("source_sha") == sha:
        return 0

    titles, descs, awarding = summarise(src / "contracts")
    if awarding == 0:
        # A dump with no blueprint rewards at all is almost certainly broken; keep the last good data.
        print("ERROR: game data has no blueprint rewards; refusing to replace the current summary", file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "version": meta["version"],
        "build": meta["build"],
        "source_sha": sha,
        "contracts_awarding": awarding,
        "titles": titles,
        "descriptions": descs,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"version": meta["version"], "build": meta["build"], "contracts_awarding": awarding,
                      "descriptions": len(descs), "titles": len(titles)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
