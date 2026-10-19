# Thin Mac layer: structure and validation

The maintenance boundary is **Mac platform and native SDK integration**. Community Patch supplies gameplay, AI, SQL, Lua and assets. The Mac layer should compile that upstream code directly as the native build becomes possible, with platform-specific changes isolated outside the checkout.

The loader and six SDK ABI diagnostics have passed real-game tests. The native Community Patch target compiles and links upstream directly. Real runs 44114 and 44163 passed the first city/turn/save/reload test, including a full turn after reloading and normal map/city screens. The same core with full Vox Populi data/UI passed all bridge/game-data checks, recorded four save-boundary writes and shut down normally in PID 45718. Full VP reload was skipped and assumed from the earlier CP test at the user's request. The original core, cache and saves are restored. The stock forwarding probe is excluded from the native payload.

## What is implemented

| Part | Responsibility |
| --- | --- |
| `macos/include/vp_mac/native_types.hpp` | Fixed-width native boundary types and size/alignment checks |
| `macos/abi/aspyr-steam-1.4.2.json` | Reviewed native engine identities, SDK declarations and function signatures |
| `macos/tools/sdk_contract.py` | Check upstream declarations, generate minimal native views and inventory the upstream project |
| `macos/tools/package_cp.py` | Apply ordered CP/VP database manifests and dependencies; package manifest-declared runtime files and upstream modpack UI addins |
| `macos/overlays.json` | Named, count-checked portability edits applied only to generated files |
| `macos/src/probe_checks.cpp` | Context, GUID, clock and stream/string interoperability diagnostics |
| `macos/src/object_checks.cpp` | Native database and localization object lifetimes and round trips |
| `macos/src/runtime_probe.cpp` | Match loaded Mach-O images before resolving or calling reviewed native functions |
| `macos/src/native_entry.cpp` | Native core identity check, singleton initialization and teardown |
| `macos/src/host_bridge.cpp` | Twelve guarded SDK forwarding functions, missing serialization helpers and startup checks |
| `macos/src/platform_support.cpp` | Native process-memory diagnostic |
| `macos/platform/include/` | Small Windows header facades and CP-owned container compatibility |
| `macos/include/vp_mac/crt.hpp`, `platform_services.hpp` | Missing integer conversion, module-path and diagnostic helpers |
| `prototype/` | Reversible stock forwarding, sparse logging, installer, restoration and report commands |

The generated context view contains the first four virtual slots used for identity queries. The stream view contains the complete SDK base vtable and data layout because the native string reader also calls `GetSizeLeft` and its error callback. Both are extracted from upstream declarations and checked against the reviewed contract.

Aspyr's `ICvPreGame1` has an additional by-value era-type string getter immediately after `era()`. Two checked overlays insert that declaration and its concrete override; `host_bridge.cpp` returns the current CP era's `Type`. The upstream gameplay methods remain unchanged. The profile checks both complete pregame interfaces, their GUIDs and inheritance, then verifies the exact symbols in all 218 native vtable slots before signing and installing the core. See `analysis/mac-civ5/pregame-abi-review.md` for the crash, disassembly and field-identification evidence. This is a reviewed pregame boundary, not a complete audit of every gameplay interface.

The generated `vp_mac/engine_objects.hpp` preserves the upstream public declarations for `Database::Connection`, `Database::Results` and `Localization::String`, including the fieldless `SingleResult` subclass and localization argument helpers. Their private storage is opaque, with reviewed native sizes of 184, 112 and 144 bytes. Native constructors, methods and destructors manage it; no Windows hash container is aliased to a modern libc++ container across this boundary. Private declarations, complete virtual-slot lists, used method signatures and enums are checked for drift. New nonvirtual methods are generated automatically. The native 64-bit signed localization overload uses `long`, matching Aspyr's symbol names. Future use of additional SDK objects must gain a reviewed native declaration.

The checked rules in `overlays.json` handle concrete compiler differences: dependent template lookup, annotation placement, empty variadic arguments, a swap exception specification, LP64 pointer alignment and mixed count types. They also suppress the incorrect non-Windows GUID fallback and a duplicate Lua integer specialization. The build checks Lua integer/number declarations against the native target sizes and reuses the game's Lua runtime.

