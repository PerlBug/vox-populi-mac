#!/usr/bin/env python3
"""Install, inspect or restore the reversible loader or native core test.

Only installation and restoration mutate the selected app. They never launch it.
"""
import argparse
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
CORE = "libCvGameCoreDLL_Expansion2_DLL.dylib"
ORIGINAL = "libCvGameCoreDLL_Expansion2_DLL.vp-original.dylib"
MANIFEST = ".vox-pop-mac-loader-probe.json"
MARKER = b"VOX_POP_MAC_LOADER_PROBE_V1"
NATIVE_MARKER = b"VOX_POP_MAC_NATIVE_CORE_V1"
DEFAULT_APP = Path.home() / (
    "Library/Application Support/Steam/steamapps/common/"
    "Sid Meier's Civilization V/Civilization V.app")
LOG = Path.home() / (
    "Library/Application Support/Sid Meier's Civilization 5/Logs/"
    "VoxPopMacLoaderProbe.log")
NATIVE_LOG = LOG.with_name("VoxPopMacNativeCore.log")
USER_DATA = LOG.parent.parent
DATA_DIRECTORY = "VP_MAC_CP"
DATA_MANIFEST = "vp-mac-package.json"
STARTUP_MOVIES = {
    "Contents/Assets": r"Civ5_Opening_Movie_[a-z]{2}_[A-Z]{2}\.mov",
    "Contents/Assets/Assets/DLC/Expansion": r"Civ5XP_Opening_Movie_[a-z]{2}_[A-Z]{2}\.mov",
    "Contents/Assets/Assets/DLC/Expansion2": r"Civ5XP2_Opening_Movie_[a-z]{2}_[A-Z]{2}\.mov",
}
MOVIE_BACKUP_SUFFIX = ".vp-mac-disabled"


class ProbeError(RuntimeError):
    pass


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise ProbeError(f"Expected a regular file, not a symlink: {path}")


