#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An assembly or a scene as one part: the compound of everything it places.

PartCAD builds an assembly as a tree, never as one piece of geometry: a node per
thing it places, each with its name, its label, its placement as data and what
it says about itself ('Assembly._get_shape_real'). That tree is what is cached,
what the IDE draws a link at a time, what a filter selects from, and what an
exporter writes a product structure, a URDF or a glTF scene graph out of. The
flat 'TopoDS_Compound' an assembly used to be made into exists only inside the
sandbox of whatever is handed the tree (see 'ocp_serialize.decode_tree'): made
again for every call, in a millisecond or so beside the time the BREP leaves
take to decode, and never cached, because nothing outside that call reads it.

This module is the one way to ask for the compound *as an object*: a part. It
is a part like any other - cached under a key of its own, measured, validated,
and written to any file type a part is - and it is made in one sandbox, by
'wrapper_transform.flatten', which places every leaf and puts each one's
colours and materials onto its faces in the compound, so that a red bolt placed
four times is four red bolts in one part rather than four uncoloured ones.

What asks for it:

  * a ``compound`` part a package declares ('part_factory_compound');
  * ``pc export --compound``, the ``compound`` parameter of ``render.objects``
    and ``render.inline``, and a file type that declares ``compound: true``
    (see 'output.Implementation.compound'): an assembly or a scene written as
    the file its compound would be, under its own name;
  * ``pc import assembly --compound`` and ``pc adhoc convert part --compound``,
    which read an assembly file as one part.

A part asked to be a compound is the part itself: there is nothing to flatten.
"""

import typing

from . import code_version, sandbox_versions, shape_envelope, transform
from .part import Part

# The kinds of object that have a compound to be made of them.
KINDS = ("assembly", "scene")

# What a file of the compound is, beside the object it is of (see
# 'Shape.get_artifact_key_async').
IDENTITY = "compound"

# The wrapper that makes a compound, which is what one is keyed on beside the
# object it is made of ('ShapeFactory.code_versions').
WRAPPERS = ("transform.py",)

# What of the declaration of the object a compound view keeps: what names and
# describes it, and the file types configured for it - a package that declares
# how its assembly is exported to STEP declares how the compound of it is too.
# Not the rest: an assembly's 'path', 'links' or 'parameters' mean nothing to a
# part, and some of them mean something else to one.
_KEPT = ("desc", "render", "export", "label")


def applies(shape) -> bool:
    """Whether 'shape' is an object a compound is made of: an assembly or a scene."""
    return getattr(shape, "kind", None) in KINDS


def environment_cache_key() -> str:
    """The environment a compound is made in: the interpreter and the stack 'transform.py' runs on."""
    return sandbox_versions.environment_cache_key(
        "python", sandbox_versions.DEFAULT_PYTHON_VERSION, sandbox_versions.PINNED_REQUIREMENTS
    )


def code_versions() -> typing.Optional[str]:
    """The versions of the code that makes a compound, as one key ('code_version.key')."""
    return code_version.wrappers_key(WRAPPERS)


async def flatten_async(ctx, part, source) -> typing.Optional[dict]:
    """The shape 'part' is when it is the compound of 'source': one envelope, made in a sandbox.

    'source' is an assembly or a scene, built (or read from the cache) as the
    tree it is. What comes back is one shape object named as 'part' is, and
    finished as 'part' asks ('Shape.finish_request()': validated, moved and
    scaled while the compound is live), so that 'Shape.get_wrapped' has
    nothing left to do but record it. None when 'source' has no shape.
    """
    tree = await source.get_wrapped(ctx)
    if tree is None:
        return None
    if shape_envelope.is_shape_object(tree):
        # One shape already - the compound of a single part is that part.
        return tree
    name, label = part._shape_metadata()
    return await transform.flatten(ctx, tree, name=name, label=label, finish=part.finish_request())


class CompoundView(Part):
    """An assembly or a scene as a part of its own: its compound.

    Built from the object it is of rather than declared, under that object's
    name and in that object's package, so that a file written of it lands where
    the object's own would have ('logo.step' of the assembly 'logo'). Keyed on
    that object's key and on the code that flattens it, which is everything it
    is, and cached like any part: the second export of an assembly's compound
    reads it back rather than flattening it again. An object that is not cached
    (`cache: false`, a filtered view) has a compound that is not cached either.
    """

    def __init__(self, source):
        config = {key: source.config[key] for key in _KEPT if key in source.config}
        config["name"] = source.name
        config["orig_name"] = source.config.get("orig_name", source.name)
        config["type"] = "compound"
        config["source"] = "%s:%s" % (source.project_name, source.name)
        if source.config.get("cache") is False:
            config["cache"] = False
        super().__init__(source.project_name, config)
        self.source = source
        # Whatever is made of it is of 'source' too: the artifacts of a view
        # that has no key of its own are keyed as the object and this.
        self.derived_from = source
        self.artifact_identity = IDENTITY
        self.set_environment_cache_key(environment_cache_key())
        versions = code_versions()
        if versions is not None:
            self.add_code_versions(versions)
        self._prepare = CompoundView._prepare_view

    async def _prepare_view(self) -> None:
        # What the object it is made of contains, which its key covers and
        # this one's own configuration does not.
        if not await self.add_cache_key_of(self.source):
            self.cacheable = False

    async def get_shape(self, ctx):
        return await flatten_async(ctx, self, self.source)


def view(source) -> Part:
    """'source' as one part, if it is an assembly or a scene; 'source' itself otherwise.

    One view per object, kept on it, so that every file type written of one
    object asks one part for its compound - built, or read back, once.
    """
    if not applies(source):
        return source
    found = source.__dict__.get("_compound_view")
    if found is None:
        found = source.__dict__.setdefault("_compound_view", CompoundView(source))
    return found
