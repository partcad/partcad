#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Building an assembly in two phases, as both ends have to agree on it.

An assembly is built out of other assemblies, and building one of those can
take minutes. Done inside the request that asked for the parent, all of it is
one request -- for as long as the deepest tree takes, with nothing the client
can do but wait and nothing the daemon can say about how far along it is.

So a daemon asked for an assembly looks first, and builds second. The first
phase reads the assembly's declaration and asks which of the assemblies it
places are not cached yet; if none are, the request proceeds exactly as it
always did. If some are, the daemon does no work at all and answers
:data:`RETRY_LATER` instead, naming them. The client then asks for each of them
in turn -- through :data:`INSTANTIATE_METHOD`, with :data:`CACHE_ONLY`, so the
result stays in the daemon's cache and never crosses the wire -- and asks for
the parent again, which now finds them cached and builds only itself.

Nesting needs nothing extra: a staging request is an assembly request like any
other, so a sub-assembly with sub-assemblies of its own answers
:data:`RETRY_LATER` too, and the client recurses. The total takes longer, since
each round trip re-reads what the previous one settled; what it buys is that no
single request is longer than one assembly's own work.

This module is what the two ends agree on, and it lives here for the reason the
rendezvous in `workspace` does: a copy on each side is a copy that can disagree,
and a disagreement here is a client that reports a daemon's "ask me again" to
the user as a failure.
"""

from typing import Any, Optional

# The JSON-RPC error code for "not yet -- build these first". An application
# code in the -32000..-32099 range the specification reserves for them, beside
# the ones in `partcad_service_json_rpc.core.operations`.
#
# An error rather than a result, because JSON-RPC has nowhere else to put it:
# the operations that answer this way return nothing at all when they succeed,
# so a status in the result would be a status nobody looks at. It is not a
# failure -- a client that understands it never shows it to the user, and one
# that does not gets a message saying what to do.
RETRY_LATER = -32004

# The method that builds one assembly and leaves the result where it was built.
INSTANTIATE_METHOD = "assembly.instantiate"

# Its parameter that keeps the result on the daemon: the assembly is built into
# the daemon's cache, and the response carries a status and nothing else. The
# client staging a sub-assembly has no use for the geometry -- what it is after
# is the cache entry the parent's next attempt will find.
CACHE_ONLY = "cacheOnly"

# Where the error's 'data' carries what has to be built first.
SUBASSEMBLIES = "subassemblies"

# Which of the two an entry is. A scene is an assembly -- the same files, the
# same tree, and an assembly is a legal child of one -- but a package registers
# the two apart, so an entry that did not say which it is would be looked for
# among the assemblies and not found. Absent means "assembly", which is what a
# link in an ASSY file always names.
KIND = "kind"
KIND_ASSEMBLY = "assembly"


def error_data(items: list) -> dict:
    """The ``data`` member of a :data:`RETRY_LATER` error."""
    return {SUBASSEMBLIES: list(items)}


def error_message(items: list) -> str:
    """What a client that does not understand the code shows the user.

    The message says what to do about it, because for such a client this is
    where the command ends. It is never shown by one that does understand it.
    """
    return "Build these sub-assemblies first, then ask again: %s" % ", ".join(identity(item) for item in items)


def pending_subassemblies(code: Optional[int], data: Any) -> list:
    """What the daemon wants built before it will do this work, or nothing.

    Answers for any error, not only this one, so that a caller can ask without
    first deciding what it is looking at. Anything malformed reads as nothing:
    an error nobody can act on is an error to report, and reporting it is what
    an empty list makes the caller do.
    """
    if code != RETRY_LATER or not isinstance(data, dict):
        return []
    items = data.get(SUBASSEMBLIES)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and item.get("name")]


def identity(item: dict) -> str:
    """How one entry is named -- for a message, and for not staging it twice.

    The kind is part of it: a package may declare an assembly and a scene of
    one name, and they are two objects.
    """
    name = "%s:%s" % (item.get("package") or "", item.get("name") or "")
    kind = item.get(KIND) or KIND_ASSEMBLY
    return name if kind == KIND_ASSEMBLY else "%s (%s)" % (name, kind)


def request_params(item: dict, context: Optional[str] = None) -> dict:
    """The params of the request that stages one entry.

    The context id travels with it, as with every context-aware request: a
    warm daemon serves several, and an assembly built into the wrong one is
    built out of another workspace's packages.
    """
    params = {
        "package": item.get("package"),
        "name": item.get("name"),
        KIND: item.get(KIND) or KIND_ASSEMBLY,
        CACHE_ONLY: True,
    }
    if context is not None:
        params["context"] = context
    return params