def checked(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise ProbeError(f"Command failed: {args[0]}: {result.stderr.strip()}")
    return result.stdout


def validate_library(path, wrapper, expected_marker=MARKER):
    regular(path)
    info = json.loads(checked([sys.executable, str(ROOT.parent / "macos/tools/macho.py"), "--binary", str(path)]))
    if info["architectures"] != ["x86_64"]:
        raise ProbeError(f"Expected an x86_64-only Mach-O library: {path}")
    names = set(info["exports"])
    if names != {"_DllGetGameContext"}:
        raise ProbeError(f"Unexpected exported interface in {path}: {sorted(names)}")
    content = path.read_bytes()
    markers = {marker for marker in [MARKER, NATIVE_MARKER] if marker in content}
    if (wrapper and markers != {expected_marker}) or (not wrapper and markers):
        raise ProbeError(f"{'Missing or ambiguous managed-core marker' if wrapper else 'Refusing to back up a managed core as stock'}: {path}")
    if wrapper:
        checked(["/usr/bin/codesign", "--verify", "--strict", str(path)])


def ensure_game_stopped(app):
    processes = checked(["/bin/ps", "-axo", "pid=,comm="])
    matches = [line.strip() for line in processes.splitlines()
               if str(app / "Contents/MacOS") + "/" in line
               or "Civilization V.app/Contents/MacOS/" in line]
    if matches:
        raise ProbeError("Quit Civ V and its launcher before changing the core. "
                         "Matching process IDs: " + ", ".join(line.split()[0] for line in matches))


def paths(app):
    directory = app.resolve() / "Contents/MacOS"
    return directory / CORE, directory / ORIGINAL, directory / MANIFEST


def load_manifest(path):
    regular(path)
    data = json.loads(path.read_text())
    if data.get("schema") not in {1, 2} or data.get("probe") != MARKER.decode():
        raise ProbeError(f"Unrecognized backup manifest: {path}")
    if data.get("core_kind", "probe") not in {"probe", "native"}:
        raise ProbeError(f"Unrecognized core kind: {path}")
    for key in ["original_sha256", "wrapper_sha256"]:
        value = data.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ProbeError(f"Invalid backup hash in {path}")
    return data


def atomic_copy(source, destination, mode):
    fd, name = tempfile.mkstemp(prefix=".vp-probe-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as target, source.open("rb") as original:
            shutil.copyfileobj(original, target)
            target.flush()
            os.fsync(target.fileno())
        temporary.chmod(mode)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def validate_native_host(app):
    checked([sys.executable, str(ROOT.parent / "macos/tools/sdk_contract.py"),
             "verify-host", "--binary", str(app / "Contents/MacOS/Civilization V")])


def validate_native_core(path):
    checked([sys.executable, str(ROOT.parent / "macos/tools/sdk_contract.py"),
             "verify-core", "--binary", str(path)])


def tree_hashes(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ProbeError(f"Expected a real directory: {directory}")
    result = {}
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ProbeError(f"Refusing symlink in managed data: {path}")
        if path.is_file():
            result[str(path.relative_to(directory))] = digest(path)
        elif not path.is_dir():
            raise ProbeError(f"Unexpected file in managed data: {path}")
    return result


def data_paths(app, plan):
    data = app.resolve() / "Contents/Assets/Assets/DLC" / DATA_DIRECTORY
    cache = Path(plan["user_data"]) / "cache"
    return data, cache, cache.with_name("cache.vp-mac-stock-backup")


def save_paths(plan):
    saves = Path(plan["user_data"]) / "Saves"
    return saves, saves.with_name("Saves.vp-mac-stock-backup")


def intro_video_setting(path):
    regular(path)
    content = path.read_bytes()
    sections = list(re.finditer(rb"(?mi)^\[GameSettings\][ \t]*\r?$([\s\S]*?)(?=^\[|\Z)", content))
    if len(sections) == 1:
        section = sections[0]
        settings = list(re.finditer(rb"(?mi)^[ \t]*SkipIntroVideo[ \t]*=[ \t]*([^\r\n]*)", section[1]))
        if len(settings) == 1 and re.fullmatch(rb"[01][ \t]*(?:[;#].*)?", settings[0][1]):
            setting = settings[0]
            return content, section.start(1) + setting.start(1)
    raise ProbeError("UserSettings.ini has no unique GameSettings/SkipIntroVideo setting. Restore and launch stock BNW once, then quit before installing again.")


def set_intro_video(plan, restore=False):
    path = Path(plan["user_data"]) / "UserSettings.ini"
    content, offset = intro_video_setting(path)
    if not restore and hashlib.sha256(content).hexdigest() != plan["intro_video"]["sha256"]:
        raise ProbeError("UserSettings.ini changed during preparation. Run restore before retrying.")
    value = plan["intro_video"]["original_value"].encode() if restore else b"1"
    if value not in {b"0", b"1"}:
        raise ProbeError("Unrecognized original intro-video setting; preserving all files")
    if content[offset:offset + 1] == value:
        return
    fd, name = tempfile.mkstemp(prefix=".vp-settings-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content[:offset] + value + content[offset + 1:])
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def movie_paths(app, relative):
    path = Path(relative)
    pattern = STARTUP_MOVIES.get(path.parent.as_posix())
    if not pattern or not re.fullmatch(pattern, path.name):
        raise ProbeError(f"Unrecognized startup movie path: {relative}")
    original = app.resolve() / path
    if not original.parent.resolve().is_relative_to(app.resolve()):
        raise ProbeError(f"Startup movie directory leaves the game app: {relative}")
    return original, original.with_name(original.name + MOVIE_BACKUP_SUFFIX)


def prepare_startup_movies(app):
    result = []
    for folder, pattern in STARTUP_MOVIES.items():
        for path in sorted((app / folder).glob("*")):
            name = path.name.removesuffix(MOVIE_BACKUP_SUFFIX)
            if re.fullmatch(pattern, name):
                original, backup = movie_paths(app, str(Path(folder) / name))
                if backup.exists() or backup.is_symlink():
                    raise ProbeError(f"An untracked startup movie backup exists; preserving it: {backup}")
                regular(original)
                result.append({"path": str(original.relative_to(app.resolve())), "sha256": digest(original)})
    return result


def stage_startup_movies(app, movies):
    for movie in movies:
        original, backup = movie_paths(app, movie["path"])
        regular(original)
        if digest(original) != movie["sha256"] or backup.exists() or backup.is_symlink():
            raise ProbeError("Startup movies changed during preparation. Run restore before retrying.")
    for movie in movies:
        original, backup = movie_paths(app, movie["path"])
        original.rename(backup)


def validate_startup_movies(app, movies):
    for movie in movies:
        original, backup = movie_paths(app, movie["path"])
        if (original.exists() or original.is_symlink()) and (backup.exists() or backup.is_symlink()):
            raise ProbeError(f"A startup movie was replaced while disabled; preserving both files: {original}")
        remaining = backup if backup.exists() or backup.is_symlink() else original
        regular(remaining)
        if digest(remaining) != movie["sha256"]:
            raise ProbeError(f"Startup movie or backup changed; preserving all files: {remaining}")


def restore_startup_movies(app, movies):
    for movie in movies:
        original, backup = movie_paths(app, movie["path"])
        if backup.exists():
            backup.rename(original)


def localization_cache_files(cache):
    """Keep the engine's working language caches when rebuilding gameplay data.

    A completely empty cache can fail in Aspyr's BinaryIO localization merge
    before the game core is entered. Do not force that unrelated rebuild.
    """
    merged = cache / "Localization-Merged.db"
    regular(merged)
    try:
        with closing(sqlite3.connect(merged.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            valid = (db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                     and db.execute("SELECT EXISTS(SELECT 1 FROM Languages), EXISTS(SELECT 1 FROM LocalizedText)").fetchone() == (1, 1))
    except sqlite3.Error as error:
        raise ProbeError("The stock localization cache is invalid. Restore and launch stock BNW before installing again.") from error
    if not valid:
        raise ProbeError("The stock localization cache is empty or damaged. Restore and launch stock BNW before installing again.")
    return sorted(p.name for p in cache.glob("Localization-*.db") if p.is_file())


def check_interface_conflicts(dlc):
    identities = {"570f793e-fc33-417f-ae19-7cecccdd5f85", "570f793e-fc33-417f-ae18-7cecccdd5f85"}
    for path in dlc.rglob("*"):
        if path.name.casefold() in {"ui_bc1", "vpui"} and (path.is_dir() or path.is_symlink()):
            raise ProbeError(f"Separate EUI / VPUI installation conflicts: {path}\n"
                             "Move it completely outside the game's DLC folder first. The installer supplies its own matching files and preserves other mods.")
        if path.is_file() and path.suffix.casefold() == ".civ5pkg" and any(guid in path.read_text(errors="replace").lower() for guid in identities):
            raise ProbeError(f"Separate EUI / VPUI package conflicts: {path}\n"
                             "Move its containing mod completely outside the game's DLC folder first.")


def prepare_native_data(app, package, user_data, wrapper):
    regular(package / DATA_MANIFEST)
    metadata = json.loads((package / DATA_MANIFEST).read_text())
    if metadata.get("schema") != 1 or metadata.get("kind") != "cp-startup-data":
        raise ProbeError("Unrecognized native data package")
    if metadata.get("native_core_sha256") != digest(wrapper):
        raise ProbeError("Data package was built for a different core. Rebuild it with macos/tools/package_cp.py.")
    files = tree_hashes(package)
    declared = metadata.get("files", {})
    if {k: v for k, v in files.items() if k != DATA_MANIFEST} != declared:
        raise ProbeError("Data package files have changed; rebuild the package")
    plan = {"user_data": str(user_data.resolve()), "files": files,
            "upstream_commit": metadata["upstream_commit"], "interface": metadata.get("interface", "standard")}
    if plan["interface"] not in {"standard", "eui"}:
        raise ProbeError("Unrecognized interface in native data package")
    target, cache, backup = data_paths(app, plan)
    if target.exists() or target.is_symlink() or backup.exists() or backup.is_symlink():
        raise ProbeError("A native data directory or cache backup already exists. Restore the previous test first.")
    check_interface_conflicts(target.parent)
    if (target.parent / "VP_MODPACK").exists():
        raise ProbeError("An existing VP_MODPACK conflicts with this startup data package; preserve it outside DLC first.")
    for manifest in target.parent.rglob("*.Civ5Pkg"):
        if "b5932ae4-0f4f-498f-9333-e2d31b20e095" in manifest.read_text(errors="replace").lower():
            raise ProbeError(f"An existing package uses the VP modpack identity: {manifest}")
    plan["cache_files"] = tree_hashes(cache)
    plan["localization_cache_files"] = localization_cache_files(cache)
    if metadata.get("gameplay_test_ready") is True:
        expected = json.loads((ROOT.parent / "macos/abi/aspyr-steam-1.4.2.json").read_text())["native_save"]
        if metadata.get("native_save") != expected:
            raise ProbeError("Gameplay probe has an unrecognized native save format")
        saves, save_backup = save_paths(plan)
        if save_backup.exists() or save_backup.is_symlink():
            raise ProbeError("A stock save backup already exists. Restore the previous gameplay test first.")
        plan["save_directory_existed"] = saves.exists()
        plan["save_files"] = tree_hashes(saves) if saves.exists() or saves.is_symlink() else {}
    if metadata.get("content") == "vox-populi":
        settings, offset = intro_video_setting(user_data / "UserSettings.ini")
        plan["intro_video"] = {"sha256": hashlib.sha256(settings).hexdigest(),
                               "original_value": chr(settings[offset])}
        plan["startup_movies"] = prepare_startup_movies(app)
    return plan


def stage_native_data(app, package, plan):
    target, cache, backup = data_paths(app, plan)
    if tree_hashes(cache) != plan["cache_files"]:
        raise ProbeError("Game cache changed during preparation; run restore before retrying")
    if "intro_video" in plan:
        set_intro_video(plan)
    stage_startup_movies(app, plan.get("startup_movies", []))
    if "save_files" in plan:
        saves, save_backup = save_paths(plan)
        current = tree_hashes(saves) if saves.exists() or saves.is_symlink() else {}
        if current != plan["save_files"] or saves.exists() != plan["save_directory_existed"]:
            raise ProbeError("Game saves changed during preparation; run restore before retrying")
        if plan["save_directory_existed"]:
            saves.rename(save_backup)
        saves.mkdir(mode=0o700)
    # Preserve the entire original directory, then carry forward only working
    # localization caches with their timestamps. Gameplay databases rebuild.
    cache.rename(backup)
    cache.mkdir(mode=stat.S_IMODE(backup.stat().st_mode))
    for name in plan["localization_cache_files"]:
        shutil.copy2(backup / name, cache / name)
        if digest(cache / name) != plan["cache_files"][name]:
            raise ProbeError("Language cache copy verification failed. Run restore.")
    with tempfile.TemporaryDirectory(prefix=".vp-data-", dir=target.parent) as name:
        staged = Path(name) / DATA_DIRECTORY
        shutil.copytree(package, staged)
        if tree_hashes(staged) != plan["files"]:
            raise ProbeError("Native data copy verification failed. Run restore.")
        staged.rename(target)


def validate_data_restore(app, plan):
    validate_startup_movies(app, plan.get("startup_movies", []))
    if "intro_video" in plan:
        intro_video_setting(Path(plan["user_data"]) / "UserSettings.ini")
        if plan["intro_video"]["original_value"] not in {"0", "1"}:
            raise ProbeError("Unrecognized original intro-video setting; preserving all files")
    target, cache, backup = data_paths(app, plan)
    if target.exists() or target.is_symlink():
        remaining = tree_hashes(target)
        # Missing owned files can result from interrupted cleanup. Unknown or
        # edited files still block restoration before touching the core.
        if any(plan["files"].get(name) != sha for name, sha in remaining.items()):
            raise ProbeError("Installed native data changed; preserving it and the core backup")
    if backup.exists() or backup.is_symlink():
        if tree_hashes(backup) != plan["cache_files"]:
            raise ProbeError("Stock cache backup changed; preserving all files")
        if cache.exists() or cache.is_symlink():
            tree_hashes(cache)  # Refuse symlinks/special files before any mutation.
    elif tree_hashes(cache) != plan["cache_files"]:
        raise ProbeError("Stock cache backup is missing and current cache differs; preserving all files")
    if "save_files" in plan:
        saves, save_backup = save_paths(plan)
        if save_backup.exists() or save_backup.is_symlink():
            if tree_hashes(save_backup) != plan["save_files"]:
                raise ProbeError("Stock save backup changed; preserving all files")
            if saves.exists() or saves.is_symlink():
                tree_hashes(saves)
        elif plan["save_directory_existed"]:
            if tree_hashes(saves) != plan["save_files"]:
                raise ProbeError("Stock save backup is missing and current saves differ; preserving all files")
        elif saves.exists() or saves.is_symlink():
            tree_hashes(saves)


def restore_native_data(app, plan):
    if "intro_video" in plan:
        set_intro_video(plan, restore=True)
    restore_startup_movies(app, plan.get("startup_movies", []))
    target, cache, backup = data_paths(app, plan)
    if target.exists():
        shutil.rmtree(target)  # Exact inventory was verified before restoring.
    if backup.exists():
        if cache.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            session = cache.with_name("cache.vp-mac-session-" + stamp)
            cache.rename(session)
            print(f"Native test cache preserved at {session}")
        backup.rename(cache)
    if "save_files" in plan:
        saves, save_backup = save_paths(plan)
        if save_backup.exists() or not plan["save_directory_existed"]:
            if saves.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
                session = saves.with_name("Saves.vp-mac-session-" + stamp)
                saves.rename(session)
                print(f"Native test saves preserved at {session}")
            if save_backup.exists():
                save_backup.rename(saves)


def install(app, wrapper, dry_run=False, expected_marker=MARKER, native_data=None, package=None):
    core, backup, manifest = paths(app)
    ensure_game_stopped(app.resolve())
    if expected_marker == NATIVE_MARKER:
        validate_native_host(app.resolve())
    validate_library(wrapper, wrapper=True, expected_marker=expected_marker)
    if expected_marker == NATIVE_MARKER:
        validate_native_core(wrapper)
    regular(core)
    if manifest.exists():
        data = load_manifest(manifest)
        regular(backup)
        if digest(backup) != data["original_sha256"]:
            raise ProbeError("Original backup hash has changed; no files changed.")
        if digest(core) == data["wrapper_sha256"] == digest(wrapper):
            print("This build is already installed; original backup is intact.")
            return
        raise ProbeError("A previous managed-core transaction exists. Restore it before installing another build.")
    if backup.exists() or backup.is_symlink():
        raise ProbeError(f"An untracked original backup exists; preserving it: {backup}")
    validate_library(core, wrapper=False)
    data = {"schema": 1, "probe": MARKER.decode(),
            "core_kind": "native" if expected_marker == NATIVE_MARKER else "probe",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "original_sha256": digest(core), "wrapper_sha256": digest(wrapper),
            "original_mode": stat.S_IMODE(core.stat().st_mode)}
    if native_data is not None:
        data["native_data"] = native_data
        if "intro_video" in native_data or "startup_movies" in native_data:
            # Older installers must refuse this transaction rather than remove
            # its manifest without restoring the newly owned startup files.
            data["schema"] = 2
    if dry_run:
        print(f"Ready. Would preserve {core.name} as {backup.name} and install the {data['core_kind']} core. No files changed.")
        if native_data:
            print("Would install matching CP startup data, preserve the stock cache and retain working localization caches.")
            if "intro_video" in native_data:
                print(f"Would disable {len(native_data['startup_movies'])} startup movie files, including publisher logos, and skip the intro video. Originals and the previous intro setting return on uninstall.")
            if "save_files" in native_data:
                print("Would preserve stock Saves and activate a fresh folder for the native gameplay probe.")
        return
    # Preserve the signed original byte-for-byte before replacing anything.
    with core.open("rb") as source, backup.open("xb") as destination:
        shutil.copyfileobj(source, destination)
        destination.flush()
        os.fsync(destination.fileno())
    shutil.copystat(core, backup)
    if digest(backup) != data["original_sha256"]:
        raise ProbeError("Backup verification failed; the installed core was not changed.")
    # A prepared manifest also supports restore after an interrupted install.
    with manifest.open("x") as destination:
        destination.write(json.dumps(data, indent=2) + "\n")
        destination.flush()
        os.fsync(destination.fileno())
    if native_data is not None:
        stage_native_data(app, package, native_data)
    atomic_copy(wrapper, core, data["original_mode"])
    if digest(core) != data["wrapper_sha256"]:
        raise ProbeError("Installed probe hash mismatch. Run restore before launching Civ V.")
    if expected_marker == NATIVE_MARKER:
        print("Native Community Patch core installed for startup testing. Original core preserved and verified.")
        if native_data:
            print("Matching CP database package installed; stock cache preserved and language caches retained.")
            if "intro_video" in native_data:
                print("Startup movies and publisher logos are disabled. Originals and your previous intro setting will return on uninstall.")
            if "save_files" in native_data:
                print("Gameplay probe: stock saves preserved; a fresh Saves folder is active for native-format saves.")
            else:
                print("This package is for main-menu startup testing.")
    else:
        print("Probe installed. Original core preserved and verified. No gameplay mods were installed.")


def restore(app, dry_run=False):
    core, backup, manifest = paths(app)
    ensure_game_stopped(app.resolve())
    if not manifest.exists():
        regular(core)
        if backup.exists() or any(marker in core.read_bytes() for marker in [MARKER, NATIVE_MARKER]):
            raise ProbeError("Untracked probe/backup found; refusing to guess which file is original.")
        print("No managed probe is installed. No files changed.")
        return
    data = load_manifest(manifest)
    regular(backup)
    regular(core)
    if digest(backup) != data["original_sha256"]:
        raise ProbeError("Original backup hash has changed; refusing restore.")
    if digest(core) not in {data["wrapper_sha256"], data["original_sha256"]}:
        raise ProbeError("The installed core changed after this probe was prepared (possibly a Steam update). "
                         "Preserving it and the original backup; no files changed.")
    if "native_data" in data:
        validate_data_restore(app, data["native_data"])
    if dry_run:
        print("Ready to restore the verified original core. No files changed.")
        return
    if digest(core) != data["original_sha256"]:
        atomic_copy(backup, core, stat.S_IMODE(backup.stat().st_mode))
    if digest(core) != data["original_sha256"]:
        raise ProbeError("Restore verification failed; backup preserved.")
    if "native_data" in data:
        restore_native_data(app, data["native_data"])
    # Remove the manifest first: an interruption leaves an untracked backup,
    # never a manifest promising that a now-deleted backup can be restored.
    manifest.unlink()
    backup.unlink()
    print("Original core restored byte-for-byte. Backup and manifest removed.")


def status(app):
    core, backup, manifest = paths(app)
    regular(core)
    current = digest(core)
    result = {"app": str(app.resolve()), "core_sha256": current, "log": str(LOG)}
    if manifest.exists():
        data = load_manifest(manifest)
        result["core_kind"] = data.get("core_kind", "probe")
        if "native_data" in data:
            result["interface"] = data["native_data"].get("interface", "standard")
        if result["core_kind"] == "native":
            result["log"] = str(NATIVE_LOG)
        regular(backup)
        result["backup_verified"] = digest(backup) == data["original_sha256"]
        result["state"] = ("installed" if current == data["wrapper_sha256"] else
                           "prepared_or_restored" if current == data["original_sha256"] else
                           "core_changed_externally")
    else:
        result["state"] = "unmanaged_probe" if any(marker in core.read_bytes() for marker in [MARKER, NATIVE_MARKER]) else "stock"
        result["untracked_backup"] = backup.exists()
    print(json.dumps(result, indent=2))


def probe_report(path):
    """Stream even the original verbose log, retaining only the latest session."""
    report = None
    with path.open(errors="replace") as source:
        for line in source:
            parsed = re.search(r"pid=(\d+) event=(\w+)\s*(.*)", line)
            if not parsed:
                continue
            pid, event, detail = parsed.groups()
            if event == "wrapper_loaded":
                report = {"pid": int(pid), "original_ready": False, "host_symbols": {},
                          "last_forward_call": 0, "abi_checks": {}, "abi_result": "not_run",
                          "clean_unload": False, "failures": []}
            if report is None or int(pid) != report["pid"]:
                continue
            if event == "host_symbol":
                symbol = re.search(r"symbol=(\S+) available=(yes|no)", detail)
                if symbol:
                    report["host_symbols"][symbol[1]] = symbol[2]
            elif event == "original_ready":
                report["original_ready"] = True
            elif event == "context_forwarded":
                count = re.search(r"call=(\d+)", detail)
                if count:
                    report["last_forward_call"] = int(count[1])
            elif event == "original_unloading":
                count = re.search(r"forwarded_calls=(\d+)", detail)
                if count:
                    report["last_forward_call"] = int(count[1])
            elif event == "abi_probe_started":
                report["abi_result"] = "incomplete"
            elif event in {"abi_context", "abi_guid", "abi_clock", "abi_stream", "abi_database", "abi_localization"}:
                report["abi_checks"][event] = detail.split()[0]
            elif event in {"abi_probe_passed", "abi_probe_failed", "abi_profile_skipped"}:
                report["abi_result"] = {"abi_probe_passed": "passed", "abi_probe_failed": "failed",
                                        "abi_profile_skipped": "skipped_unreviewed_images"}[event]
            elif event == "wrapper_unloaded":
                report["clean_unload"] = True
            if event.endswith("_failed") or event.endswith("_refused") or detail == "failed" or event == "original_returned_null":
                report["failures"].append({"event": event, "detail": detail})
    return report or {"abi_result": "no_session_found"}


def prepare_native_log(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as output:
        # Preserve history while ensuring a launch that never reaches the core
        # cannot be mistaken for an earlier successful test.
        output.write("\n" + json.dumps({"event": "native_test_prepared"}) + "\n")
        output.flush()
        os.fsync(output.fileno())


def matching_native_crash(path, pid, directory):
    """Attach a recent macOS crash for this session, without treating silence as failure."""
    boundary = path.stat().st_mtime - 2  # Allow timestamp granularity differences.
    candidates = sorted(directory.glob("Civilization V*.ips"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
    for candidate in candidates:
        if candidate.stat().st_mtime < boundary:
            continue  # Exclude old crashes after macOS reuses a process ID.
        try:
            raw = candidate.read_text()
            decoder = json.JSONDecoder()
            _, end = decoder.raw_decode(raw)
            crash = json.loads(raw[end:].strip())
            if crash.get("pid") != pid or crash.get("procName") != "Civilization V":
                continue
            native_frame = None
            for frame in crash["threads"][crash["faultingThread"]]["frames"]:
                image = crash["usedImages"][frame["imageIndex"]]
                if image.get("name") == CORE:
                    native_frame = {key: frame[key] for key in ["symbol", "sourceFile", "sourceLine", "imageOffset"] if key in frame}
                    break
            return {"report": str(candidate), "exception": crash.get("exception", {}),
                    "native_frame": native_frame}
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            continue
    return None


def engine_startup_failures(directory, since):
    failures = []
    for name in ["Database.log", "Localization.log"]:
        path = directory / name
        if not path.is_file() or path.stat().st_mtime < since:
            continue
        with path.open(errors="replace") as source:
            lines = [line.rstrip() for line in source if re.search(
                r"Failed to Load database|no such table: (?:Languages|LocalizedText)|ERR:", line)]
        if lines:
            failures.append({"event": "engine_initialization_failed", "log": str(path), "detail": "\n".join(lines[-12:])})
    return failures


def native_report(path, crash_directory=None, engine_log_directory=None):
    report = None
    with path.open(errors="replace") as source:
        for line in source:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if not isinstance(item, dict):
                continue
            event, pid = item.get("event"), item.get("pid")
            if event == "native_test_prepared":
                report = None
                continue
            if event == "native_loaded":
                report = {"pid": pid, "native_core": True, "profile": "not_run",
                          "database_bridge": "not_run", "lua_bridge": "not_run", "stream_bridge": "not_run",
                          "lock_bridge": "not_run", "game_data": "not_run", "save_identity": "not_run",
                          "save_guid": None, "save_headers_written": 0, "save_headers_read": 0,
                          "context_ready": False, "context_destroyed": False, "failures": []}
            if report is None or pid != report["pid"]:
                continue
            for name, key in [("profile", "profile"), ("database", "database_bridge"), ("lua", "lua_bridge"), ("stream", "stream_bridge"), ("lock", "lock_bridge"), ("game_data", "game_data"), ("save_identity", "save_identity")]:
                if event in {f"native_{name}_passed", f"native_{name}_failed"}:
                    report[key] = "passed" if event.endswith("_passed") else "failed"
                    if event.endswith("_failed"):
                        report["failures"].append(event)
            if event == "native_save_identity_passed":
                report["save_guid"] = item.get("detail")
            elif event == "native_save_header_written":
                report["save_headers_written"] += 1
            elif event == "native_save_header_read":
                report["save_headers_read"] += 1
            if event == "native_precondition_failed":
                report["failures"].append({"event": event, "detail": item.get("detail", "")})
            if event == "native_context_ready":
                report["context_ready"] = True
            elif event == "native_context_destroyed":
                report["context_destroyed"] = True
    if report is None:
        failures = engine_startup_failures(engine_log_directory, path.stat().st_mtime - 2) if engine_log_directory else []
        return {"native_core": False, "stage": "before_native_entry", "failures": failures,
                "startup_result": "failed" if failures else "not_started",
                "detail": "No native core entry was recorded after the latest test preparation."}
    if crash_directory is not None:
        crash = matching_native_crash(path, report["pid"], crash_directory)
        if crash:
            report["crash"] = crash
            report["failures"].append("native_process_crashed")
    passed = (all(report[key] == "passed" for key in ["profile", "database_bridge", "lua_bridge", "stream_bridge", "lock_bridge", "game_data", "save_identity"])
              and report["context_ready"] and report["context_destroyed"])
    report["startup_result"] = "failed" if report["failures"] else "passed" if passed else "incomplete"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["install", "install-native", "restore", "status", "logs", "report", "native-report"])
    parser.add_argument("--app", type=Path, default=DEFAULT_APP)
    parser.add_argument("--wrapper", type=Path, default=ROOT / "build" / CORE)
    parser.add_argument("--native-core", type=Path, default=ROOT / "build-core/macos" / CORE)
    parser.add_argument("--data-package", type=Path, default=ROOT / "build-core" / DATA_DIRECTORY)
    parser.add_argument("--user-data", type=Path, default=USER_DATA)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    args.log = args.log or (NATIVE_LOG if args.command == "native-report" else LOG)
    try:
        if args.command == "install":
            install(args.app, args.wrapper, args.dry_run)
        elif args.command == "install-native":
            # Native CP also runs during initial menu caching, before a user
            # could activate mods. Require its schema/data in the same install.
            plan = prepare_native_data(args.app, args.data_package, args.user_data, args.native_core)
            install(args.app, args.native_core, args.dry_run, NATIVE_MARKER, plan, args.data_package)
            if not args.dry_run:
                prepare_native_log(NATIVE_LOG)
        elif args.command == "restore":
            restore(args.app, args.dry_run)
        elif args.command == "status":
            status(args.app)
        elif args.command == "report":
            print(json.dumps(probe_report(args.log), indent=2))
        elif args.command == "native-report":
            print(json.dumps(native_report(args.log, Path.home() / "Library/Logs/DiagnosticReports", args.log.parent), indent=2))
        elif args.log.exists():
            with args.log.open() as source:
                print("".join(deque(source, maxlen=80)), end="")
        else:
            print(f"No probe log yet: {args.log}")
    except (ProbeError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
