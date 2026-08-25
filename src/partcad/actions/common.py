from typing import Callable, Union

from partcad import logging as pc_logging
from partcad.context import Context
from partcad.project import Project
from partcad.shape import Shape


def _search(
    ctx: Context,
    package: str,
    recursive: bool,
    keyword: str,
    get_items: Callable[[Project], list[Union[Project, Shape]]],
) -> list[Union[Project, Shape]]:
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

        for item in get_items(package):
            if keyword and not item.matches(keyword):
                continue
            result.append(item)

    return result
