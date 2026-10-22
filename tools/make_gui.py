#!/usr/bin/env python3
"""Build a universal Mac installer app around the verified beta distribution."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from make_beta import ROOT, digest, git, validate_package


def extract_runtime(archive, destination):
    with tempfile.TemporaryDirectory(prefix="runtime-", dir=destination.parent) as temporary:
        temporary = Path(temporary)
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "python":
                    raise ValueError("Unsafe Python runtime archive path")
                if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise ValueError("Unsupported Python runtime archive entry")
            bundle.extractall(temporary, filter="data")
        python = temporary / "python"
        for path in python.rglob("*"):
            if path.is_symlink() and not path.resolve().is_relative_to(python.resolve()):
                raise ValueError("Python runtime link escapes its distribution")
        # Materialize internal aliases so release hashes and ZIP tools handle
        # every runtime file consistently without external symlinks.
        shutil.copytree(python, destination, symlinks=False)


def prepare_runtimes(root, cache, destination):
    config = json.loads((root / "gui/python-runtimes.json").read_text())
    cache.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True)
    for arch in ["arm64", "x86_64"]:
        item = config[arch]
        archive = cache / (arch + ".tar.gz")
        if not archive.exists():
            print("Downloading pinned Python runtime: " + arch, flush=True)
            temporary = archive.with_suffix(".download")
            try:
                with urllib.request.urlopen(item["url"]) as source, temporary.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if digest(temporary) != item["sha256"]:
                    raise ValueError("Python runtime download checksum differs: " + arch)
                temporary.rename(archive)
            finally:
                temporary.unlink(missing_ok=True)
        if digest(archive) != item["sha256"]:
            raise ValueError("Cached Python runtime checksum differs: " + arch)
        extract_runtime(archive, destination / arch)
        if arch == platform.machine() or platform.machine() == "arm64":
            subprocess.run([str(destination / arch / "bin/python3.13"), "-I", "-B", "-c",
                            "import sys,sqlite3,hashlib,json,struct; assert sys.version_info >= (3,11); print(sys.version)"], check=True)
    return config


def make_gui(root, distribution, output, cache):
    version = (root / "VERSION").read_text().strip()
    metadata = json.loads((distribution / "release.json").read_text())
    if metadata["version"] != version or metadata["source_commit"] != git(root, "rev-parse", "HEAD") or git(root, "status", "--porcelain"):
        raise ValueError("Build the matching command-line distribution from the current clean commit first")
    validate_package(distribution / "payload/libCvGameCoreDLL_Expansion2_DLL.dylib", distribution / "payload/VP_MAC_VP")
    eui = validate_package(distribution / "payload/libCvGameCoreDLL_Expansion2_DLL.dylib", distribution / "payload/VP_MAC_VP_EUI")
    if eui.get("interface") != "eui":
        raise ValueError("GUI release requires the matching EUI package")
    name = "Vox Populi Mac Installer.app"
    output.mkdir(parents=True, exist_ok=True)
    final = output / name
    archive = output / ("Vox-Populi-Mac-" + version + "-macOS.zip")
    if final.exists() or archive.exists() or archive.with_suffix(".zip.sha256").exists():
        raise ValueError("GUI release output exists; choose a fresh directory")
    with tempfile.TemporaryDirectory(prefix=".gui-", dir=output) as temporary:
        temporary = Path(temporary)
        app = temporary / name
        contents = app / "Contents"
        binaries = contents / "MacOS"
        resources = contents / "Resources"
        binaries.mkdir(parents=True)
        resources.mkdir()
        print("Preparing standalone Apple Silicon and Intel runtimes...", flush=True)
        runtimes = prepare_runtimes(root, cache, resources / "Runtimes")
        shutil.copytree(distribution, resources / "Distribution")
        shutil.copyfile(root / "gui/Guide.html", resources / "Distribution/Installation Guide.html")
        print("Compiling native Mac interface...", flush=True)
        for arch in ["arm64", "x86_64"]:
            subprocess.run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-O", "-target", arch + "-apple-macos11.0",
                            "-module-cache-path", str(cache / "swift-modules"), "-framework", "AppKit",
                            str(root / "gui/Installer.swift"), "-o", str(temporary / ("Installer-" + arch))], check=True)
        subprocess.run(["/usr/bin/lipo", "-create", str(temporary / "Installer-arm64"), str(temporary / "Installer-x86_64"),
                        "-output", str(binaries / "Installer")], check=True)
        info = {"CFBundleIdentifier": "community.voxpopmac.installer", "CFBundleName": "Vox Populi Mac Installer",
                "CFBundleDisplayName": "Vox Populi Mac Installer", "CFBundleExecutable": "Installer", "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": version.split("-")[0], "CFBundleVersion": version.rsplit(".", 1)[-1],
                "LSMinimumSystemVersion": "11.0", "NSHighResolutionCapable": True,
                "LSApplicationCategoryType": "public.app-category.utilities",
                "NSHumanReadableCopyright": "Unofficial community installer. See bundled notices and upstream credits."}
        with (contents / "Info.plist").open("wb") as file:
            plistlib.dump(info, file)
        (resources / "GUI-release.json").write_text(json.dumps({"version": version, "source_commit": metadata["source_commit"],
                "architectures": ["arm64", "x86_64"], "minimum_macos": "11.0", "python_runtimes": runtimes,
                "native_core_sha256": metadata["native_core_sha256"], "signing": "ad hoc; not notarized"}, indent=2) + "\n")
        # Sign the app envelope, leaving the independently verified game core
        # and bundled interpreter binaries byte-for-byte intact.
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(app)], check=True)
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
        if digest(resources / "Distribution/payload/libCvGameCoreDLL_Expansion2_DLL.dylib") != metadata["native_core_sha256"]:
            raise ValueError("App signing changed the tested game core")
        print("Creating standalone GUI ZIP...", flush=True)
        staged_zip = temporary / archive.name
        subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(staged_zip)], check=True)
        checksum = digest(staged_zip)
        app.rename(final)
        staged_zip.rename(archive)
        archive.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive.name}\n")
    return {"app": str(final), "archive": str(archive), "sha256": checksum, "bytes": archive.stat().st_size}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, default=ROOT / "dist" / ("Vox-Populi-Mac-" + (ROOT / "VERSION").read_text().strip()))
    parser.add_argument("--output", type=Path, default=ROOT / "dist/gui")
    parser.add_argument("--cache", type=Path, default=ROOT / "dist/runtime-cache")
    args = parser.parse_args()
    try:
        print(json.dumps(make_gui(ROOT, args.distribution.resolve(), args.output.resolve(), args.cache.resolve()), indent=2))
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as error:
        parser.exit(1, f"Error: {error}\n")
