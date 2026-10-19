# Release notes

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
