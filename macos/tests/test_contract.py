#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sdk_contract", ROOT / "tools/sdk_contract.py")
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)
parser = argparse.ArgumentParser()
parser.add_argument("--upstream", required=True, type=Path)
parser.add_argument("--compiler", default="clang++")
ARGS = parser.parse_args()


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vp-sdk-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.upstream = self.workspace / "upstream"
        self.upstream.mkdir()
        self.profile = json.loads(sdk.DEFAULT_PROFILE.read_text())
        for relative in set(self.profile["upstream"].values()) | set(self.profile.get("sdk_projection_headers", [])):
            destination = self.upstream / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ARGS.upstream / relative, destination)
        for edit in json.loads(sdk.OVERLAYS.read_text())["edits"]:
            destination = self.upstream / edit["source"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ARGS.upstream / edit["source"], destination)

    def edit(self, key, old, new):
        path = self.upstream / self.profile["upstream"][key]
        text = path.read_bytes().decode("latin-1")
        self.assertIn(old, text)
        path.write_bytes(text.replace(old, new, 1).encode("latin-1"))

    def test_current_sdk_generates_without_windows_headers(self):
        text = sdk.generate(self.upstream, self.profile)
        self.assertIn("class ContextPrefix", text)
        self.assertIn("class StreamView", text)
        self.assertNotIn("__stdcall", text)
        self.assertNotIn("Windows.h", text)

    def test_gameplay_changes_do_not_pin_a_git_revision(self):
        before = sdk.generate(self.upstream, self.profile)
        (self.upstream / "CvGameplayChanged.cpp").write_text("// independently updated gameplay\n")
        self.assertEqual(sdk.generate(self.upstream, self.profile), before)

    def test_comments_and_spacing_do_not_break_contract(self):
        self.edit("interfaces", "virtual void* DLLCALL QueryInterface", "virtual /* comment */ void *   DLLCALL QueryInterface")
        sdk.check(self.upstream, self.profile)

    def test_inserted_base_virtual_is_rejected(self):
        self.edit("interfaces", "virtual void* DLLCALL QueryInterface", "virtual void NewSlot() = 0; virtual void* DLLCALL QueryInterface")
        with self.assertRaisesRegex(sdk.ContractError, "unknown_virtuals"):
            sdk.check(self.upstream, self.profile)

    def test_context_slot_shift_is_rejected(self):
        self.edit("interfaces", "virtual GUID DLLCALL GetDLLGUID()", "virtual void NewSlot() = 0; virtual GUID DLLCALL GetDLLGUID()")
        with self.assertRaisesRegex(sdk.ContractError, "context_prefix"):
            sdk.check(self.upstream, self.profile)

    def test_pregame_slot_insertion_is_rejected_before_generation(self):
        self.edit("interfaces", "virtual EraTypes DLLCALL era() = 0;",
                  "virtual int AddedSlot() = 0; virtual EraTypes DLLCALL era() = 0;")
        with self.assertRaisesRegex(sdk.ContractError, "ICvPreGame1"):
            sdk.prepare(self.upstream, self.profile, self.workspace / "generated")

    def test_mac_pregame_slot_is_inserted_before_all_later_methods(self):
        output = self.workspace / "generated"
        sdk.prepare(self.upstream, self.profile, output)
        original = self.upstream / "CvGameCoreDLLUtil/include/CvDllInterfaces.h"
        before = original.read_bytes()
        adapted = (output / "sdk/CvDllInterfaces.h").read_text()
        methods = sdk.virtuals(adapted, "ICvPreGame1")
        self.assertIn("era()", methods[25])
        self.assertIn("vpMacEraType()", methods[26])
        self.assertIn("findPlayerByNickname", methods[27])
        self.assertIn("SetCityScreenBlocked", methods[182])
        self.assertIn("setVersionString", methods[183])
        self.assertEqual(original.read_bytes(), before)

    def test_pregame_extension_change_is_rejected(self):
        self.edit("interfaces2", "virtual int DLLCALL pitBossTurnTime() = 0;",
                  "virtual long DLLCALL pitBossTurnTime() = 0;")
        with self.assertRaisesRegex(sdk.ContractError, "ICvPreGame2"):
            sdk.check(self.upstream, self.profile)

    def test_native_lock_storage_preserves_public_api_and_scoped_helper(self):
        sibling = self.upstream / "FirePlace/include/FireWorks/FCriticalSection.inl"
        shutil.copyfile(ARGS.upstream / sibling.relative_to(self.upstream), sibling)
        output = self.workspace / "generated"
        sdk.prepare(self.upstream, self.profile, output)
        adapted = (output / "FireWorks/FCriticalSection.h").read_text()
        self.assertIn("alignas(8) unsigned char native_private_[40];", adapted)
        self.assertIn("class FScopedCriticalSection", adapted)
        source = (f'#include "{self.upstream}/FirePlace/include/FireWorks/FCriticalSection.h"\n'
                  'static_assert(sizeof(FCriticalSection) == 40, "size");\n'
                  'static_assert(alignof(FCriticalSection) == 8, "alignment");\n'
                  'void use(FCriticalSection& s) { FScopedCriticalSection scoped(s); }\n')
        result = subprocess.run([ARGS.compiler, "-arch", "x86_64", "-std=c++14", "-DVP_MAC_NATIVE=1",
                                 "-Werror", "-fsyntax-only", "-x", "c++", "-ivfsoverlay",
                                 str(output / "clang-overlay.json"), "-"],
                                input=source, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_changed_native_lock_declaration_stops_before_generation(self):
        self.edit("critical_section", "void Enter( void );", "void Enter( int flags );")
        output = self.workspace / "generated"
        with self.assertRaisesRegex(sdk.ContractError, "FCriticalSection"):
            sdk.prepare(self.upstream, self.profile, output)
        self.assertFalse(output.exists())

    def test_save_header_is_fixed_width_and_rejects_stock_identity(self):
        header = sdk.native_save_header(self.profile)
        self.assertEqual(header[:12], b"VPMACSAV\x01\x00\x00\x00")
        self.assertEqual(len(header), 28)
        self.assertNotEqual(self.profile["native_save"]["guid"], "BF9BF7F0-E078-4D4E-8A3E-84712F85AA2B")
        self.profile["native_save"]["guid"] = self.profile["stock_dll_guid"]
        with self.assertRaisesRegex(sdk.ContractError, "differ from the stock"):
            sdk.native_save_header(self.profile)

    def test_save_boundary_hooks_precede_upstream_reset_and_save_header(self):
        output = self.workspace / "generated"
        sdk.prepare(self.upstream, self.profile, output)
        adapted = (output / "core/CvGame.cpp").read_text()
        read = adapted[adapted.index("void CvGame::Read(FDataStream& kStream)"):]
        write = adapted[adapted.index("void CvGame::Write(FDataStream& kStream) const"):]
        self.assertLess(read.index("vp_mac::read_save_boundary"), read.index("reset(NO_HANDICAP)"))
        self.assertLess(write.index("vp_mac::write_save_boundary"), write.index("GC.setSaveVersion"))
        context = (output / "core/CvDllContext.cpp").read_text()
        self.assertIn("return vp_mac::native_save_guid();", context)

    def test_changed_game_save_entry_signature_aborts_generation(self):
        source = self.upstream / "CvGameCoreDLL_Expansion2/CvGame.cpp"
        source.write_bytes(source.read_bytes().replace(b"void CvGame::Read(FDataStream& kStream)",
                                                      b"void CvGame::Read(FDataStream& kStream, int version)"))
        with self.assertRaisesRegex(sdk.ContractError, "native-game-save-header-read"):
            sdk.prepare(self.upstream, self.profile, self.workspace / "generated")

    def vtable_fixture(self):
        binary = self.workspace / "fixture.dylib"
        data = bytearray(0x600)
        struct.pack_into("<IIIIIIII", data, 0, 0xfeedfacf, 0x1000007, 3, 8, 2, 96, 0, 0)
        struct.pack_into("<II16sQQQQIIII", data, 32, 0x19, 72, b"__DATA", 0, len(data), 0, len(data), 3, 3, 0, 0)
        struct.pack_into("<QQ", data, 0x110, 0x200, 0x220)
        profile = {"core_vtables": [{"class": "Fixture", "symbol": "__ZTV7Fixture",
                                    "slot_symbols": ["__ZN7Fixture4flagEb", "__ZN7Fixture7versionERKNSt3__112basic_stringIcNS0_11char_traitsIcEENS0_9allocatorIcEEEE"]}]}
        strings = bytearray(b"\0")
        for index, (name, address) in enumerate(zip(["__ZTV7Fixture"] + profile["core_vtables"][0]["slot_symbols"], [0x100, 0x200, 0x220])):
            struct.pack_into("<IBBHQ", data, 0x300 + index * 16, len(strings), 0x0e, 1, 0, address)
            strings.extend(name.encode() + b"\0")
        struct.pack_into("<6I", data, 104, 2, 24, 0x300, 3, 0x330, len(strings))
        data[0x330:0x330 + len(strings)] = strings
        binary.write_bytes(data)
        return binary, profile

    def test_linked_vtable_checks_exact_symbols_and_rejects_swapped_slots(self):
        binary, profile = self.vtable_fixture()
        self.assertEqual(sdk.verify_core(binary, profile)["result"], "passed")
        data = bytearray(binary.read_bytes())
        struct.pack_into("<QQ", data, 0x110, 0x220, 0x200)
        binary.write_bytes(data)
        with self.assertRaisesRegex(sdk.ContractError, "slot 0"):
            sdk.verify_core(binary, profile)

    def test_linked_vtable_rejects_non_macho_and_out_of_file_address(self):
        binary, profile = self.vtable_fixture()
        data = bytearray(binary.read_bytes())
        struct.pack_into("<Q", data, 0x308, 0x1000)
        binary.write_bytes(data)
        with self.assertRaisesRegex(sdk.ContractError, "outside Mach-O"):
            sdk.verify_core(binary, profile)
        binary.write_bytes(b"bad")
        with self.assertRaisesRegex(sdk.ContractError, "Mach-O"):
            sdk.verify_core(binary, profile)

    def test_macho_rejects_corrupt_command_symbol_and_string_bounds(self):
        binary, _ = self.vtable_fixture()
        original = binary.read_bytes()
        for offset, changed in [(16, 1000), (36, 4), (116, 1000), (120, len(original)), (0x300, 1000)]:
            with self.subTest(offset=offset):
                data = bytearray(original)
                struct.pack_into("<I", data, offset, changed)
                with self.assertRaises(ValueError):
                    sdk.macho.read_image(data)

    def test_changed_stream_field_type_is_rejected(self):
        self.edit("stream", "unsigned int m_uiPosition;", "unsigned long m_uiPosition;")
        with self.assertRaisesRegex(sdk.ContractError, "stream_members"):
            sdk.check(self.upstream, self.profile)

    def test_changed_guid_is_rejected(self):
        self.edit("interfaces", "0xd89ba82f", "0xd89ba830")
        with self.assertRaisesRegex(sdk.ContractError, "SDK GUID changed"):
            sdk.check(self.upstream, self.profile)

    def test_generated_objects_keep_public_api_and_hide_windows_containers(self):
        text = sdk.generate_objects(self.upstream, self.profile)
        self.assertIn("namespace Database", text)
        self.assertIn("class Connection", text)
        self.assertIn("bool Step();", text)
        self.assertIn("String(const char* szString);", text)
        self.assertIn("PushArgument(const long val);", text)
        self.assertIn("Connection& operator=(const Connection&);", text)
        for platform_detail in ["hash_map", "unordered_map", "SharedString", "__declspec", "__int64", "_In_"]:
            self.assertNotIn(platform_detail, text)

    def test_changed_private_layout_is_rejected(self):
        self.edit("results", "bool m_bSingleQuery;", "long m_bSingleQuery;")
        with self.assertRaisesRegex(sdk.ContractError, "opaque layout changed"):
            sdk.generate_objects(self.upstream, self.profile)

    def test_changed_object_virtual_slots_are_rejected(self):
        self.edit("localization", "CvLocalizationAPI virtual ~String();", "virtual void NewSlot(); CvLocalizationAPI virtual ~String();")
        with self.assertRaisesRegex(sdk.ContractError, "opaque vtable changed"):
            sdk.generate_objects(self.upstream, self.profile)

    def test_changed_used_native_signature_is_rejected(self):
        self.edit("results", "bool Bind(int idx, int iValue);", "bool Bind(long idx, int iValue);")
        with self.assertRaisesRegex(sdk.ContractError, "native method changed"):
            sdk.generate_objects(self.upstream, self.profile)

    def test_new_nonvirtual_api_is_generated_without_pinning_revision(self):
        self.edit("results", "bool Step();", "bool Step(); bool AddedUpstream(int value);")
        text = sdk.generate_objects(self.upstream, self.profile)
        self.assertIn("bool AddedUpstream(int value);", text)

    def test_changed_enum_is_rejected(self):
        self.edit("database", "OPEN_CREATE\t\t= 0x00000004", "OPEN_CREATE = 0x00000008")
        with self.assertRaisesRegex(sdk.ContractError, "native enum changed"):
            sdk.check(self.upstream, self.profile)

    def test_syntax_overlay_never_modifies_upstream(self):
        source = self.upstream / "ThirdPartyLibs/Lua51/include/lua.h"
        original = source.read_bytes()
        output = self.workspace / "build-output"
        sdk.prepare(self.upstream, self.profile, output)
        self.assertEqual(source.read_bytes(), original)
        adapted = (output / "lua.h").read_bytes()
        self.assertEqual(adapted, original.replace(b"[[noreturn]]", b"__attribute__((noreturn))"))

    def test_syntax_overlay_drift_stops_generation(self):
        source = self.upstream / "ThirdPartyLibs/Lua51/include/lua.h"
        source.write_bytes(source.read_bytes().replace(b"[[noreturn]]", b"[[different]]"))
        output = self.workspace / "build-output"
        with self.assertRaisesRegex(sdk.ContractError, "lua-noreturn-attribute-position"):
            sdk.prepare(self.upstream, self.profile, output)
        self.assertFalse(output.exists())

    def test_generated_output_inside_upstream_is_refused(self):
        with self.assertRaisesRegex(sdk.ContractError, "outside the upstream"):
            sdk.prepare(self.upstream, self.profile, self.upstream / "build-output")

    def test_compiler_overlay_handles_original_sdk_path_and_sibling_include(self):
        original = self.upstream / "ThirdPartyLibs/Lua51/include/lua.h"
        sibling = original.with_name("luaconf.h")
        shutil.copyfile(ARGS.upstream / "ThirdPartyLibs/Lua51/include/luaconf.h", sibling)
        before = {p: p.read_bytes() for p in (original, sibling)}
        output = self.workspace / "build with spaces"
        sdk.prepare(self.upstream, self.profile, output)
        source = f'#include "{original}"\nstatic_assert(sizeof(lua_Number) == 8);\n'
        command = [ARGS.compiler, "-arch", "x86_64", "-std=c++17", "-Werror", "-fsyntax-only", "-x", "c++"]
        # A direct path bypasses ordinary -I shadowing and fails without the
        # syntax edit. The overlay must also retain luaconf.h's original path.
        raw = subprocess.run(command + ["-"], input=source, capture_output=True, text=True)
        self.assertNotEqual(raw.returncode, 0)
        adapted = subprocess.run(command + ["-ivfsoverlay", str(output / "clang-overlay.json"), "-"],
                                 input=source, capture_output=True, text=True)
        self.assertEqual(adapted.returncode, 0, adapted.stderr)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_overlay_revision_tracks_effective_changes_without_rebuild_churn(self):
        output = self.workspace / "build-output"
        sdk.prepare(self.upstream, self.profile, output)
        marker = output / "vp_mac/overlay_revision.hpp"
        before = marker.read_bytes(), marker.stat().st_mtime_ns
        sdk.prepare(self.upstream, self.profile, output)
        self.assertEqual((marker.read_bytes(), marker.stat().st_mtime_ns), before)
        source = self.upstream / "ThirdPartyLibs/Lua51/include/lua.h"
        source.write_bytes(source.read_bytes() + b"\ntypedef int AddedUpstreamDeclaration;\n")
        sdk.prepare(self.upstream, self.profile, output)
        self.assertNotEqual(marker.read_bytes(), before[0])

    def test_native_sdk_projection_compiles_original_includes_and_templates(self):
        output = self.workspace / "build-output"
        sdk.prepare(self.upstream, self.profile, output)
        database = self.upstream / "CvGameDatabase/include/CvGameDatabase.h"
        localization = self.upstream / "CvLocalization/include/CvLocalization.h"
        source = (f'#include "{database}"\n#include "{localization}"\n'
                  'static_assert(sizeof(Database::Results) == 112, "results");\n'
                  'static_assert(sizeof(Database::SingleResult) == 112, "derived");\n'
                  'static_assert(sizeof(Localization::String) == 144, "string");\n'
                  'Localization::String example() { auto s = Localization::Lookup("key"); s << 42; return s; }\n')
        for standard in ["c++14", "c++17"]:
            result = subprocess.run([ARGS.compiler, "-arch", "x86_64", "-std=" + standard, "-Werror", "-fsyntax-only",
                                 "-x", "c++", "-ivfsoverlay", str(output / "clang-overlay.json"), "-"],
                                input=source, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_composed_overlays_preserve_every_edit(self):
        output = self.workspace / "build-output"
        sdk.prepare(self.upstream, self.profile, output)
        container = (output / "core/TContainer.h").read_text()
        self.assertIn("typename std::tr1::unordered_map<int,T*>::const_iterator it=m_items.find( m_order", container)
        self.assertIn("(*pStream) >> nItems;", container)
        self.assertIn("(*pStream) << GetCount();", container)
        lua = (output / "FireWorks/FLuaCommon.h").read_text()
        self.assertNotIn("inline long Get(", lua)
        self.assertIn("class ErrorHandler; class ScopedErrorHandler;", lua)

    def test_derived_native_layout_change_is_rejected(self):
        self.edit("results", "class SingleResult : public Results", "class SingleResult : protected Results")
        with self.assertRaisesRegex(sdk.ContractError, "derived layout changed"):
            sdk.generate_objects(self.upstream, self.profile)

    def test_lookup_signature_change_is_rejected(self):
        self.edit("localization", "String Lookup(const char* textKey);", "String Lookup(char* textKey);")
        with self.assertRaisesRegex(sdk.ContractError, "native function changed"):
            sdk.generate_objects(self.upstream, self.profile)

    def test_build_metadata_is_virtual_and_has_real_dependency_path(self):
        output = self.workspace / "build-output"
        sdk.prepare(self.upstream, self.profile, output)
        metadata = output / "vp_mac/commit_id.inc"
        self.assertFalse((self.upstream / "commit_id.inc").exists())
        dependency = self.workspace / "metadata.d"
        source = f'#include "{self.upstream}/CvGameCoreDLL_Expansion2/../commit_id.inc"\nconst char* version() {{ return CURRENT_GAMECORE_VERSION; }}\n'
        result = subprocess.run([ARGS.compiler, "-arch", "x86_64", "-std=c++14", "-Werror", "-fsyntax-only",
                                 "-MMD", "-MF", str(dependency), "-x", "c++", "-ivfsoverlay", str(output / "clang-overlay.json"), "-"],
                                input=source, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(metadata.resolve()), dependency.read_text())
        self.assertFalse((self.upstream / "commit_id.inc").exists())

    def test_gameplay_revision_only_updates_context_metadata_dependency(self):
        output = self.workspace / "build-output"
        with mock.patch.object(sdk.subprocess, "run", return_value=mock.Mock(stdout="revision-one")):
            sdk.prepare(self.upstream, self.profile, output)
        marker = output / "vp_mac/overlay_revision.hpp"
        metadata = output / "vp_mac/commit_id.inc"
        before = marker.read_bytes(), marker.stat().st_mtime_ns
        old_metadata = metadata.read_bytes()
        with mock.patch.object(sdk.subprocess, "run", return_value=mock.Mock(stdout="revision-two")):
            sdk.prepare(self.upstream, self.profile, output)
        self.assertEqual((marker.read_bytes(), marker.stat().st_mtime_ns), before)
        self.assertNotEqual(metadata.read_bytes(), old_metadata)

    def test_projected_cpp_changes_do_not_invalidate_shared_header_revision(self):
        output = self.workspace / "build-output"
        sdk.prepare(self.upstream, self.profile, output)
        marker = output / "vp_mac/overlay_revision.hpp"
        projected = output / "core/CvEspionageClasses.cpp"
        before = marker.read_bytes(), marker.stat().st_mtime_ns
        old_cpp = projected.read_bytes()
        source = self.upstream / "CvGameCoreDLL_Expansion2/CvEspionageClasses.cpp"
        source.write_bytes(source.read_bytes() + b"\n// Upstream gameplay-only update.\n")
        sdk.prepare(self.upstream, self.profile, output)
        self.assertEqual((marker.read_bytes(), marker.stat().st_mtime_ns), before)
        self.assertNotEqual(projected.read_bytes(), old_cpp)

    def test_appended_gameplay_function_stays_outside_windows_tool_guard(self):
        source = self.upstream / "CvGameCoreDLL_Expansion2/CvGame.cpp"
        source.write_bytes(source.read_bytes() + b"\nvoid CvGame::NewGameplayFunction() {}\n")
        output = self.workspace / "build-output"
        sdk.prepare(self.upstream, self.profile, output)
        adapted = (output / "core/CvGame.cpp").read_text()
        self.assertLess(adapted.index("#endif // Windows-only modpack creation tool"),
                        adapted.index("void CvGame::NewGameplayFunction()"))

    def test_native_host_verification_rejects_changed_image_and_entry_bytes(self):
        binary = self.workspace / "host"
        data = bytes(range(64))
        binary.write_bytes(data)
        profile = {"host_sha256": hashlib.sha256(data).hexdigest(),
                   "internal_functions": {"probe": {"rva": 4, "code_prefix": data[4:36].hex()}}}
        sdk.verify_host(binary, profile)
        profile["internal_functions"]["probe"]["code_prefix"] = bytes(32).hex()
        with self.assertRaisesRegex(sdk.ContractError, "entry-point bytes|function bytes"):
            sdk.verify_host(binary, profile)
        binary.write_bytes(data + b"changed")
        with self.assertRaisesRegex(sdk.ContractError, "SHA-256"):
            sdk.verify_host(binary, profile)

    def test_invalid_native_function_descriptor_is_rejected(self):
        self.profile["internal_functions"]["lua_pcall"]["rva"] = -1
        with self.assertRaisesRegex(sdk.ContractError, "Invalid reviewed native function"):
            sdk.generate_host_functions(self.profile)

    def test_generated_native_function_profile_is_cxx14_compatible(self):
        output = self.workspace / "build-output"
        sdk.prepare(self.upstream, self.profile, output)
        result = subprocess.run([ARGS.compiler, "-arch", "x86_64", "-std=c++14", "-Werror", "-fsyntax-only",
                                 "-I", str(output), "-I", str(ROOT / "include"), "-x", "c++", "-"],
                                input='#include "vp_mac/host_function_profile.hpp"\n', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(argv=[__file__], verbosity=2)