Clang's [virtual filesystem overlay](https://www.llvm.org/docs/doxygen/classllvm_1_1vfs_1_1RedirectingFileSystem.html) redirects only those files and the reviewed SDK views. Original include paths and sibling includes keep working. Generated headers have a stable revision dependency; projected `.cpp` files have individual dependencies, so a gameplay-only edit does not invalidate every object. Build version metadata is generated outside the upstream tree.

The gameplay build uses C++14 and upstream's available Clang warning suppressions. Legacy STL adapters apply to CP-owned containers; the three native objects retain opaque storage. Save-game file operations, performance counters, heap APIs and available checked CRT functions call Aspyr's existing exports.

The profile records twelve native Lua/database entry points present in the executable but omitted from its exports. Small forwarding functions call them in the existing engine runtime. Build and native installation require the reviewed executable SHA-256; runtime dispatch checks its Mach-O UUID and each entry's first 32 code bytes before calling it. These addresses follow the stable Aspyr executable, independently of Community Patch releases. A new Mac executable requires a fresh profile review. Static identification and code evidence are recorded in `analysis/mac-civ5/internal-api-review.md`. All twelve passed their startup bridge checks in native run PID 32068; its later pregame crash is a separate ABI failure.

The SDK `dword` and CRC table entries remain 32 bits. Aspyr's `unsigned long` stream writer also emits four bytes despite LP64, so it cannot serialize CP's 64-bit RNG seed. The Mac layer encodes signed/unsigned 64-bit scalars explicitly as eight bytes and serializes GUID fields with fixed widths. Its startup check verifies exact bytes and round trips in both byte orders using a guarded native 72-byte `FMemoryStream`, including destruction.

Three optional Windows development facilities are excluded: the `TurnByTurn` debugger mutex hook, unused x86 naked timer helpers, and the in-game modpack creation tool. The five modpack authoring Lua calls raise an explicit error before touching files. Packaged data loading is independent. Unused private FLua error-handler classes remain forward-declared because their methods are not exported and their Windows callback cast is invalid on this ABI; future use will fail to compile rather than silently succeed.

## Why upstream updates should remain manageable

1. **No gameplay fork.** Nothing in `Community-Patch-DLL/` is changed by the build or generator. Build outputs inside the upstream checkout are refused.
2. **No hardcoded gameplay revision requirement.** Compatibility checks examine SDK declarations, ignoring comments and formatting. The SDK checks and all current portability rules pass against upstream 5.4.6 and 5.4.8; results are in `analysis/mac-civ5/upstream-version-check.json`. This is a source-contract check, not a gameplay test of both releases.
3. **Engine profiles follow Aspyr builds.** The reviewed Mach-O identities belong to the Mac executable and stock core, which are separate from Community Patch releases. Upstream AI or balance updates do not change those identities.
4. **Generated source stays generated.** Do not edit `prototype/build/macos/generated/`. Change a small adapter or a named rule when a real platform issue is found.
5. **Drift is explicit.** Changing a checked method slot, field type or interface GUID stops the build. A syntax rule must match its expected count. If upstream fixes that syntax itself, review and remove the corresponding rule rather than weaken the check.
6. **Discover upstream sources.** The gameplay target reads all 173 current C++ source entries and include directories from `VoxPopuli.vcxproj`. Only the Windows DLL entry translation unit is replaced by a small native lifetime adapter. There is no parallel handwritten gameplay file list.

For the full native build, prefer small platform shims and generated include overlays over editing gameplay `.cpp` files. If a platform-only source section needs an edit, keep it as a named, narrowly matched rule with its own test. Avoid copying full gameplay implementations into the Mac layer. Do not silently stub functions that CP needs for real behavior.

The final amount of compatibility code depends on the remaining SDK boundaries. Database, localization, allocators and world-builder objects may require additional native declarations or adapters. The current work does not establish that all of them can be handled by trivial aliases.

## Update workflow

