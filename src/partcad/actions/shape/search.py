from typing import Optional

from partcad.actions.common import _search
from partcad.assembly import Assembly
from partcad.context import Context
from partcad.interface import Interface
from partcad.part import Part
from partcad.scene import Scene
from partcad.sketch import Sketch

# Each of these returns the matching objects of the package, and of the packages
# below it when 'recursive'. From a package whose repository plugin searches the
# kind itself, what comes back is a 'SearchHit' per object it found - at most
# 'limit' from each such package - rather than the object (see '_search').


def search_parts(
    ctx: Context,
    package: str,
    recursive: bool,
    keyword: str,
    interface: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[Part]:
    return _search(ctx, package, recursive, keyword, lambda project: project.parts.values(), "part", interface, limit)


def search_sketches(
    ctx: Context,
    package: str,
    recursive: bool,
    keyword: str,
    interface: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[Sketch]:
    return _search(
        ctx, package, recursive, keyword, lambda project: project.sketches.values(), "sketch", interface, limit
    )


def search_assemblies(
    ctx: Context,
    package: str,
    recursive: bool,
    keyword: str,
    interface: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[Assembly]:
    return _search(
        ctx, package, recursive, keyword, lambda project: project.assemblies.values(), "assembly", interface, limit
    )


def search_scenes(
    ctx: Context,
    package: str,
    recursive: bool,
    keyword: str,
    interface: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[Scene]:
    return _search(ctx, package, recursive, keyword, lambda project: project.scenes.values(), "scene", interface, limit)


def search_interfaces(ctx: Context, package: str, recursive: bool, keyword: str) -> list[Interface]:
    return _search(ctx, package, recursive, keyword, lambda project: project.interfaces.values(), "interface")
