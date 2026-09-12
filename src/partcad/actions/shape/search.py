from partcad.actions.common import _search
from partcad.assembly import Assembly
from partcad.context import Context
from partcad.interface import Interface
from partcad.part import Part
from partcad.scene import Scene
from partcad.sketch import Sketch


def search_parts(ctx: Context, package: str, recursive: bool, keyword: str) -> list[Part]:
    return _search(
        ctx,
        package,
        recursive,
        keyword,
        lambda project: project.parts.values()
    )

def search_sketches(ctx: Context, package: str, recursive: bool, keyword: str) -> list[Sketch]:
    return _search(
        ctx,
        package,
        recursive,
        keyword,
        lambda project: project.sketches.values()
    )

def search_assemblies(ctx: Context, package: str, recursive: bool, keyword: str) -> list[Assembly]:
    return _search(
        ctx,
        package,
        recursive,
        keyword,
        lambda project: project.assemblies.values()
    )

def search_scenes(ctx: Context, package: str, recursive: bool, keyword: str) -> list[Scene]:
    return _search(
        ctx,
        package,
        recursive,
        keyword,
        lambda project: project.scenes.values()
    )

def search_interfaces(ctx: Context, package: str, recursive: bool, keyword: str) -> list[Interface]:
    return _search(
        ctx,
        package,
        recursive,
        keyword,
        lambda project: project.interfaces.values()
    )
