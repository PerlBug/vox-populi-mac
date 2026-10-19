# Building and updating the Mac beta

The player README describes the prebuilt beta. A source checkout contains the Mac layer and an unmodified upstream submodule; generated binaries, packages and local test evidence are ignored by Git.

## Get the source

Clone this repository with `git clone --recurse-submodules <repository-url>`. For an existing clone, run:

```sh
git submodule update --init --recursive
```

The pinned upstream commit is recorded by Git. Do not edit or copy upstream gameplay code into the Mac layer.

Each playable beta ZIP also includes two source snapshots for inspection and native-core compilation. Extract **both** into the same working directory:

```sh
tar -xzf /path/to/beta/source/mac-layer.tar.gz
tar -xzf /path/to/beta/source/community-patch.tar.gz
cd Vox-Populi-Mac-source
```

The data packager and release builder use Git revision metadata. For a complete package rebuild, use the Git checkout above; to work from these snapshots, replace the extracted upstream directory with a Git clone checked out at the `upstream_commit` in the beta's `release.json`.

## Build

Requirements: the supported Steam Mac game, Python 3.11+, CMake 3.20+, and Apple's C++ Command Line Tools. Quit and restore any installed beta first. Launch stock BNW once to seed the cache. The stock game executable supplies engine imports at link time; it is never included in a release archive.

From the source root:

```sh
python3 macos/tools/sdk_contract.py check
cmake -S prototype -B prototype/build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build prototype/build -j 4
ctest --test-dir prototype/build --output-on-failure
cmake -S prototype -B prototype/build-core -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=OFF
cmake --build prototype/build-core --target vp_mac_core -j 4
python3 macos/tools/package_cp.py \
  --app "$HOME/Library/Application Support/Steam/steamapps/common/Sid Meier's Civilization V/Civilization V.app" \
  --cache "$HOME/Library/Application Support/Sid Meier's Civilization 5/cache" \
  --runtime-assets --vox-populi \
  --output prototype/build-core/VP_MAC_VP-gameplay-probe
```

For another Steam library, configure `-DVP_MAC_HOST_EXECUTABLE="/path/to/Civilization V.app/Contents/MacOS/Civilization V"` for the native build and use the matching `--app` when packaging/installing. Existing package output directories are refused; move an old build aside or choose a fresh path.

`python3 vp-mac.py install` uses `payload/` in a release ZIP. In a source checkout it uses the default native core and full VP package paths shown above. The original `prototype/manage.py` commands remain available for development.

Beta 0.1 intentionally ships the previously tested Debug core. An optimized build is a separate future test; rebuilding does not imply runtime validation.

## Updating upstream

Use a development branch. Update the submodule to the intended upstream revision, run the checks above, rebuild the native core, rebuild its matching data package and test a new game. A changed ABI declaration or overlay match count is a review point; do not blindly update the profile to make a failing check pass. Preserve old beta artifacts for their saves.

The SQL/XML actions and runtime assets come from the ordered CP/VP manifests. Mod dependencies, addins, map scripts and hashes are discovered from upstream. The small native ABI profile follows the Aspyr executable independently of VP balance releases. More detail is in [the Mac layer notes](../macos/README.md).

## Make a beta archive

Update `VERSION` and `CHANGELOG.md`, run tests, commit the Mac sources and pinned upstream revision, then run:

```sh
python3 tools/make_beta.py
```

The builder requires clean source repositories, checks the native signature/ABI and complete data inventory, verifies the pinned upstream revision, and creates:

- `dist/Vox-Populi-Mac-<version>/`: extracted player distribution.
- `dist/Vox-Populi-Mac-<version>.zip`: playable beta, notices and both exact source snapshots.
- `dist/Vox-Populi-Mac-<version>.zip.sha256`: archive checksum.

An internal `SHA256SUMS` covers the staged files. No stock core, stock executable, cache, save or personal log is copied. `dist/` is ignored by Git. A fresh output location can be selected with `--output`; an existing release is never overwritten.

Before publishing, exercise the extracted player commands from the archive: version, status, install dry run, then a real install/uninstall round trip. Tag the committed source after verification. Creating this local Git repository and archive does not publish to GitHub.
