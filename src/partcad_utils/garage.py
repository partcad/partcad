#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a user decided about building an object, kept on their own machine.

The "garage" is the user's workshop: what they have chosen to make themselves
and what they will buy. Today it holds one kind of decision, the Build vs Buy
choice of every line item of an object (see `partcad.build_plan`), one file per
object browsed:

    ~/.partcad/garage/default/bvb/<escaped object name>.json
    {"object": "//pkg:name", "choices": {"//pkg:part": "build", ...}}

It is written and read by **clients** only -- the IDE's host process and the
CLI -- and never by a daemon. A daemon can be remote, and these are the
decisions of whoever sits in front of the client: a daemon is handed them with
the request that needs them, like the user configuration is.

It lives here, beside the rest of what both clients share, for the reason the
rendezvous does: the editor extension reimplements the path and the escaping in
TypeScript ('ide/vscode/src/common/garage.ts'), and a copy that drifts is a
choice saved by one client that the other cannot find. The escaping is spelled
so that both languages have it built in: every byte of the UTF-8 name outside
'[A-Za-z0-9_.~-]' becomes '%XX' -- 'urllib.parse.quote(name, safe="")' here,
'encodeURIComponent' plus '!'()*' there. A name holds '/' and ':', which no
file name may, and an escaping that maps two names to one file (replacing both
with '_', say) would hand one object the other's choices.
"""

import json
import os
import urllib.parse

from .user_config import UserConfig

# The one workshop there is so far. Named, rather than left out of the path,
# so that a second one is a directory beside it and not a migration.
DEFAULT_GARAGE = "default"

BUILD = "build"
BUY = "buy"
CHOICES = (BUILD, BUY)


def garage_dir(garage: str = DEFAULT_GARAGE) -> str:
    return os.path.join(UserConfig.get_config_dir(), "garage", garage)


def bvb_dir(garage: str = DEFAULT_GARAGE) -> str:
    return os.path.join(garage_dir(garage), "bvb")


def escape(name: str) -> str:
    """A file name standing for an object name, and for no other."""
    return urllib.parse.quote(name, safe="")


def bvb_path(object_name: str, garage: str = DEFAULT_GARAGE) -> str:
    return os.path.join(bvb_dir(garage), escape(object_name) + ".json")


def _clean(choices) -> dict:
    """Only what reads as a choice: a name, and 'build' or 'buy'."""
    if not isinstance(choices, dict):
        return {}
    return {str(name): value for name, value in choices.items() if value in CHOICES}


def load_bvb(object_name: str, garage: str = DEFAULT_GARAGE) -> dict:
    """The Build vs Buy choices saved for an object, or {} when there are none.

    A file that cannot be read or parsed is the same as none: these are
    preferences, and the defaults they override are always a valid answer.
    """
    try:
        with open(bvb_path(object_name, garage), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return _clean(data.get("choices") if isinstance(data, dict) else None)


def load_all_bvb(garage: str = DEFAULT_GARAGE) -> dict:
    """Every object's saved choices, as {object name: choices}.

    For a client that does not know the fully qualified name of the object it
    is asking about -- the CLI is handed whatever the user typed, and only the
    daemon resolves that against a package -- so it sends them all and lets the
    daemon pick. They are a few hundred bytes each. The name is read from the
    file rather than unescaped from its name, because the file says it.
    """
    found = {}
    try:
        entries = os.listdir(bvb_dir(garage))
    except OSError:
        return found
    for entry in sorted(entries):
        if not entry.endswith(".json"):
            continue
        try:
            with open(os.path.join(bvb_dir(garage), entry), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("object"), str):
            found[data["object"]] = _clean(data.get("choices"))
    return found


def save_bvb(object_name: str, choices: dict, garage: str = DEFAULT_GARAGE) -> str:
    """Save an object's Build vs Buy choices, and say where they went."""
    path = bvb_path(object_name, garage)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump({"object": object_name, "choices": _clean(choices)}, f, indent=2, sort_keys=True)
        f.write("\n")
    # Replaced rather than rewritten, so that a reader never sees half a file.
    os.replace(temporary, path)
    return path
