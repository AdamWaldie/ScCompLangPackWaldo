# ⚙️ ScCompLangPackWaldo

![GitHub release (latest by date)](https://img.shields.io/github/v/release/AdamWaldie/ScCompLangPackWaldo)
![GitHub pre-release](https://img.shields.io/github/v/release/AdamWaldie/ScCompLangPackWaldo?include_prereleases&label=pre-release&color=orange)

A Star Citizen language pack that puts ship component stats in the item name, so you can see
whether a component is worth looting the moment you scan it. It is rebuilt and released for
every patch, for both LIVE and PTU.

> Based on [ScCompLangPackRemix](https://github.com/BeltaKoda/ScCompLangPackRemix) by **BeltaKoda**,
> which itself remixes the original [ScCompLangPack](https://github.com/ExoAE/ScCompLangPack) by **ExoAE**.
> All credit for the idea and the naming formats goes to them. See [CREDITS.md](CREDITS.md).

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

The tags cover coolers, power plants, shield generators, quantum drives and radars.
Missiles and torpedoes are tagged with their tracking signal: **IR** (infrared), **EM**
(electromagnetic) or **CS** (cross-section).

Capital-ship and Vanduul parts that have no grade, such as the Idris and 890J internals, keep their stock names.

## ⬇️ Install

1. Download the zip for your channel and format from the [Releases page](https://github.com/AdamWaldie/ScCompLangPackWaldo/releases):
   - `ScCompLangPackWaldo-<version>-LIVE.zip`: Remix format
   - `ScCompLangPackWaldo-Classic-<version>-LIVE.zip`: Classic format
   - PTU builds are marked as pre-releases.
2. Extract it and copy the `data` folder and `user.cfg` into your game folder, e.g.
   `C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\`.
   If you already have a `user.cfg`, add the line `g_language = english` to it instead of overwriting it.
3. Launch the game. The main menu version text ends with `ScCompLangPackWaldo`.

### Auto-update URLs

These URLs always point at the latest build, for tools such as the
[SC Launch Configurator](https://www.luftwerft.com/?lang=en):

```
https://raw.githubusercontent.com/AdamWaldie/ScCompLangPackWaldo/main/dist/LIVE/remix/data/Localization/english/global.ini
https://raw.githubusercontent.com/AdamWaldie/ScCompLangPackWaldo/main/dist/LIVE/classic/data/Localization/english/global.ini
https://raw.githubusercontent.com/AdamWaldie/ScCompLangPackWaldo/main/dist/PTU/remix/data/Localization/english/global.ini
```

## 🔄 How it stays up to date

```
 your PC (after the launcher patches)          GitHub Actions
 ────────────────────────────────────          ───────────────────────────────────────────────
 update.bat ── extracts stock global.ini ──▶  update/<ch>-<ver> branch
              from Data.p4k (seconds)          ├─ rebuild + validate
                                               └─ opens a PR with the change report
                                                        │ you review & merge
                                                        ▼
                                               main ── release workflow ── tagged release + zips
```

- **No game-data extraction needed.** Every component's description in the stock `global.ini` already
  lists its type, size, grade and class (`Item Type: Cooler\nSize: 2\nGrade: A\nClass: Military`),
  and missile descriptions list their tracking signal. `scripts/build.py` reads these. That means no Wine,
  no `unforge.exe`, no 5 GB DataForge dump, and the tags always match what the game shows in the item description.
- **New items are tagged automatically.** The build scans every item in the new stock file, so a new
  component is tagged the first time it appears. Nothing has to be added by hand.
- **Every patch gets a change report** (in the PR, and in the release notes) listing new, changed and removed
  items, plus anything that **needs attention**.
- **CI blocks bad builds.** It checks that the output has the same keys in the same order as stock, that it
  has a UTF-8 BOM, that only intended keys changed, that tags are well-formed, and that every component
  was classified.

### Maintainer: updating for a new patch

1. Let the RSI launcher finish patching.
2. Double-click `update.bat` (or `update.bat PTU`). On Linux or macOS run `python scripts/update_stock.py --channel LIVE --push`.
   - It needs Python 3.10+ and `git`; the script installs `zstandard` itself.
   - If Star Citizen isn't in a standard location, copy `config.ini.example` to `config.ini` and set `sc_base`.
3. Open the pull request that appears and read the report. If anything is listed under **Needs attention**,
   add a row for it to `data/component_overrides.csv` and push to the same branch.
4. Merge. The release is published automatically.

### Fixing a name by hand

| File | Use it for |
|---|---|
| `data/component_overrides.csv` | Stats for components whose description is missing or wrong, or `skip` to leave one alone |
| `data/overrides/common.ini` | Final text for any key, in both formats (e.g. `Hephaestanite` → `Heph`) |
| `data/overrides/remix.ini` / `classic.ini` | Final text for one format only |

Overrides are matched by key, so they carry over to later patches automatically.

### Repository layout

```
stock/<CHANNEL>/global.ini      unmodified CIG file (+ version.json)
dist/<CHANNEL>/<variant>/       built pack: data/Localization/english/global.ini + user.cfg
data/                           overrides
scripts/build.py                stock -> packs
scripts/report.py               patch change report
scripts/validate.py             CI checks
scripts/update_stock.py         extract stock from Data.p4k and push (maintainer)
scripts/p4k_reader.py           minimal Data.p4k reader (from ScCompLangPackRemix)
```

## 🚧 Found a wrong name?

Open an [issue](https://github.com/AdamWaldie/ScCompLangPackWaldo/issues) with the item name, what it
shows and what it should show. A screenshot helps.

## Notes

- Not affiliated with Cloud Imperium Games.
- Language packs are permitted by CIG:
  [Community Localization Update](https://robertsspaceindustries.com/spectrum/community/SC/forum/1/thread/star-citizen-community-localization-update).
