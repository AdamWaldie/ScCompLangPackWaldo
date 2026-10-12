# ScCompLangPackWaldo

![GitHub release (latest by date)](https://img.shields.io/github/v/release/AdamWaldie/ScCompLangPackWaldo)

A Star Citizen language pack that puts ship component stats in the item name, so you can see
whether a component is worth looting the moment you scan it. It is rebuilt and released for
every LIVE patch, automatically.

> [!TIP]
> **Want component tags *and* another pack's mission text?** Use the **[Pack Merger](https://adamwaldie.github.io/ScCompLangPackWaldo/)**:
> pick a preset (or a source per category) and download one combined `global.ini`. It runs in your browser and always
> merges onto the latest LIVE stock file.

## Two formats

| | Remix (default) | Classic |
|---|---|---|
| Components | `M2A XL-1` | `XL-1 Military A` |
| Missiles / torpedoes | `EM Dominator II Missile` | `[EM] Dominator II Missile` |
| Bombs | `B5 Stormburst Bomb` | `Stormburst Bomb` |
| MFD short names | `EM Dmntr II` | `[EM] Dmntr II` |

**Remix tag format:** `[Class][Size][Grade]`

| Class | | Grade | |
|---|---|---|---|
| **M** | Military | **A** | Best |
| **I** | Industrial | **B** | Good |
| **C** | Civilian | **C** | Average |
| **R** | Racing (in-game "Competition") | **D** | Basic |
| **S** | Stealth | | |

The tags cover coolers, power plants, shield generators, quantum drives, radars and computers.
Missiles and torpedoes are tagged with their tracking signal: **IR** (infrared), **EM**
(electromagnetic) or **CS** (cross-section).

Capital-ship and Vanduul parts that have no grade, such as the Idris and 890J internals, keep their stock names.

## Contracts: rewards and requirements

Both formats also annotate contracts, generated each patch from the game's own contract data:

- **Title:** `[BP] Defend InterSec Operative [200 Rep]`. `[BP]` marks contracts that can award blueprints
  (`[BP]*` when only some versions of a shared contract award), and the suffix is the reputation it pays
  (`[200/400/800 Rep]` when one title covers several difficulties).
- **Description:** ends with the details, e.g.

  ```
  Reputation awarded: 200
  Requires: Sr. Contractor standing with Dead Saints
  Scenario progress: 255 points

  Blueprints this contract can award:
  - Pulse "Rouge" Pistol
  ```

The game data is the [StarCitizenWiki's scunpacked-data](https://github.com/StarCitizenWiki/scunpacked-data),
extracted with [ScDataDumper](https://github.com/octfx/ScDataDumper). It is usually published some days after a
patch, so until then the details come from the previous patch and say so: `Reputation awarded (as of 4.10.1): 200`.
As soon as the current patch's data is published, a new release ("blueprint update") goes out automatically with it.

## Install

1. Download the zip for your format from the [Releases page](https://github.com/AdamWaldie/ScCompLangPackWaldo/releases):
   - `ScCompLangPackWaldo-<version>-LIVE.zip`: Remix format
   - `ScCompLangPackWaldo-Classic-<version>-LIVE.zip`: Classic format
2. Extract it and copy the `data` folder and `user.cfg` into your game folder, e.g.
   `C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\`.
   If you already have a `user.cfg`, add the line `g_language = english` to it instead of overwriting it.
3. Launch the game. The main menu version text ends with `ScCompLangPackWaldo`.

### Auto-update URLs

**Zips with fixed names**, for installers and auto-updaters. These always hold the newest build:

```
https://github.com/AdamWaldie/ScCompLangPackWaldo/releases/download/latest/ScCompLangPackWaldo-LIVE.zip
https://github.com/AdamWaldie/ScCompLangPackWaldo/releases/download/latest/ScCompLangPackWaldo-Classic-LIVE.zip
```

**The raw `global.ini`**, for tools such as the [SC Launch Configurator](https://www.luftwerft.com/?lang=en):

```
https://raw.githubusercontent.com/AdamWaldie/ScCompLangPackWaldo/main/dist/LIVE/remix/data/Localization/english/global.ini
https://raw.githubusercontent.com/AdamWaldie/ScCompLangPackWaldo/main/dist/LIVE/classic/data/Localization/english/global.ini
```

### Combining with other packs

Each build also publishes a `changes.ini` that contains only the lines this pack changes, at
`dist/<CHANNEL>/<remix|classic>/changes.ini` and as a release asset. Load it into a merging tool such as
the [Pack Merger](https://adamwaldie.github.io/ScCompLangPackWaldo/) to use the component tags alongside another pack's
mission and contract text.

## How it stays up to date

It's fully automatic and runs entirely on GitHub. Nobody's PC is involved.

```
 every 2 hours (GitHub Actions: Auto-update)
 ───────────────────────────────────────────────────────────────────────────────
 fetch newest stock LIVE global.ini ─▶ build ─▶ validate ─┬─ pass ─▶ commit to main ─▶ release + zips
 (public community localization repo)                      └─ fail ─▶ open an issue, release nothing
```

- **Remote stock source.** A public community localization repository (set in `scripts/fetch_stock.py`)
  publishes the English `global.ini` imported from the game files, usually on patch day. The version and
  build are read from its commit messages. `scripts/fetch_stock.py` only accepts a file that is newer than ours,
  is complete, and still carries component stats. Their 4.8.0 file was checked against an extraction from
  `Data.p4k`, and every value was identical.
- **No game-data extraction needed.** Every component's description in the stock `global.ini` already
  lists its type, size, grade and class (`Item Type: Cooler\nSize: 2\nGrade: A\nClass: Military`),
  and missile descriptions list their tracking signal. `scripts/build.py` reads these. That means no Wine,
  no `unforge.exe`, no 5 GB DataForge dump, and the tags always match what the game shows in the item description.
- **New items are tagged automatically.** The build scans every item in the new stock file, so a new
  component is tagged the first time it appears. Nothing has to be added by hand.
- **Validation gates every release.** It checks that the output has the same keys in the same order as stock
  (plus the missing names below, added at the end), that it has a UTF-8 BOM, that only intended keys changed,
  that tags are well-formed, and that every component was classified. If anything fails, nothing is released and an `auto-update-blocked` issue explains why.
- **No missing or raw `@key` text from us.** Every build is the complete current stock file plus our changes, and
  validation refuses a release that drops a key, adds a line break, starts a value with `@` or blanks a line.
  Text CIG itself ships as `@Some text` (shown with the `@` in game) is cleaned up automatically. The Pack Merger
  always merges onto the current stock file, so other packs that are older than the game can't leave gaps either.
- **Names CIG never wrote are filled in.** The game names item types, subtypes and item ports by looking up keys
  such as `item_TypeUtilityTurret`, and shows the raw key when CIG left it out of `global.ini` (4.10.2's mining-ship
  turrets show `@ITEM_TYPEUTILITYTURRET` in the component list). The same holds for ship names, careers and roles,
  and released contracts' titles and descriptions. `scripts/fetch_gamedata.py` lists every such key from the
  patch's game data; the build adds the ones stock lacks (`Utility Turret`; a missing description gets its
  title's text), and validation fails if any is left without text or the list itself goes missing. Once CIG adds
  a key, theirs is used. Each patch's change report lists the new ones, so their wording gets a look.
- **Every release has a change report** listing new, changed and removed items.
- **Backstop.** Every 6 hours a job compares our build with the CIG build string in the
  README of another community pack (set in `scripts/check_patch.py`). If the auto-update source is lagging, it opens a
  `patch-detected` issue. Only the build string is read.

Everything runs from `main`. GitHub starts scheduled runs (and "Run workflow" in the Actions tab, by default) on the
repository's default branch; if that isn't `main`, Auto-update and Patch watch hand the run over to `main` straight away
(and open one reminder issue), and Release, Deploy Pack Merger and Refresh release notes always build from `main`.

Only **LIVE** is supported. PTU changes too often between builds to keep a pack stable.

### Maintainer: when something needs a person

- **`auto-update-blocked` issue:** usually a new component's stats couldn't be read. Add a row for it to
  `data/component_overrides.csv` on `main`; the next run releases. If it says the game data lists too few UI
  keys, scunpacked-data changed its layout: update `summarise_ui_keys`/`ship_keys` in `scripts/fetch_gamedata.py`. You can also start one from
  **Actions → Auto-update → Run workflow**.
- **Releasing faster than the source** (optional): after the RSI launcher patches, double-click `update.bat`.
  It extracts the stock file from your own `Data.p4k` in seconds and opens a pull request; merging it releases.
  - It needs Python 3.10+ and `git`; the script installs `zstandard` itself.
  - If Star Citizen isn't in a standard location, copy `config.ini.example` to `config.ini` and set `sc_base`.

Every release creates a versioned release (e.g. `4.10.2-LIVE`) and refreshes the fixed-name `latest` release.

### Fixing a name by hand

| File | Use it for |
|---|---|
| `data/component_overrides.csv` | Stats for components whose description is missing or wrong, or `skip` to leave one alone |
| `data/overrides/common.ini` | Final text for any key, in both formats (e.g. `Hephaestanite` → `Heph`) |
| `data/overrides/remix.ini` / `classic.ini` | Final text for one format only |
| `data/ui_text.ini` | Wording for item type/port names CIG left out (otherwise made from the key) |

Overrides are matched by key, so they carry over to later patches automatically.

### Repository layout

```
stock/<CHANNEL>/global.ini      unmodified CIG file (+ version.json)
dist/<CHANNEL>/<variant>/       built pack: data/Localization/english/global.ini + user.cfg + changes.ini
data/                           overrides
scripts/build.py                stock -> packs
scripts/report.py               patch change report
scripts/validate.py             CI checks
scripts/fetch_stock.py          fetch the newest stock file remotely (Auto-update)
scripts/update_stock.py         extract stock from your own Data.p4k and push (optional)
scripts/check_patch.py          detect a newer game build (starts Auto-update straight away)
scripts/fetch_gamedata.py       contract/blueprint summary from per-patch game data -> data/gamedata/LIVE.json
scripts/version_info.py         release titles / versions for the workflows
scripts/p4k_reader.py           minimal Data.p4k reader
scripts/build_category_db.py    category data for the Pack Merger (run on every Pages deploy)
site/                           the Pack Merger web app (GitHub Pages)
```

## Found a wrong name?

Open an [issue](https://github.com/AdamWaldie/ScCompLangPackWaldo/issues) with the item name, what it
shows and what it should show. A screenshot helps.

## Notes

- Not affiliated with Cloud Imperium Games.
- Language packs are permitted by CIG:
  [Community Localization Update](https://robertsspaceindustries.com/spectrum/community/SC/forum/1/thread/star-citizen-community-localization-update).
