# Vox Populi for Mac — 0.1 beta

Play Vox Populi on the **Steam macOS version of Civilization V: Brave New World**, including Apple Silicon Macs running the game through Rosetta.

Vox Populi improves Civ V's AI and expands its gameplay. This unofficial Mac port runs the upstream Community Patch game core natively in the Mac game process and includes the full Vox Populi balance changes, interface and assets. **Optional Enhanced User Interface (EUI) is included in the installer.** It is an early beta for single-player testing; EUI needs in-game testing on Mac.

The Mac compatibility code lives separately from the [upstream Vox Populi project](https://github.com/LoneGazebo/Community-Patch-DLL). This repository pins an untouched upstream checkout instead of maintaining a separate gameplay fork.

## Before you install

- Own the **Steam Mac edition** of Civ V, **Gods & Kings**, **Brave New World**, and all gameplay/civilization DLC. A Complete Edition installation is the simplest match.
- This beta supports the reviewed **Aspyr 1.4.2 (180925), Intel x86_64** game build. The installer checks the executable and refuses a different build. Apple Silicon runs that game through Rosetta. Other storefronts and game builds are untested.
- The graphical installer requires **macOS 11 or newer** and includes its own Apple Silicon and Intel Python runtimes. You do **not** need Terminal, a separate Python installation, or Apple's developer tools to use the app.
- Launch normal, unmodified BNW once and quit to create its working cache.
- Quit **Civ V and its launcher**. Steam can stay open.
- Remove conflicting DLC mods as described below. Keep a separate copy of important saves.

The graphical beta is the **complete `-macOS.zip` release**, not GitHub's automatic “Source code” download. A source checkout needs a local build; see the [developer guide](docs/DEVELOPMENT.md).

## Install

1. Extract `Vox-Populi-Mac-0.1.0-beta.4-macOS.zip` and keep **Vox Populi Mac Installer.app** in Documents or Applications.
2. Double-click the app. It finds the default Steam installation. If Steam uses another library, click **Choose Game…** and select `Civilization V.app`.
3. Leave **Enhanced User Interface (EUI)** unchecked for the standard interface, or check it to install the bundled VP-compatible EUI. Click **Check Compatibility** to check your selection without changing files.
4. Click **Install Beta** and wait for **Vox Populi is installed**. No administrator password is requested; the app needs normal write access to your game and user-data folders.
5. Launch Civ V through Steam with BNW enabled. Choose **regular Single Player → Set Up Game** and start a **new game**. The package loads automatically; there is no Mods-menu activation step.

This community beta is **ad hoc signed, not Apple-notarized**. macOS may block a downloaded copy. For an app you trust, Apple's per-app **System Settings → Privacy & Security → Open Anyway** flow may be available after the first launch attempt. See [Apple's instructions](https://support.apple.com/en-au/102445).

## Choosing EUI or changing an existing beta

EUI changes the city screen, unit panel, tooltips, top bar and other interface screens. The installer includes the EUI version and VP compatibility files from the same pinned upstream revision as the game data. You do not need a separate EUI download or MODS-folder activation.

If a beta is already installed, quit the game and click **Uninstall / Restore** first. Then select or clear **Enhanced User Interface (EUI)** and install again. The installer shows which interface is installed and locks the checkbox until restoration. Start a **new game** after switching; cross-interface saves are untested. Your previous beta saves are archived during restoration.

Move any separately installed `UI_bc1` or `VPUI` folders completely outside the game's DLC folder before using either option. The installer refuses those copies, including recognized renamed packages, and leaves them intact. Its bundled EUI is managed inside the VP data package and removed by **Uninstall / Restore**.

To test EUI, start a new regular Single Player game, found a city, choose production and research, inspect unit actions and plot tooltips, and open the city and policy screens. Play a few turns, save, quit, relaunch, reload and finish another turn. Report missing controls, blank panels or Lua errors using **Diagnostics → Copy Details**, and mention that EUI was selected. Startup checks alone do not verify the interface.

## Why the MODS folder is not supported

Copying this beta into `MODS` will not install it. Mac Civ V already has its own **native game core**, but it cannot load Vox Populi's **Windows DLL** from the MODS folder. This port replaces the stock core with a native Mac version of the VP core, alongside its SQL, Lua and assets.

In this port, the native VP core runs while the game is starting, before ordinary mod activation. Its matching database tables must already exist at that point. A normal MODS-folder copy cannot replace the Mac core or supply that early startup data. Missing VP tables caused startup failures during development.

The installer therefore manages the **native core and matching DLC-style data package together**, with a verified backup and restore path. Do not copy the Windows VP folders into MODS, activate another copy of CP/VP, or try to move only this beta's assets into MODS. This restriction concerns installing this port; it does not mean every other Mac mod uses the same installation method.

**VP stays active for regular games until you uninstall it.** This is a replacement game core plus a DLC-style data package, not a mod you can toggle independently for each save. Do not activate another copy of CP or VP.

## Your saves and original game files

The installer preserves and verifies the original game core, moves your normal cache and `Saves` folder aside, and creates a separate save folder for the beta. Working language caches are retained. Your original files return when you uninstall.

Start a **new beta game**. Stock Civ V saves and Windows VP saves are not supported. Beta saves use a separate Mac format and are not intended for stock Civ V or Windows VP. Keep the same beta installed while saving and reloading a campaign; compatibility with future beta versions is not promised.

When you uninstall, beta saves and cache are preserved in dated folders next to your normal Civ V user-data folders. The uninstaller prints their locations. A later installation starts a fresh beta save folder. To resume an archived game, install the **same beta**, then copy its named `.Civ5Save` from the archived `Saves.vp-mac-session-…/single` folder into the active `Saves/single` folder while the game is closed.

## Other mods and conflicts

For beta 0.1, use **this package on its own**, with the official DLC.

| Other content | Beta 0.1 guidance |
| --- | --- |
| Another Community Patch, Vox Populi or VP modpack | Conflicts with the included core and data. Remove/restore it first. The installer refuses detected VP modpacks. |
| EUI bundled with this installer | Supported as an optional, experimental interface. Select the EUI checkbox before installation. It is restored together with VP. |
| Separate EUI / `UI_bc1` or `VPUI` | Conflicts with the managed interface. Move these folders completely outside DLC for either installation option. Renaming a recognized package inside DLC is not sufficient. |
| Another replacement game core or DLL mod | Cannot share the same core. Restore the original installation before switching. Windows DLLs do not run in the Mac game. |
| UI, balance, civilization or other gameplay mods | Compatibility is untested. They may replace the same screens or database entries. Leave them disabled; adding one to the MODS folder does not integrate it into this VP package. |
| Mods merely stored in MODS | These are not activated by regular Single Player. Do not select/activate additional mods for this beta. |
| Multiplayer, 43-civilization variants or mod collections | Not supported by beta 0.1. |

The installer does **not** detect every possible third-party modification. It preserves conflicting files rather than deleting them. Keep disabled DLC mods **outside the entire game's DLC directory**, since DLC packages can load without using the Mods menu.

Uninstall this beta before Steam file verification, a game update, or installing another core/modpack. If Steam changes the game while the beta is installed, the uninstaller can refuse to overwrite the changed files; keep the backup and the error message for investigation.

## Uninstall / return to normal Civ V

Quit Civ V and its launcher, reopen **Vox Populi Mac Installer.app**, and click **Uninstall / Restore**. Wait for **Your original game is restored**.

This restores the verified original core, original cache and original saves, and preserves the beta session separately. **Do not delete backups or use Steam verification as the normal uninstall method.** Keep the installer app until removal is complete. The dates and paths of preserved beta sessions appear under **Show technical details**.

## What has been tested?

- The native core passed startup, database, Lua, stream, lock and game-data checks, followed by normal context shutdown.
- With Community Patch data, a new city, a full turn, saving, relaunching, reloading and another turn worked with normal map/city screens.
- With full VP data, the first session passed those bridge checks, recorded save writes and shut down normally. A separate full-VP reload was not repeated for this beta; it is assumed from the preceding core test.
- Automated loader, rollback, ABI, upstream-contract and packaging checks pass.
- EUI is packaged from the pinned upstream skins and compatibility manifest. Its Mac gameplay/UI validation is pending; the previous gameplay results used the standard interface.

Long campaigns, later eras, all UI screens and all gameplay systems have **not** been validated. The beta uses the tested Debug build, so performance is not representative of a future optimized release. The database snapshot does not preserve CP's custom query indexes or SQL triggers; VP's final triggers primarily support additional mods. Two duplicate strategic-view art warnings remain under review. See the [release notes](CHANGELOG.md).

## If something goes wrong

Quit to desktop if possible, open the installer and click **Diagnostics**, then **Copy Details**.

Share that output, what you were doing, the turn number and whether it was a new game or a reload. A report showing startup checks passed does not establish that every gameplay feature worked. After a crash, uninstall before switching builds; uninstall also preserves the session's cache and saves for debugging.

Logs are under `~/Library/Application Support/Sid Meier's Civilization 5/Logs/`. If installation says the localization cache is missing or damaged, restore first, launch stock BNW once and quit, then retry. If it reports a changed core or backup, stop and retain those files; do not manually delete them to force installation.

### Optional command-line tools

The separate command-line beta ZIP and source builds support `python3 vp-mac.py install` for standard VP, `python3 vp-mac.py install --eui` for bundled EUI, and `status`, `report` and `uninstall`. Add `--app "/path/to/Civilization V.app"` for another Steam library, or `--dry-run` to check installation/removal. Restore before switching interfaces. These direct commands require Python 3.11+. The GUI uses the same backend with its bundled runtime.

## Development and credits

The Git repository contains the Mac layer and a pinned `Community-Patch-DLL` submodule. Generated game packages, binaries, personal logs and saves are excluded. See [building and updating](docs/DEVELOPMENT.md) and the [technical Mac layer notes](macos/README.md).

Vox Populi and Community Patch are the work of their upstream contributors. Civilization V and its game assets belong to their respective owners; a separately installed game is required. Upstream notices are retained in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [LICENSES](LICENSES/CommunityPatch-License.rtf). This is an unofficial community beta, not an Aspyr, Firaxis, 2K or upstream VP release.
