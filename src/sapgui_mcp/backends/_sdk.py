"""Make pyrfc's native dependency loadable without relying on DYLD_* env vars.

The SAP NW RFC SDK is a separate native download (not pip-installable). pyrfc's
compiled extension looks for `libsapnwrfc.dylib` (+ ICU/ucum libs) at
`@loader_path` — i.e. next to itself. macOS strips DYLD_LIBRARY_PATH across many
process spawns (e.g. `creds exec`), so the robust fix is to colocate the SDK
dylibs beside the installed pyrfc extension. This runs once and is idempotent.

Set SAPNWRFC_HOME to point at your SDK, or drop it in one of the known locations.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# dylibs pyrfc's extension resolves via @loader_path (macOS).
_REQUIRED = (
    "libsapnwrfc.dylib",
    "libsapucum.dylib",
    "libicudata57.dylib",
    "libicui18n57.dylib",
    "libicuuc57.dylib",
)


def _candidate_sdk_libdirs() -> list[Path]:
    """Bounded, explicit locations only — never crawl the filesystem looking for an SDK.

    Point SAPGUI_MCP_SDK_LIB (or SAPNWRFC_HOME) at your SDK if it lives elsewhere.
    """
    dirs: list[Path] = []
    if lib := os.environ.get("SAPGUI_MCP_SDK_LIB"):
        dirs.append(Path(lib))
    if home := os.environ.get("SAPNWRFC_HOME"):
        dirs.append(Path(home) / "lib")
    home_dir = Path.home()
    dirs += [
        home_dir / ".cidb-sap-monitor" / "nwrfcsdk" / "lib",
        home_dir / "nwrfcsdk" / "lib",
        home_dir / "sap" / "nwrfcsdk" / "lib",
        Path("/usr/local/sap/nwrfcsdk/lib"),
        Path("/opt/sap/nwrfcsdk/lib"),
        Path("/usr/local/lib"),  # a loose libsapnwrfc.dylib may live here
    ]
    return dirs


def _find_sdk_libdir() -> Path | None:
    for d in _candidate_sdk_libdirs():
        if (d / "libsapnwrfc.dylib").is_file():
            return d
    return None


def ensure_sdk_dylibs() -> None:
    """Colocate SDK dylibs next to the installed pyrfc extension if missing.

    No-op on non-macOS, or if pyrfc isn't installed, or if libs are already present.
    Best-effort: never raises for a copy failure — the import will surface the real
    error with a clear message if the SDK truly can't be found.
    """
    # find_spec locates the package WITHOUT importing it — important, because a
    # failing native load is precisely the condition we're here to repair.
    pkg_dir = _pyrfc_dir()
    if pkg_dir is None or all((pkg_dir / lib).exists() for lib in _REQUIRED):
        return

    src = _find_sdk_libdir()
    if src is None:
        return  # let the import raise its own descriptive error

    for lib in _REQUIRED:
        target, source = pkg_dir / lib, src / lib
        if not target.exists() and source.is_file():
            try:
                shutil.copy2(source, target)
            except OSError:
                pass  # e.g. read-only site-packages; import will report the shortfall


def _pyrfc_dir() -> Path | None:
    import importlib.util

    spec = importlib.util.find_spec("pyrfc")
    if spec is None or not spec.origin:
        return None
    return Path(spec.origin).parent
