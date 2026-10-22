# Third-party notices

This is an unofficial Mac compatibility layer for the Community Patch / Vox Populi project.

- Upstream: https://github.com/LoneGazebo/Community-Patch-DLL
- Beta 0.1 upstream revision: `7307aefdf985a4f401a7996a896283557b896e2b` (5.4.8).
- The upstream license notice is preserved unchanged as `LICENSES/CommunityPatch-License.rtf`.
- The full upstream source snapshot in a built beta archive retains its own notices, licenses and credits, including those for SDK and third-party components. This notice does not replace them or relicense game assets.
- Civilization V is a separately installed commercial game. No stock Aspyr executable or stock core library, personal cache, save or log is included in the beta archive.

The Mac-specific changes are separate from the unmodified upstream checkout. Source and build instructions accompany beta archives. See `docs/DEVELOPMENT.md` for reproducing the build and the source snapshot layout.

The optional Enhanced User Interface is bc1's EUI as bundled and adapted by Vox Populi, with the pinned upstream `UI_bc1`, `VPUI` and `(3a) VP - EUI Compatibility Files` sources. Existing file credits and notices are retained in the payload and upstream source snapshot. It is not a separately downloaded generic EUI release.

## Graphical installer runtimes

The GUI app includes CPython 3.13.16 for Apple Silicon and Intel from Astral's [Python Build Standalone](https://github.com/astral-sh/python-build-standalone) release `20261013`. Exact download URLs and SHA-256 hashes are pinned in `gui/python-runtimes.json`. These are portable, self-contained distributions; see the [distribution documentation](https://docs.astral.sh/python-build-standalone/distributions/).

Python's license is retained under each runtime's `lib/python3.13/LICENSE.txt`, along with bundled third-party notices and pip dependency licenses. The installer does not install this runtime system-wide. The Python/CPython source is available from [python/cpython](https://github.com/python/cpython/tree/v3.13.16); distribution build sources are available from the Python Build Standalone project and its pinned release.
