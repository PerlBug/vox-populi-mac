#!/usr/bin/env python3
"""Player commands for the Vox Populi Mac beta; reuse the reversible installer."""
import sys

if sys.version_info < (3, 11):
    raise SystemExit("Vox Populi Mac needs Python 3.11 or newer. Run it with that Python installation.")

import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
DEFAULT_APP = Path.home() / "Library/Application Support/Steam/steamapps/common/Sid Meier's Civilization V/Civilization V.app"
CORE = "libCvGameCoreDLL_Expansion2_DLL.dylib"


def install_payload(root):
    if (root / "payload").is_dir():
        core, package = root / "payload" / CORE, root / "payload/VP_MAC_VP"
    else:
        core = root / "prototype/build-core/macos" / CORE
        package = root / "prototype/build-core/VP_MAC_VP-gameplay-probe"
    if not core.is_file() or not (package / "vp-mac-package.json").is_file():
        raise ValueError("Prebuilt beta files are missing. Extract the complete beta archive, or follow docs/DEVELOPMENT.md to build from source.")
    metadata = json.loads((package / "vp-mac-package.json").read_text())
    if metadata.get("content") != "vox-populi" or metadata.get("gameplay_test_ready") is not True:
        raise ValueError("This command requires the full Vox Populi package with its native save format.")
    return core, package


def check_conflicts(app):
    dlc = app / "Contents/Assets/Assets/DLC"
    for path in dlc.rglob("*"):
        if path.name.casefold() == "ui_bc1" and (path.is_dir() or path.is_symlink()):
            raise ValueError(f"EUI conflicts with beta 0.1: {path}\nQuit Civ V and move that folder completely outside the game's DLC folder before installing. Keep it to restore later.")


def command_for(args, root=ROOT):
    command = {"install": "install-native", "uninstall": "restore", "status": "status", "report": "native-report"}[args.command]
    result = [sys.executable, str(root / "prototype/manage.py"), command, "--app", str(args.app)]
    if args.command == "install":
        check_conflicts(args.app)
        core, package = install_payload(root)
        result += ["--native-core", str(core), "--data-package", str(package)]
    if args.dry_run:
        if args.command not in {"install", "uninstall"}:
            raise ValueError("--dry-run is available for install and uninstall.")
        result.append("--dry-run")
    return result


def main(argv=None):
    version = (ROOT / "VERSION").read_text().strip()
    parser = argparse.ArgumentParser(description=f"Vox Populi Mac {version}: install, play and return to stock Civ V.")
    parser.add_argument("--version", action="version", version=version)
    parser.add_argument("command", choices=["install", "uninstall", "status", "report"])
    parser.add_argument("--app", type=lambda p: Path(p).expanduser().resolve(), default=DEFAULT_APP,
                        help="Path to Civilization V.app when Steam uses another library")
    parser.add_argument("--dry-run", action="store_true", help="Check installation or removal without changing files")
    args = parser.parse_args(argv)
    try:
        result = subprocess.run(command_for(args), check=False)
        if result.returncode == 0 and args.command == "install" and not args.dry_run:
            print("\nVox Populi Mac is installed. Launch from Steam and start a NEW regular Single Player game.", flush=True)
            print("It stays active until you run: python3 vp-mac.py uninstall", flush=True)
        return result.returncode
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
