#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What '--fast-only' leaves out: the objects that declare they are slow.

An assembly (or a scene) that declares a ``timeout:`` is one its author knows
takes longer to build than PartCAD waits by default (see
``partcad_utils.timeouts``). A command run with ``--fast-only`` passes over
every such object -- which is what a recursive render or test of a large tree
in CI wants: everything that is quick, and nothing that is known not to be.

Read from the declaration and nothing else, so leaving an object out builds
nothing and resolves nothing. An assembly that places a slow one is built by
building that one, and is still not left out unless it declares a timeout of
its own: what is skipped is what the package says is slow, not what PartCAD
would have to build to find out.
"""

import typing

from partcad_utils import timeouts
from partcad_utils.utils import parse_parameterized_name

from . import logging as pc_logging


def _say(kind: str, package: str, name: str, seconds: float) -> None:
    pc_logging.info(
        "Skipping the %s '%s:%s': it declares 'timeout: %g' and '--fast-only' was given"
        % (kind, package, name, seconds)
    )


def leaves_out(shape) -> bool:
    """Whether '--fast-only' passes over this object, saying so when it does."""
    seconds = getattr(shape, "timeout", None)
    if seconds is None:
        return False
    _say(shape.kind, shape.project_name, shape.name, seconds)
    return True


def leaves_out_declared(project, kind: str, name: str, quiet: bool = False) -> bool:
    """'leaves_out' for an object that has not been created, from its declaration.

    For a listing, which reads declarations so as not to build a package to
    print it, and for a request naming one object, which is asked about before
    anything is made of it. ``quiet`` is for the former: a listing that left a
    row out because it was asked to is not news.
    """
    if kind not in timeouts.KINDS_DECLARING:
        return False
    # Parameters are the caller's, not part of the name it is declared under.
    base, _ = parse_parameterized_name(name)
    seconds = timeouts.declared(project.object_config(kind, base))
    if seconds is None:
        return False
    if not quiet:
        _say(kind, project.name, name, seconds)
    return True


def without_slow(shapes: typing.Iterable) -> list:
    """``shapes`` without the ones '--fast-only' passes over."""
    return [shape for shape in shapes if not leaves_out(shape)]