Update the upstream checkout normally, then rebuild. Do not automatically rewrite the ABI contract when the build flags a mismatch.

```sh
cd /Users/work/Vox-Pop-Mac
python3 macos/tools/sdk_contract.py check
cmake --build prototype/build -j 4
ctest --test-dir prototype/build --output-on-failure
```

To validate a different upstream checkout without moving or patching it:

```sh
cmake -S prototype -B prototype/build-other \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DVP_UPSTREAM_DIR="/absolute/path/to/Community-Patch-DLL"
cmake --build prototype/build-other -j 4
ctest --test-dir prototype/build-other --output-on-failure
```

Create an inventory for a bug report or source-update review:

```sh
cmake --build prototype/build --target vp_mac_upstream_inventory
```

It records the upstream commit, source list and checked declaration fingerprint under `prototype/build/macos/upstream-inventory.json`. The commit identifies what was tested; it is not a compatibility gate.

For native gameplay development, use a separate build directory:

```sh
cmake -S prototype -B prototype/build-core -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=OFF
cmake --build prototype/build-core --target vp_mac_core -j 4
```

`vp_mac_core_objects` compiles the source files without linking. `vp_mac_core` builds a Mach-O bundle named `prototype/build-core/macos/libCvGameCoreDLL_Expansion2_DLL.dylib`, exporting only `DllGetGameContext`. Its `-bundle_loader` option requires all imports to resolve against the installed executable or system libraries. Set `VP_MAC_HOST_EXECUTABLE` for a nondefault Steam location. No unchecked `dynamic_lookup` is used by this target. The native entry validates the executable UUID before initializing Community Patch; it does not forward gameplay to the stock library. These development targets do not install anything.

## Native core startup test

The previous native bundle and matching database startup package passed this test in PID 39091, followed by the runtime-assets preview in PID 40217. The current format-1 build passed the first gameplay/save/reload test in PIDs 44114 and 44163. It also passes automated checks, all 34 source-contract rules against upstream 5.4.6/5.4.8, its linked 218-slot pregame ABI check and signature validation. The default database-only package remains for menu startup; use the separate gameplay packages below for new-game tests.

The earlier core-only test crashed in `CvDatabaseUtility::PrepareResults` while reading `Building_LakePlotYieldChangesGlobal`, which does not exist in the stock database. The crash evidence is in `analysis/mac-civ5/native-startup-crash.json`. Installing CP as a normal mod later in the menu cannot supply tables needed during initial menu caching, so the startup package uses the existing DLC modpack path.

The subsequent data-enabled run loaded the CP database and passed Lua, then crashed when the engine's boolean call at pregame offset `0x5c0` reached the version-string setter. The corrected interface now places `SetCityScreenBlocked(bool)` at that offset. The prior run and cache evidence are recorded in `real-native-bridge-test.json` and `real-cp-database-load.json` under `analysis/mac-civ5/`.

PID 34901 subsequently reached the main menu with that correction. Its shutdown crashed during `CvDllGameContext::Uninit()`, before singleton destruction, when the plot manager entered an overwritten lock. `FCriticalSection` now receives opaque 40-byte, 8-aligned native storage through one checked overlay; Aspyr still supplies all locking operations. The evidence is in `analysis/mac-civ5/critical-section-abi-review.md` and `native-shutdown-lock-crash.json`.

PID 39091 then passed the guarded native lock lifetime check and normal context teardown, with no reported failures or matching crash. Its actual report is in `analysis/mac-civ5/real-native-startup-test.json`. The stock library hash and restoration of the stock cache were verified afterward. This is the completed startup milestone.

Quit Civ V and its launcher, then run in Terminal:

```sh
cd /Users/work/Vox-Pop-Mac
python3 prototype/manage.py restore
python3 prototype/manage.py install-native
```

Installation verifies the matching core/data hashes, installs `VP_MAC_CP` under the bundled `Assets/Assets/DLC`, and moves the original user-data `cache` to `cache.vp-mac-stock-backup`. It verifies the stock merged language database, then copies only `Localization-*.db` back with their original timestamps and verifies every copy. Gameplay databases rebuild; working language caches remain available. Existing VP modpacks are refused to avoid conflicting overrides.

