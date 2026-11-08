#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a topology check leaves behind: the object, and the place on it that is the finding.

"12 faces of 'bracket' have no tolerance" says how many, and not which, and
which is what somebody about to fix the drawing needs to see. So a topology
check leaves an assembly to look at for each finding: the subject, where it is,
and a sub-assembly named 'focus' holding the geometry the finding is about --
the faces, the edges (drawn as thin tubes, so that a renderer that draws only
surfaces still draws them), the volumes -- each as a part of a colour that
stands out. The artifact says which link is the finding ('FOCUS_KEY'), and the
IDE's Topology tab shows the assembly with everything else faded.

Nothing declares these objects, so they are made the way the interference check
makes the overlaps it shows (see 'partcad.test.interference_artifact', which
predates this and keeps its own layout): registered in the subject's package,
in memory only, under names worked out from what they are --

    <subject>/<check>                    the assembly to look at
    <subject>/<check>/focus              what the finding is about
    <subject>/<check>/focus/<geometry>   each piece of it, a 'brep' part

-- so that checking the same object again names the same objects, and asking for
one by name, in any request to the same daemon, finds it. Each is marked
'Shape.artifact', which keeps it out of what lists the package's declarations.

Each piece of geometry is a 'brep' part read from a file under PartCAD's state
directory ('internalStateDir'/qual), named after a digest of its bytes, so the
same finding writes the same file and its part's cache key is the same from one
run to the next. What a verdict keeps with it, in the cache, is the recipe: the
subject by name, and the files. A verdict read back in a daemon that has not run
the check registers the objects again from it ('restore_async'), as long as the
files are still there.
"""

import hashlib
import os
import tempfile
import typing

from .. import logging as pc_logging
from ..assembly import Assembly, AssemblyChild
from ..geom import Location
from ..part_config import PartConfiguration

# The key of an artifact naming the link of it that is the finding, as a path
# of link names from the artifact's root: what the viewer leaves unfaded.
FOCUS_KEY = "focus"

# The sub-assembly of the geometry a finding is about.
FOCUS = "focus"

# The folder under PartCAD's state directory the geometry is written to.
FOLDER = "qual"

# What each kind of geometry is drawn in: colours no part is likely to be, and
# that read against the faded rest of the object.
COLORS = {
    "face": "#FF2D55",
    "edge": "#FF9500",
    "volume": "#FF2D55",
}


def write_brep(ctx, data: bytes, folder: str = FOLDER) -> str:
    """Write one piece of geometry where its digest says, once, and return the path."""
    directory = os.path.join(ctx.user_config.internal_state_dir, folder)
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


def brep_part(project, name: str, path: str, desc: str, kind: str = "face"):
    """A 'brep' part of 'path', registered in 'project' under 'name' as an artifact; None if it cannot be."""
    config = {
        "type": "brep",
        "name": name,
        "orig_name": name,
        "path": path,
        "desc": desc,
        "manufacturable": False,
        "properties": {"color": COLORS.get(kind, COLORS["face"])},
    }
    config = PartConfiguration.normalize(name, config, "%s:%s" % (project.name, name), project.ctx.user_config)
    existing = project.objects("part").get(name)
    if existing is not None and (existing.config or {}).get("path") != path:
        # An earlier run's geometry, under the name this one's has: replaced,
        # not kept, since it is no longer what the finding is.
        project.objects("part").pop(name, None)
    part = project.materialize_part_by_config(config)
    if part is None:
        return None
    part.artifact = True
    return part


def in_memory(project_name: str, name: str, desc, children: list) -> Assembly:
    """An assembly holding exactly 'children', put together here rather than read from a file.

    Never cacheable: its cache key would cover its configuration and not what
    it holds or where (see 'assembly_filter.derive', which makes the same kind).
    """
    item = Assembly(project_name, {"name": name, "desc": desc, "cache": False, "manufacturable": False})
    item.instantiate = lambda _: True
    item.children.extend(children)
    item._wrapped = None
    item.artifact = True
    return item


def name_of(subject_name: str, check: str) -> str:
    """The name of the assembly a check leaves behind for 'subject_name'."""
    return "%s/%s" % (subject_name, check)


async def make_async(
    ctx,
    shape,
    check: str,
    title: str,
    desc: str,
    geometry: typing.List[dict],
) -> typing.Optional[dict]:
    """The artifact for one finding of 'check' on 'shape', registered and ready to be shown.

    'geometry' is what the finding is about, each a {'name', 'kind', 'brep',
    'desc'} where 'brep' is OCCT BREP bytes, as a wrapper answered them
    ('shape_envelope.brep_plain'), and 'kind' is 'face', 'edge' or 'volume'. None
    when there is nothing to show, or it could not be kept.
    """
    pieces = []
    try:
        for item in geometry:
            data = item.get("brep")
            if not data:
                continue
            pieces.append(
                {
                    "name": item.get("name") or item.get("kind") or "geometry",
                    "kind": item.get("kind") or "face",
                    "desc": item.get("desc") or "",
                    "path": write_brep(ctx, data),
                }
            )
    except Exception as e:  # pylint: disable=broad-except
        # Only what is left to look at is lost; the verdict stands without it.
        pc_logging.debug("%s: the finding of '%s' could not be kept to be looked at: %s" % (shape.name, check, e))
        return None
    if not pieces:
        return None

    kind = "assembly" if isinstance(shape, Assembly) else "part"
    artifact = {
        "kind": "assembly",
        "package": shape.project_name,
        "name": name_of(shape.name, check),
        "title": title,
        "desc": desc,
        FOCUS_KEY: FOCUS,
        "recipe": {
            "subject": {"object": "%s:%s" % (shape.project_name, shape.name), "kind": kind},
            "geometry": pieces,
        },
    }
    return artifact if await restore_async(ctx, artifact) else None


async def restore_async(ctx, artifact: dict) -> bool:
    """Register the objects 'artifact' names, from its recipe; whether it can be shown.

    Registering the same objects again replaces what an earlier run left under
    those names, so that a check run after an edit shows the finding as it is
    now rather than as it was.
    """
    recipe = artifact.get("recipe") or {}
    pieces = recipe.get("geometry") or []
    if not pieces or not all(os.path.isfile(piece.get("path") or "") for piece in pieces):
        return False
    project = ctx.get_project(artifact.get("package"))
    if project is None:
        return False

    subject = recipe.get("subject") or {}
    try:
        if subject.get("kind") == "assembly":
            item = ctx.get_assembly(subject.get("object"))
        else:
            item = await ctx.get_part_async(subject.get("object"))
    except Exception:  # pylint: disable=broad-except
        item = None
    if item is None:
        return False

    name = artifact["name"]
    focus_name = "%s/%s" % (name, FOCUS)
    children = []
    for piece in pieces:
        part = brep_part(
            project, "%s/%s" % (focus_name, piece["name"]), piece["path"], piece.get("desc") or "", piece.get("kind")
        )
        if part is None:
            return False
        children.append(AssemblyChild(part, piece["name"], Location()))

    focus = in_memory(project.name, focus_name, "What %s is about" % artifact.get("title", "the finding"), children)
    label = str(subject.get("object", "subject")).rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    root = in_memory(
        project.name,
        name,
        artifact.get("desc"),
        [AssemblyChild(item, label, Location()), AssemblyChild(focus, FOCUS, Location())],
    )
    assemblies = project.objects("assembly")
    for registered_name, registered in ((focus_name, focus), (name, root)):
        assemblies.pop(registered_name, None)
        project.register_object("assembly", registered_name, registered)
    return True
