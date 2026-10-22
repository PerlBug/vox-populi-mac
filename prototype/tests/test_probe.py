#!/usr/bin/env python3
"""Exercise native loading and reversible installation using synthetic cores."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock

parser = argparse.ArgumentParser()
for argument in ["wrapper", "host", "stock", "no-entry"]:
    parser.add_argument("--" + argument, required=True, type=Path)
ARGS = parser.parse_args()
spec = importlib.util.spec_from_file_location("probe_manage", Path(__file__).parents[1] / "manage.py")
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vox pop probe ")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.app = self.directory / "Civilization V.app"
        self.core, self.backup, self.manifest = manage.paths(self.app)
        self.core.parent.mkdir(parents=True)
        self.log = self.directory / "probe log.txt"

    def launch(self, expect_failure=False, log=None, stress=False):
        environment = dict(os.environ, VOX_POP_MAC_PROBE_LOG=str(log or self.log))
        result = subprocess.run([str(ARGS.host), str(self.core),
                                 "failure" if expect_failure else "stress" if stress else "success"],
                                cwd="/", env=environment, capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return self.log.read_text() if self.log.exists() else ""


class LoaderTests(Fixture):
    def setUp(self):
        super().setUp()
        shutil.copy2(ARGS.wrapper, self.core)

    def test_forwarding_host_imports_and_two_unload_cycles(self):
        shutil.copy2(ARGS.stock, self.backup)
        text = self.launch()
        self.assertEqual(text.count("event=wrapper_loaded "), 2)
        self.assertEqual(text.count("event=context_forwarded "), 6)
        self.assertEqual(text.count("symbol=timeGetTime available=yes"), 2)
        self.assertEqual(text.count("event=original_unloaded"), 2)
        self.assertEqual(text.count("fixture_unloaded"), 2)
        self.assertNotIn("failed", text)

    def test_missing_original_fails_without_recursion(self):
        text = self.launch(expect_failure=True)
        self.assertIn("event=original_open_failed", text)
        self.assertEqual(text.count("event=forward_failed"), 6)

    def test_hot_context_path_keeps_log_small(self):
        shutil.copy2(ARGS.stock, self.backup)
        text = self.launch(stress=True)
        self.assertLess(text.count("event=context_forwarded"), 50)
        self.assertLess(self.log.stat().st_size, 16000)
        self.assertEqual(text.count("forwarded_calls=100000"), 2)

    def test_missing_entry_point_is_reported(self):
        shutil.copy2(ARGS.no_entry, self.backup)
        text = self.launch(expect_failure=True)
        self.assertIn("event=original_symbol_failed", text)

    def test_self_copy_does_not_recurse(self):
        shutil.copy2(ARGS.wrapper, self.backup)
        text = self.launch(expect_failure=True)
        self.assertIn("event=original_recursion_refused", text)

    def test_unavailable_log_does_not_change_forwarding(self):
        shutil.copy2(ARGS.stock, self.backup)
        text = self.launch(log=self.directory / "missing directory/log.txt")
        self.assertEqual(text, "")


class InstallerTests(Fixture):
    def setUp(self):
        super().setUp()
        shutil.copy2(ARGS.stock, self.core)
        self.original = self.core.read_bytes()
        # Synthetic app transactions need no access to the machine's process list.
        self.stopped = mock.patch.object(manage, "ensure_game_stopped")
        self.stopped.start()
        self.addCleanup(self.stopped.stop)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def install(self, dry_run=False):
        manage.install(self.app, ARGS.wrapper, dry_run)

    def test_dry_run_does_not_write_any_files(self):
        self.install(dry_run=True)
        self.assertEqual(self.core.read_bytes(), self.original)
        self.assertFalse(self.backup.exists())
        self.assertFalse(self.manifest.exists())

    def test_install_idempotence_and_byte_exact_restore(self):
        self.install()
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(self.core.read_bytes(), ARGS.wrapper.read_bytes())
        self.install()
        manage.restore(self.app, dry_run=True)
        self.assertEqual(self.core.read_bytes(), ARGS.wrapper.read_bytes())
        manage.restore(self.app)
        self.assertEqual(self.core.read_bytes(), self.original)
        self.assertFalse(self.backup.exists())
        self.assertFalse(self.manifest.exists())
        manage.restore(self.app)  # already restored is a no-op

    def test_external_update_is_never_overwritten(self):
        self.install()
        self.core.write_bytes(b"new Steam core")
        with self.assertRaisesRegex(manage.ProbeError, "changed after"):
            manage.restore(self.app)
        self.assertEqual(self.core.read_bytes(), b"new Steam core")
        self.assertEqual(self.backup.read_bytes(), self.original)

    def test_corrupt_backup_blocks_install_and_restore(self):
        self.install()
        self.backup.write_bytes(b"corrupt backup")
        for action in [self.install, lambda: manage.restore(self.app)]:
            with self.assertRaisesRegex(manage.ProbeError, "backup hash"):
                action()
        self.assertEqual(self.core.read_bytes(), ARGS.wrapper.read_bytes())

    def test_interrupted_install_can_restore_prepared_backup(self):
        with mock.patch.object(manage, "atomic_copy", side_effect=OSError("interrupted")):
            with self.assertRaisesRegex(OSError, "interrupted"):
                self.install()
        self.assertTrue(self.manifest.exists())
        self.assertEqual(self.core.read_bytes(), self.original)
        manage.restore(self.app)
        self.assertEqual(self.core.read_bytes(), self.original)
        self.assertFalse(self.manifest.exists())

    def test_untracked_backup_is_preserved(self):
        self.backup.write_bytes(b"existing backup")
        with self.assertRaisesRegex(manage.ProbeError, "untracked original"):
            self.install()
        self.assertEqual(self.backup.read_bytes(), b"existing backup")
        self.assertEqual(self.core.read_bytes(), self.original)

    def test_stock_symlink_is_refused(self):
        self.core.unlink()
        self.core.symlink_to(ARGS.stock)
        with self.assertRaisesRegex(manage.ProbeError, "not a symlink"):
            self.install()
        self.assertFalse(self.backup.exists())

    def test_wrapper_cannot_be_backed_up_as_stock(self):
        shutil.copy2(ARGS.wrapper, self.core)
        with self.assertRaisesRegex(manage.ProbeError, "managed core as stock"):
            self.install()

    def native_fixture(self):
        fixture = self.directory / "native fixture.dylib"
        replacement = manage.NATIVE_MARKER.ljust(len(manage.MARKER), b"\0")
        fixture.write_bytes(ARGS.wrapper.read_bytes().replace(manage.MARKER, replacement))
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(fixture)], check=True, capture_output=True)
        return fixture

    def test_native_install_and_restore_use_the_same_verified_transaction(self):
        fixture = self.native_fixture()
        with mock.patch.object(manage, "validate_native_host") as host_check, mock.patch.object(manage, "validate_native_core") as core_check:
            manage.install(self.app, fixture, expected_marker=manage.NATIVE_MARKER)
        host_check.assert_called_once_with(self.app.resolve())
        core_check.assert_called_once_with(fixture)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(manage.load_manifest(self.manifest)["core_kind"], "native")
        manage.restore(self.app)
        self.assertEqual(self.core.read_bytes(), self.original)

    def test_native_marker_is_never_backed_up_as_stock(self):
        shutil.copy2(self.native_fixture(), self.core)
        with self.assertRaisesRegex(manage.ProbeError, "managed core as stock"):
            self.install()
        self.assertFalse(self.backup.exists())

    def test_native_host_rejection_leaves_game_untouched(self):
        with mock.patch.object(manage, "validate_native_host", side_effect=manage.ProbeError("unreviewed host")):
            with self.assertRaisesRegex(manage.ProbeError, "unreviewed host"):
                manage.install(self.app, self.native_fixture(), expected_marker=manage.NATIVE_MARKER)
        self.assertEqual(self.core.read_bytes(), self.original)
        self.assertFalse(self.backup.exists())
        self.assertFalse(self.manifest.exists())

    def test_native_vtable_rejection_leaves_game_untouched(self):
        with mock.patch.object(manage, "validate_native_host"), mock.patch.object(manage, "validate_native_core", side_effect=manage.ProbeError("Core ABI mismatch")):
            with self.assertRaisesRegex(manage.ProbeError, "Core ABI mismatch"):
                manage.install(self.app, self.native_fixture(), expected_marker=manage.NATIVE_MARKER)
        self.assertEqual(self.core.read_bytes(), self.original)
        self.assertFalse(self.backup.exists())


class ProcessGuardTests(unittest.TestCase):
    def test_running_game_is_refused(self):
        app = Path("/tmp/Civilization V.app")
        snapshot = "123 /tmp/Civilization V.app/Contents/MacOS/Civilization V\n"
        with mock.patch.object(manage, "checked", return_value=snapshot):
            with self.assertRaisesRegex(manage.ProbeError, "123"):
                manage.ensure_game_stopped(app)

    def test_process_inspection_failure_is_not_ignored(self):
        with mock.patch.object(manage, "checked", side_effect=manage.ProbeError("ps unavailable")):
            with self.assertRaisesRegex(manage.ProbeError, "ps unavailable"):
                manage.ensure_game_stopped(Path("/tmp/Civilization V.app"))


class NativeDataTests(Fixture):
    def setUp(self):
        super().setUp()
        shutil.copy2(ARGS.stock, self.core)
        self.original = self.core.read_bytes()
        self.package = self.directory / "package"
        self.package.mkdir()
        (self.package / "VPMac.Civ5Pkg").write_text("<Civ5Package/>")
        metadata = {"schema": 1, "kind": "cp-startup-data", "upstream_commit": "fixture",
                    "native_core_sha256": manage.digest(ARGS.wrapper),
                    "files": manage.tree_hashes(self.package)}
        (self.package / manage.DATA_MANIFEST).write_text(json.dumps(metadata))
        self.user_data = self.directory / "user data"
        self.cache = self.user_data / "cache"
        self.cache.mkdir(parents=True)
        (self.cache / "stock.db").write_bytes(b"original cache")
        (self.cache / "Civ5CoreDatabase.db").write_bytes(b"old gameplay cache")
        with sqlite3.connect(self.cache / "Localization-Merged.db") as db:
            db.executescript("CREATE TABLE Languages(Type text); INSERT INTO Languages VALUES ('en_US'); CREATE TABLE LocalizedText(Tag text,Text text); INSERT INTO LocalizedText VALUES ('TAG','English');")
        (self.cache / "Localization-BaseGame.db").write_bytes(b"base language fixture")
        (self.app / "Contents/Assets/Assets/DLC").mkdir(parents=True)
        self.plan = manage.prepare_native_data(self.app, self.package, self.user_data, ARGS.wrapper)
        self.target, _, self.cache_backup = manage.data_paths(self.app, self.plan)
        stopped = mock.patch.object(manage, "ensure_game_stopped")
        stopped.start()
        self.addCleanup(stopped.stop)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def install(self, dry_run=False):
        # The shared transaction is independent of native Mach-O validation;
        # existing tests above separately validate the native marker/profile.
        manage.install(self.app, ARGS.wrapper, dry_run=dry_run, native_data=self.plan, package=self.package)

    def test_install_and_restore_data_and_cache_without_deleting_test_history(self):
        self.install()
        self.assertTrue(self.target.exists())
        self.assertTrue(self.cache.exists())
        self.assertFalse((self.cache / "Civ5CoreDatabase.db").exists())
        for name in self.plan["localization_cache_files"]:
            self.assertEqual((self.cache / name).read_bytes(), (self.cache_backup / name).read_bytes())
            self.assertEqual((self.cache / name).stat().st_mtime_ns, (self.cache_backup / name).stat().st_mtime_ns)
        self.assertEqual((self.cache_backup / "stock.db").read_bytes(), b"original cache")
        (self.cache / "new.db").write_bytes(b"new session")
        manage.restore(self.app)
        self.assertEqual(self.core.read_bytes(), self.original)
        self.assertFalse(self.target.exists())
        self.assertEqual((self.cache / "stock.db").read_bytes(), b"original cache")
        sessions = list(self.user_data.glob("cache.vp-mac-session-*"))
        self.assertEqual((sessions[0] / "new.db").read_bytes(), b"new session")

    def test_dry_run_keeps_data_cache_and_core_intact(self):
        self.install(dry_run=True)
        self.assertTrue(self.cache.exists())
        self.assertFalse(self.cache_backup.exists())
        self.assertFalse(self.target.exists())
        self.assertEqual(self.core.read_bytes(), self.original)

    def test_separate_eui_and_vpui_are_preserved_and_refused_for_both_interfaces(self):
        dlc = self.target.parent
        for name in ["custom/UI_Bc1", "VPUI"]:
            directory = dlc / name
            directory.mkdir(parents=True)
            keep = directory / "keep.lua"
            keep.write_text("existing UI")
            for interface in ["standard", "eui"]:
                path = self.package / manage.DATA_MANIFEST
                metadata = json.loads(path.read_text())
                metadata["interface"] = interface
                path.write_text(json.dumps(metadata))
                with self.assertRaisesRegex(manage.ProbeError, "Separate EUI / VPUI"):
                    manage.prepare_native_data(self.app, self.package, self.user_data, ARGS.wrapper)
                self.assertEqual(keep.read_text(), "existing UI")
                self.assertEqual(self.core.read_bytes(), self.original)
                self.assertFalse(self.backup.exists())
            shutil.rmtree(directory)

    def test_renamed_standalone_eui_package_is_refused(self):
        path = self.target.parent / "renamed-interface.civ5pkg"
        path.write_text("<Civ5Package><GUID>{570F793E-FC33-417F-AE19-7CECCCDD5F85}</GUID></Civ5Package>")
        with self.assertRaisesRegex(manage.ProbeError, "Separate EUI / VPUI package"):
            manage.prepare_native_data(self.app, self.package, self.user_data, ARGS.wrapper)
        self.assertTrue(path.exists())

    def test_embedded_eui_uses_verified_transaction_and_is_removed_on_restore(self):
        panel = self.package / "Interface/UI_bc1/Core/EUI_context.lua"
        panel.parent.mkdir(parents=True)
        panel.write_text("-- bundled EUI")
        path = self.package / manage.DATA_MANIFEST
        metadata = json.loads(path.read_text())
        metadata["interface"] = "eui"
        metadata["files"] = {name: sha for name, sha in manage.tree_hashes(self.package).items() if name != manage.DATA_MANIFEST}
        path.write_text(json.dumps(metadata))
        self.plan = manage.prepare_native_data(self.app, self.package, self.user_data, ARGS.wrapper)
        self.install()
        self.assertEqual(manage.load_manifest(self.manifest)["native_data"]["interface"], "eui")
        self.assertEqual((self.target / panel.relative_to(self.package)).read_text(), "-- bundled EUI")
        manage.restore(self.app)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.core.read_bytes(), self.original)

    def enable_gameplay_probe(self, existing=True):
        if existing:
            saves = self.user_data / "Saves/single"
            saves.mkdir(parents=True)
            (saves / "stock.Civ5Save").write_bytes(b"original stock save")
        metadata = json.loads((self.package / manage.DATA_MANIFEST).read_text())
        metadata["native_save"] = json.loads((manage.ROOT.parent / "macos/abi/aspyr-steam-1.4.2.json").read_text())["native_save"]
        metadata["gameplay_test_ready"] = True
        (self.package / manage.DATA_MANIFEST).write_text(json.dumps(metadata))
        self.plan = manage.prepare_native_data(self.app, self.package, self.user_data, ARGS.wrapper)
        return manage.save_paths(self.plan)

    def test_gameplay_probe_isolates_and_restores_stock_saves(self):
        saves, backup = self.enable_gameplay_probe()
        before = manage.tree_hashes(saves)
        self.install()
        self.assertEqual(manage.tree_hashes(saves), {})
        self.assertEqual(manage.tree_hashes(backup), before)
        (saves / "experimental.Civ5Save").write_bytes(b"native save")
        manage.restore(self.app)
        self.assertEqual(manage.tree_hashes(saves), before)
        sessions = list(self.user_data.glob("Saves.vp-mac-session-*"))
        self.assertEqual((sessions[0] / "experimental.Civ5Save").read_bytes(), b"native save")
        self.assertFalse(backup.exists())

    def test_gameplay_probe_without_previous_saves_preserves_new_saves(self):
        saves, backup = self.enable_gameplay_probe(existing=False)
        self.install()
        (saves / "experimental.Civ5Save").write_bytes(b"native save")
        manage.restore(self.app)
        self.assertFalse(saves.exists())
        self.assertFalse(backup.exists())
        self.assertEqual(len(list(self.user_data.glob("Saves.vp-mac-session-*/experimental.Civ5Save"))), 1)

    def test_gameplay_probe_interruption_restores_saves_and_detects_changed_backup(self):
        saves, backup = self.enable_gameplay_probe()
        before = manage.tree_hashes(saves)
        with mock.patch.object(manage.shutil, "copytree", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.install()
        original = (backup / "single/stock.Civ5Save").read_bytes()
        (backup / "single/stock.Civ5Save").write_bytes(b"external edit")
        with self.assertRaisesRegex(manage.ProbeError, "Stock save backup changed"):
            manage.restore(self.app)
        self.assertTrue(self.cache_backup.exists())
        (backup / "single/stock.Civ5Save").write_bytes(original)
        manage.restore(self.app)
        self.assertEqual(manage.tree_hashes(saves), before)

    def test_gameplay_probe_dry_run_keeps_save_folder_intact(self):
        saves, backup = self.enable_gameplay_probe()
        before = manage.tree_hashes(saves)
        self.install(dry_run=True)
        self.assertEqual(manage.tree_hashes(saves), before)
        self.assertFalse(backup.exists())

    def test_core_copy_interruption_can_restore_data_and_cache(self):
        with mock.patch.object(manage, "atomic_copy", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.install()
        manage.restore(self.app)
        self.assertFalse(self.target.exists())
        self.assertTrue(self.cache.exists())

    def test_package_copy_interruption_can_restore_cache(self):
        with mock.patch.object(manage.shutil, "copytree", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.install()
        manage.restore(self.app)
        self.assertTrue(self.cache.exists())
        self.assertFalse(self.cache_backup.exists())

    def test_language_cache_copy_interruption_can_restore_the_entire_stock_cache(self):
        before = manage.tree_hashes(self.cache)
        with mock.patch.object(manage.shutil, "copy2", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.install()
        manage.restore(self.app)
        self.assertEqual(manage.tree_hashes(self.cache), before)

    def test_damaged_merged_language_cache_is_rejected_before_any_install(self):
        (self.cache / "Localization-Merged.db").write_bytes(b"")
        with self.assertRaisesRegex(manage.ProbeError, "localization cache is invalid"):
            manage.prepare_native_data(self.app, self.package, self.user_data, ARGS.wrapper)
        self.assertEqual(self.core.read_bytes(), self.original)
        self.assertFalse(self.backup.exists())

    def test_changed_installed_data_blocks_restore_before_core_changes(self):
        self.install()
        (self.target / "VPMac.Civ5Pkg").write_text("external changes")
        with self.assertRaisesRegex(manage.ProbeError, "native data changed"):
            manage.restore(self.app)
        self.assertEqual(self.core.read_bytes(), ARGS.wrapper.read_bytes())
        self.assertTrue(self.cache_backup.exists())

    def test_restore_can_resume_after_partial_owned_data_cleanup(self):
        self.install()
        (self.target / "VPMac.Civ5Pkg").unlink()
        manage.restore(self.app)
        self.assertEqual(self.core.read_bytes(), self.original)
        self.assertTrue(self.cache.exists())
        self.assertFalse(self.target.exists())

    def test_mismatched_core_and_modified_package_are_rejected(self):
        (self.package / "VPMac.Civ5Pkg").write_text("changed")
        with self.assertRaisesRegex(manage.ProbeError, "files have changed"):
            manage.prepare_native_data(self.app, self.package, self.user_data, ARGS.wrapper)
        with self.assertRaisesRegex(manage.ProbeError, "different core"):
            manage.prepare_native_data(self.app, self.package, self.user_data, ARGS.stock)


class ReportTests(Fixture):
    def test_interrupted_object_check_is_incomplete(self):
        self.log.write_text("pid=2 event=wrapper_loaded probe\n"
                            "pid=2 event=abi_probe_started checks=6\n"
                            "pid=2 event=abi_context passed\n"
                            "pid=2 event=abi_stream passed\n")
        report = manage.probe_report(self.log)
        self.assertEqual(report["abi_result"], "incomplete")
        self.assertFalse(report["clean_unload"])

    def test_database_and_localization_results_are_reported(self):
        self.log.write_text("pid=2 event=wrapper_loaded probe\n"
                            "pid=2 event=abi_probe_started checks=6\n"
                            "pid=2 event=abi_database passed guards=intact\n"
                            "pid=2 event=abi_localization failed\n"
                            "pid=2 event=abi_probe_failed checks=6\n")
        report = manage.probe_report(self.log)
        self.assertEqual(report["abi_result"], "failed")
        self.assertEqual(report["abi_checks"], {"abi_database": "passed", "abi_localization": "failed"})
        self.assertEqual(len(report["failures"]), 2)

    def test_only_latest_session_is_reported(self):
        self.log.write_text("pid=1 event=wrapper_loaded old\n"
                            "pid=1 event=abi_probe_failed old failure\n"
                            "pid=2 event=wrapper_loaded new\n"
                            "pid=2 event=original_ready path\n"
                            "pid=2 event=context_forwarded call=8 context=0x123\n"
                            "pid=2 event=abi_context passed interfaces=4\n"
                            "pid=2 event=abi_probe_passed checks=4\n"
                            "pid=2 event=original_unloading forwarded_calls=12\n"
                            "pid=2 event=wrapper_unloaded\n")
        report = manage.probe_report(self.log)
        self.assertEqual(report["pid"], 2)
        self.assertEqual(report["abi_result"], "passed")
        self.assertEqual(report["last_forward_call"], 12)
        self.assertTrue(report["clean_unload"])
        self.assertEqual(report["failures"], [])

    def test_unreviewed_profile_is_not_reported_as_passed(self):
        self.log.write_text("pid=2 event=wrapper_loaded probe\n"
                            "pid=2 event=abi_profile_skipped reason=unknown\n")
        self.assertEqual(manage.probe_report(self.log)["abi_result"], "skipped_unreviewed_images")


class NativeReportTests(Fixture):
    def events(self, names, pid=42):
        with self.log.open("a") as output:
            for name in names:
                output.write(json.dumps({"pid": pid, "event": "native_" + name}) + "\n")

    def test_complete_native_session_is_passed(self):
        self.events(["loaded", "profile_passed", "lock_passed", "stream_passed", "database_passed", "save_identity_passed", "context_ready", "lua_passed", "game_data_passed", "context_destroyed"])
        self.assertEqual(manage.native_report(self.log)["startup_result"], "passed")

    def test_save_header_events_are_counted_without_claiming_full_reload(self):
        self.events(["loaded", "save_identity_passed", "save_header_written", "save_header_written", "save_header_read"])
        report = manage.native_report(self.log)
        self.assertEqual(report["save_headers_written"], 2)
        self.assertEqual(report["save_headers_read"], 1)
        self.assertEqual(report["startup_result"], "incomplete")

    def test_mismatched_save_identity_fails_before_gameplay(self):
        self.events(["loaded", "profile_passed", "save_identity_failed"])
        report = manage.native_report(self.log)
        self.assertEqual(report["save_identity"], "failed")
        self.assertEqual(report["failures"], ["native_save_identity_failed"])
        self.assertEqual(report["startup_result"], "failed")

    def test_lock_failure_is_reported_before_context_construction(self):
        self.events(["loaded", "profile_passed", "lock_failed"])
        report = manage.native_report(self.log)
        self.assertEqual(report["lock_bridge"], "failed")
        self.assertEqual(report["startup_result"], "failed")
        self.assertFalse(report["context_ready"])
        self.assertEqual(report["failures"], ["native_lock_failed"])

    def test_session_without_new_lock_check_stays_incomplete(self):
        self.events(["loaded", "profile_passed", "stream_passed", "database_passed", "context_ready", "lua_passed", "game_data_passed", "context_destroyed"])
        report = manage.native_report(self.log)
        self.assertEqual(report["lock_bridge"], "not_run")
        self.assertEqual(report["startup_result"], "incomplete")

    def test_clean_exit_without_lua_check_is_incomplete(self):
        self.events(["loaded", "profile_passed", "stream_passed", "database_passed", "context_ready", "context_destroyed"])
        self.assertEqual(manage.native_report(self.log)["startup_result"], "incomplete")

    def test_latest_native_session_and_failures_are_kept(self):
        self.events(["loaded", "profile_passed", "stream_passed", "database_passed", "context_ready", "lua_passed", "context_destroyed"])
        self.events(["loaded", "profile_failed"], pid=43)
        report = manage.native_report(self.log)
        self.assertEqual(report["pid"], 43)
        self.assertEqual(report["startup_result"], "failed")
        self.assertFalse(report["context_ready"])
        self.assertEqual(report["failures"], ["native_profile_failed"])

    def test_fatal_precondition_retains_query_and_marks_startup_failed(self):
        self.events(["loaded", "profile_passed", "context_ready"])
        message = 'Failed query "table"\nno such table: missing'
        with self.log.open("a") as output:
            output.write(json.dumps({"pid": 42, "event": "native_precondition_failed", "detail": message}) + "\n")
        report = manage.native_report(self.log)
        self.assertEqual(report["startup_result"], "failed")
        self.assertEqual(report["failures"][0]["detail"], message)

    def test_bridge_success_without_game_data_is_incomplete(self):
        self.events(["loaded", "profile_passed", "stream_passed", "database_passed", "context_ready", "lua_passed", "context_destroyed"])
        self.assertEqual(manage.native_report(self.log)["startup_result"], "incomplete")

    def crash_file(self, pid=42):
        directory = self.directory / "DiagnosticReports"
        directory.mkdir(exist_ok=True)
        path = directory / "Civilization V-test.ips"
        data = {"pid": pid, "procName": "Civilization V", "exception": {"signal": "SIGSEGV"},
                "faultingThread": 0, "threads": [{"frames": [{"imageIndex": 0, "symbol": "CvDllPreGame::setVersionString", "imageOffset": 123}]}],
                "usedImages": [{"name": manage.CORE}]}
        path.write_text(json.dumps({"app_name": "Civilization V"}) + "\n" + json.dumps(data))
        return directory, path

    def test_matching_native_crash_marks_startup_failed_and_keeps_passed_checks(self):
        self.events(["loaded", "profile_passed", "stream_passed", "database_passed", "context_ready", "lua_passed", "game_data_passed"])
        directory, _ = self.crash_file()
        report = manage.native_report(self.log, directory)
        self.assertEqual(report["game_data"], "passed")
        self.assertEqual(report["startup_result"], "failed")
        self.assertIn("native_process_crashed", report["failures"])
        self.assertEqual(report["crash"]["native_frame"]["symbol"], "CvDllPreGame::setVersionString")

    def test_other_pid_and_old_pid_reuse_crashes_do_not_change_report(self):
        self.events(["loaded", "profile_passed"])
        directory, path = self.crash_file(pid=43)
        self.assertNotIn("crash", manage.native_report(self.log, directory))
        self.crash_file(pid=42)
        old = self.log.stat().st_mtime - 60
        os.utime(path, (old, old))
        self.assertEqual(manage.native_report(self.log, directory)["startup_result"], "incomplete")

    def test_new_installation_cannot_report_an_old_success(self):
        self.events(["loaded", "profile_passed", "stream_passed", "database_passed", "context_ready", "lua_passed", "context_destroyed"])
        manage.prepare_native_log(self.log)
        self.assertEqual(manage.native_report(self.log)["startup_result"], "not_started")
        self.events(["loaded", "profile_passed"], pid=43)
        self.assertEqual(manage.native_report(self.log)["startup_result"], "incomplete")

    def test_engine_localization_failure_is_reported_before_native_entry(self):
        manage.prepare_native_log(self.log)
        (self.directory / "Database.log").write_text("[18.3] Failed to Load database.\n[18.3] no such table: Languages\n")
        (self.directory / "Localization.log").write_text("[18.3] ERR: Languages table not found or is empty.\n")
        report = manage.native_report(self.log, engine_log_directory=self.directory)
        self.assertEqual(report["startup_result"], "failed")
        self.assertEqual(report["stage"], "before_native_entry")
        self.assertFalse(report["native_core"])
        self.assertIn("Languages table not found", report["failures"][1]["detail"])

    def test_old_engine_errors_are_excluded_from_a_new_unstarted_test(self):
        (self.directory / "Database.log").write_text("Failed to Load database.\n")
        old = self.log.parent.stat().st_mtime - 60
        os.utime(self.directory / "Database.log", (old, old))
        manage.prepare_native_log(self.log)
        report = manage.native_report(self.log, engine_log_directory=self.directory)
        self.assertEqual(report["startup_result"], "not_started")
        self.assertEqual(report["failures"], [])


if __name__ == "__main__":
    unittest.main(argv=[__file__], verbosity=2)