An empty-cache launch exited before the native entry point because Aspyr failed to copy its base localization database while rebuilding `Localization-Merged.db`. The individual source language databases matched the working stock/previous-run copies byte-for-byte, while the failed merged output was empty. Keeping the working language caches avoids forcing this unrelated native-engine rebuild. Evidence is recorded in `analysis/mac-civ5/localization-cache-review.json`; PID 34901 confirmed that this policy reaches the menu.

Launch through Steam with BNW enabled, wait for the main menu, then quit normally. Collect the result and restore, including after a crash:

```sh
python3 prototype/manage.py native-report
python3 prototype/manage.py restore
```

Restore removes verified owned package files and restores both the original core and stock cache. Any new test cache is preserved beside it as `cache.vp-mac-session-<timestamp>` for debugging. Nothing in upstream is changed. Unexpected edited package files or a modified stock backup stop restoration before the core changes.

The native core checks its executable profile, recursive lock construction/use/destruction with memory guards, eight-byte/GUID serialization, float/double database binding, transaction commit, analysis and explicit close/reopen. It then initializes the real CP context. On first game-script registration it checks Lua table access, metamethods, stack replacement, compilation, protected calls and error handling using private stack objects, restoring the original stack afterwards. The ABI database check uses private `:memory:` storage; `game_data` records completion of the actual upstream gameplay database cache. Fatal precondition messages now appear in `failures` with the original query and database error.

The complete result is:

```json
{
  "native_core": true,
  "profile": "passed",
  "lock_bridge": "passed",
  "stream_bridge": "passed",
  "database_bridge": "passed",
  "lua_bridge": "passed",
  "game_data": "passed",
  "save_identity": "passed",
  "save_guid": "68D2A25F-DA12-49C6-A780-30F193FED051",
  "save_headers_written": 0,
  "save_headers_read": 0,
  "context_ready": true,
  "context_destroyed": true,
  "startup_result": "passed",
  "failures": []
}
```

If the main menu does not register game scripts, `lua_bridge` stays `not_run` and the overall result stays `incomplete`. Send that report as well. Context teardown is reported separately from the game's later global/process teardown. The startup result does not establish gameplay, save compatibility or full VP data loading. Restore even if startup fails or no native log is produced.

`native-report` also checks recent macOS DiagnosticReports for the same PID and session time. When a matching crash exists it reports `failed`, includes the first native stack frame and retains each successful bridge result. Old reports and reports for other PIDs are excluded. If macOS has not finished writing its report yet, the result can initially remain `incomplete`.

If the native core has not been entered, the report returns `not_started`, or `failed` with `stage: before_native_entry` and fresh database/localization errors when available. Preparing another test prevents stale engine errors from being attributed to it.

Native logging uses `VoxPopMacNativeCore.log` alongside the old probe log. Both modes share the same verified backup/restore transaction; restore before changing modes or installing another build. Neither recognized managed-core marker can be backed up as stock. Native installation verifies the host before writing anything; Steam updates and changed backups retain the existing refusal protections.

## Rebuilding CP startup data

`package_cp.py` reads the CP `.modinfo` action order, applies its SQL and XML to an in-memory copy of the installed stock database, and emits the same full-database XML/override layout as upstream's `ModpackMaker.lua`. It discovers the upstream skip lists rather than maintaining copies of gameplay tables. It uses a small, fail-closed XML action subset; unknown operations stop packaging. Database connections close on success and failure. No database parsing code is added to the native core.

The current package includes all 172 CP database actions, 823 gameplay tables and English text. A narrow recorded repair resolves upstream 5.4.8's `CoreGameOptionTextChanges.xml` action to its supplied `.sql` file. Source files remain untouched. This is a database-only startup package: it does not include UI/assets or preserve SQL triggers/indexes in the XML snapshot, and is not a gameplay release.

After rebuilding the core, restore any installed test first. With Civ V closed and a stock BNW cache available, build to a new directory:

