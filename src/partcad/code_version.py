#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The version a wrapper or a plugin reports for what it produces.

Every piece of code PartCAD runs to produce something it caches states, as a
module-level ``CACHE_VERSION = <int>``, when what it produces stopped meaning
what it used to mean: a repository plugin for the objects it serves, a wrapper
for the shapes, analyses and verdicts it computes, an implementation of a file
type, an analysis, a route or a simulation for what it writes. The number is
part of the cache key of everything that code produces, so raising it is how
its author has every result it produced before computed again. For a shape or a
test's verdict nothing else is: an edit that does not change the result, a
comment or a refactoring, costs nobody a rebuild. An analysis, a route or a
simulation is keyed on its package's sources as well ('source_key'), so there
an edit already does, and the version says the same thing a second time.

The number belongs to the code and to nobody else. A package that uses a
plugin, or a shape that a wrapper builds, has no way of knowing that the code
now does something else, and should not have to be told; so the number is read
out of the script itself, never out of the configuration of whoever uses it.

It is *read* rather than asked for: the script is parsed, never executed, and
the key has to be worked out before anything runs. A Python script states it as
an assignment at the top level of the module; a JavaScript one as a top-level
``const``, ``let`` or ``var`` (``export``-ed or not). A script that states none
reports 0, and a 0 is left out of every key - which is what a script that
predates the convention keyed as, so adopting it costs nothing until the number
is first raised.
"""

import ast
import os
import re
from typing import Iterable, Optional

from . import logging as pc_logging
from .cache_hash import FileMemo

# The module-level name a script states its version with.
NAME = "CACHE_VERSION"

_JS_DECLARATION = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+" + NAME + r"\s*=\s*([^;\s]+)\s*;?\s*(?://.*)?$",
    re.MULTILINE,
)


class _Unreadable(Exception):
    """A script whose text could not be had, which states no version - and is not remembered."""


def _parse_python(path: str, text: str) -> int:
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError) as e:
        pc_logging.debug("Cannot read the %s of %s: %s" % (NAME, path, e))
        return 0
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = node.targets
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == NAME for t in targets):
            continue
        value = node.value
        # 'bool' is an 'int', and 'CACHE_VERSION = True' is a typo, not a version.
        if isinstance(value, ast.Constant) and isinstance(value.value, int) and not isinstance(value.value, bool):
            return value.value
        pc_logging.error("%s: %s must be an integer literal" % (path, NAME))
        return 0
    return 0


def _parse_javascript(path: str, text: str) -> int:
    match = _JS_DECLARATION.search(text)
    if match is None:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        pc_logging.error("%s: %s must be an integer literal" % (path, NAME))
        return 0


def _version_of(f) -> int:
    path = f.name
    try:
        # As text mode would read it, line endings and all.
        text = f.read().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except (OSError, UnicodeDecodeError) as e:
        raise _Unreadable(e)
    if os.path.splitext(path)[1] in (".js", ".mjs", ".cjs"):
        return _parse_javascript(path, text)
    return _parse_python(path, text)


# A daemon holds a context for as long as it runs and the scripts under it are
# edited in place, so a version is remembered only for as long as the file looks
# the same from outside - by the rule a dependency's digest is (see FileMemo).
_declared = FileMemo(_version_of)


def declared(path: Optional[str]) -> int:
    """The version the script at 'path' states, or 0 if it states none.

    0 too for a script that cannot be read - which is not remembered, so the
    first successful read is not shadowed by an earlier failed one.
    """
    if not path:
        return 0
    try:
        return _declared.get(path)
    except (OSError, _Unreadable) as e:
        pc_logging.debug("Cannot read the %s of %s: %s" % (NAME, path, e))
        return 0


def wrapper(name: str) -> int:
    """The version of one of PartCAD's own wrappers, by the name 'wrapper.get()' takes."""
    from . import wrapper as pc_wrapper

    return declared(pc_wrapper.get(name))


def key(versions: Iterable[tuple]) -> Optional[str]:
    """'versions' - '(what, version)' pairs - as one string for a cache key, or None.

    The pairs that state no version are left out, and None means none was
    left: a key that something is added to only when there is something to add
    is the key it was before any of this existed.
    """
    stated = sorted("%s@%d" % (what, version) for what, version in versions if version)
    return ";".join(stated) if stated else None


def wrappers_key(names: Iterable[str]) -> Optional[str]:
    """The key of PartCAD's own wrappers called 'names'. See 'key'."""
    return key((name, wrapper(name)) for name in names)


def scripts_key(paths: Iterable[Optional[str]]) -> Optional[str]:
    """The key of the scripts at 'paths', named by their file names. See 'key'."""
    return key((os.path.basename(path), declared(path)) for path in paths if path)
