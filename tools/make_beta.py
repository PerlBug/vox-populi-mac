#!/usr/bin/env python3
"""Package a verified core and VP data, installer, notices and source snapshots."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = ["VERSION", "README.md", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md", "vp-mac.py",
                 "docs/DEVELOPMENT.md", "macos/README.md", "prototype/manage.py",
                 "macos/tools/sdk_contract.py", "macos/abi/aspyr-steam-1.4.2.json",
                 "LICENSES/CommunityPatch-License.rtf"]


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def git(directory, *args):
    return subprocess.check_output(["git", "-C", str(directory), *args], text=True).strip()


def inventory(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlinks are not allowed in release payloads: {path}")
        if path.is_file():
            result[str(path.relative_to(directory))] = digest(path)
        elif not path.is_dir():
            raise ValueError(f"Unsupported release payload file: {path}")
    return result


def validate_package(core, package):
    if core.is_symlink() or not core.is_file():
        raise ValueError("Expected a regular native core")
    files = inventory(package)
    metadata = json.loads((package / "vp-mac-package.json").read_text())
    if metadata.get("content") != "vox-populi" or metadata.get("gameplay_test_ready") is not True:
        raise ValueError("Release requires the full VP package with native save isolation")
    if metadata.get("native_core_sha256") != digest(core):
        raise ValueError("Package and native core hashes differ")
    if {k: v for k, v in files.items() if k != "vp-mac-package.json"} != metadata.get("files"):
        raise ValueError("Data package inventory differs from its manifest")
    if any(Path(name).suffix.casefold() in {".dll", ".dylib", ".exe", ".so"} for name in files):
        raise ValueError("Unexpected executable in data package")
    return metadata


def make_release(root, upstream, core, package, output):
    version = (root / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+-beta\.\d+", version):
        raise ValueError("VERSION must identify a beta, for example 0.1.0-beta.1")
    if git(root, "status", "--porcelain") or git(upstream, "status", "--porcelain"):
        raise ValueError("Commit the Mac sources and keep upstream clean before making a release")
    metadata = validate_package(core, package)
    revision, upstream_revision = git(root, "rev-parse", "HEAD"), git(upstream, "rev-parse", "HEAD")
    if metadata["upstream_commit"] != upstream_revision:
        raise ValueError("Source snapshot does not match the data package's upstream revision")
    profile = json.loads((root / "macos/abi/aspyr-steam-1.4.2.json").read_text())
    if metadata.get("native_save") != profile["native_save"]:
        raise ValueError("Package native save identity differs from the reviewed profile")
    spec = importlib.util.spec_from_file_location("beta_manage", root / "prototype/manage.py")
    manage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manage)
    manage.validate_library(core, True, manage.NATIVE_MARKER)
    manage.validate_native_core(core)
    name = "Vox-Populi-Mac-" + version
    if output.resolve().is_relative_to(upstream.resolve()):
        raise ValueError("Release output must be outside upstream")
    output.mkdir(parents=True, exist_ok=True)
    if any((output / suffix).exists() for suffix in [name, name + ".zip", name + ".zip.sha256"]):
        raise ValueError("Release output already exists; use a fresh output directory")
    with tempfile.TemporaryDirectory(prefix=".beta-", dir=output) as temp:
        folder = Path(temp) / name
        folder.mkdir()
        for relative in RUNTIME_FILES:
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / relative, target)
        payload = folder / "payload"
        payload.mkdir()
        shutil.copy2(core, payload / manage.CORE)
        shutil.copytree(package, payload / "VP_MAC_VP")
        sources = folder / "source"
        sources.mkdir()
        print("Archiving Mac and upstream source snapshots...", flush=True)
        for source, filename, prefix in [(root, "mac-layer.tar.gz", "Vox-Populi-Mac-source/"),
                                         (upstream, "community-patch.tar.gz", "Vox-Populi-Mac-source/Community-Patch-DLL/")]:
            subprocess.run(["git", "-C", str(source), "archive", "--format=tar.gz", "--prefix=" + prefix,
                            "--output=" + str(sources / filename), "HEAD"], check=True)
        release = {"schema": 1, "name": "Vox Populi Mac", "version": version, "source_commit": revision,
                   "upstream_commit": upstream_revision, "native_core_sha256": digest(core),
                   "data_manifest_sha256": digest(package / "vp-mac-package.json"),
                   "native_save": profile["native_save"], "configuration": "full VP without EUI",
                   "core_build": "Debug; beta uses the previously game-tested core",
                   "source_snapshots": ["source/mac-layer.tar.gz", "source/community-patch.tar.gz"]}
        (folder / "release.json").write_text(json.dumps(release, indent=2) + "\n")
        hashes = inventory(folder)
        # Confirm that staging retained every byte of the independently bound payload.
        if inventory(payload / "VP_MAC_VP") != inventory(package) or digest(payload / manage.CORE) != digest(core):
            raise ValueError("Staged payload verification failed")
        (folder / "SHA256SUMS").write_text("".join(f"{sha}  {path}\n" for path, sha in hashes.items()))
        print("Creating beta ZIP...", flush=True)
        archive = Path(temp) / (name + ".zip")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    bundle.write(path, str(path.relative_to(folder.parent)),
                                 compress_type=zipfile.ZIP_STORED if path.suffix == ".gz" else zipfile.ZIP_DEFLATED)
        checksum = digest(archive)
        folder.rename(output / name)
        archive.rename(output / archive.name)
        (output / (name + ".zip.sha256")).write_text(f"{checksum}  {name}.zip\n")
    return {"archive": str(output / (name + ".zip")), "sha256": checksum,
            "bytes": (output / (name + ".zip")).stat().st_size, **release}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, default=ROOT / "Community-Patch-DLL")
    parser.add_argument("--core", type=Path, default=ROOT / "prototype/build-core/macos/libCvGameCoreDLL_Expansion2_DLL.dylib")
    parser.add_argument("--package", type=Path, default=ROOT / "prototype/build-core/VP_MAC_VP-gameplay-probe")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        print(json.dumps(make_release(ROOT, *(getattr(args, k).resolve() for k in ["upstream", "core", "package", "output"])), indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
