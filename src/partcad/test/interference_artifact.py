#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the interference check leaves behind for two parts that overlap.

"'tub/battery' and 'frame' share 12.400 mm^3" says which two and how much, and
not where, which is what somebody about to move one of them needs to see. So for
each pair it reports, the check also leaves an assembly to look at: the two
parts, placed exactly where the assembly places them, and a sub-assembly named
'interference' whose parts are the volumes they share -- one part per solid of
the boolean common. Turned in the Digital Thread with the two parts switched
off, what is left is the overlap itself.

Nothing declares these objects, so they are made the way PartCAD makes the parts
a STEP assembly is read into: registered in the package of the assembly being
checked, in memory only, under names worked out from what they are --

    <assembly>/interference/<a>+<b>                     the assembly to look at
    <assembly>/interference/<a>+<b>/interference        what the two share
    <assembly>/interference/<a>+<b>/interference/volume-<n>

-- so that checking the same assembly again names the same objects, and asking
for one by name, in any request to the same daemon, finds it. A name made up
afresh on each run would leave every run's objects behind it and share nothing
with the last one.

Each volume is a 'brep' part read from a file under PartCAD's own state
directory ('internalStateDir'/interference), named after a digest of its bytes:
the same overlap writes the same file, and the part's cache key -- which covers
its configuration and the file's content -- is the same from one run and one
process to the next, so its geometry is cached like any other part's. The two
parts placed in the assembly are the objects themselves, not copies, cached as
they always are. Only the assembly holding them is not cacheable, which no
assembly put together in memory is (see 'assembly_filter.derive').

What a verdict keeps with it, in the cache (see 'Test.artifact()'), is the
recipe: the two parts by name and placement, and the files of the volumes. A
verdict read back in a daemon that has not run the check registers the objects
again from it ('restore_async'), as long as the files are still there.
"""

import hashlib
import os
import tempfile
import typing

from .. import logging as pc_logging
from .. import shape_envelope
from ..assembly import Assembly, AssemblyChild
from ..geom import Location
from ..part_config import PartConfiguration

# The sub-assembly of the volumes the two parts share, and the folder under
# PartCAD's state directory their files are written to.
SUBASSEMBLY = "interference"


def name_of(assembly_name: str, a: str, b: str) -> str:
    """The name of the assembly left behind for the overlap of 'a' and 'b' in 'assembly_name'.

    'a' and 'b' are paths of link names, as the check reports them; '+' is not
    something a link name is written with, so two pairs never come out as one
    name.
    """
    return "%s/%s/%s+%s" % (assembly_name, SUBASSEMBLY, a, b)


def _directory(ctx) -> str:
    return os.path.join(ctx.user_config.internal_state_dir, SUBASSEMBLY)


def _write(directory: str, data: bytes) -> str:
    """Write one volume's BREP where its digest says, once, and return the path."""
    path = os.path.join(directory, "%s.brep" % hashlib.sha256(data).hexdigest()[:32])
    if os.path.isfile(path):
        return path
    os.makedirs(directory, exist_ok=True)
    # Written beside it and renamed into place, so that a process reading the
    # file while another writes it finds either nothing or all of it.
    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise
    return path


def _label(path: str, other: str) -> str:
    """What the assembly left behind calls one of the two: its own link name, unless both have the same one."""
    own = path.rsplit("/", 1)[-1]
    if own != other.rsplit("/", 1)[-1]:
        return own
    # Two of one name - a bolt in two sub-assemblies - are told apart by the
    # whole of where they are, with dots rather than slashes, which a link name
    # does not hold.
    return path.replace("/", ".")


