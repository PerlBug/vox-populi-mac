# Release notes

## 0.1.0-beta.4 — optional EUI

- Adds an optional Enhanced User Interface checkbox to the Mac installer, with standard VP selected by default. Shows the installed interface and requires restoration before switching.
- Builds EUI from the same pinned 5.4.8 upstream revision: BNW EUI/VPUI skins, the `(3a)` compatibility layer and its database/text actions. Excludes the CP/VP `LUA` directories as required by upstream's EUI installation layout; retains core overrides and addins.
- Embeds EUI inside the existing managed data package. Installation, interrupted-install recovery and removal use the same verified core/cache/save transaction. Separate EUI/VPUI copies are refused and preserved, including recognized renamed packages.
- Bundles both interface choices in the app; adds `vp-mac.py install --eui` and reproducible EUI packaging instructions.
- Native core, upstream sources and Mac save format are unchanged. Standard VP's payload is retained. EUI in-game validation on Mac is pending; start a new game when switching interfaces.

## 0.1.0-beta.3 — clearer installation explanation

- Explains directly in the installer that Mac Civ V already has a game core, but cannot load VP's Windows DLL from MODS. The installer replaces that core with the native Mac VP version and installs its matching startup data, with backups.
- Clarifies the same requirement in the installation guide and README. Installation behavior, game core, data and save format are unchanged from beta.2.

## 0.1.0-beta.2 — graphical Mac installer

- Adds a native universal Apple Silicon / Intel installer app: game picker, compatibility check, install, restore, diagnostics and copyable details.
- Bundles checksum-pinned Python 3.13.16 runtimes; players do not need to install Python or Apple's developer tools.
- Replaces installer-only `nm`/`lipo` calls with bounds-checked Mach-O inspection, retaining the exact host hash, core exports, signature, 218-slot vtable and save-identity checks.
- Explains why this port cannot be installed through the MODS folder: the Mac core and startup database must be installed together.
- Reuses the exact beta.1 game core and full VP payload. Gameplay behavior and save format are unchanged; beta.1's validation limits still apply.
- The GUI app is ad hoc signed, not Apple-notarized. The game core retains its existing signature and hash.

## 0.1.0-beta.1 — 0.1 beta

First packaged Mac beta, based on Community Patch / Vox Populi 5.4.8, upstream commit `7307aefdf985a4f401a7996a896283557b896e2b`.

- Uses the same native x86_64 core tested under Rosetta; no gameplay source fork.
- Includes the standard CP + full VP package without EUI: 414 database actions, 1,716 upstream runtime files, 16 UI addins and 24 map scripts.
- Adds player commands for install, status, report and uninstall, with an EUI conflict check.
- Preserves the verified original core, cache and saves; isolates beta saves using Mac save format 1.
- Pins upstream in a Git submodule and provides a repeatable archive builder with checksums and source snapshots.

### Validation

CP city/turn/save/reload/turn passed. Full VP first-session bridge/game-data checks, save-boundary writes and normal context teardown passed. Full VP reload was skipped and assumed from the earlier CP core test at the tester's request. Extended gameplay remains unverified.

### Known limits

- Steam Aspyr Mac build 1.4.2 (180925) only; other executables are refused.
- Single player, without EUI or additional mods. Multiplayer and 43-civ variants are untested.
- Debug build; no optimized-build performance validation yet.
- The XML database snapshot omits custom SQL indexes and triggers. The live VP cache has no CP `idx_*` query indexes. VP's final trigger file explicitly targets additional mods; absence alone does not establish a standard-gameplay defect.
- Two duplicate `ArtDefine_StrategicView` warnings remain under review. They did not prevent the tested session from completing.
- No stock/Windows save conversion, future-version save guarantee, or graceful foreign-save conversion UI.
- Changed Steam files or modified backups stop restoration rather than being overwritten.

### Next priorities

Package fidelity and query indexes; longer games and broader UI coverage; optimized build; a combined build/update command. Keep changes in the Mac adapters and tooling, deriving gameplay/data from upstream.
