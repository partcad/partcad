#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An assembly's ``timeout:``, as both ends of the daemon connection read it.

A client gives up on a daemon that says nothing for too long -- five minutes by
default (``partcad_client.client.DEFAULT_IDLE_TIMEOUT``). That bound is on
silence rather than on the operation, and one big assembly built or rendered in
a sandbox is exactly a stretch of silence: the sandbox says nothing between
starting and finishing. An assembly that is known to take longer says so in its
declaration::

    assemblies:
      skyscraper:
        type: assy
        timeout: 1800

and the daemon passes that on while it works on the assembly. It opens a
*window* when it starts -- a :data:`START` marker carrying the seconds -- and
closes it when it is done (:data:`END`); a client that sees one waits that long
instead of its default for as long as the window is open. The markers travel
the way the process and action markers already do, as structured ``log``
events, so a client that knows nothing about them (the editor extension, which
has no such bound) passes them over.

Several windows can be open at once -- a recursive render builds several
assemblies together -- and the longest one is what the client waits for. A
declared timeout only ever lengthens the wait: the bound is one bound for the
whole connection, and the work running beside a quick assembly still deserves
the default. A client told to wait forever (``PC_DAEMON_IDLE_TIMEOUT=0``) keeps
waiting forever.

Declaring one is also saying the assembly is slow, and that is the other thing
this key is read for: a command run with ``--fast-only`` -- a recursive render
or test of a whole tree, typically -- passes over every assembly (and scene)
that declares a timeout. It is read from the declaration and nothing else, so
leaving an object out costs nothing -- which is also why an assembly that
*places* a slow one is not left out unless it declares a timeout of its own.

This module is what the two ends agree on, and lives here for the reason
``staging`` does: a copy on each side is a copy that can disagree.
"""

import math
from typing import Any, Optional

# The key an assembly (or a scene) declares its timeout under, in seconds.
KEY = "timeout"

# The two markers, as the 'kind' of a forwarded 'log' event.
START = "timeout_start"
END = "timeout_end"
KINDS = (START, END)

# Where a marker carries the seconds.
SECONDS = "seconds"

# The kinds of object that can declare one. A scene is an assembly -- the same
# files, the same tree, built the same way -- so it can be just as slow.
KINDS_DECLARING = ("assembly", "scene")


def seconds(value: Any) -> Optional[float]:
    """``value`` as a timeout in seconds, or None if it is not one.

    A positive, finite number. Anything else -- absent, zero, negative, a
    string, a boolean (which Python would otherwise count as 1) -- is no
    timeout at all, rather than an error: the schema is what reports a
    malformed declaration (``pc lint``), and an object must not fail to build
    over how long somebody is prepared to wait for it.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def declared(config: Any) -> Optional[float]:
    """The timeout a declaration states, or None."""
    if not isinstance(config, dict):
        return None
    return seconds(config.get(KEY))


def event(kind: str, value: float, package: Optional[str], item: Optional[str]) -> dict:
    """The structured ``log`` event one marker travels as."""
    return {"kind": kind, SECONDS: value, "package": package, "item": item}


def subject(marker: dict) -> str:
    """What declared the timeout a marker carries, for a message."""
    package = marker.get("package") or ""
    item = marker.get("item")
    return "%s:%s" % (package, item) if item else package