async def make_async(ctx, assembly, overlap: dict) -> typing.Optional[dict]:
    """The artifact for one reported overlap, registered and ready to be shown; None when there is nothing to show.

    'overlap' is an entry of what the assembly's interference measurement
    returns when asked to keep what each pair shares ('keep_common'): the two
    paths, the volume, the solids they share and the two parts by object name
    and placement.
    """
    members = overlap.get("members") or {}
    solids = overlap.get("solids") or []
    if not solids or not members.get("a") or not members.get("b"):
        return None
    try:
        directory = _directory(ctx)
        volumes = [_write(directory, shape_envelope.brep_plain(solid.get(shape_envelope.KEY_BREP))) for solid in solids]
    except Exception as e:  # pylint: disable=broad-except
        # Only what is left to look at is lost; the verdict stands without it.
        pc_logging.debug("%s: the overlap could not be kept to be looked at: %s" % (assembly.name, e))
        return None

    a, b = overlap["a"], overlap["b"]
    artifact = {
        "kind": "assembly",
        "package": assembly.project_name,
        "name": name_of(assembly.name, a, b),
        "title": "'%s' and '%s'" % (a, b),
        "desc": "Where '%s' and '%s' overlap: the two, and the %.3f mm^3 they share as the parts of '%s'"
        % (a, b, overlap.get("volume", 0.0), SUBASSEMBLY),
        "recipe": {
            "a": {"path": a, "object": members["a"]["object"], "location": members["a"]["location"]},
            "b": {"path": b, "object": members["b"]["object"], "location": members["b"]["location"]},
            "volumes": volumes,
        },
    }
    return artifact if await restore_async(ctx, artifact) else None


async def restore_async(ctx, artifact: dict) -> bool:
    """Register the objects 'artifact' names, from its recipe; whether it can be shown.

    Registering the same objects again replaces what an earlier run left under
    those names, so that a check run after an edit shows the overlap as it is
    now rather than as it was.
    """
    recipe = artifact.get("recipe") or {}
    volumes = recipe.get("volumes") or []
    if not volumes or not all(os.path.isfile(path) for path in volumes):
        return False
    project = ctx.get_project(artifact.get("package"))
    if project is None:
        return False

    placed = []
    for side, other in (("a", "b"), ("b", "a")):
        member = recipe.get(side) or {}
        try:
            item = await ctx.get_part_async(member.get("object"))
        except Exception:  # pylint: disable=broad-except
            item = None
        if item is None:
            return False
        location = member.get("location")
        placed.append(
            AssemblyChild(
                item,
                _label(member.get("path", side), (recipe.get(other) or {}).get("path", other)),
                Location(location) if location is not None else Location(),
            )
        )

    name = artifact["name"]
    shared = "%s/%s" % (name, SUBASSEMBLY)
    volume_children = []
    for index, path in enumerate(volumes, start=1):
        part_name = "%s/volume-%d" % (shared, index)
        config = {
            "type": "brep",
            "name": part_name,
            "orig_name": part_name,
            "path": path,
            "desc": "Volume %d of what %s share" % (index, artifact.get("title", "the two")),
            "manufacturable": False,
        }
        config = PartConfiguration.normalize(part_name, config, "%s:%s" % (project.name, part_name))
        existing = project.objects("part").get(part_name)
        if existing is not None and (existing.config or {}).get("path") != path:
            # An earlier run's volume, under the name this one's has: replaced,
            # not kept, since it is no longer what the two share.
            project.objects("part").pop(part_name, None)
        part = project.materialize_part_by_config(config)
        if part is None:
            return False
        volume_children.append(AssemblyChild(part, "volume-%d" % index, Location()))

    common = _in_memory(project.name, shared, "What %s share" % artifact.get("title", "the two"), volume_children)
    root = _in_memory(
        project.name, name, artifact.get("desc"), placed + [AssemblyChild(common, SUBASSEMBLY, Location())]
    )
    assemblies = project.objects("assembly")
    for registered_name, item in ((shared, common), (name, root)):
        assemblies.pop(registered_name, None)
        project.register_object("assembly", registered_name, item)
    return True


def _in_memory(project_name: str, name: str, desc, children: list) -> Assembly:
    """An assembly holding exactly 'children', put together here rather than read from a file.

    Never cacheable: its cache key would cover its configuration and not what
    it holds or where (see 'assembly_filter.derive', which makes the same kind).
    """
    item = Assembly(project_name, {"name": name, "desc": desc, "cache": False, "manufacturable": False})
    item.instantiate = lambda _: True
    item.children.extend(children)
    item._wrapped = None
    return item
