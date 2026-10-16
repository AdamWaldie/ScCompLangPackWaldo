"""Unit tests for the build pipeline. Run with: python -m unittest discover -s tests"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build  # noqa: E402
import fetch_gamedata  # noqa: E402
from fetch_stock import parse_message, version_key  # noqa: E402

STOCK = (
    "﻿Frontend_PU_Version,P=4.10 - Test\r\n"
    "item_NameCOOL_AEGS_S01_Bracer=Bracer\r\n"
    "item_Name_COMP_BEHR_S02_CSMTL=CSM-TL\r\n"
    "item_Desc_COMP_BEHR_S02_CSMTL=Item Type: Computer\\nManufacturer: Behring\\nSize: 2\\nGrade: B\\nClass: Military\\n\\nFlavour.\r\n"
    "item_Name_dmc_frontier_gloves_01_02_11,P=PLACEHOLDER - dmc_frontier_gloves_01_02_11\r\n"
    "item_Desc_dmc_frontier_gloves_01_02_11,P=PLACEHOLDER - dmc_frontier_gloves_01_02_11\r\n"
    "item_Name_cbd_boots_01_01_01,P=Placeholder - CBD Boots\r\n"
    "item_NameHangarGravPallet=\r\n"
    "item_Desc_cbd_jacket_02_01_01,P=Placeholder - CBD Jacket Desc\\n\\nCarrying Capacity: 1K\r\n"
    "Miners_RepUI_Name,P=[PH] Miners\r\n"
    "kiosk_Armor_Shop,P=Armor_Shop\r\n"
    "mg_clovus_satrecover_title=CitCon_Prototype\r\n"
    "chat_emote_asl_hello=asl_hello\r\n"
    "DXSM_Screen_Slot=\r\n"
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

    def test_computers_tagged(self):
        ini, _ = self.built("remix")
        self.assertEqual(ini.get("item_Name_COMP_BEHR_S02_CSMTL"), "M2B CSM-TL")
        ini, _ = self.built("classic")
        self.assertEqual(ini.get("item_Name_COMP_BEHR_S02_CSMTL"), "CSM-TL Military B")

    def test_unfinished_stock_text_never_shown(self):
        ini, stats = self.built("remix")
        self.assertEqual(ini.get("item_Name_dmc_frontier_gloves_01_02_11"), "DMC Frontier Gloves")
        self.assertEqual(ini.get("item_Desc_dmc_frontier_gloves_01_02_11"), "DMC Frontier Gloves")
        self.assertEqual(ini.get("item_Name_cbd_boots_01_01_01"), "CBD Boots")
        self.assertEqual(ini.get("item_NameHangarGravPallet"), "Hangar Grav Pallet")
        self.assertEqual(ini.get("item_Desc_cbd_jacket_02_01_01"), "Carrying Capacity: 1K")
        self.assertEqual(ini.get("Miners_RepUI_Name"), "Miners")
        self.assertEqual(ini.get("kiosk_Armor_Shop"), "Armor Shop")
        self.assertEqual(ini.get("mg_clovus_satrecover_title"), "CitCon Prototype")
        # Deliberate identifiers and blanks are kept.
        self.assertEqual(ini.get("chat_emote_asl_hello"), "asl_hello")
        self.assertEqual(ini.get("DXSM_Screen_Slot"), "")
        self.assertEqual(stats["left_blank"], [])

    def test_bespoke_left_alone(self):
        ini, stats = self.built("remix")
        self.assertEqual(ini.get("item_NameCOOL_AEGS_S04_Idris"), "Exotherm")
        self.assertIn("item_NameCOOL_AEGS_S04_Idris", stats["bespoke"])

    def test_untouched_lines_are_byte_identical(self):
        ini, stats = self.built("remix")
        out = self.dir / "out.ini"
        ini.save(out)
        stock_lines = self.stock.read_bytes().split(b"\n")
        out_lines = out.read_bytes().split(b"\n")
        # Keys CIG never wrote (data/ui_text.ini) are appended; every stock line keeps its place.
        self.assertEqual(len(stock_lines) + len(stats["added"]), len(out_lines))
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
        "Old_Desc=Old job.\r\n"
        "item_DescKGGR_NavigationLight=@Navigation light\r\n"
        "item_NamePistol=@mp_ePistol\r\n"
        "item_NameClothingCabinet=@mp_eFlashlightNova\r\n"
        "mp_eGood=Good item\r\n"
        "item_NameGood=@mp_eGood\r\n"
        "item_typeturret=Turret\r\n"
    )
    GAMEDATA = {
        "version": "4.10.2", "build": "123",
        "titles": {"some_contract_title": {"bp": 2, "total": 2}, "Shared_Title": {"bp": 1, "total": 3},
                   "Rep_Title": {"bp": 0, "total": 3, "rep": [200, 400, 800]}},
        "descriptions": {"Some_Contract_Desc": {"bp": 2, "total": 2, "items": ["Arclight Pistol", "Testudo Core"]},
                         "Rep_Desc": {"bp": 0, "total": 3, "rep": [200, 400, 800],
                                      "req": [["Contractor", 2200], ["Sr. Contractor", 5800]],
                                      "faction": "Dead Saints", "scenario": [255]},
                         "Old_Desc": {"bp": 1, "total": 1, "items": ["Testudo Core"], "rep": [50],
                                      "asof": "4.10.1"}},
        "ui_keys": ["item_TypeTurret", "item_TypeUtilityTurret", "item_TypeFPS_Deployable",
                    "item_SubTypeMidRangeRadar", "itemPort_port_NameFuelPort"],
    }
    UI_DESC_GAMEDATA = {
        "version": "4.10.2", "titles": {}, "descriptions": {},
        "ui_keys": ["Rep_Title", "CFP_EliminateAll_Rockcracker_title_001"],
        "ui_desc_keys": {"Rep_Desc": "Rep_Title", "New_Contract_Desc": "Rep_Title",
                         "CFP_EliminateAll_Rockcracker_desc": "CFP_EliminateAll_Rockcracker_title_001",
                         "Orphan_Ship_Desc_001": "Missing_Ship_Name"},
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

    def test_entry_from_older_source_labelled_with_its_patch(self):
        ini, _ = self.build_with("4.10.2", "123")
        self.assertEqual(ini.get("Old_Desc"),
                         "Old job.\\n\\nReputation awarded (as of 4.10.1): 50"
                         "\\n\\nBlueprints this contract can award (as of 4.10.1):\\n- Testudo Core")

    def test_older_game_data_used_as_of_its_patch(self):
        for version, build_no, asof in (("4.10.3", "", "4.10.2"), ("4.10.2", "999", "4.10.2 build 123")):
            ini, stats = self.build_with(version, build_no)
            self.assertEqual(ini.get("Some_Contract_Title"), "[BP] Defend the Outpost")
            self.assertEqual(ini.get("Some_Contract_Desc"),
                             f"Go there.\\nKill them.\\n\\nBlueprints this contract can award (as of {asof}):"
                             "\\n- Arclight Pistol\\n- Testudo Core")
            self.assertIn(f"as of {asof}", stats["gamedata"])

    def test_ptu_game_data_labelled_until_live_arrives(self):
        import json
        gd = dict(self.GAMEDATA, channel="PTU")
        (self.gd_dir / "gamedata" / "LIVE.json").write_text(json.dumps(gd))
        ini, stats = self.build_with("4.10.2", "123")
        self.assertTrue(ini.get("Some_Contract_Desc").endswith(
            "Blueprints this contract can award (as of 4.10.2 PTU):\\n- Arclight Pistol\\n- Testudo Core"))
        self.assertIn("as of 4.10.2 PTU", stats["gamedata"])

    def test_newer_game_data_not_used(self):
        ini, stats = self.build_with("4.10.1")
        self.assertEqual(ini.get("Some_Contract_Title"), "Defend the Outpost")
        self.assertIn("newer", stats["gamedata"])

    def test_gamedata_match(self):
        cases = [({"version": "4.10.2", "build": "1"}, {"version": "4.10.2", "build": "1"}, "matched"),
                 ({"version": "4.10.2", "build": "1"}, {"version": "4.10.2", "build": ""}, "matched"),
                 ({"version": "4.10.2", "build": "1"}, {"version": "4.10.2", "build": "2"}, "older"),
                 ({"version": "4.10.1"}, {"version": "4.10.2"}, "older"),
                 ({"version": "4.11.0"}, {"version": "4.10.2"}, "newer"),
                 ({"version": "4.10.2", "channel": "PTU"}, {"version": "4.10.2"}, "older"),
                 ({"version": "4.10.2", "channel": "LIVE"}, {"version": "4.10.2"}, "matched")]
        for gd, meta, want in cases:
            self.assertEqual(build.gamedata_match(gd, meta), want, (gd, meta))

    def test_literal_at_text_and_dangling_references_fixed(self):
        ini, _ = self.build_with("4.10.1")
        self.assertEqual(ini.get("item_DescKGGR_NavigationLight"), "Navigation light")
        # References to keys that exist are kept; ones to missing keys would show raw, so get a name.
        self.assertEqual(ini.get("item_NameGood"), "@mp_eGood")
        self.assertEqual(ini.get("item_NamePistol"), "Pistol")
        self.assertEqual(ini.get("item_NameClothingCabinet"), "Clothing Cabinet")

    def test_missing_ui_names_added(self):
        (self.gd_dir / "ui_text.ini").write_text("# comment\nitem_SubTypeMidRangeRadar=Mid-Range Radar\n"
                                                 "item_TypeTurret=Not used: stock has it\n")
        ini, stats = self.build_with("4.10.1")
        # The game shows "@item_TypeUtilityTurret" when the key is missing; stock keys are left alone.
        self.assertEqual(ini.get("item_typeturret"), "Turret")
        self.assertNotIn("item_TypeTurret", ini.index)
        self.assertEqual(ini.get("item_TypeUtilityTurret"), "Utility Turret")
        self.assertEqual(ini.get("item_TypeFPS_Deployable"), "Deployable")
        self.assertEqual(ini.get("item_SubTypeMidRangeRadar"), "Mid-Range Radar")
        self.assertEqual(ini.get("itemPort_port_NameFuelPort"), "Fuel Port")
        self.assertEqual(stats["added"], ["item_TypeUtilityTurret", "item_TypeFPS_Deployable",
                                          "item_SubTypeMidRangeRadar", "itemPort_port_NameFuelPort"])
        # Appended after the stock keys, with the file's line ending, and listed for merge tools.
        self.assertEqual(ini.lines[-1], "itemPort_port_NameFuelPort=Fuel Port\r")
        stock = build.IniFile.load(self.dir / "global.ini")
        self.assertEqual(list(ini.index)[:len(stock.index)], list(stock.index))
        self.assertIn("item_TypeUtilityTurret=Utility Turret\r", ini.changes_since(stock))

    def test_missing_items_added_and_tagged(self):
        (self.gd_dir / "ui_text.ini").write_text(
            "item_Name_RADR_WLOP_S03_Lephari=Lephari\n"
            "item_Desc_RADR_WLOP_S03_Lephari=Item Type: Radar\\nSize: 3\\nGrade: C\\nClass: Civilian\n"
            "item_NameGood=Not used: stock has it\n")
        ini, stats = self.build_with("4.10.1")
        self.assertEqual(ini.get("item_Name_RADR_WLOP_S03_Lephari"), "C3C Lephari")
        self.assertEqual(ini.get("item_NameGood"), "@mp_eGood")
        self.assertEqual(stats["added"][:2], ["item_Name_RADR_WLOP_S03_Lephari", "item_Desc_RADR_WLOP_S03_Lephari"])

    def test_missing_titles_and_descriptions_added(self):
        import json
        (self.gd_dir / "gamedata" / "LIVE.json").write_text(json.dumps(self.UI_DESC_GAMEDATA))
        ini, stats = self.build_with("4.10.2")
        # Existing text is kept; a missing title gets a name from its key, a missing description the
        # text of its title (or a name from its own key when the title is unknown too).
        self.assertEqual(ini.get("Rep_Desc"), "Get the cargo.")
        self.assertEqual(ini.get("CFP_EliminateAll_Rockcracker_title_001"), "CFP Eliminate All Rockcracker")
        self.assertEqual(ini.get("CFP_EliminateAll_Rockcracker_desc"), "CFP Eliminate All Rockcracker")
        self.assertEqual(ini.get("New_Contract_Desc"), "Taking Back Our Goods")
        self.assertEqual(ini.get("Orphan_Ship_Desc_001"), "Orphan Ship")
        self.assertEqual(len(stats["added"]), 4)

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
            self.assertEqual(list(again.index).count("item_TypeUtilityTurret"), 1)
            self.tearDown()



class ScmdbSummaryTests(unittest.TestCase):
    DATA = {
        "version": "4.10.2-live.123",
        "scopes": {"std": {"scopeName": "FactionReputation"}, "aff": {"scopeName": "Affinity"}},
        "eventScopes": {"ev": {"eventName": "CleanAir"}},
        "factions": {"f1": {"name": "Dead Saints"}},
        "blueprintPools": {"p1": {"blueprints": [{"name": "Testudo Core"}, {"name": "@placeholder"}]}},
        "factionRewardsPools": [[{"scopeGuid": "std", "amount": 200}, {"scopeGuid": "aff", "amount": 999}]],
        "contracts": [
            {"titleLocKey": "DS_Title", "descriptionLocKey": "DS_Desc", "factionGuid": "f1",
             "factionRewardsIndex": 0, "contractDefinitionIds": ["a", "b"],
             "blueprintRewards": [{"blueprintPool": "p1"}],
             "minStanding": {"name": "Sr. Contractor", "minReputation": 5800}},
            {"titleLocKey": "Event_Title", "descriptionLocKey": "Event_Desc", "factionGuid": "x",
             "minStanding": {"name": "Neutral", "minReputation": 0},
             "completionTags": [{"tag": "ev", "count": 225}, {"tag": "other", "count": 5}]},
        ],
        "legacyContracts": [],
    }

    def test_summarise(self):
        titles, descs = fetch_gamedata.summarise_scmdb(self.DATA).result()
        self.assertEqual(titles["DS_Title"], {"bp": 2, "total": 2, "rep": [200]})
        self.assertEqual(descs["DS_Desc"], {"bp": 2, "total": 2, "items": ["Testudo Core"], "rep": [200],
                                            "req": [["Sr. Contractor", 5800]], "faction": "Dead Saints"})
        self.assertEqual(descs["Event_Desc"], {"bp": 0, "total": 1, "scenario": [225]})
        self.assertNotIn("Event_Title", titles)


class FetchMergeTests(unittest.TestCase):
    def test_parse_version_channels(self):
        self.assertEqual(fetch_gamedata.parse_version("4.10.2-live.12881860"),
                         {"version": "4.10.2", "channel": "LIVE", "build": "12881860"})
        self.assertEqual(fetch_gamedata.parse_version("4.11.0-PTU.13000000")["channel"], "PTU")

    def test_rank_prefers_newer_patch_then_live_then_source(self):
        def src(name, version, channel, build="1"):
            return {"name": name, "version": version, "channel": channel, "build": build}
        ranked = sorted([src("fleetyards", "4.10.2", "LIVE"), src("scmdb", "4.10.2", "PTU", "9"),
                         src("scunpacked", "4.10.1", "LIVE"), src("scmdb", "4.10.2", "LIVE")],
                        key=fetch_gamedata._rank, reverse=True)
        self.assertEqual([(s["name"], s["channel"]) for s in ranked],
                         [("scmdb", "LIVE"), ("fleetyards", "LIVE"), ("scmdb", "PTU"), ("scunpacked", "LIVE")])

    def test_placeholder_and_negative_standings_dropped(self):
        self.assertIsNone(fetch_gamedata.standing({"name": "<= PLACEHOLDER =>", "minReputation": 500}, "Ruto"))
        self.assertIsNone(fetch_gamedata.standing({"name": "Hostile", "minReputation": -500}, "Ruto"))
        self.assertEqual(fetch_gamedata.standing({"name": "Contractor", "minReputation": 2200}, "<= PLACEHOLDER =>"),
                         ("Contractor", 2200, ""))

    def test_unstated_standing_reputation_filled_from_other_sources(self):
        descs = {"A": {"req": [["Contractor", 2200]]},
                 "B": {"req": [["Contractor", None], ["Sr. Contractor", None]], "faction": "X"},
                 "C": {"req": [["Neutral", None]], "faction": "Y"}}
        fetch_gamedata.resolve_standings(descs)
        self.assertEqual(descs["B"], {"req": [["Contractor", 2200]], "faction": "X"})
        self.assertEqual(descs["C"], {})

    def test_ui_keys_from_items(self):
        import json
        items = [
            {"type": "UtilityTurret", "subType": "MannedTurret",
             "stdItem": {"Ports": [{"DisplayName": "@itemPort_port_NameFuelPort"},
                                   {"DisplayName": "Resolved name", "Ports": [{"DisplayName": "@ui_shiploadout_slot"}]},
                                   {"DisplayName": "@Magazine Slot"}, {"DisplayName": "@Placeholder"}]}},
            {"type": "Cooler", "subType": "", "stdItem": {}},
        ]
        path = Path(tempfile.mkdtemp()) / "items.json"
        path.write_text(json.dumps(items))
        self.assertEqual(fetch_gamedata.summarise_ui_keys(path),
                         {"item_TypeUtilityTurret", "item_SubTypeMannedTurret", "item_TypeCooler",
                          "itemPort_port_NameFuelPort", "ui_shiploadout_slot"})

    def test_ship_and_contract_keys(self):
        import json
        root = Path(tempfile.mkdtemp())
        (root / "contracts").mkdir()
        (root / "items.json").write_text(json.dumps([{"type": "UtilityTurret"}]))
        (root / "ships.json").write_text(json.dumps([
            {"NameKey": "@vehicle_NameMISC_Prospector", "CareerKey": "@vehicle_focus_industrial",
             "RoleKey": "@vehicle_class_mining", "DescriptionKey": "@vehicle_DescMISC_Prospector"}]))
        contracts = [
            {"TitleKey": "Live_Title", "DescriptionKey": "Live_Desc"},
            {"TitleKey": "Hidden_Title", "DescriptionKey": "Hidden_Desc", "NotForRelease": True},
            {"TitleKey": "Draft_Title", "DescriptionKey": "Draft_Desc", "WorkInProgress": True},
            {"TitleKey": "WIP_Goto_Manfred_Title", "DescriptionKey": "WIP_Goto_Manfred_Desc"},
        ]
        for i, c in enumerate(contracts):
            (root / "contracts" / f"{i}.json").write_text(json.dumps(c))
        summary = fetch_gamedata.summarise_scunpacked(root / "contracts")
        self.assertEqual(summary.ui_keys, {"item_TypeUtilityTurret", "vehicle_NameMISC_Prospector",
                                           "vehicle_focus_industrial", "vehicle_class_mining", "Live_Title"})
        self.assertEqual(summary.ui_desc_keys, {"vehicle_DescMISC_Prospector": "vehicle_NameMISC_Prospector",
                                                "Live_Desc": "Live_Title"})

    def test_fleetyards_text_matching(self):
        self.assertEqual(fetch_gamedata.normalise_text("Line one\n\nLine  two "),
                         fetch_gamedata.normalise_text("Line one\\n\\nLine two"))

if __name__ == "__main__":
    unittest.main()