```sh
python3 macos/tools/package_cp.py \
  --app "$HOME/Library/Application Support/Steam/steamapps/common/Sid Meier's Civilization V/Civilization V.app" \
  --cache "$HOME/Library/Application Support/Sid Meier's Civilization 5/cache" \
  --output prototype/build-core/VP_MAC_CP-next
python3 prototype/manage.py install-native --data-package prototype/build-core/VP_MAC_CP-next
```

Existing output directories are refused. The package manifest binds its files to the exact native core hash and records its upstream commit and input hashes. A package for an older core is refused at install time. All source/cache inputs are read-only during packaging.

## CP runtime-assets preview

`--runtime-assets` adds the CP `.modinfo` files marked `import=1`, plus entry-point scripts and their declared Lua/XML companions. The Windows DLL selected by `OnGetDLLPath` is excluded; the tested native core remains the only replacement core. Source paths are preserved under `Mods/CommunityPatch`, with no maintained list of individual assets.

The builder reads the `ADDIN_FILES` declarations from upstream `ModpackMaker.lua`. Like the upstream Windows modpack tool, it copies the addin consumer scripts into `UI/` and appends `g_uiAddins` registrations. The existing upstream hook loads the contexts; no gameplay script bodies are rewritten. Unknown addin types, changed consumer hooks, missing files and ambiguous VFS basenames stop packaging.

The original preview is `prototype/build-core/VP_MAC_CP-runtime-preview`: 586 source files, nine addin registrations and 1,169 inventory files in total, including the database package and five generated UI consumer copies. It passed menu/resource startup and normal context teardown in PID 40217, using the previous `6b4a…` core. The actual report is `analysis/mac-civ5/real-native-runtime-assets-test.json`. Its files subsequently passed the initial gameplay test with the format-1 core. This older artifact remains historical; its hash does not match the new format-1 core.

To reproduce it, choose a new output directory with the game restored to stock:

```sh
python3 macos/tools/package_cp.py \
  --app "$HOME/Library/Application Support/Steam/steamapps/common/Sid Meier's Civilization V/Civilization V.app" \
  --cache "$HOME/Library/Application Support/Sid Meier's Civilization 5/cache" \
  --runtime-assets --output prototype/build-core/VP_MAC_CP-runtime-next
```

The default database-only package has been rebound to the new core for startup regression tests. The format-1 runtime package is `VP_MAC_CP-gameplay-probe`. A runtime build whose core contains the reviewed Mac GUID/header is marked ready for a bounded gameplay test; this is not a validation result. The installer isolates its local save folder. Neither menu pass establishes ongoing SQL trigger behavior, full VP or working in-game UI contexts.

## First native CP new-game test

The format-1 core and matching `VP_MAC_CP-gameplay-probe` passed this test in PIDs 44114 and 44163. The user confirmed both full turns and normal map/city screens. The first process recorded four save boundary writes; the reload process recorded one read. Both contexts shut down normally, with no reported bridge failures. Evidence is in `analysis/mac-civ5/real-native-gameplay-test.json`. Stock core/cache/saves have been restored and experimental saves preserved separately.

Their 1,169 data/asset files are byte-identical to the runtime preview that passed PID 40217. Three checked source rules change the returned core GUID and insert save-boundary calls before the upstream game reader/writer. They preserve the upstream serializer bodies. See `analysis/mac-civ5/native-save-format-review.md` for the exact format and scalar-width audit. The following procedure reproduces the CP-only test.

With Civ V and its launcher closed:

```sh
cd /Users/work/Vox-Pop-Mac
python3 prototype/manage.py install-native --data-package prototype/build-core/VP_MAC_CP-gameplay-probe
```

This transaction also preserves the original `Saves` directory as `Saves.vp-mac-stock-backup` and activates a fresh directory. Existing local saves and autosaves remain in the verified backup. Use this order:

1. Launch from Steam and start a **new single-player BNW game**, preferably Duel size with two civilizations.
2. Found the capital and finish one complete turn. Save as `VP Mac Probe 1`, then quit to desktop.
3. Keep the same installation active. Relaunch from Steam, load `VP Mac Probe 1`, play another turn and quit to desktop.
4. Collect the report, then restore even if any step crashes:

