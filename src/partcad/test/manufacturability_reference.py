#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Resolving the objects a part's `manufacturing:` section points at.

Three of the manufacturability checks are about a part defined in terms of
another object -- the blank a sheet metal part is bent from, the stock a
subtractive part is cut out of -- so they all have to turn a reference into the
object it names. One copy of that, here, because the rule it implements is one
rule and a second copy is a second answer to "what does `source: blank` mean".

What the rule is: the reference is resolved against the package the *part* is
declared in, like every other reference a part makes, so a blank beside the part
is named by its bare name and one somewhere else carries its package. A
reference may also carry parameters -- `panel;include=BEND_UP` -- and the
accessors read them, which is the whole reason the layer filters are parameters.
"""

from .. import logging as pc_logging
from ..utils import resolve_resource_path


async def resolve_reference(ctx, shape, reference: str, kind: str = "part"):
    """The object a 'manufacturing:' reference names, or None where there is none.

    Quiet: None is returned and nothing is logged by the resolver, because the
    check is what reports it. A missing blank is a failure of the part that
    named it, said against that part with the field it came from, and the
    resolver's own wording for a lookup the user never made would be a second
    line saying less (see 'Project.get_object', whose 'quiet' exists for this).

    Args:
        ctx: Execution context.
        shape: The part whose declaration carries the reference, which is what
            the reference is resolved relative to.
        reference: What the section said, with or without a package and with or
            without parameters.
        kind: 'part' or 'sketch' -- which accessor answers.
    """
    project_name, object_name = resolve_resource_path(shape.project_name, reference)
    project = ctx.get_project(project_name)
    if project is None:
        pc_logging.debug("Package '%s' not found" % project_name)
        return None
    if kind == "sketch":
        return project.get_sketch(object_name, quiet=True)
    # The asynchronous accessor, because every caller of this is a coroutine and
    # 'get_part()' says so in as many words: materializing a *derived* part --
    # one an assembly produces rather than the package declaring it, a STEP
    # component or a URDF link -- instantiates that assembly, which is
    # asynchronous, and the synchronous accessor drives it with 'asyncio.run()'.
    # On a thread that already has a loop that raises rather than building, so a
    # part whose source is derived would fail the check with a RuntimeError
    # about the loop instead of being measured. A declared part resolves the
    # same either way; this costs nothing and covers the case that does not.
    return await project.get_part_async(object_name, quiet=True)


async def reference_key(ctx, shape, reference: str, kind: str = "part") -> str:
    """What a reference contributes to a check's cache key.

    The name *and* the cache key of what it resolves to, because a check that
    read another object has to re-run when that object changes and the part's
    own hash says nothing about it -- 'manufacturing:' is one of the keys a
    shape's hash deliberately leaves out.

    A reference that resolves to nothing still keys, as the name with an empty
    key after it: "the blank is missing" is a verdict like any other, and it has
    to stop being the answer the moment somebody adds the blank.
    """
    if not reference:
        return "%s@" % kind
    object = await resolve_reference(ctx, shape, reference, kind)
    key = None
    if object is not None:
        try:
            key = await object.get_cache_key_async()
        except Exception as e:  # pylint: disable=broad-except
            pc_logging.debug("Failed to key '%s' for a manufacturability test: %s" % (reference, e))
    return "%s:%s@%s" % (kind, reference, key or "")
