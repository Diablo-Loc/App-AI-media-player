# App-AI-media-player (BoTube)

A media player with AI-powered subtitle, translation and processing features.
This repository contains both the application code and tooling for building
packaged executables.

---

## Updating from older versions

### Manual hot-patch (v1.0.2)

This step is required once for users of the original 4 GB/66 MB installer.

1. Download `update.zip` from the **v1.0.2** release assets on GitHub.
2. Extract the archive; it contains `BoTube_patch.exe` and `version.json`.
3. **Do not copy** `BoTube_patch.exe` over the old `BoTube.exe`.
   Instead, **run `BoTube_patch.exe`**; it will overwrite the old executable and
   also update the local `version.json` file.
4. After the patcher finishes, the real application will start. Future updates
   will be handled automatically by the built-in updater.

*The patcher binary is deliberately small (__~9 MB__) and contains only the
update logic—it does not include the full app. Copying it over the original
exe will render the program unlaunchable!*

### Automatic updates (1.0.2+)

From version 1.0.2 onwards the app can check GitHub for a `version.json` and
download a tiny `update.zip` when a newer release is available.  The updater
decides whether to fetch the patcher or the full binary based on the metadata.

Configuration is stored in `config.json` (see `config.example.json`).  You may
specify:

- `version_url`: link to the remote `version.json` metadata (fallback is built in)
- `update_url`: link to the archive which should be downloaded when an update is
  found (this typically points to the same GitHub release asset).

The app will display progress, verify the ZIP integrity, and then launch the
appropriate helper script (`update_helper.bat` or `.sh`) to apply the update.

---

## Building

- `python build_app.py` produces the full `BoTube.exe` in `dist/BoTube`.
- `python patch_build.py` creates a tiny `BoTube_patch.exe` and an accompanying
  `update.zip` containing the patcher plus current `version.json`.

Refer to the source files for more details.
