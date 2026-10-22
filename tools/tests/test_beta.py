#!/usr/bin/env python3
"""Player-entry-point and release integrity checks, using isolated fixtures."""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import tarfile
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


player = load("beta_player", "vp-mac.py")
release = load("make_beta", "tools/make_beta.py")
sys.modules["make_beta"] = release
gui = load("make_gui", "tools/make_gui.py")


class BetaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="VP beta with spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / "Steam Library/Civilization V.app"

    def payload(self, packaged=True, eui=False):
        name = "VP_MAC_VP_EUI" if eui else "VP_MAC_VP"
        if packaged:
            core = self.root / "payload" / player.CORE
            package = self.root / "payload" / name
        else:
            core = self.root / "prototype/build-core/macos" / player.CORE
            package = self.root / "prototype/build-core" / (name + "-gameplay-probe")
        core.parent.mkdir(parents=True, exist_ok=True)
        core.write_bytes(b"fixture core")
        package.mkdir(parents=True)
        (package / "example.xml").write_text("<GameData/>")
        (package / "UI").mkdir()
        (package / "UI/VPMacCamera.lua").write_bytes((ROOT / "macos/runtime/VPMacCamera.lua").read_bytes())
        (package / "UI/WorldView.lua").write_text("-- generated camera context fixture")
        metadata = {"content": "vox-populi", "gameplay_test_ready": True,
                    "interface": "eui" if eui else "standard",
                    "camera_controls": {"schema": 1, "module_sha256": release.digest(package / "UI/VPMacCamera.lua"),
                                        "world_views": {"UI/WorldView.lua": release.digest(package / "UI/WorldView.lua")}},
                    "native_core_sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
                    "files": release.inventory(package)}
        (package / "vp-mac-package.json").write_text(json.dumps(metadata))
        return core, package

    def args(self, command, dry_run=False, eui=False):
        return argparse.Namespace(command=command, app=self.app, dry_run=dry_run, eui=eui)

    def test_player_uses_release_payload_with_literal_space_paths(self):
        core, package = self.payload()
        command = player.command_for(self.args("install", True), self.root)
        self.assertEqual(command[2], "install-native")
        self.assertEqual(command[command.index("--app") + 1], str(self.app))
        self.assertEqual(command[command.index("--native-core") + 1], str(core))
        self.assertEqual(command[command.index("--data-package") + 1], str(package))
        self.assertEqual(command[-1], "--dry-run")
        self.assertFalse(self.app.exists())

    def test_player_supports_source_build_and_rejects_incomplete_download(self):
        with self.assertRaisesRegex(ValueError, "complete beta archive"):
            player.command_for(self.args("install"), self.root)
        core, package = self.payload(packaged=False)
        self.assertEqual(player.install_payload(self.root), (core, package))

    def test_player_refuses_cp_only_package(self):
        _, package = self.payload()
        path = package / "vp-mac-package.json"
        metadata = json.loads(path.read_text())
        metadata["content"] = "community-patch"
        path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "full Vox Populi"):
            player.install_payload(self.root)

    def test_player_selects_separate_eui_package_and_refuses_mislabeled_payload(self):
        self.payload()
        with self.assertRaisesRegex(ValueError, "complete beta archive"):
            player.command_for(self.args("install", eui=True), self.root)
        core, package = self.payload(eui=True)
        command = player.command_for(self.args("install", dry_run=True, eui=True), self.root)
        self.assertEqual(command[command.index("--data-package") + 1], str(package))
        self.assertEqual(command[command.index("--native-core") + 1], str(core))
        path = package / "vp-mac-package.json"
        data = json.loads(path.read_text())
        data["interface"] = "standard"
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "selected interface"):
            player.command_for(self.args("install", eui=True), self.root)

    def test_eui_source_selection_and_install_only_flag(self):
        core, package = self.payload(packaged=False, eui=True)
        self.assertEqual(player.install_payload(self.root, True), (core, package))
        for command in ["uninstall", "status", "report"]:
            with self.assertRaisesRegex(ValueError, "available for install"):
                player.command_for(self.args(command, eui=True), self.root)

    def test_player_recovery_commands_do_not_require_payload_or_clear_eui(self):
        eui = self.app / "Contents/Assets/Assets/DLC/UI_bc1"
        eui.mkdir(parents=True)
        for name, expected in [("uninstall", "restore"), ("status", "status"), ("report", "native-report")]:
            self.assertEqual(player.command_for(self.args(name), self.root)[2], expected)
        with self.assertRaisesRegex(ValueError, "install and uninstall"):
            player.command_for(self.args("report", True), self.root)

    def test_release_refuses_changed_or_extra_package_files(self):
        core, package = self.payload()
        self.assertEqual(release.validate_package(core, package)["content"], "vox-populi")
        (package / "unexpected.lua").write_text("unexpected")
        with self.assertRaisesRegex(ValueError, "inventory differs"):
            release.validate_package(core, package)
        (package / "unexpected.lua").unlink()
        (package / "example.xml").write_text("changed")
        with self.assertRaisesRegex(ValueError, "inventory differs"):
            release.validate_package(core, package)

    def test_release_refuses_mismatched_core_and_symlinks(self):
        core, package = self.payload()
        core.write_bytes(b"different core")
        with self.assertRaisesRegex(ValueError, "hashes differ"):
            release.validate_package(core, package)
        (package / "linked.xml").symlink_to(package / "example.xml")
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            release.inventory(package)

    def test_release_refuses_stale_camera_payload_even_with_a_matching_inventory(self):
        core, package = self.payload()
        path = package / "vp-mac-package.json"
        metadata = json.loads(path.read_text())
        metadata.pop("camera_controls")
        path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "matching WASD camera controls"):
            release.validate_package(core, package)
        with self.assertRaisesRegex(ValueError, "Matching WASD camera files"):
            player.install_payload(self.root)

    def test_eui_release_refuses_unresolved_or_mismatched_skin_files(self):
        core, package = self.payload(eui=True)
        with self.assertRaisesRegex(ValueError, "resolved skin overrides are missing"):
            release.validate_package(core, package)
        target = package / "Interface/Panel.xml"
        target.parent.mkdir()
        target.write_bytes((package / "example.xml").read_bytes())
        path = package / "vp-mac-package.json"
        metadata = json.loads(path.read_text())
        metadata["files"] = {k: v for k, v in release.inventory(package).items() if k != path.name}
        metadata["interface_overrides"] = [{"target": "Interface/Panel.xml", "source": "example.xml",
                                            "sha256": metadata["files"]["example.xml"]}]
        path.write_text(json.dumps(metadata))
        release.validate_package(core, package)
        target.write_text("<Context/>")
        metadata["files"]["Interface/Panel.xml"] = release.digest(target)
        path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "skin overrides differ"):
            release.validate_package(core, package)

    def test_release_refuses_executables_even_with_matching_inventory(self):
        core, package = self.payload()
        (package / "foreign.dll").write_bytes(b"MZ")
        path = package / "vp-mac-package.json"
        data = json.loads(path.read_text())
        data["files"] = {k: v for k, v in release.inventory(package).items() if k != path.name}
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "Unexpected executable"):
            release.validate_package(core, package)

    def test_runtime_internal_links_are_materialized(self):
        archive = self.root / "runtime.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            item = tarfile.TarInfo("python/bin/python3.13")
            item.size = 4
            item.mode = 0o755
            bundle.addfile(item, io.BytesIO(b"test"))
            link = tarfile.TarInfo("python/bin/python3")
            link.type = tarfile.SYMTYPE
            link.linkname = "python3.13"
            bundle.addfile(link)
        destination = self.root / "runtime"
        gui.extract_runtime(archive, destination)
        self.assertFalse((destination / "bin/python3").is_symlink())
        self.assertEqual((destination / "bin/python3").read_bytes(), b"test")

    def test_runtime_traversal_and_external_links_are_rejected(self):
        for name, target in [("python/../../escape", None), ("python/bin/link", "../../../escape")]:
            with self.subTest(name=name):
                archive = self.root / "bad.tar.gz"
                with tarfile.open(archive, "w:gz") as bundle:
                    item = tarfile.TarInfo(name)
                    if target:
                        item.type, item.linkname = tarfile.SYMTYPE, target
                    bundle.addfile(item)
                with self.assertRaises((ValueError, tarfile.TarError)):
                    gui.extract_runtime(archive, self.root / "rejected")
                self.assertFalse((self.root.parent / "escape").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
