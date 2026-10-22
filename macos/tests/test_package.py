#!/usr/bin/env python3
import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest import mock
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("package_cp", Path(__file__).parents[1] / "tools/package_cp.py")
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vp-package-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)

    def test_xml_schema_booleans_unicode_case_and_delete(self):
        pack.apply_xml(self.db, ET.fromstring('''<GameData><Table name="Items">
          <Column name="ID" type="integer" primarykey="true" autoincrement="true"/>
          <Column name="Text" type="text" notnull="true"/>
          <Column name="Enabled" type="boolean" default="true"/>
          </Table><Items><Row Text="é &amp; 雪"/><Row Text="remove" Enabled="false"/>
          <Delete text="remove"/></Items></GameData>'''))
        self.assertEqual(self.db.execute("SELECT * FROM Items").fetchall(), [(1, "é & 雪", 1)])

    def test_unknown_xml_operation_fails(self):
        self.db.execute("CREATE TABLE Items(ID integer)")
        with self.assertRaisesRegex(pack.PackageError, "Unsupported XML operation"):
            pack.apply_xml(self.db, ET.fromstring("<GameData><Items><FutureOperation/></Items></GameData>"))

    def test_core_save_identity_requires_complete_matching_format_tag(self):
        save = json.loads((pack.ROOT / "macos/abi/aspyr-steam-1.4.2.json").read_text())["native_save"]
        core = self.root / "core"
        guid = save["guid"].encode()
        core.write_bytes(guid + save["magic"].encode())
        self.assertIsNone(pack.core_save_identity(core))
        header = save["magic"].encode() + save["format"].to_bytes(4, "little") + uuid.UUID(save["guid"]).bytes
        core.write_bytes(guid + header)
        self.assertEqual(pack.core_save_identity(core), save)
        header = bytearray(header)
        header[8] ^= 1
        core.write_bytes(guid + header)
        self.assertIsNone(pack.core_save_identity(core))

    def test_unknown_column_flag_fails(self):
        with self.assertRaisesRegex(pack.PackageError, "Unsupported column"):
            pack.apply_xml(self.db, ET.fromstring('<GameData><Table name="T"><Column name="A" type="text" future="yes"/></Table></GameData>'))

    def test_xml_replace_replaces_matching_unique_row(self):
        self.db.executescript("CREATE TABLE Items(ID integer PRIMARY KEY, Type text UNIQUE, Value integer DEFAULT 7); INSERT INTO Items VALUES(1,'OLD',3);")
        pack.apply_xml(self.db, ET.fromstring('<GameData><Items><Replace Type="OLD" Value="9"/><Replace Type="NEW"/></Items></GameData>'))
        self.assertEqual(self.db.execute("SELECT Type,Value FROM Items ORDER BY Type").fetchall(), [("NEW", 7), ("OLD", 9)])

    def test_stock_overlap_requires_matching_document_and_complete_rows(self):
        self.db.executescript("CREATE TABLE Items(Type text PRIMARY KEY, Value integer DEFAULT 7, Note text);"
                             "INSERT INTO Items(Type) VALUES('EXISTING');")
        root = ET.fromstring('<GameData><Items><Row Type="EXISTING"/></Items></GameData>')
        stock = {pack.xml_shape(root): "bundled.xml"}
        self.assertEqual(pack.existing_stock_action(self.db, root, stock), "bundled.xml")
        self.assertIsNone(pack.existing_stock_action(self.db, root, {}))
        self.db.execute("UPDATE Items SET Value=8")
        self.assertIsNone(pack.existing_stock_action(self.db, root, stock))
        with self.assertRaises(sqlite3.IntegrityError):
            pack.apply_xml(self.db, root)
        self.db.execute("DELETE FROM Items")
        self.assertIsNone(pack.existing_stock_action(self.db, root, stock))

    def test_database_xml_round_trip_preserves_values_and_defaults(self):
        self.db.executescript("CREATE TABLE Items(ID integer PRIMARY KEY AUTOINCREMENT, Text text DEFAULT 'it''s good', Enabled boolean DEFAULT 1);"
                             "INSERT INTO Items(Text,Enabled) VALUES ('雪 & <quoted>',0),('',1);")
        path = self.root / "data.xml"
        pack.dump_database(self.db, path, set(), set())
        other = sqlite3.connect(":memory:")
        self.addCleanup(other.close)
        pack.apply_xml(other, pack.xml(path))
        self.assertEqual(other.execute("SELECT * FROM Items").fetchall(), self.db.execute("SELECT * FROM Items").fetchall())
        other.execute("INSERT INTO Items DEFAULT VALUES")
        self.assertEqual(other.execute("SELECT Text,Enabled FROM Items WHERE ID=3").fetchone(), ("it's good", 1))

    def test_upstream_skip_lists_are_discovered_and_unknown_syntax_rejected(self):
        self.assertEqual(pack.upstream_set("local LIST = { A = true, -- comment\n B = true, };", "LIST"), {"A", "B"})
        with self.assertRaises(pack.PackageError):
            pack.upstream_set("local LIST = { A = false, };", "LIST")

    def fixture(self):
        upstream = self.root / "upstream"
        mod = upstream / "(1) Community Patch"
        mod.mkdir(parents=True)
        (mod / "CP.modinfo").write_text('''<Mod id="d1b6328c-ff44-4b0d-aad7-c657f83610cd">
          <Dependencies><Dlc id="abc"/></Dependencies><Actions><OnModActivated>
          <UpdateDatabase>new.xml</UpdateDatabase><UpdateDatabase>change.sql</UpdateDatabase>
          </OnModActivated></Actions></Mod>''')
        (mod / "new.xml").write_text('''<GameData><Table name="NewData"><Column name="ID" type="integer"/></Table>
          <NewData><Row ID="7"/></NewData></GameData>''')
        (mod / "change.sql").write_text("UPDATE NewData SET ID=ID+1; UPDATE Language_en_US SET Text='updated';")
        maker = upstream / "(5) Modpack Maker for VP"
        maker.mkdir()
        (maker / "ModpackMaker.lua").write_text("local SKIPPED_TABLES = { DownloadableContent = true, };\nlocal SKIPPED_SCHEMAS = { EngineData = true, };")
        cache = self.root / "cache"
        cache.mkdir()
        with closing(sqlite3.connect(cache / "Civ5DebugDatabase.db")) as db, db:
            db.executescript("CREATE TABLE DownloadableContent(PackageID text); INSERT INTO DownloadableContent VALUES ('abc'); CREATE TABLE EngineData(A integer);")
        with closing(sqlite3.connect(cache / "Localization-Merged.db")) as db, db:
            db.executescript("CREATE TABLE Language_en_US(Tag text,Text text,Gender text,Plurality text); INSERT INTO Language_en_US VALUES ('TAG','original',NULL,NULL);")
        app = self.root / "Game.app"
        assets = app / "Contents/Assets/Assets"
        assets.mkdir(parents=True)
        for name in ["CIV5Units.xml", "CIV5Units_Mongol.xml"]:
            (assets / name).write_text("<GameData/><!-- <GameData> -->")
        (assets / "UI.xml").write_text("<Context/>")
        core = self.root / "core.dylib"
        core.write_bytes(b"native core fixture")
        return upstream, app, cache, core

    def test_full_build_is_ordered_read_only_and_hashes_its_output(self):
        args = self.fixture()
        before = {str(p): pack.sha256(p) for root in args[:3] for p in root.rglob("*") if p.is_file()}
        output = self.root / "package"
        with mock.patch.object(pack.subprocess, "check_output", return_value="test-commit\n"):
            report = pack.build(*args, output)
        self.assertEqual(len(report["actions"]), 2)
        data = pack.xml(output / "Override/CIV5Units.xml")
        self.assertEqual(data.find("./NewData/Row/ID").text, "8")
        text = pack.xml(output / "Override/CIV5Units_Mongol.xml")
        self.assertEqual(text.find("./Language_en_US/Row/Text").text, "updated")
        for name, sha in report["files"].items():
            self.assertEqual(pack.sha256(output / name), sha)
        self.assertFalse((output / "Override/UI.xml").exists())
        self.assertEqual({p: pack.sha256(Path(p)) for p in before}, before)
        with self.assertRaisesRegex(pack.PackageError, "already exists"):
            pack.build(*args, output)

    def test_missing_action_aborts_without_partial_output(self):
        args = self.fixture()
        (args[0] / "(1) Community Patch/change.sql").unlink()
        with self.assertRaisesRegex(pack.PackageError, "Missing or unsafe"):
            pack.build(*args, self.root / "package")
        self.assertFalse((self.root / "package").exists())

    def test_already_modded_input_is_rejected(self):
        args = self.fixture()
        with closing(sqlite3.connect(args[2] / "Civ5DebugDatabase.db")) as db, db:
            db.execute("CREATE TABLE CustomModOptions(Name text)")
        with self.assertRaisesRegex(pack.PackageError, "already modded"):
            pack.build(*args, self.root / "package")

    def runtime_fixture(self):
        args = self.fixture()
        mod = args[0] / "(1) Community Patch"
        manifest = mod / "CP.modinfo"
        tree = ET.parse(manifest)
        dll = ET.SubElement(tree.find("./Actions"), "OnGetDLLPath")
        ET.SubElement(dll, "SetDllPath").text = "core.dll"
        files = ET.SubElement(tree.getroot(), "Files")
        for name, flag, data in [
            ("UI/InGame.lua", "1", b"local g_uiAddins = {};\n"),
            ("Art/texture.dds", "1", b"\x00\xfftexture"),
            ("core.dll", "1", b"MZ Windows binary"),
            ("New/Panel.xml", "0", b"<Context/>"),
            ("New/Panel.lua", "0", b"print('panel')"),
            ("New/Logic.lua", "0", b"print('logic')"),
            ("Unused.lua", "0", b"not activated"),
        ]:
            source = mod / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(data)
            ET.SubElement(files, "File", {"import": flag}).text = name
        points = ET.SubElement(tree.getroot(), "EntryPoints")
        for name in ["New/Panel.xml", "New/Logic.lua"]:
            ET.SubElement(points, "EntryPoint", type="InGameUIAddin", file=name)
        tree.write(manifest)
        maker = args[0] / "(5) Modpack Maker for VP/ModpackMaker.lua"
        maker.write_text(maker.read_text() + '\nlocal ADDIN_FILES = {\n'
                         '{ File = "InGame.lua", AddinType = "InGameUIAddin", },\n};\n')
        return args

    def test_runtime_assets_and_addins_follow_manifest_without_windows_core(self):
        args = self.runtime_fixture()
        mod = args[0] / "(1) Community Patch"
        before = {p: p.read_bytes() for p in mod.rglob("*") if p.is_file()}
        output = self.root / "runtime"
        with mock.patch.object(pack.subprocess, "check_output", return_value="test-commit\n"):
            report = pack.build(*args, output, include_runtime=True)
        self.assertTrue(report["ui_assets_included"])
        self.assertFalse(report["gameplay_test_ready"])
        self.assertEqual(report["runtime_assets"]["files_copied"], 5)
        self.assertEqual((output / "Mods/CommunityPatch/Art/texture.dds").read_bytes(), b"\x00\xfftexture")
        self.assertTrue((output / "Mods/CommunityPatch/New/Panel.lua").is_file())
        self.assertFalse(list(output.rglob("*.dll")))
        self.assertFalse(list(output.rglob("Unused.lua")))
        generated = (output / "UI/InGame.lua").read_text()
        self.assertIn('g_uiAddins[#g_uiAddins + 1] = "Panel";', generated)
        self.assertIn('g_uiAddins[#g_uiAddins + 1] = "Logic";', generated)
        self.assertEqual((output / "Mods/CommunityPatch/UI/InGame.lua").read_bytes(), before[mod / "UI/InGame.lua"])
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        for name, sha in report["files"].items():
            self.assertEqual(pack.sha256(output / name), sha)

    def test_unknown_entry_type_and_changed_addin_hook_fail_without_output(self):
        args = self.runtime_fixture()
        manifest = args[0] / "(1) Community Patch/CP.modinfo"
        original = manifest.read_bytes()
        tree = ET.parse(manifest)
        tree.find("./EntryPoints/EntryPoint").set("type", "FutureEntryPoint")
        tree.write(manifest)
        output = self.root / "runtime"
        with self.assertRaisesRegex(pack.PackageError, "Unsupported runtime entry point"):
            pack.build(*args, output, include_runtime=True)
        self.assertFalse(output.exists())
        manifest.write_bytes(original)
        (args[0] / "(1) Community Patch/UI/InGame.lua").write_text("-- removed upstream hook\n")
        with self.assertRaisesRegex(pack.PackageError, "addin consumer changed"):
            pack.build(*args, output, include_runtime=True)
        self.assertFalse(output.exists())

    def test_runtime_vfs_collision_and_path_escape_are_rejected(self):
        args = self.runtime_fixture()
        mod = args[0] / "(1) Community Patch"
        manifest = mod / "CP.modinfo"
        tree = ET.parse(manifest)
        (mod / "Other").mkdir()
        (mod / "Other/TEXTURE.dds").write_bytes(b"different")
        extra = ET.SubElement(tree.find("./Files"), "File", {"import": "1"})
        extra.text = "Other/TEXTURE.dds"
        tree.write(manifest)
        output = self.root / "runtime"
        with self.assertRaisesRegex(pack.PackageError, "Ambiguous runtime VFS basename"):
            pack.build(*args, output, include_runtime=True)
        self.assertFalse(output.exists())
        extra.text = "../outside.dds"
        tree.write(manifest)
        with self.assertRaisesRegex(pack.PackageError, "Unsafe runtime file path"):
            pack.build(*args, output, include_runtime=True)
        self.assertFalse(output.exists())

    def vp_fixture(self):
        args = self.runtime_fixture()
        cp = args[0] / "(1) Community Patch/CP.modinfo"
        tree = ET.parse(cp)
        tree.getroot().set("version", "151")
        tree.write(cp)
        vp = args[0] / "(2) Vox Populi"
        vp.mkdir()
        (vp / "VP.modinfo").write_text('''<Mod id="8411a7a8-dad3-4622-a18e-fcc18324c799" version="17">
          <Dependencies><Mod id="d1b6328c-ff44-4b0d-aad7-c657f83610cd" minversion="151" maxversion="999"/></Dependencies>
          <Actions><OnModActivated><UpdateDatabase>balance.sql</UpdateDatabase></OnModActivated></Actions>
          <Files><File import="1">UI/InGame.lua</File><File import="1">Art/texture.dds</File>
          <File import="0">Balance.lua</File><File import="0">Map.lua</File></Files>
          <EntryPoints><EntryPoint type="InGameUIAddin" file="Balance.lua"/>
          <EntryPoint type="MapScript" file="Map.lua"/></EntryPoints></Mod>''')
        (vp / "balance.sql").write_text("UPDATE NewData SET ID=ID*10; UPDATE Language_en_US SET Text='balanced';")
        (vp / "UI").mkdir()
        (vp / "Art").mkdir()
        (vp / "UI/InGame.lua").write_text("local g_uiAddins = {}; -- VP consumer\n")
        (vp / "Art/texture.dds").write_bytes(b"VP texture")
        (vp / "Balance.lua").write_text("-- balance addin")
        (vp / "Map.lua").write_text("-- custom map")
        return args

    def test_vp_layers_preserve_action_order_overrides_and_all_addins(self):
        args = self.vp_fixture()
        output = self.root / "vp-package"
        with mock.patch.object(pack.subprocess, "check_output", return_value="test-commit\n"):
            report = pack.build(*args, output, include_runtime=True, include_vp=True)
        self.assertEqual(report["content"], "vox-populi")
        self.assertEqual(len(report["actions"]), 3)
        self.assertEqual(pack.xml(output / "Override/CIV5Units.xml").find("./NewData/Row/ID").text, "80")
        self.assertEqual(pack.xml(output / "Override/CIV5Units_Mongol.xml").find("./Language_en_US/Row/Text").text, "balanced")
        consumer = (output / "UI/InGame.lua").read_text()
        self.assertIn("VP consumer", consumer)
        for name in ["Panel", "Logic", "Balance"]:
            self.assertIn('g_uiAddins[#g_uiAddins + 1] = "' + name + '";', consumer)
        self.assertTrue((output / "Mods/02_(2) Vox Populi/Map.lua").is_file())
        self.assertEqual(report["runtime_assets"]["map_scripts"], ["Map.lua"])
        self.assertEqual((output / "Mods/02_(2) Vox Populi/Art/texture.dds").read_bytes(), b"VP texture")
        self.assertTrue((output / "Mods/01_(1) Community Patch/Art/texture.dds").is_file())

    def test_vp_dependency_version_and_missing_runtime_are_rejected(self):
        args = self.vp_fixture()
        output = self.root / "vp-package"
        with self.assertRaisesRegex(pack.PackageError, "requires --runtime-assets"):
            pack.build(*args, output, include_vp=True)
        manifest = args[0] / "(2) Vox Populi/VP.modinfo"
        tree = ET.parse(manifest)
        tree.find("./Dependencies/Mod").set("minversion", "999")
        tree.write(manifest)
        with self.assertRaisesRegex(pack.PackageError, "incompatible mod dependency"):
            pack.build(*args, output, include_runtime=True, include_vp=True)
        self.assertFalse(output.exists())

    def eui_fixture(self):
        args = self.vp_fixture()
        for name in ["(1) Community Patch", "(2) Vox Populi"]:
            mod = args[0] / name
            tree = ET.parse(next(mod.glob("*.modinfo")))
            (mod / "LUA").mkdir()
            (mod / "LUA/UnitPanel.lua").write_text("-- standard UI must not load with EUI")
            ET.SubElement(tree.find("./Files"), "File", {"import": "1"}).text = "LUA/UnitPanel.lua"
            tree.write(next(mod.glob("*.modinfo")))
        compat = args[0] / "(3a) VP - EUI Compatibility Files"
        compat.mkdir()
        (compat / "EUI.modinfo").write_text('''<Mod id="24923240-e4fb-4bf6-8f0e-6e5b6cf4d3c2" version="1">
          <Dependencies><Mod id="8411a7a8-dad3-4622-a18e-fcc18324c799" minversion="17"/></Dependencies>
          <Actions><OnModActivated><UpdateDatabase>text.xml</UpdateDatabase></OnModActivated></Actions>
          <Files><File import="1">LUA/UnitPanel.lua</File><File import="1">LUA/InGame.lua</File></Files></Mod>''')
        (compat / "text.xml").write_text('<GameData><Language_en_US><Replace Tag="TAG" Text="EUI"/></Language_en_US></GameData>')
        (compat / "LUA").mkdir()
        (compat / "LUA/UnitPanel.lua").write_text("-- EUI compatibility panel")
        (compat / "LUA/InGame.lua").write_text("local g_uiAddins = {}; -- EUI consumer\n")
        for name, manifest in [("UI_bc1", "EUI_2.Civ5Pkg"), ("VPUI", "VPUI_2.Civ5Pkg")]:
            directory = args[0] / name
            (directory / "Core").mkdir(parents=True)
            (directory / "Core" / (name + ".xml")).write_text("<Context/>")
            (directory / manifest).write_text('''<Civ5Package>
              <UISkin name="Expansion2Primary" set="Expansion2" platform="Common">
              <Skin><Directory>Core</Directory></Skin></UISkin></Civ5Package>''')
        (args[0] / "UI_bc1/Core/UnitPanel.lua").write_text("-- base EUI panel must not shadow VP compatibility")
        (args[0] / "UI_bc1/Core/InGame.lua").write_text("-- base consumer without VP addins")
        (args[0] / "VPUI Text").mkdir()
        (args[0] / "VPUI Text/VPUI_tips_en_us.xml").write_text('<GameData><Language_en_US><Replace Tag="TIP" Text="VP tip"/></Language_en_US></GameData>')
        return args

    def test_eui_build_loads_compatibility_last_and_excludes_standard_lua(self):
        args = self.eui_fixture()
        before = {p: pack.sha256(p) for p in args[0].rglob("*") if p.is_file()}
        output = self.root / "eui-package"
        with mock.patch.object(pack.subprocess, "check_output", return_value="test-commit\n"):
            report = pack.build(*args, output, include_runtime=True, include_vp=True, include_eui=True)
        self.assertEqual(report["interface"], "eui")
        self.assertEqual(report["mods"][-1]["directory"], "(3a) VP - EUI Compatibility Files")
        for name in ["01_(1) Community Patch", "02_(2) Vox Populi"]:
            self.assertFalse((output / "Mods" / name / "LUA").exists())
        self.assertEqual((output / "Mods/03_(3a) VP - EUI Compatibility Files/LUA/UnitPanel.lua").read_text(), "-- EUI compatibility panel")
        self.assertEqual((output / "Interface/UI_bc1/Core/UnitPanel.lua").read_text(), "-- EUI compatibility panel")
        consumer = (output / "UI/InGame.lua").read_text()
        self.assertIn("EUI consumer", consumer)
        for context in ["Panel", "Logic", "Balance"]:
            self.assertIn(f'g_uiAddins[#g_uiAddins + 1] = "{context}";', consumer)
        self.assertEqual((output / "Interface/UI_bc1/Core/InGame.lua").read_text(), consumer)
        self.assertEqual({n["target"] for n in report["interface_overrides"]},
                         {"Interface/UI_bc1/Core/InGame.lua", "Interface/UI_bc1/Core/UnitPanel.lua"})
        skin = pack.xml(output / "VPMac.Civ5Pkg").find("UISkin")
        self.assertEqual([n.text for n in skin.findall("./Skin/Directory")], ["Interface/UI_bc1/Core", "Interface/VPUI/Core"])
        self.assertEqual([n.text for n in skin.findall("./GameplaySkin/Directory")], ["Mods", "UI"])
        self.assertEqual(list(output.rglob("*.Civ5Pkg")), [output / "VPMac.Civ5Pkg"])
        text = pack.xml(output / "Override/CIV5Units_Mongol.xml")
        values = {n.findtext("Tag"): n.findtext("Text") for n in text.findall("./Language_en_US/Row")}
        self.assertEqual(values, {"TAG": "EUI", "TIP": "VP tip"})
        self.assertEqual({p: pack.sha256(p) for p in before}, before)
        for name, sha in report["files"].items():
            self.assertEqual(pack.sha256(output / name), sha)

    def test_eui_requires_full_vp_and_refuses_unsafe_skin_or_changed_contract(self):
        args = self.eui_fixture()
        output = self.root / "rejected"
        with self.assertRaisesRegex(pack.PackageError, "requires --vox-populi"):
            pack.build(*args, output, include_runtime=True, include_eui=True)
        manifest = args[0] / "UI_bc1/EUI_2.Civ5Pkg"
        original = manifest.read_text()
        for changed, error in [(original.replace("Core</", "../outside</"), "Unsafe interface directory"),
                               (original.replace("<Skin>", "<GameplaySkin>").replace("</Skin>", "</GameplaySkin>"), "Unsupported interface directory")]:
            manifest.write_text(changed)
            with self.assertRaisesRegex(pack.PackageError, error):
                pack.build(*args, output, include_runtime=True, include_vp=True, include_eui=True)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
