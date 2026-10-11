#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The joint model's one promise, held over every example: the steps *are* the placement.

A connected child's location is composed out of its target's placement, the
two ports, the half turn between them and every freedom-of-movement parameter
the connection names. 'partcad.joint' keeps that product as its factors, and the
factory takes the child's location from it, so the two cannot differ - unless
something composes on top of one and not the other, which is what this walks
the examples looking for. Bit for bit: '_q' and '_t' are the whole of a
Location, and a joint that is the placement "to within rounding" is a second
placement.

Only what an ASSY file declares is instantiated, because that is the only kind
of assembly that connects anything - and instantiating one reads its file and
its interfaces without building any geometry, so this needs no sandbox.
"""

import asyncio
import os

import partcad as pc

EXAMPLES = "examples"


def _example_packages():
    """Every package under examples/ that is a directory with a 'partcad.yaml'."""
    for directory, subdirectories, files in os.walk(EXAMPLES):
        subdirectories[:] = sorted(name for name in subdirectories if not name.startswith("."))
        if "partcad.yaml" in files and os.path.abspath(directory) != os.path.abspath(EXAMPLES):
            yield "//" + os.path.relpath(directory, EXAMPLES).replace(os.sep, "/")


def _assy_objects(project):
    """'(kind, name)' of every assembly and scene the package declares as an ASSY file."""
    for kind, configs in (("assembly", project.object_configs("assembly")), ("scene", project.object_configs("scene"))):
        for name, config in sorted(configs.items()):
            if isinstance(config, dict) and config.get("type") == "assy":
                yield kind, name


def _children(assembly):
    for child in assembly.children:
        yield child
        item = child.item
        if isinstance(item, pc.Assembly) and item.config.get("child", False):
            yield from _children(item)


def test_every_connected_child_of_every_example_is_the_product_of_its_steps():
    ctx = pc.init(EXAMPLES)
    connected = 0
    assemblies = 0
    for package in _example_packages():
        project = ctx.get_project(package)
        assert project is not None, package
        for kind, name in _assy_objects(project):
            path = "%s:%s" % (package, name)
            obj = ctx.get_assembly(path) if kind == "assembly" else ctx.get_scene(path)
            asyncio.run(obj.do_instantiate())
            assemblies += 1
            for child in _children(obj):
                if child.connection is None:
                    # Placed by 'location:', or a connection that found no target.
                    assert child.composition is None, "%s: %s" % (path, child.name)
                    continue
                assert child.composition is not None, "%s: %s" % (path, child.name)
                product = child.composition.location()
                location = child.location if isinstance(child.location, pc.geom.Location) else None
                assert location is not None, "%s: %s" % (path, child.name)
                assert (product._q, product._t) == (location._q, location._t), "%s: %s" % (path, child.name)
                if child.joint is not None:
                    assert child.joint.composition is child.composition
                connected += 1
    # Not vacuous: the examples connect a few dozen children between them.
    assert assemblies > 10
    assert connected > 20
