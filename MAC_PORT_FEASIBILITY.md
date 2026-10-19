# Vox Populi on Steam Civ V for macOS: feasibility and port plan

Assessed 18 October 2026 against the local installation and source checkout.

**Verdict: a native Mac game-core port is plausible, but unproven and substantial.** Your installed game has a dynamically loaded 64-bit Intel core and exposes many of the support functions a replacement would need. The main uncertainty is reproducing Aspyr's C++ binary interface, followed by resolving every support function used by Vox Populi. This is more than changing the build system or renaming the Windows DLL.

The correct target is **x86_64 macOS**, running with the game under Rosetta. An ARM64-only library cannot be loaded into this Intel game process. Rosetta does not make a Windows PE DLL into a macOS library. See [Apple's Rosetta documentation](https://developer.apple.com/documentation/apple-silicon/about-the-rosetta-translation-environment).

## What is installed and what was checked

| Item | Observed locally |
| --- | --- |
| Host | Apple Silicon (`arm64`), macOS 26.5.2 |
| Steam app/build | Civ V app 8930, Steam build 4390913 |
| Mac bundle | `com.aspyr.civ5xp.steam`, version 1.4.2, build 180925 |
| Main game executable | Mach-O, x86_64 |
| Brave New World core | `Contents/MacOS/libCvGameCoreDLL_Expansion2_DLL.dylib`, Mach-O, x86_64 |
| Local VP source | 5.4.8, commit `7307aefdf985a4f401a7996a896283557b896e2b` |
| Shipped VP core | `CvGameCore_Expansion2.dll`, PE32, Intel 80386, Windows |
| Required DLC | All 10 Community Patch dependency GUIDs have installed package manifests, including Gods & Kings and Brave New World |
| Current user MODS directory | Empty at inspection |

The Mac bundle version is not the Windows game version required by upstream; engine revision and mod version checks still need runtime verification. DLC manifest presence does not by itself prove runtime activation.

Installation:

```text
/Users/work/Library/Application Support/Steam/steamapps/common/
  Sid Meier's Civilization V/Civilization V.app
```

User data:

```text
/Users/work/Library/Application Support/Sid Meier's Civilization 5/
```

The audit used `file`, `nm`, `otool`, Mach-O bind tables, focused disassembly, source inspection and an Apple Clang syntax probe. It did not launch the game, load its libraries, alter the installation or install mods. The source checkout remains unchanged. [Aspyr's FAQ](https://support.aspyr.com/hc/en-us/articles/360020548611-Civilization-V-Mac-FAQ) independently confirms that Mac Steam Civ V is 64-bit and documents this user-data location.

## The important positive finding: a replacement boundary exists

The stock BNW dylib exports just one public symbol:

```text
_DllGetGameContext
```

VP already implements the corresponding C entry point in [CvGameCoreDLL.cpp](Community-Patch-DLL/CvGameCoreDLL_Expansion2/CvGameCoreDLL.cpp:18). The engine communicates through versioned `ICv*` virtual interfaces. That gives us a concrete boundary to target, although the Mac vtables and types must be checked against the published Windows headers.

The stock Mac core imports **460 unique symbols**. **360 are also exported by the main game executable**, including:

- `Database::Connection` and `Database::Results` methods;
- `Localization::String`, `FStringA/W`, `FDataStream` and archive methods;
- world-builder map and FLua support;
- Lua C API functions;
- compatibility functions such as `CoCreateGuid`, `HeapAlloc`, `QueryPerformanceCounter` and `timeGetTime`.

The remaining 100 are runtime/system imports consistent with its libc++ and libSystem dependencies. The binding table shows flat-namespace lookups for engine support functions. This suggests that a replacement can reuse much of Aspyr's existing support code rather than recreate every proprietary SDK component.

**This measures stock-core imports only.** It does not establish that all VP imports are available, nor that any shared class layout is compatible. The port must generate and audit its own complete undefined-symbol list.

The [2018 upstream Mac discussion](https://github.com/LoneGazebo/Community-Patch-DLL/issues/4686) identified static linking and unavailable SDK sources as obstacles. The static-linking description does not describe this installed 64-bit build. The unavailable-source issue remains relevant, but the executable's exports provide a possible route around it.

## Required changes, in dependency order

### 1. Add a Mac build target

Create an Apple Clang build, preferably CMake, for `x86_64` and libc++. Keep the existing Windows build working.

The current Visual Studio project targets `MachineX86` with the v90 toolset. The existing Clang scripts also build Windows code: `clang-cl.exe`, `-m32`, Windows headers and `.lib` files. They are not a Mac build system.

The linked SDK packages are `CvGameCoreDLLUtil`, `CvGameDatabase`, `CvLocalization`, `CvWorldBuilderMap`, FireWorks, FLua and Lua 5.1. Their directories contain headers and Windows libraries, but no `.c`/`.cpp` implementation files. Those binaries cannot be linked into the native Mac core. Use verified executable exports where possible; obtain compatible implementations or add narrowly scoped adapters for remaining functions.

The source tree contains 173 C++ implementation files and 194 headers, roughly 607,000 lines. That is the inspected scope, not an estimate of lines needing changes.

### 2. Establish Mac declarations and binary layouts before linking support code

This is the highest-risk work. Matching a function's name is insufficient if it receives an object with the wrong size or layout.

| Type | Current Windows target | Mac x86_64 target |
| --- | ---: | ---: |
| pointer | 4 bytes | 8 bytes |
| `int` | 4 | 4 |
| `long` | 4 | 8 |
| `size_t` | 4 | 8 |
| default `wchar_t` | 2 | 4 |

These sizes were checked using compiler target macros. Concrete problems in the available headers include:

- `FFireTypes.h` defines `dword` as `unsigned long`. Its non-Windows `GUID` also uses `unsigned long` for `Data1`, which produces the wrong layout on LP64. A packed 16-byte `ICvUnknown` GUID constant is present in the stock core. Define and verify the Mac-facing GUID representation explicitly.
- `FCriticalSection.h` has Windows and PS3 storage definitions but no Mac member storage. Turning off `WIN32` leaves an empty class, despite the executable exporting nontrivial constructor and locking functions. Its Mac layout must be recovered or isolated behind a compatible adapter.
- `Database::Results` embeds `stdext::hash_map`; localization classes embed TR1 smart pointers and other containers. Substituting a different container can change offsets and allocation sizes that Aspyr's constructors expect.
- The public localization header declares `PushArgument(const __int64)`, while the Mac executable exports `Localization::String::PushArgument(long)`. Apple Clang's MS extension treats `__int64` as `long long`; those types have different C++ mangled names even when both are eight bytes.

Audit all shared types: `FString`, `FDataStream`, database results/connections, localization objects, archive classes, world-builder structures, allocator records, and `ICv*`/`ICvDLL*` interfaces. Verify size, alignment, fields, virtual slots, parameter/return conventions, libc++ ABI configuration and ownership. Do not globally force Windows type widths or enable short `wchar_t` without checking the corresponding Mac interface.

Gameplay classes wholly inside the replacement can change layout. Objects created, destroyed or accessed by both the game and the replacement require exact compatibility.

### 3. Isolate Windows platform code and library lifecycle

The first unmodified Apple Clang syntax probe stops at `CvGameCoreDLLUtil_Win32Headers.h:54`: **`Windows.h` not found**. Beyond that first failure, source inspection identifies:

- unconditional `Windows.h`, `MMSystem.h` and `tchar.h` dependencies;
- `__declspec`, `DLLCALL/__stdcall`, secure CRT functions and MS STL/TR1 usage;
- Windows crash handlers, `dbghelp.dll`, minidumps, SEH structures and Win32 memory/module APIs;
- x86 register assumptions and pointer truncation in stack/crash diagnostics;
- Win32 inline assembly in supporting debug/timer headers.

Create a Mac platform layer for types, attributes, timing, synchronization, file paths, GUID creation and diagnostics. Reuse Aspyr compatibility exports only with verified declarations. Keep minidumps and Windows stack walking in the Windows build; use macOS crash reports and appropriate Mac diagnostics for the port.

Replace Windows `DllMain` initialization/cleanup with a Mac lifecycle that preserves singleton creation, teardown and repeated game-core reloads. Retain the C entry point and export it explicitly; keep internal game-core symbols hidden to avoid accidental interposition.

### 4. Handle the Mac loader explicitly

The executable's loader helper at unslid address `0x10057f4d0` compares against three Windows-style identifiers:

```text
Assets\DLC\Expansion2\CvGameCore_Expansion2.dll
Assets\DLC\Expansion\CvGameCore_Expansion1.dll
CvGameCoreDLL.dll
```

It maps them to three fixed dylib names beside the main executable. Other identifiers take a failure path. The BNW mapping selects `libCvGameCoreDLL_Expansion2_DLL.dylib`. The caller uses `dlopen` at `0x10057f809` and resolves `DllGetGameContext` with `dlsym` at `0x10057f8af`.

**Static-analysis implication:** the existing `.modinfo` `OnGetDLLPath/SetDllPath` action is unlikely to load an arbitrary replacement from `MODS`. Runtime confirmation is still required, but normal Windows installation instructions do not fit this loader.

The first experiment should use an isolated, reversible replacement of the bundled BNW dylib, preserving its original, and keep the engine requesting the recognized stock identifier. A separate loader hook is an alternative if per-mod core selection is required later. A compatibility build may use dynamic lookup into executable exports, as the stock library does, with an explicit whitelist for every unresolved engine symbol.

Replacing the bundled core affects every BNW session using that app copy. Package selection must therefore select the matching core and data together. Verify signing and launch behavior on the local copy, and protect against Steam updates overwriting the replacement. The inspected executable has no hardened-runtime flag in its CodeDirectory; this does not by itself prove modified-app launch will succeed.

### 5. Package the SQL, XML, Lua, UI and assets together with the core

Most data and UI files are candidates for reuse. They still depend on VP's C++ behavior and Lua methods. For example, `LeaderHeadRoot.lua` calls vassal APIs implemented in `CvLuaTeam`; removing the DLL does not make a working VP variant.

Both core mod manifests already say `<SupportsMac>1</SupportsMac>`. That is metadata, not native binary support. VP explicitly depends on Community Patch. The core manifest's DLL path action needs platform-specific handling for the Mac loader strategy.

Replace the Inno Setup installer with a Mac packaging process that reproduces its actual component selection:

- Community Patch and VP data under the Mac user-data `MODS` directory;
- the appropriate non-EUI Lua files for the first full-VP build;
- `VPUI` in `Contents/Assets/Assets/DLC/VPUI`;
- optional `UI_bc1` and `(3a) VP - EUI Compatibility Files` only when EUI is selected;
- `VPUI Text/VPUI_tips_en_us.xml` under user-data `Text`;
- the city-state audio package changes under the bundled `DLC/Expansion2` tree.

The extra `Assets/Assets` nesting is real in this Mac installation. Merge the intended audio package changes into the installed Mac package rather than blindly overwrite it with a Windows package. Check virtual-file paths, case, load order and database schema updates. Start with standard civilization limits; defer the 43-civilization core and optional Squads until the base port is stable.

Use the game's existing Lua state and compatible Lua 5.1 API. The provided headers identify Lua 5.1.4 and define `lua_Integer` as `ptrdiff_t`. Validate the Mac host's exact conventions. Introducing a separate Lua runtime would not automatically integrate with the host's existing state.

## Recommended proof and acceptance gates

1. **Loader proof:** an x86_64 Mac wrapper, using an isolated app/core copy, logs its load and forwards to the preserved stock core. A stock game starts and exits normally. This establishes replacement loading and signing behavior; it does not establish VP compatibility.
2. **Support/ABI proof:** validate representative shared objects and engine callbacks for database, localization, strings/streams, Lua and memory ownership. Resolve or explicitly implement every symbol the native VP objects need. No unexplained unresolved symbols or guessed shared layouts.
3. **Community Patch core:** compile and load the standard-limit CP configuration. Found cities, fight, conduct diplomacy, run AI turns, then save, quit and reload. Repeat mod activation and core teardown/reload.
4. **Full VP without EUI:** apply data/schema/UI changes and verify happiness, supply, religion, diplomacy/vassalage, corporations, trade and VP Lua APIs. Use logs and sustained AI autoplay to expose failures beyond startup.
5. **Packaging and optional variants:** verify EUI, art/audio, installer rollback and update handling. Treat multiplayer and Windows save interchange as separate compatibility projects requiring explicit validation.

Proceed with a bounded loader/ABI prototype. Do not commit to a completion date for full VP until the shared-type and symbol checks pass. If unavailable support functions or unrecoverable layouts block the native path, running the Windows game and existing VP together in a suitable Windows compatibility environment is a separate fallback; it does not port the installed Mac game.

## Existing Mac fork checked

The public [Community-Patch-DLL-macOS fork](https://github.com/AngelaDMerkel/Community-Patch-DLL-macOS) has a Mac-support description. At inspection its only branch pointed to upstream 5.4.6 commit `dcb33a654cd9e8efb038a0733b4025e19cbcd8ba`, with no releases. GitHub's comparison returned **identical**, zero added commits and zero changed files against that upstream commit. It is not evidence of an implemented Mac port. [Comparison](https://github.com/LoneGazebo/Community-Patch-DLL/compare/dcb33a654cd9e8efb038a0733b4025e19cbcd8ba...AngelaDMerkel:master).

## Local evidence and reproduction

Run from this workspace:

```sh
python3 tools/inspect_mac_civ5.py
```

The script writes only to its output directory. It records binary hashes, bundle details, DLC manifests, symbol coverage, linked libraries, binding tables and the expected unmodified compile failure.

- [Machine-readable inventory](analysis/mac-civ5/metadata.json)
- [Stock support imports available from the executable](analysis/mac-civ5/stock-imports-provided-by-executable-demangled.txt)
- [Stock dylib lazy bindings](analysis/mac-civ5/stock-core-lazy-bind.txt)
- [Unmodified native compile probe](analysis/mac-civ5/unmodified-mac-syntax-probe.txt)
- [Focused loader disassembly and decoded strings](analysis/mac-civ5/loader-disassembly.txt)
- [Audit script](tools/inspect_mac_civ5.py)

The loader excerpt is a separately captured static analysis for executable SHA256 `d56d6bfbc0ef517fcb7cbaff46c42d1bdfab809c084684045761bd9d85807ee9`. Its addresses must be rechecked if Steam changes that binary. The general audit script does not regenerate that build-specific excerpt.
