#!/usr/bin/env python3
"""Read-only Civ V/VP audit; writes evidence only under --output.

Does not launch Civ V, load its dylibs, install mods, or change Steam files.
Requires macOS Command Line Tools (nm, otool, clang++).
"""

import argparse
import hashlib
import json
import platform
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
import plistlib


WORKSPACE = Path(__file__).resolve().parents[1]


def run(args, stdin=None):
    result = subprocess.run(args, input=stdin, capture_output=True, text=True)
    return {"command": args, "exit_code": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}


def symbols(binary, flags):
    result = run(["nm", flags, str(binary)])
    if result["exit_code"]:
        raise RuntimeError(result["stderr"])
    return {line.split()[-1] for line in result["stdout"].splitlines()
            if line.strip() and not line.endswith(":" )}


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def normalize_guid(value):
    return value.strip().strip("{}").upper()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path.home() /
                        "Library/Application Support/Steam/steamapps/common/"
                        "Sid Meier's Civilization V/Civilization V.app")
    parser.add_argument("--repo", type=Path,
                        default=WORKSPACE / "Community-Patch-DLL")
    parser.add_argument("--output", type=Path,
                        default=WORKSPACE / "analysis/mac-civ5")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    app = args.app.resolve()
    repo = args.repo.resolve()
    executable = app / "Contents/MacOS/Civilization V"
    core = app / "Contents/MacOS/libCvGameCoreDLL_Expansion2_DLL.dylib"
    vp_dll = repo / "(1) Community Patch/CvGameCore_Expansion2.dll"
    plist = plistlib.loads((app / "Contents/Info.plist").read_bytes())

    exports = symbols(executable, "-gU")
    imports = symbols(core, "-gu")
    provided = imports & exports
    remaining = imports - exports
    for name, entries in [("executable-exports", exports),
                          ("stock-core-imports", imports),
                          ("stock-core-exports", symbols(core, "-gU")),
                          ("stock-imports-provided-by-executable", provided),
                          ("stock-imports-outside-executable", remaining)]:
        (output / (name + ".txt")).write_text("\n".join(sorted(entries)) + "\n")
    demangled = run(["c++filt"], "\n".join(sorted(provided)) + "\n")
    (output / "stock-imports-provided-by-executable-demangled.txt").write_text(
        demangled["stdout"])

    cp_info = repo / "(1) Community Patch/(1) Community Patch (v 151).modinfo"
    cp = ET.parse(cp_info).getroot()
    required = {normalize_guid(item.attrib["id"])
                for item in cp.findall("./Dependencies/Dlc")}
    packages = {}
    dlc_root = app / "Contents/Assets/Assets/DLC"
    for path in dlc_root.rglob("*.Civ5Pkg"):
        try:
            package = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        guid = package.findtext("GUID")
        if guid:
            packages[normalize_guid(guid)] = str(path.relative_to(dlc_root))

    source_files = sorted((repo / "CvGameCoreDLL_Expansion2").rglob("*.cpp"))
    headers = sorted((repo / "CvGameCoreDLL_Expansion2").rglob("*.h"))
    dependencies = {}
    for directory in ["CvGameCoreDLLUtil", "CvGameDatabase", "CvLocalization",
                      "CvWorldBuilderMap", "FirePlace", "ThirdPartyLibs/Lua51"]:
        path = repo / directory
        dependencies[directory] = {
            "c_cpp_files": len(list(path.rglob("*.cpp"))) + len(list(path.rglob("*.c"))),
            "windows_libraries": [str(p.relative_to(repo)) for p in path.rglob("*.lib")],
        }

    binaries = {}
    for label, path in [("game", executable), ("stock_bnw_core", core),
                        ("vp_windows_core", vp_dll)]:
        binaries[label] = {"path": str(path), "sha256": sha256(path),
                           "file": run(["file", str(path)])["stdout"].strip()}

    metadata = {
        "host_architecture": platform.machine(),
        "os": run(["sw_vers"])["stdout"].strip(),
        "source_commit": run(["git", "-C", str(repo), "rev-parse", "HEAD"])["stdout"].strip(),
        "source_status": run(["git", "-C", str(repo), "status", "--short"])["stdout"],
        "bundle": {key: plist.get(key) for key in ["CFBundleIdentifier",
                   "CFBundleShortVersionString", "CFBundleVersion"]},
        "binaries": binaries,
        "stock_core_import_count": len(imports),
        "stock_imports_provided_by_executable": len(provided),
        "stock_imports_outside_executable": len(remaining),
        "scope_note": "Stock import coverage is not a VP import or ABI compatibility check.",
        "core_source": {"cpp_files": len(source_files), "headers": len(headers),
                        "lines": sum(len(p.read_bytes().splitlines())
                                     for p in source_files + headers)},
        "dependencies": dependencies,
        "required_dlc_packages": {guid: packages.get(guid) for guid in sorted(required)},
        "dlc_note": "Manifest presence does not prove runtime activation or entitlement.",
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    checks = {
        "game-linked-libraries": run(["otool", "-L", str(executable)]),
        "stock-core-linked-libraries": run(["otool", "-L", str(core)]),
        "stock-core-lazy-bind": run(["xcrun", "llvm-objdump", "--macho", "--lazy-bind", str(core)]),
        "game-signature": run(["codesign", "-dv", "--verbose=4", str(executable)]),
    }
    includes = [repo / "CvGameCoreDLL_Expansion2"] + [
        repo / directory / "include" for directory in ["CvWorldBuilderMap",
        "CvGameCoreDLLUtil", "CvLocalization", "CvGameDatabase", "FirePlace",
        "ThirdPartyLibs/Lua51"]] + [repo / "FirePlace/include/FireWorks"]
    command = ["xcrun", "clang++", "-arch", "x86_64", "-std=c++03",
               "-fms-extensions", "-fsyntax-only", "-DNDEBUG", "-DFINAL_RELEASE"]
    for path in includes:
        command += ["-I", str(path)]
    command += [str(repo / "CvGameCoreDLL_Expansion2/CvGameCoreDLL.cpp")]
    checks["unmodified-mac-syntax-probe"] = run(command)
    for target in ["x86_64-apple-macos10.15", "i686-pc-windows-msvc"]:
        result = run(["xcrun", "clang++", "--target=" + target, "-dM", "-E", "-x", "c++", "-"], "")
        result["stdout"] = "\n".join(line for line in result["stdout"].splitlines()
            if any(macro in line for macro in ["__SIZEOF_INT__", "__SIZEOF_LONG__",
                "__SIZEOF_POINTER__", "__SIZEOF_SIZE_T__", "__SIZEOF_WCHAR_T__"])) + "\n"
        checks["scalar-types-" + target] = result
    for name, result in checks.items():
        (output / (name + ".txt")).write_text(
            "Command: " + repr(result["command"]) + "\nExit: " + str(result["exit_code"])
            + "\n\n" + result["stdout"] + result["stderr"])
    print(json.dumps({"output": str(output), "stock_imports": len(imports),
        "provided_by_executable": len(provided),
        "dlc_manifests_present": sum(value is not None for value in metadata["required_dlc_packages"].values()),
        "dlc_manifests_required": len(required),
        "unmodified_compile_exit": checks["unmodified-mac-syntax-probe"]["exit_code"]}, indent=2))


if __name__ == "__main__":
    main()