```sh
python3 prototype/manage.py native-report
python3 prototype/manage.py restore
```

The new report should have `save_identity: passed`, the Mac GUID above, and at least one `save_headers_read` after reload. Boundary counters alone do not prove a complete saved game/reload; the observed turn after loading is required. After restoration, experimental saves remain under the printed `Saves.vp-mac-session-<timestamp>` path and original saves return to their normal location. Keep saving/reloading within the same installed test until restoration; a subsequent installation creates a fresh experiment.

This format intentionally differs from stock and Windows CP. A foreign or missing tag fails the existing fatal precondition path before this game reader resets/parses the object; no conversion or graceful rejection UI is implemented. The first test establishes only the exercised new-game/turn/save path, not full VP, multiplayer or platform interchange.

## Full Vox Populi test without EUI

`prototype/build-core/VP_MAC_VP-gameplay-probe` adds `(2) Vox Populi` after `(1) Community Patch` using the **same tested native core**. It contains 414 database actions, 1,716 manifest-selected runtime files, 16 UI addins and 24 map scripts. `BALANCE_VP` is enabled; events, city events, corporations and the free-luxury mission are present. All 2,299 payload file hashes and read-only installer/save preparation checks pass. PID 45718 passed every bridge/game-data check, recorded four save-boundary writes and shut down normally. The archived live cache confirms `BALANCE_VP = 1` and populated event/corporation tables. Full VP reload was not repeated; it is assumed from the preceding CP test at the user's request. See `analysis/mac-civ5/real-native-vp-first-session-test.json`. The stock installation is restored. The procedure below remains available to reproduce the test.

The builder checks the mod IDs and declared version dependencies, preserves action order and copies each mod into an ordered folder. It combines addin registrations after selecting the final UI consumers, preserving both mods' addins. No gameplay SQL, Lua or C++ is maintained separately. `Replace` XML actions use SQLite replacement semantics. One VP Explorer map XML document is identical to the installed stock document; it is reused only after checking the complete existing rows, and the match is recorded in the package manifest. Conflicting data still fails packaging.

With Civ V and its launcher closed:

```sh
cd /Users/work/Vox-Pop-Mac
python3 prototype/manage.py install-native --data-package prototype/build-core/VP_MAC_VP-gameplay-probe
```

1. Launch through Steam. Use **regular Single Player → Set Up Game**, with BNW enabled; the package loads automatically.
2. Start a **new** Duel or Tiny game. Found a capital, select research and production, open the city screen, and play five turns.
3. Save as `VP Mac Full 1` and quit to desktop. Relaunch with the same installation, load that save, play another full turn, and quit normally.
4. Collect the report and restore, including after a crash:

```sh
python3 prototype/manage.py native-report
python3 prototype/manage.py restore
```

Send the report and any visible failure or broken screen. A successful reload should record at least one `save_headers_read`, all bridge checks passed, and normal context destruction. The installer isolates saves again; keep the installation active between saving and reloading. This test starts a fresh game because the database differs from the preceding CP-only experiment.

To rebuild from another upstream update with stock BNW cache available, choose a fresh output directory:

```sh
python3 macos/tools/package_cp.py \
  --app "$HOME/Library/Application Support/Steam/steamapps/common/Sid Meier's Civilization V/Civilization V.app" \
  --cache "$HOME/Library/Application Support/Sid Meier's Civilization 5/cache" \
  --runtime-assets --vox-populi --output prototype/build-core/VP_MAC_VP-next
```

EUI and 43-civilization variants remain separate. Like upstream Modpack Maker, this package uses a database XML snapshot; ongoing trigger behavior and extended gameplay still need validation.

## In-game test: database and localization

The first ABI run passed all four context/GUID/clock/stream checks and forwarded 476,256 context requests. The expanded run (PID 13188) passed all six checks, including database and localization, and forwarded 550,205 requests. Both unloaded cleanly and the original core was restored byte-for-byte. Reports are preserved at `analysis/mac-civ5/real-abi-test.json` and `analysis/mac-civ5/real-object-abi-test.json`.

