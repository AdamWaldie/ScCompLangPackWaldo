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
    """Every line our packs change must fall in a component/ordnance category of the Pack Merger,
    otherwise picking our pack for e.g. "Quantum Drives" would silently miss items."""

    def test_pack_changes_are_categorised(self):
        import json
        import re
        root = Path(__file__).resolve().parent.parent
        data = json.loads((root / "site" / "data" / "categories.json").read_text())
        rules = [(re.compile(p), g["name"]) for g in data["groups"] for c in g["categories"] for p in c["patterns"]]

        def group_of(key):
            return next((group for rx, group in rules if rx.search(key)), "Other")

        allowed = {"Ship Components", "Ordnance", "Items"}  # Items: the Heph commodity override
        for variant in ("remix", "classic"):
            changes = root / "dist" / "LIVE" / variant / "changes.ini"
            keys = [line.split("=", 1)[0] for line in changes.read_text(encoding="utf-8-sig").splitlines() if "=" in line]
            misplaced = [k for k in keys if group_of(k) not in allowed]
            self.assertEqual(misplaced, [], f"{variant}: keys outside merger categories")


if __name__ == "__main__":
    unittest.main()
