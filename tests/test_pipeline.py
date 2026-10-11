"""Unit tests for the build pipeline. Run with: python -m unittest discover -s tests"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build  # noqa: E402
from fetch_stock import parse_message, version_key  # noqa: E402

STOCK = (
    "﻿Frontend_PU_Version,P=4.10 - Test\r\n"
    "item_NameCOOL_AEGS_S01_Bracer=Bracer\r\n"
    "item_DescCOOL_AEGS_S01_Bracer=Item Type: Cooler\\nManufacturer: Aegis\\nSize: 1\\nGrade: C\\nClass: Military\\n\\nFlavour.\r\n"
    "item_NamePOWR_JUST_S01_Endurance_SCItem=Endurance\r\n"
    "item_Desc_POWR_JUST_S01_Endurance=Item Type: Power Plant\\nSize: 1\\nGrade: B\\nClass: Industrial\\n\\nText\r\n"
    "item_NameCOOL_AEGS_S04_Idris=Exotherm\r\n"
    "item_DescCOOL_AEGS_S04_Idris=Item Type: Cooler\\nSize: 4\\nGrade: Bespoke\\nClass: Military\r\n"
    "item_NameMISL_S02_EM_TALN_Dominator=Dominator II Missile\r\n"
    "item_NameMISL_S02_EM_TALN_Dominator_short=Dmntr II\r\n"
    "item_DescMISL_S02_EM_TALN_Dominator=Manufacturer: Talon\\nTracking Signal: Electromagnetic\\nSize: 2\r\n"
    "item_NameBOMB_S05_FSKI_Stormburst=Stormburst Bomb\r\n"
    "item_DescBOMB_S05_FSKI_Stormburst=Manufacturer: FSKI\\nItem Type: Explosive Bomb\\nSize: 5\r\n"
    "ui_Untouched=Some text with = sign  \r\n"
)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.stock = self.dir / "global.ini"
        self.stock.write_text(STOCK, encoding="utf-8", newline="")

    def built(self, variant):
        ini, stats = build.build(self.stock, variant)
        return ini, stats

    def test_remix_tags(self):
        ini, stats = self.built("remix")
        self.assertEqual(ini.get("item_NameCOOL_AEGS_S01_Bracer"), "M1C Bracer")
        # Description key spelled differently (underscore, no _SCItem) is still found.
        self.assertEqual(ini.get("item_NamePOWR_JUST_S01_Endurance_SCItem"), "I1B Endurance")
        self.assertEqual(ini.get("item_NameMISL_S02_EM_TALN_Dominator"), "EM Dominator II Missile")
        self.assertEqual(ini.get("item_NameMISL_S02_EM_TALN_Dominator_short"), "EM Dmntr II")
        self.assertEqual(ini.get("item_NameBOMB_S05_FSKI_Stormburst"), "B5 Stormburst Bomb")
        self.assertEqual(stats["unresolved"], [])

    def test_classic_tags(self):
        ini, _ = self.built("classic")
        self.assertEqual(ini.get("item_NameCOOL_AEGS_S01_Bracer"), "Bracer Military C")
        self.assertEqual(ini.get("item_NameMISL_S02_EM_TALN_Dominator"), "[EM] Dominator II Missile")
        self.assertEqual(ini.get("item_NameBOMB_S05_FSKI_Stormburst"), "Stormburst Bomb")

    def test_bespoke_left_alone(self):
        ini, stats = self.built("remix")
        self.assertEqual(ini.get("item_NameCOOL_AEGS_S04_Idris"), "Exotherm")
        self.assertIn("item_NameCOOL_AEGS_S04_Idris", stats["bespoke"])

    def test_untouched_lines_are_byte_identical(self):
        ini, _ = self.built("remix")
        out = self.dir / "out.ini"
        ini.save(out)
        stock_lines = self.stock.read_bytes().split(b"\n")
        out_lines = out.read_bytes().split(b"\n")
        self.assertEqual(len(stock_lines), len(out_lines))
        self.assertTrue(out.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"ui_Untouched=Some text with = sign  \r", out_lines)

    def test_branding_keeps_key_flag(self):
        ini, _ = self.built("remix")
        line = ini.lines[ini.index["Frontend_PU_Version"]]
        self.assertTrue(line.startswith("Frontend_PU_Version,P=4.10 - Test - ScCompLangPackWaldo"))

    def test_component_key_without_description_keeps_stock_name(self):
        self.stock.write_text(STOCK + "item_NameCOOL_AEGS_S04_Idirs=Exotherm\r\n", encoding="utf-8", newline="")
        ini, stats = self.built("remix")
        self.assertEqual(ini.get("item_NameCOOL_AEGS_S04_Idirs"), "Exotherm")
        self.assertIn("item_NameCOOL_AEGS_S04_Idirs", stats["no_description"])
        self.assertEqual(stats["unresolved"], [])

    def test_never_double_tags(self):
        ini, _ = self.built("remix")
        once = self.dir / "once.ini"
        ini.save(once)
        again, _ = build.build(once, "remix")
        self.assertEqual(again.get("item_NameCOOL_AEGS_S01_Bracer"), "M1C Bracer")
        self.assertEqual(again.get("item_NameMISL_S02_EM_TALN_Dominator_short"), "EM Dmntr II")


class FetchStockTests(unittest.TestCase):
    def test_parse_messages(self):
        cases = {
            "4.10.2 LIVE - English+Brazilian (#697)": ("LIVE", "4.10.2", ""),
            "English + Brazilian 4.10.1-live.12660092": ("LIVE", "4.10.1", "12660092"),
            "English+Brazilian 4.10 LIVE 12519617": ("LIVE", "4.10", "12519617"),
            "4.9.0-ptu.12206539 (EN)": ("PTU", "4.9.0", "12206539"),
        }
        for message, (channel, version, build_no) in cases.items():
            with self.subTest(message=message):
                meta = parse_message(message)
                self.assertEqual((meta["channel"], meta["version"], meta["build"]), (channel, version, build_no))

    def test_unclassifiable_messages(self):
        for message in ("README Update", "Brazilian small changes", "Update French localization (#688)"):
            self.assertIsNone(parse_message(message))

    def test_version_ordering(self):
        self.assertLess(version_key("4.9.0"), version_key("4.10"))
        self.assertEqual(version_key("4.10"), version_key("4.10.0"))


class MergerCategoryTests(unittest.TestCase):
    """Every component/ordnance tag must fall in a component or ordnance category of the Pack Merger,
    otherwise picking our pack for e.g. "Quantum Drives" would silently miss items."""

    def test_tagged_items_are_categorised(self):
        import json
        import re
        root = Path(__file__).resolve().parent.parent
        data = json.loads((root / "site" / "data" / "categories.json").read_text())
        rules = [(re.compile(p), g["name"]) for g in data["groups"] for c in g["categories"] for p in c["patterns"]]

        def group_of(key):
            return next((group for rx, group in rules if rx.search(key)), "Other")

        ini = build.IniFile.load(root / "stock" / "LIVE" / "global.ini")
        result = build.classify(ini)
        lower = {k.lower(): k for k in ini.keys()}
        keys = [i.key for i in result.items] + [lower[i.key.lower() + "_short"] for i in result.items
                                                  if i.kind != "component" and i.key.lower() + "_short" in lower]
        misplaced = [k for k in keys if group_of(k) not in ("Ship Components", "Ordnance")]
        self.assertEqual(misplaced, [], "tagged keys outside component/ordnance categories")


class GameDataLayerTests(unittest.TestCase):
    STOCK = (
        "\ufeffFrontend_PU_Version=4.10 - Test\r\n"
        "Some_Contract_Title=Defend the Outpost\r\n"
        "Some_Contract_Desc=Go there.\\nKill them.\r\n"
        "Shared_Title=Shared Job\r\n"
        "Rep_Title=Taking Back Our Goods\r\n"
        "Rep_Desc=Get the cargo.\r\n"
        "item_DescKGGR_NavigationLight=@Navigation light\r\n"
        "item_NamePistol=@mp_ePistol\r\n"
    )
    GAMEDATA = {
        "version": "4.10.2", "build": "123",
        "titles": {"some_contract_title": {"bp": 2, "total": 2}, "Shared_Title": {"bp": 1, "total": 3},
                   "Rep_Title": {"bp": 0, "total": 3, "rep": [200, 400, 800]}},
        "descriptions": {"Some_Contract_Desc": {"bp": 2, "total": 2, "items": ["Arclight Pistol", "Testudo Core"]},
                         "Rep_Desc": {"bp": 0, "total": 3, "rep": [200, 400, 800],
                                      "req": [["Contractor", 2200], ["Sr. Contractor", 5800]],
                                      "faction": "Dead Saints", "scenario": [255]}},
    }

    def setUp(self):
        import json
        self.dir = Path(tempfile.mkdtemp()) / "LIVE"
        self.dir.mkdir()
        (self.dir / "global.ini").write_text(self.STOCK, encoding="utf-8", newline="")
        self.gd_dir = Path(tempfile.mkdtemp())
        (self.gd_dir / "gamedata").mkdir()
        (self.gd_dir / "gamedata" / "LIVE.json").write_text(json.dumps(self.GAMEDATA))
        self._data_dir, build.DATA_DIR = build.DATA_DIR, self.gd_dir

    def tearDown(self):
        build.DATA_DIR = self._data_dir

    def build_with(self, version, build_no=""):
        import json
        (self.dir / "version.json").write_text(json.dumps({"version": version, "build": build_no}))
        return build.build(self.dir / "global.ini", "remix")

    def test_blueprints_applied_when_patch_matches(self):
        ini, stats = self.build_with("4.10.2", "123")
        self.assertEqual(ini.get("Some_Contract_Title"), "[BP] Defend the Outpost")
        self.assertEqual(ini.get("Shared_Title"), "[BP]* Shared Job")
        self.assertEqual(ini.get("Some_Contract_Desc"),
                         "Go there.\\nKill them.\\n\\nBlueprints this contract can award:"
                         "\\n- Arclight Pistol\\n- Testudo Core")
        self.assertIn("matched", stats["gamedata"])

    def test_reputation_standing_and_scenario_added(self):
        ini, _ = self.build_with("4.10.2", "123")
        self.assertEqual(ini.get("Rep_Title"), "Taking Back Our Goods [200/400/800 Rep]")
        self.assertEqual(ini.get("Rep_Desc"),
                         "Get the cargo.\\n\\nReputation awarded: 200 / 400 / 800 (depends on the version offered)"
                         "\\nRequires: Contractor / Sr. Contractor standing with Dead Saints"
                         " (depends on the version offered)\\nScenario progress: 255 points")
        ini, _ = self.build_with("4.10.3")
        self.assertTrue(ini.get("Rep_Desc").startswith("Get the cargo.\\n\\nReputation awarded (as of 4.10.2): 200"))

    def test_older_game_data_used_as_of_its_patch(self):
        for version, build_no, asof in (("4.10.3", "", "4.10.2"), ("4.10.2", "999", "4.10.2 build 123")):
            ini, stats = self.build_with(version, build_no)
            self.assertEqual(ini.get("Some_Contract_Title"), "[BP] Defend the Outpost")
            self.assertEqual(ini.get("Some_Contract_Desc"),
                             f"Go there.\\nKill them.\\n\\nBlueprints this contract can award (as of {asof}):"
                             "\\n- Arclight Pistol\\n- Testudo Core")
            self.assertIn(f"as of {asof}", stats["gamedata"])

    def test_newer_game_data_not_used(self):
        ini, stats = self.build_with("4.10.1")
        self.assertEqual(ini.get("Some_Contract_Title"), "Defend the Outpost")
        self.assertIn("newer", stats["gamedata"])

    def test_gamedata_match(self):
        cases = [({"version": "4.10.2", "build": "1"}, {"version": "4.10.2", "build": "1"}, "matched"),
                 ({"version": "4.10.2", "build": "1"}, {"version": "4.10.2", "build": ""}, "matched"),
                 ({"version": "4.10.2", "build": "1"}, {"version": "4.10.2", "build": "2"}, "older"),
                 ({"version": "4.10.1"}, {"version": "4.10.2"}, "older"),
                 ({"version": "4.11.0"}, {"version": "4.10.2"}, "newer")]
        for gd, meta, want in cases:
            self.assertEqual(build.gamedata_match(gd, meta), want, (gd, meta))

    def test_literal_at_text_fixed_but_key_references_kept(self):
        ini, _ = self.build_with("4.10.1")
        self.assertEqual(ini.get("item_DescKGGR_NavigationLight"), "Navigation light")
        self.assertEqual(ini.get("item_NamePistol"), "@mp_ePistol")

    def test_rebuild_is_idempotent(self):
        for version in ("4.10.2", "4.10.3"):
            self.setUp()
            ini, _ = self.build_with(version, "123")
            ini.save(self.dir / "global.ini")
            again, _ = self.build_with(version, "123")
            self.assertEqual(again.get("Some_Contract_Title"), "[BP] Defend the Outpost")
            self.assertEqual(again.get("Some_Contract_Desc").count("Blueprints this contract"), 1)
            self.assertEqual(again.get("Rep_Title").count(" Rep]"), 1)
            self.assertEqual(again.get("Rep_Desc").count("Reputation awarded"), 1)
            self.tearDown()


if __name__ == "__main__":
    unittest.main()
