#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Another tool's CMF, in PartCAD's convention (docs/design/cmf.md, section 7).

A source - a STEP file, a script, an OpenSCAD model, an LDraw file - states CMF
in its own terms: a colour's RGB and maybe a name, a material's designation, a
finish's. The wrapper that reads it writes those into the payload's CMF section
as they were stated, in sets whose origin is 'raw:<convention>' (see
'cmf_section'), and nothing outside the core ever sees such a set: the core
converts every one of them here, as the part is built, before the part's own
parameters complete them ('partcad.cmf.apply_declared').

Converting is looking up. A convention says which key of a declaration's 'ids'
holds what its tool calls it, whether that tool's names are folded to one case,
and which packages beside the part's own to look in ('catalogs'). A colour
nothing claims becomes the display-only '//builtin/color:rgba' of the value the
source stated, so the part still looks as its source drew it and is not
manufacturable on that face; a material or a finish nothing claims stays unset,
for the part's parameters to complete. Each is reported once per part.

The conventions PartCAD knows are in BUILTIN. A package declares more in its
'cmfConventions:' section, each a variation on one of those:

    cmfConventions:
      solidworks:
        extends: step          # whose facts it reads; the builtin of its name by default
        ids: solidworks        # the 'ids' key its names are looked up under; its own name by default
        catalogs: [//pub/acme] # packages to look in beside the part's own
        caseFold: true         # whether names are compared folded to lower case

and a part names one in its 'cmfConvention' parameter: a builtin by name, one
of its package's by name, or another package's by reference ('//pkg:name').
"""

import typing

from . import cmf as pc_cmf
from . import logging as pc_logging

RAW = "raw:"
SOURCE = "source:"
SECTION = "cmfConventions"


class Convention:
    """How one tool's CMF is read into PartCAD's: where its names are looked up, and how."""

    def __init__(self, name: str, ids: typing.Optional[str], case_fold: bool, catalogs=(), extends=None, package=""):
        self.name = name
        self.ids = ids
        self.case_fold = case_fold
        self.catalogs = tuple(catalogs or ())
        self.extends = extends or name
        self.package = package

    def key(self, value) -> str:
        text = str(value).strip()
        return text.casefold() if self.case_fold else text


# 'partcad' is PartCAD's own: what the source states is a reference already, as
# 'set_cmf' writes it and as PartCAD's own exports carry it. Every other one
# looks the source's names up under the 'ids' key of its name.
BUILTIN = {
    "partcad": Convention("partcad", None, False),
    "step": Convention("step", "step", True),
    "build123d": Convention("build123d", "build123d", True),
    "cadquery": Convention("cadquery", "cadquery", True),
    "openscad": Convention("openscad", "openscad", True),
    "3mf": Convention("3mf", "3mf", False),
    "gltf": Convention("gltf", "gltf", False),
    # OpenUSD: a material's name, as USD names it (see the 'usd' part type).
    "usd": Convention("usd", "usd", False),
    "ldraw": Convention("ldraw", "ldraw", False),
}


def is_raw(origin) -> bool:
    return isinstance(origin, str) and origin.startswith(RAW)


def needs_converting(summary) -> bool:
    """Whether a CMF summary has a set still in its source's terms (see the module docstring)."""
    if not isinstance(summary, dict):
        return False
    return any(isinstance(entry, dict) and is_raw(entry.get("origin")) for entry in summary.get("sets") or [])


def _declared(ctx, package: str, name: str) -> typing.Optional[Convention]:
    project = ctx.get_project(package) if ctx is not None else None
    section = getattr(project, "config_obj", {}).get(SECTION) if project is not None else None
    if not isinstance(section, dict) or not isinstance(section.get(name), dict):
        return None
    config = section[name]
    base = BUILTIN.get(config.get("extends", name)) or BUILTIN.get("step")
    return Convention(
        name,
        config.get("ids", name),
        bool(config.get("caseFold", base.case_fold)),
        catalogs=config.get("catalogs") or (),
        extends=base.name,
        package=package,
    )


def resolve(ctx, name: typing.Optional[str], package: str, default: str) -> Convention:
    """The convention 'name' names as 'package' sees it; 'default' for None.

    'default' is what the source's reader stated: a builtin by name, or - for a
    package's own part type - a convention that package declares, by reference
    ('//pub/universe/lego:ldraw'), so that its declarations are in scope for the
    parts its part type builds in packages below it.
    """
    if not name:
        if ":" in default:
            owner, _, own = default.rpartition(":")
            found = _declared(ctx, owner or package, own)
            if found is not None:
                return found
            pc_logging.warning(
                "The convention '%s' a part's source names is not declared; reading it as '%s'" % (default, own)
            )
            return BUILTIN.get(own) or BUILTIN["partcad"]
        return BUILTIN.get(default) or BUILTIN["partcad"]
    if ":" in name:
        owner, _, own = name.rpartition(":")
        found = _declared(ctx, owner or package, own)
    else:
        found = _declared(ctx, package, name) or BUILTIN.get(name)
    if found is None:
        pc_logging.error(
            "'cmfConvention: %s' names no convention: one of %s, or one a package declares under '%s:'; reading "
            "the source as '%s'" % (name, ", ".join(sorted(BUILTIN)), SECTION, default)
        )
        # As though it named none: what the source's reader stated, which may
        # be a package's convention as much as a builtin.
        return resolve(ctx, None, package, default)
    return found


class _Index:
    """What every declaration in scope is called under one 'ids' key, by kind."""

    def __init__(self, ctx, convention: Convention, package: str):
        self.found = {}
        for scope in (package, convention.package, *convention.catalogs):
            if not scope:
                continue
            project = ctx.get_project(scope) if ctx is not None else None
            if project is None:
                pc_logging.warning("CMF convention '%s': no package '%s' to look in" % (convention.name, scope))
                continue
            for kind in pc_cmf.KINDS:
                for name in project.object_names(kind):
                    declaration = project.get_cmf(kind, name, quiet=True)
                    if declaration is not None:
                        self._add(kind, declaration, convention)

    def _add(self, kind, declaration, convention):
        if getattr(declaration, "is_alias", False):
            return
        ids = getattr(declaration, "ids", None) or {}
        values = ids.get(convention.ids)
        if values is None:
            return
        for value in values if isinstance(values, (list, tuple)) else [values]:
            # The first declaration to claim a name keeps it: the part's own
            # package is looked in first, so it can say what a catalog's name
            # means in it.
            self.found.setdefault((kind, convention.key(value)), declaration.reference())

    def get(self, kind, value, convention):
        return self.found.get((kind, convention.key(value)))


def convert(ctx, shape, section, convention_name: typing.Optional[str]):
    """'section' with every set still in its source's terms converted into PartCAD's.

    'convention_name' is the part's 'cmfConvention', None for the one each set's
    reader stated ('raw:<convention>'). What nothing claims is reported once,
    for the whole part.
    """
    import cmf_section

    package = shape.project_name
    conventions = {}
    indices = {}
    unmatched = []
    sets = []
    for cmf_set in section.sets:
        if not is_raw(cmf_set.origin):
            sets.append(cmf_set)
            continue
        default = cmf_set.origin[len(RAW) :]
        # The part's 'cmfConvention' says how its source's tool is read, and so
        # never applies to what was stated in PartCAD's own terms ('set_cmf').
        asked = None if default == "partcad" else convention_name
        key = asked or default
        if key not in conventions:
            conventions[key] = resolve(ctx, asked, package, default)
        convention = conventions[key]
        values = {}
        for kind in pc_cmf.KINDS:
            stated = getattr(cmf_set, kind)
            if stated is None:
                values[kind] = None
                continue
            if convention.ids is None:
                found = pc_cmf.lookup(ctx, kind, stated, package, quiet=True)
                reference = found.reference() if found is not None else None
            else:
                if convention.name not in indices:
                    indices[convention.name] = _Index(ctx, convention, package)
                reference = indices[convention.name].get(kind, stated, convention)
            if reference is None:
                unmatched.append((kind, stated))
            values[kind] = reference
        rgba, texture = cmf_set.rgba, cmf_set.texture
        if values["color"] is None and rgba is not None and cmf_set.color is not None:
            # Still the colour the source drew, and now said to be only that.
            values["color"] = pc_cmf.rgba_reference(rgba)
        elif values["color"] is not None and pc_cmf.rgba_of_reference(values["color"]) is None:
            # Drawn as its declaration says, which is what claiming the name
            # means - with the image it is drawn with, if it is one.
            color = pc_cmf.lookup(ctx, "color", values["color"], package, quiet=True)
            declared = pc_cmf.display(ctx, color)
            rgba = declared if declared is not None else rgba
            texture = pc_cmf.texture_of(ctx, color)
        if values["color"] is None and values["material"] is not None:
            claim = getattr(
                pc_cmf.lookup(ctx, "material", values["material"], package, quiet=True), "color_claim", None
            )
            if claim:
                values["color"] = pc_cmf.canonical(ctx, "color", claim, package, quiet=True)
                color = pc_cmf.lookup(ctx, "color", values["color"], package, quiet=True)
                rgba = pc_cmf.rgba_of_reference(values["color"]) or pc_cmf.display(ctx, color)
                texture = pc_cmf.texture_of(ctx, color)
        roughness, metallic = cmf_set.roughness, cmf_set.metallic
        if values["finish"] is not None:
            # What the finish's declaration says to draw it as, and the
            # source's own values for what it leaves unsaid.
            finish = pc_cmf.lookup(ctx, "finish", values["finish"], package, quiet=True)
            declared = getattr(finish, "roughness", None)
            roughness = declared if declared is not None else roughness
            declared = getattr(finish, "metallic", None)
            metallic = declared if declared is not None else metallic
        sets.append(
            cmf_section.CmfSet(
                color=values["color"],
                material=values["material"],
                finish=values["finish"],
                origin=SOURCE + convention.name,
                rgba=rgba,
                roughness=roughness,
                metallic=metallic,
                texture=texture,
            )
        )
    if unmatched:
        said = sorted({"%s '%s'" % pair for pair in unmatched})
        pc_logging.warning(
            "%s:%s: nothing in scope claims %s of its source (convention '%s'); a colour is drawn as stated and is "
            "display-only, a material or finish is left for the part's parameters. Declare it with 'ids: {%s: ...}'"
            % (package, shape.name, ", ".join(said), ", ".join(sorted(conventions)), _ids_key(conventions))
        )
    return cmf_section.Section(sets, section.default, section.solids, section.faces).compacted()


def _ids_key(conventions) -> str:
    keys = sorted({convention.ids for convention in conventions.values() if convention.ids})
    return keys[0] if len(keys) == 1 else "<tool>"


def reference_for(ctx, package: str, kind: str, designation: str, rgba=None, convention: str = "step"):
    """The reference 'designation' - a source's name for a colour, material or finish - converts to in 'package'.

    One fact at a time, for a reader that writes CMF rather than carrying it in
    a payload: 'pc import' of a STEP assembly writing an instance's overriding
    colour as its link's 'params:'. A colour nothing claims is the display-only
    'rgba' of 'rgba'; anything else nothing claims is None.
    """
    found = resolve(ctx, convention, package, convention)
    if found.ids is None:
        declaration = pc_cmf.lookup(ctx, kind, designation, package, quiet=True)
        reference = declaration.reference() if declaration is not None else None
    else:
        reference = _Index(ctx, found, package).get(kind, designation, found)
    if reference is None and kind == "color" and rgba is not None:
        return pc_cmf.rgba_reference(tuple(rgba))
    return reference
