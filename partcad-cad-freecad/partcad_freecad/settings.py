#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where the addon keeps its few preferences and its downloaded bundle.

Inside FreeCAD these live in the usual parameter tree
(``BaseApp/Preferences/Mod/PartCAD``) so they survive restarts and show up in the
parameter editor. Outside FreeCAD -- in tests, or when the module is driven from
a plain interpreter -- they fall back to a JSON file next to PartCAD's own
configuration, which keeps every entry point in this package importable without
FreeCAD.
"""

import json
import os
from typing import Optional

PREFERENCES = "User parameter:BaseApp/Preferences/Mod/PartCAD"

KEY_PACKAGE_DIR = "PackageDir"
KEY_RECENT = "RecentPackages"

_RECENT_LIMIT = 8


def _freecad():
    try:
        import FreeCAD  # pylint: disable=import-outside-toplevel

        return FreeCAD
    except ImportError:
        return None


def _fallback_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".partcad", "freecad-addon.json")


def _read_fallback() -> dict:
    try:
        with open(_fallback_path(), "r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return {}


def _write_fallback(values: dict) -> None:
    path = _fallback_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(values, stream, indent=2)


def get(key: str, default: str = "") -> str:
    freecad = _freecad()
    if freecad is not None:
        return freecad.ParamGet(PREFERENCES).GetString(key, default)
    return _read_fallback().get(key, default)


def set(key: str, value: str) -> None:  # pylint: disable=redefined-builtin
    freecad = _freecad()
    if freecad is not None:
        freecad.ParamGet(PREFERENCES).SetString(key, value)
        return
    values = _read_fallback()
    values[key] = value
    _write_fallback(values)


def cache_dir() -> str:
    """Where a downloaded bundle is unpacked.

    FreeCAD's per-user data directory when there is one, so the addon's ~875MB
    of payload lands with the rest of the user's FreeCAD data rather than in a
    temporary directory that a reboot clears.
    """
    override = os.environ.get("PC_CAD_BUNDLE_DIR")
    if override:
        return override
    freecad = _freecad()
    if freecad is not None:
        return os.path.join(freecad.getUserAppDataDir(), "PartCAD")
    return os.path.join(os.path.expanduser("~"), ".partcad", "freecad")


def package_dir() -> Optional[str]:
    """The PartCAD package directory the explorer is showing, if any."""
    value = os.environ.get("PC_CAD_PACKAGE_DIR") or get(KEY_PACKAGE_DIR)
    return value or None


def set_package_dir(path: str) -> None:
    set(KEY_PACKAGE_DIR, path)
    recent = [path] + [entry for entry in recent_packages() if entry != path]
    set(KEY_RECENT, json.dumps(recent[:_RECENT_LIMIT]))


def recent_packages() -> list:
    """Recently opened package directories, most recent first."""
    try:
        entries = json.loads(get(KEY_RECENT) or "[]")
    except ValueError:
        return []
    return [entry for entry in entries if isinstance(entry, str)]
