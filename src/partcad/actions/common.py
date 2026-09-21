from typing import Callable, Optional, Union

from partcad import logging as pc_logging
from partcad import shape_ports
from partcad.context import Context
from partcad.project import Project
from partcad.shape import Shape


def _search(
    ctx: Context,
    package: str,
    recursive: bool,
    keyword: str,
    get_items: Callable[[Project], list[Union[Project, Shape]]],
    kind: Optional[str] = None,
    interface: Optional[str] = None,
) -> list[Union[Project, Shape]]:
    """The objects of a package (and, recursively, of those below it) that match.

    'keyword' is matched against the declaration as text. 'interface' is matched
    against what the object connects by: it selects the objects that implement
    that interface or anything derived from it, read from the declarations
    through 'shape_ports.interface_index' rather than by instantiating anything.
    Both may be given, and then both have to hold.
    """
    project = ctx.get_project(package)
    if project is None or project.broken:
        if project is None:
            pc_logging.error("Package %s is not found" % package)
        else:
            pc_logging.error("Failed to load the package: %s" % package)
        return []

    result = []
    packages = [package]
    if recursive:
        child_packages = ctx.get_all_packages(parent_name=package)
        if ctx.stats_git_ops:
            pc_logging.info(f"Git operations: {ctx.stats_git_ops}")
        # get_packages() selects children with name.startswith(parent_name), so
        # the starting package is in its own child list. Without this filter it
        # is searched twice and every object it holds is reported (and counted
        # in "Matches:") twice.
        packages += [p["name"] for p in child_packages if p["name"] != project.name]

    for package_name in packages:
        package = ctx.get_project(package_name)

        if package is None or package.broken:
            pc_logging.warning("Skipping unavailable or broken package: %s" % package_name)
            continue

        items = shape_ports.implementers(ctx, package, kind, interface) if interface else get_items(package)
        for item in items:
            if keyword and not item.matches(keyword):
                continue
            result.append(item)

    return result
