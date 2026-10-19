# Stage 1: Mac Civ V loader probe

The native Community Patch core uses `install-native`; follow the [full Vox Populi test](../macos/README.md#full-vox-populi-test-without-eui) for the current milestone. This document describes the separate stock forwarding probe selected by `install`.

The default build now also includes the [stage 2 SDK ABI diagnostics](../macos/README.md). The loader-only behavior described here remains available with `-DVP_MAC_ABI_PROBES=OFF`. Run `python3 prototype/manage.py report` after a new test for a concise latest-session result.

This is a built, x86_64 macOS wrapper for the Brave New World core. It loads the preserved Aspyr core and returns its original `DllGetGameContext()` pointer unchanged. It records library lifecycle events and checks whether five selected engine-support symbols are visible.

**Gameplay remains stock Brave New World.** This milestone tests the native replacement boundary. It does not compile Vox Populi, wrap virtual interfaces, change shared object layouts or install mod data.

The wrapper has been built; the loader/installer and SDK ABI test suites pass on this machine. Real Steam game runs completed the five-turn/save check, all six ABI checks including database/localization, clean exit and byte-exact restoration. Evidence is preserved under `analysis/mac-civ5/`, including `real-abi-test.json` and `real-object-abi-test.json`.

The initial run exposed excessive accessor logging. The current build samples successful calls and records a total on unload. Restore an installed probe before installing a newer build.

## Test in the installed game

Use Terminal for these commands. The binary is already built; no rebuild is needed for this first test.

1. Quit Civilization V **and its launcher**. Keep Steam available.

2. Check the installation preflight, then install:

   ```sh
   cd /Users/work/Vox-Pop-Mac
   python3 prototype/manage.py install --dry-run
   python3 prototype/manage.py install
   python3 prototype/manage.py status
   ```

   The preflight should say `Ready`. After installation, status should contain `"state": "installed"` and `"backup_verified": true`. Installation checks that no Civ V app process is running, validates the Intel library and its entry point, and preserves the original before replacing it.

3. Launch Civ V normally from **Steam**, with **Brave New World enabled**. Use an ordinary single-player game with no mods. Start a small new map, found a city, and play at least five turns. Check that ordinary map, city and diplomacy screens work. Seeing normal Civ V gameplay is expected.

4. Save under a new name such as `Mac Loader Probe`, quit to desktop normally, then relaunch from Steam and load that save. Play another turn and quit normally. This exercises startup, gameplay, save/reload and cleanup in two separate game processes.

5. Read the probe log:

   ```sh
   python3 prototype/manage.py logs
   ```

   For each game process, look for:

   ```text
   event=wrapper_loaded VOX_POP_MAC_LOADER_PROBE_V1
   event=host_symbol symbol=timeGetTime available=yes
   ...four more host_symbol lines...
   event=original_ready ...libCvGameCoreDLL_Expansion2_DLL.vp-original.dylib
   event=context_forwarded call=1 context=0x...
   ...
   event=original_unloaded
   event=wrapper_unloaded
   ```

   The context must be non-null. `available=yes` is expected for all five selected symbols in this audited game build. A lookup checks symbol presence only; it does not establish C++ class-layout compatibility. Normal quitting should produce cleanup events; force-quitting may not.

6. With the game and launcher closed, restore the original after testing:

   ```sh
   python3 prototype/manage.py restore
   python3 prototype/manage.py status
   ```

   Status should return to `"state": "stock"`. Restore verifies the original hash and copies the original bytes back. The probe log is retained for analysis.

**Pass:** normal BNW startup, five turns, save/reload and exit, with `original_ready`, a non-null `context_forwarded` and normal cleanup in the log. This establishes that a Mac replacement core can forward to stock through the game's real loading path. The next milestone is verified support-function calls and shared-type layouts before porting CP/VP gameplay.

## If the test fails

Quit the game/launcher and run `restore` before trying another build. Preserve the launch error and the log. If the game refuses to launch before any probe log appears, the replacement may not have reached its constructor; investigate the launch/signature error. This tool ad-hoc signs only its own built dylib and does not change security settings or re-sign the entire app.

`original_open_failed`, `original_symbol_failed`, `original_recursion_refused`, `forward_failed` or `original_returned_null` are failure events. A non-null forwarded pointer followed by a gameplay failure means the loading milestone alone was insufficient; retain the macOS crash report as well.

If Steam changes the installed core after installation, restore refuses to overwrite the changed file. It also refuses corrupt backups, unmanaged backups and symlinks. Preserve those files for inspection rather than manually deleting or renaming them to make installation proceed.

Full log:

```text
/Users/work/Library/Application Support/Sid Meier's Civilization 5/Logs/VoxPopMacLoaderProbe.log
```

The logger appends UTC timestamps and process IDs. Successful context calls are sampled at startup and at exponentially spaced call counts; the unload event records the total. `logs` displays the last 80 lines, so use the full file when comparing multiple runs. A custom launch environment can set `VOX_POP_MAC_PROBE_LOG` to an existing directory's log-file path; ordinary Steam launching uses the path above. Logging failure does not prevent forwarding.

## Build and automated verification

The required Apple Command Line Tools, CMake and Python 3.11+ are present on this machine.

```sh
cd /Users/work/Vox-Pop-Mac
cmake -S prototype -B prototype/build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build prototype/build -j 4
ctest --test-dir prototype/build --output-on-failure
```

Output library:

```text
/Users/work/Vox-Pop-Mac/prototype/build/libCvGameCoreDLL_Expansion2_DLL.dylib
```

The build explicitly targets `x86_64`, uses an `@rpath` install name distinct from the stock core's root install name, exports only `_DllGetGameContext`, and ad-hoc signs the result. The wrapper itself does not need unresolved engine imports. Its synthetic stock-core fixture deliberately imports `timeGetTime` from the test executable, exercising the host-to-plugin binding that Aspyr also uses.

The tests cover forwarding, host imports, repeated load/unload, missing originals, missing entry points, recursion refusal, unavailable logs, nonmutating preflight, install idempotence, exact restoration, interrupted installation, external core updates, corrupt/untracked backups, symlink refusal and the process guard. They use temporary fake app directories and synthetic libraries, never the real game or its saves. They do not validate Aspyr's object layouts or run actual gameplay.

CTest's detailed result is at `prototype/build/Testing/Temporary/LastTest.log`. A separately captured synthetic example is under `prototype/build/smoke-test/`; its other engine symbols are absent by design because it is not the game executable. The test host reports an unknown translation status if its optional `sysctl` query is denied by the execution sandbox; the test executables and libraries are checked as x86_64.

## Installation layout and scope

Only these files in the selected app's `Contents/MacOS` directory are involved:

| File | Purpose |
| --- | --- |
| `libCvGameCoreDLL_Expansion2_DLL.dylib` | Probe during testing; original after restore |
| `libCvGameCoreDLL_Expansion2_DLL.vp-original.dylib` | Byte-for-byte stock core backup used by the probe |
| `.vox-pop-mac-loader-probe.json` | Hashes and installation transaction record |

The probe opens the original beside its own resolved image path, independent of the working directory. It keeps the original loaded while the wrapper is loaded, then balances the handle on unload. It passes opaque pointers only and makes no calls through guessed Civ V vtables.

`install`, `restore` and `status` accept `--app "/absolute/path/Civilization V.app"` for a separate app copy. `install` also accepts `--wrapper /absolute/path/to/the/built/library`. Read-only `status` and `logs` never launch the game. No command in this tool launches Civ V or installs Vox Populi data.