The library is built at `prototype/build/libCvGameCoreDLL_Expansion2_DLL.dylib`. For a fresh test, first restore any installed probe, then close Civ V and its launcher and run:

```sh
cd /Users/work/Vox-Pop-Mac
python3 prototype/manage.py install
```

Launch through Steam, load a stock BNW save or start a small unmodded game, play a turn, and quit normally. The checks run once on the first context request. The stream checks use a bounded private buffer. The database check creates a private `:memory:` database, prepares a parameterized query, binds an integer and UTF-8 text, reads both by column name, resets/rebinds, then destroys results before the connection. The localization check constructs, converts and destroys a literal UTF-8 string. All three objects have adjacent memory guards checked after destruction. The checks do not edit the live game database or save.

Then run:

```sh
python3 prototype/manage.py report
python3 prototype/manage.py restore
```

The latest-session report should contain:

```json
{
  "abi_checks": {
    "abi_context": "passed",
    "abi_guid": "passed",
    "abi_clock": "passed",
    "abi_stream": "passed",
    "abi_database": "passed",
    "abi_localization": "passed"
  },
  "abi_result": "passed",
  "clean_unload": true,
  "failures": []
}
```

These fields establish:

- native by-value 16-byte GUID arguments/returns and the first context vtable slots;
- native GUID creation without overwriting adjacent memory;
- 64-bit performance-counter arguments and monotonic reads;
- callbacks from host serialization code into our C++ stream vtable, both integer byte orders, and allocation-sized UTF-8 `std::string` round trips across the host's libc++ boundary;
- native database construction/destruction, statement binding/reset and private column lookup containers;
- native localization construction/destruction and UTF-8 literal conversion.

The game executable and preserved stock core must match the reviewed Mach-O UUIDs. Other images produce `skipped_unreviewed_images`, which is not a passing ABI test. UUIDs identify the reviewed builds; they are not a cryptographic integrity check.

The report streams the existing log and retains the latest session, so the original verbose log need not be deleted. An interrupted probe reports `incomplete`; only the final six-check result can report `passed`. Restore still checks the original backup hash and preserves an externally updated core. If the game fails to launch, collect the report and restore without playing a turn.

## Validation and remaining work

Automated coverage includes native synthetic interoperability checks, negative ABI cases, constructor/destructor ownership and cleanup after query failures, memory-guard failures, unsupported-image refusal, SDK drift detection, source-preserving overlays, loader lifecycle, logging bounds and installer rollback. Synthetic results are separate from real-game results. Static review evidence is recorded under `analysis/mac-civ5/`, including `database-allocation-sites.txt` and `localization-literal-constructor.txt`.

The remaining work is:

1. **Audit package fidelity.** Compare the live database and effective UI/assets with the ordered upstream result. The archived VP cache has none of CP's `idx_*` query indexes: XML snapshots preserve rows, not those indexes. Review an upstream-derived way to retain them. VP's final `Triggers.sql` explicitly targets additional mods; its absence alone does not establish a standard-gameplay defect. Resolve the duplicate strategic-view art warnings with evidence rather than suppressing errors.
2. **Exercise more gameplay.** Cover longer AI games, combat, diplomacy/trade, policies/religion, workers, great people, events and later-era corporations. Extend UI and custom-map coverage. Only change native adapters when a concrete failure identifies a missing boundary.
3. **Build for performance.** The tested core is a Debug build. Produce and compare an optimized build; make optional bridge diagnostics configurable while retaining required host/save checks and useful crash logs.
4. **Make updates reproducible.** Combine upstream contract checks, native compilation, ordered data/assets packaging, hashes and reports into one local command. Keep the ABI profile tied to Aspyr and derive gameplay content from upstream manifests.
5. **Optional variants.** Add EUI, other languages, multiplayer and 43-civilization variants after the standard configuration is stable.

`VP_MAC_ABI_PROBES=OFF` retains the loader-only build for comparison. Runtime probes are intended to be excluded from a future release gameplay core.
