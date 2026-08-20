#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The work behind ``pc install``: make a package ready to build, offline.

``pc install`` is to a PartCAD package what ``npm install`` is to a Node.js one.
It downloads every package the current one imports, and then asks every sketch,
part and assembly for its cache key.

Asking for the cache key is what does the rest of the work. The key hashes the
content of the files an object is built from, so it is only computable once
those files are on disk: requesting it downloads whatever ``fileFrom`` points
at. Getting there also resolves each alias, enrich, compound and assembly link,
which loads the packages the objects *really* depend on - not just the ones
``partcad.yaml`` names, and not just the ones that happen to be reachable
through the import tree.

Nothing is built here. Preparing an object is deliberately cheaper than
instantiating it: no CAD script runs, no wrapper is invoked.
"""

import asyncio

from ... import logging as pc_logging

# How many objects are prepared at once when the user configuration does not say.
_DEFAULT_CONCURRENCY = 8

# The object kinds an install covers, paired with the accessor that resolves one
# by name. Interfaces and providers are deliberately absent: neither carries a
# file of its own to download.
_KINDS = {
    "sketch": lambda project, name: project.get_sketch(name),
    "part": lambda project, name: project.get_part(name),
    "assembly": lambda project, name: project.get_assembly(name),
}


async def _install_object(project, kind: str, name: str, stats: dict) -> None:
    try:
        obj = _KINDS[kind](project, name)
        if obj is None:
            raise Exception("%s is not found" % kind)
        await obj.get_cache_key_async()
        stats[kind] += 1
    except Exception as e:  # pylint: disable=broad-except
        # One object that cannot be prepared must not cost the user the rest of
        # the install; the count comes back so the caller can still fail.
        pc_logging.error("Failed to install %s %s:%s: %s" % (kind, project.name, name, e))
        stats["failed"] += 1


async def install_async(ctx, packages: list[str]) -> dict:
    """Prepare every sketch, part and assembly of every named package.

    Returns the per-kind counts of what was prepared, plus ``failed`` (objects
    that could not be) and ``failed_packages`` (packages whose objects could not
    even be enumerated). Every failure is reported through the log as it happens;
    the counts are there so the caller can still fail the command afterwards.
    """
    stats = {"sketch": 0, "part": 0, "assembly": 0, "failed": 0, "failed_packages": 0}
    # A package can declare thousands of objects. Preparing them concurrently is
    # the point (most of the time goes into downloads), but unbounded fan-out
    # would open a socket per object; keep it to the same width as the rest of
    # PartCAD's parallelism.
    semaphore = asyncio.Semaphore(ctx.user_config.threads_max or _DEFAULT_CONCURRENCY)

    async def prepare_one(project, kind, name):
        async with semaphore:
            await _install_object(project, kind, name, stats)

    for package_name in packages:
        project = ctx.get_project(package_name)
        if project is None or project.broken:
            pc_logging.error("Failed to install the package %s: it is unavailable or broken" % package_name)
            stats["failed_packages"] += 1
            continue

        await project.ensure_enumerated_async()
        await asyncio.gather(
            *[prepare_one(project, kind, name) for kind in _KINDS for name in project.object_names(kind)]
        )

    return stats


def install(ctx, packages: list[str]) -> dict:
    return asyncio.run(install_async(ctx, packages))
