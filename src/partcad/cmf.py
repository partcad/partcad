#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""CMF: the colour, the material and the finish of what a product is made of.

Three kinds of one declaration (see docs/design/cmf.md). A package declares
them under 'colors:', 'materials:' and 'finishes:', addresses each as
'<package>:<name>', and every one of them says the same things about itself:

- 'display': how to draw it - a hint, never a claim. For a colour, any CSS
  colour ('#c91a09', 'oklch(52% 0.19 33)', 'firebrick') or the reference of
  another colour whose display it takes; for a material, the look of the
  substance as it comes; for a finish, '{roughness, metallic}' for a 3D view.
- 'manufacturable': whether the declaration is a claim that this can be
  sourced or made as declared. True unless it says otherwise: a colour that is
  only a picture - '//pub/std/color:rgba' - says 'false'.
- 'ids': what other systems call it ({'ldraw': '71', 'bricklink': '86', ...}),
  which is how a converter maps another tool's names onto it.
- 'parameters': a declaration may be parametric, and its fields are rendered
  with the values a reference gives ('rgba;color=C91A09FF').
- 'aliases': other names of itself; and 'type: alias' with a 'source:' makes the
  declaration another name for one elsewhere.

A material adds its physical facts (see 'material.py') and may claim a colour
for its natural surface ('color:'); a finish adds nothing PartCAD computes
with. 'texture' is reserved for a visual texture and is none of these.

A reference to a declaration is canonicalised before it becomes part of an
item's name ('canonical'): its aliases followed, a relative reference made
absolute against the package that wrote it, and its name escaped as
'partcad_utils.utils.RESERVED_IN_NAMES' says. That is what makes two packages
that alias one vendor colour differently name the same item.
"""

import copy
import os
import sys
import typing

from partcad_utils.utils import escape_name, format_parameterized_name, parse_parameterized_name

from . import logging as pc_logging
from .utils import resolve_resource_path

# The wrappers directory is on the path for anything that imports 'partcad'
# (see 'shape.py'); said again so that this module stands on its own.
_WRAPPERS = os.path.join(os.path.dirname(__file__), "wrappers")
if _WRAPPERS not in sys.path:
    sys.path.append(_WRAPPERS)
import css_color  # noqa: E402

# The three kinds, in the order CMF names them and every view lists them.
KINDS = ("color", "material", "finish")
SECTIONS = {"color": "colors", "material": "materials", "finish": "finishes"}

# The object-type parameters every part and every assembly type accepts (see
# docs/design/cmf.md, "Where CMF comes from"). The first three name a
# declaration of their own kind; 'sourceCmf' says what of the CMF the source
# states is kept ('keep', 'drop', or a list of the components to drop), and
# 'cmfConvention' which converter reads the source's CMF.
SOURCE_CMF = "sourceCmf"
CONVENTION = "cmfConvention"
TYPE_PARAMETERS = KINDS + (SOURCE_CMF, CONVENTION)
SOURCE_CMF_KEEP = "keep"
SOURCE_CMF_DROP = "drop"

# The display-only colour anybody can name to colour a picture without claiming
# anything: '//pub/std/color:rgba;color=RRGGBBAA'.
RGBA = "//pub/std/color:rgba"


class Declaration:
    """One colour, material or finish of a package."""

    kind: str = "cmf"

    def __init__(self, name: str, project_name: str, config: typing.Optional[dict] = None) -> None:
        config = config if config is not None else {}
        self.name = name
        self.project_name = project_name
        self.config = config
        # What it was declared as, and with which values, when it is an
        # instance of a parametric declaration ('rgba;color=C91A09FF').
        self.base_name, self.parameter_values = parse_parameterized_name(name)
        desc = config.get("desc", "")
        self.desc = desc.strip() if isinstance(desc, str) else desc
        self.errors: list = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        pc_logging.error("%s: %s: %s" % (self.project_name, self.name, msg))

    @property
    def url(self) -> typing.Optional[str]:
        return self.config.get("url")

    @property
    def is_alias(self) -> bool:
        """Whether this is another name for a declaration elsewhere ('type: alias')."""
        return self.config.get("type") == "alias"

    @property
    def source(self) -> typing.Optional[str]:
        """What an alias names, as written - relative to this declaration's package."""
        source = self.config.get("source")
        return source if isinstance(source, str) and source else None

    @property
    def display_text(self) -> typing.Optional[str]:
        """The 'display' as written, or None."""
        display = self.config.get("display")
        return display if isinstance(display, str) and display.strip() else None

    @property
    def ids(self) -> dict:
        """What other systems call this, as '{system: identifier}', every identifier a string.

        A system with several identifiers for it - LEGO's white is both 1 and
        426 - has them as a list of strings.
        """
        ids = self.config.get("ids")
        if not isinstance(ids, dict):
            return {}
        result = {}
        for system, identifier in ids.items():
            if isinstance(identifier, (list, tuple)):
                listed = [str(each) for each in identifier if each is not None]
                if listed:
                    result[str(system)] = listed
            elif identifier is not None:
                result[str(system)] = str(identifier)
        return result

    @property
    def manufacturable(self) -> bool:
        """Whether this is a claim that it can be sourced or made as declared. True unless it says not."""
        value = self.config.get("manufacturable", True)
        return value if isinstance(value, bool) else True

    @property
    def aliases(self) -> list:
        aliases = self.config.get("aliases")
        if not aliases:
            return []
        if isinstance(aliases, str):
            return [aliases]
        return [str(alias) for alias in aliases]

    def reference(self) -> str:
        """This declaration's canonical reference: its package, its escaped name, its values."""
        # The values formatted on their own: 'format_parameterized_name' reads
        # the name it is handed, which would decode the escapes just made.
        values = format_parameterized_name("", self.parameter_values) if self.parameter_values else ""
        return "%s:%s%s" % (self.project_name, escape_name(self.base_name), values)

    def cmf_info(self) -> dict:
        """What every kind of declaration says about itself, as 'pc info' prints it."""
        info = {"Path": self.project_name, "Name": self.name, "Kind": self.kind}
        if self.is_alias:
            info["Alias of"] = self.source
        if self.desc:
            info["Desc"] = self.desc
        if self.display_text is not None:
            info["Display"] = self.display_text
        info["Manufacturable"] = "yes" if self.manufacturable else "no (display only)"
        if self.ids:
            info["Ids"] = ", ".join(
                "%s: %s" % (system, " / ".join(ids) if isinstance(ids, list) else ids)
                for system, ids in sorted(self.ids.items())
            )
        if self.aliases:
            info["Aliases"] = ", ".join(self.aliases)
        if self.url:
            info["Url"] = self.url
        if self.errors:
            info["Errors"] = list(self.errors)
        return info

    def info(self) -> dict:
        return self.cmf_info()

    def matches(self, keyword: str) -> bool:
        if not keyword:
            return False
        keyword = keyword.lower()
        return keyword in self.name.lower() or keyword in str(self.config).lower()


class Color(Declaration):
    """A colour a product can be made in."""

    kind = "color"


class Finish(Declaration):
    """A finish a surface can be given: a process, a gloss, a surface specification ('ids')."""

    kind = "finish"

    def _display_number(self, key: str) -> typing.Optional[float]:
        display = self.config.get("display")
        if not isinstance(display, dict):
            return None
        value = display.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return max(0.0, min(1.0, float(value)))

    @property
    def display_text(self) -> typing.Optional[str]:
        return None

    @property
    def roughness(self) -> typing.Optional[float]:
        """How rough the surface looks, 0 (mirror) to 1 (matte), for a 3D view; None if not said."""
        return self._display_number("roughness")

    @property
    def metallic(self) -> typing.Optional[float]:
        """How metallic it looks, 0 to 1, for a 3D view; None if not said."""
        return self._display_number("metallic")

    def cmf_info(self) -> dict:
        info = super().cmf_info()
        hints = []
        if self.roughness is not None:
            hints.append("roughness %g" % self.roughness)
        if self.metallic is not None:
            hints.append("metallic %g" % self.metallic)
        if hints:
            info["Display"] = ", ".join(hints)
        return info


def normalize(kind: str, config) -> dict:
    """A declaration as written - the short form included - as the mapping it stands for.

    The short form of a colour is its display ('red: "#C91A09"'), of a finish its
    description, and of a material its full name (see 'material_config').
    """
    if config is None:
        return {}
    if isinstance(config, str):
        if kind == "color":
            return {"display": config}
        if kind == "material":
            return {"full": config}
        return {"desc": config}
    return config


def with_parameters(config: dict, values: dict, object_name: str) -> dict:
    """The declaration of the instance 'values' name: its parameters set, its fields rendered.

    Every string field may name a parameter in PartCAD's own expression syntax
    ('%color%', see 'partcad.expr'), which is how '//pub/std/color:rgba' turns
    'color=C91A09FF' into its display. Not Jinja2's: 'partcad.yaml' is rendered
    as a template before it is read, long before any reference gives a value.
    """
    from . import expr
    from .config import apply_parameter_values

    instance = copy.deepcopy(config)
    parameters = instance.get("parameters") or {}
    apply_parameter_values(parameters, values, object_name)
    context = {name: declared.get("default") for name, declared in parameters.items() if isinstance(declared, dict)}
    for key, value in list(instance.items()):
        if key != "parameters":
            instance[key] = expr.resolve(value, context, object_name)
    return instance


def _split(ref: str, relative_to: str) -> tuple:
    """'(package, name with its parameters)' of a reference written in 'relative_to'.

    A bare name and ':name' are both the writing package's own.
    """
    package, name = resolve_resource_path(relative_to or "", ref)
    return package, name


def lookup(ctx, kind: str, ref: str, relative_to: str = "", quiet: bool = False, follow: bool = True):
    """The declaration of 'kind' that 'ref' names, written in package 'relative_to', or None.

    Aliases are followed unless 'follow' is False, so what comes back is the
    declaration that says what the thing is. An alias that leads back to itself
    is reported and resolves to nothing.
    """
    seen = set()
    current_ref, current_package = ref, relative_to
    while True:
        package_name, name = _split(current_ref, current_package)
        project = ctx.get_project(package_name) if ctx is not None else None
        if project is None:
            if not quiet:
                pc_logging.error("The %s '%s' is not found: no package '%s'" % (kind, ref, package_name))
            return None
        declaration = project.get_cmf(kind, name, quiet=quiet)
        if declaration is None or not follow or not declaration.is_alias:
            return declaration
        key = (declaration.project_name, declaration.name)
        if key in seen:
            if not quiet:
                pc_logging.error("The %s '%s' is an alias that leads back to itself" % (kind, ref))
            return None
        seen.add(key)
        if declaration.source is None:
            if not quiet:
                declaration.error("is an alias with no 'source'")
            return None
        current_ref, current_package = declaration.source, declaration.project_name


def canonical(ctx, kind: str, value, relative_to: str = "", quiet: bool = True) -> typing.Optional[str]:
    """The canonical reference a CMF parameter's value stands for, or None for no value.

    A reference to a declaration becomes the reference of the declaration it
    resolves to (aliases followed). One that does not resolve is still made
    absolute, so that what is written in one package means the same thing in
    another. A colour that is no reference but a colour - '#C91A09', 'red' as
    CSS reads it, which is what a 'color' parameter could hold before colours
    were declarations - becomes the display-only '//pub/std/color:rgba' of it,
    with a warning: it draws as it did, and claims nothing.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value:
        return None
    if ctx is not None:
        found = lookup(ctx, kind, value, relative_to, quiet=True)
        if found is not None:
            return found.reference()
    if kind == "color" and ":" not in value:
        rgba = css_color.parse(value)
        if rgba is not None:
            reference = rgba_reference(rgba)
            if not quiet:
                pc_logging.warning(
                    "The colour '%s' is no declaration, and is read as the display-only '%s': "
                    "name a colour declaration to say what it is" % (value, reference)
                )
            return reference
    package, name = _split(value, relative_to)
    return "%s:%s" % (package, name)


def rgba_reference(rgba) -> str:
    """The display-only colour '//pub/std/color:rgba' of '(red, green, blue, alpha)'."""
    red, green, blue, alpha = rgba
    return "%s;color=%02X%02X%02X%02X" % (RGBA, red, green, blue, round(alpha * 255))


def rgba_of_reference(reference: str):
    """The colour a '//pub/std/color:rgba' reference draws, read from the reference itself, or None.

    So that a picture can be drawn where the standard catalogue is not at hand:
    the reference states its colour in full.
    """
    if not isinstance(reference, str) or not reference.startswith(RGBA + ";"):
        return None
    _base, values = parse_parameterized_name(reference.split(":", 1)[1])
    return css_color.parse("#" + values.get("color", ""))


def display(ctx, declaration, depth: int = 0):
    """'(red, green, blue, alpha)' a declaration is drawn in, or None if it states none.

    A colour's display may name another colour, whose display it takes; a
    material's is its own, else the colour it claims. A finish draws no colour.
    """
    if declaration is None or depth > 8:
        return None
    text = declaration.display_text
    if text is not None:
        parsed = css_color.parse(text)
        if parsed is not None:
            return parsed
        other = lookup(ctx, "color", text, declaration.project_name, quiet=True)
        if other is not None:
            return display(ctx, other, depth + 1)
        declaration.error("has a 'display' that is neither a CSS colour nor a colour declaration: %r" % text)
        return None
    claim = getattr(declaration, "color_claim", None)
    if claim:
        other = lookup(ctx, "color", claim, declaration.project_name, quiet=True)
        return display(ctx, other, depth + 1)
    return None


def canonical_parameters(ctx, parameters: dict, relative_to: str) -> dict:
    """'parameters' with every CMF parameter that names a declaration canonicalised.

    For whoever writes a reference into a name: an ASSY link's 'params:', an
    enrich's or an alias's 'with:', an assembly's parameters passed on to its
    links. Everything else is handed back as it was.
    """
    if not parameters:
        return parameters
    result = dict(parameters)
    for kind in KINDS:
        if kind in result and isinstance(result[kind], str):
            result[kind] = canonical(ctx, kind, result[kind], relative_to)
    return result


def source_cmf_drops(value) -> typing.Optional[tuple]:
    """The components 'sourceCmf' discards from what the source states, or None if it is not one.

    'keep' (and nothing at all) discards none, 'drop' all three, and a list
    those it names.
    """
    if value is None or value == SOURCE_CMF_KEEP:
        return ()
    if value == SOURCE_CMF_DROP:
        return KINDS
    if isinstance(value, str):
        value = [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)) and all(item in KINDS for item in value):
        return tuple(kind for kind in KINDS if kind in value)
    return None


# --------------------------------------------------------------------------- #
# A part's own CMF, and what it does to its payload                           #
# --------------------------------------------------------------------------- #


def _parameter_value(config, name: str):
    """The value an object states for the parameter 'name', or None.

    Its declaration's default - which is where the values a reference names it
    with land - or, for an 'enrich' or an 'alias', the value the instance it
    resolves to is named with ('source_resolved'): what such an object fixes
    is in that name, and nowhere in a 'parameters:' of its own.
    """
    if not isinstance(config, dict):
        return None
    parameters = config.get("parameters")
    if isinstance(parameters, dict) and name in parameters:
        declared = parameters[name]
        return declared.get("default") if isinstance(declared, dict) else declared
    resolved = config.get("source_resolved")
    if isinstance(resolved, str) and ";" in resolved:
        _, values = parse_parameterized_name(resolved)
        return values.get(name)
    return None


def own_parameters(shape) -> dict:
    """{kind: canonical reference} of the colour, material and finish an object states itself.

    Read off its declaration's parameters - which is also where the values a
    reference names it with land - and canonicalised against its own package,
    which is where a default written as ':red' was written.
    """
    config = getattr(shape, "config", None)
    ctx = getattr(getattr(shape, "project", None), "ctx", None)
    result = {}
    for kind in KINDS:
        value = _parameter_value(config, kind)
        if isinstance(value, str) and value.strip():
            result[kind] = canonical(ctx, kind, value, getattr(shape, "project_name", ""))
    return result


# Raised whenever what the core makes of an item's CMF changes, so that what
# was built with the earlier answer is not served as this one (see 'key_of').
KEY_VERSION = 1


def key_of(ctx, shape) -> dict:
    """What an assembly is keyed on of one item's CMF: {} for an item that states none.

    A part's own key does not cover its CMF: that is applied as the part is
    read, from declarations the key does not cover (see 'Shape._with_cmf'). An
    assembly's cached tree holds its parts as they were read, CMF and all, so
    the assembly's key covers what that CMF came from: the references the item
    names, what each declaration draws it in and whether it is a claim, and the
    version of what the core does with them. An item that states no CMF adds
    nothing, so the keys of assemblies with none are what they were.
    """
    references = own_parameters(shape)
    if not references:
        return {}
    described = {"version": KEY_VERSION}
    for kind, reference in sorted(references.items()):
        declaration = lookup(ctx, kind, reference, quiet=True) if ctx is not None else None
        rgba = display(ctx, declaration) if declaration is not None else rgba_of_reference(reference)
        described[kind] = {
            "reference": reference,
            "display": list(rgba) if rgba is not None else None,
            "manufacturable": declaration.manufacturable if declaration is not None else None,
        }
    return described


def declared_set(ctx, shape, quiet: bool = False):
    """'(set, drops)': the CMF an object states itself as one 'cmf_section.CmfSet', and what 'sourceCmf' drops.

    'set' is None when it states no colour, material or finish. The colour's
    display comes from its declaration, or from the reference itself for a
    display-only 'rgba'; a part that states a material and no colour takes the
    colour its material claims. 'drops' is a tuple of components.

    'quiet' is for a reader that only shows what the object states (see
    'own_info'): a 'sourceCmf' it cannot read is reported by whoever builds the
    part, once, rather than by every view that lists it.
    """
    import cmf_section

    references = own_parameters(shape)
    raw_drops = _parameter_value(getattr(shape, "config", None), SOURCE_CMF)
    drops = source_cmf_drops(raw_drops)
    if drops is None:
        if not quiet:
            pc_logging.error(
                "%s:%s: 'sourceCmf' is 'keep', 'drop' or a list of %s, not %r; keeping the source's CMF"
                % (shape.project_name, shape.name, ", ".join(KINDS), raw_drops)
            )
        drops = ()
    if not references:
        return None, drops
    package = shape.project_name
    color_ref = references.get("color")
    origin = "declared"
    if color_ref is None and references.get("material"):
        material = lookup(ctx, "material", references["material"], package, quiet=True)
        claim = getattr(material, "color_claim", None)
        if claim:
            color_ref = canonical(ctx, "color", claim, material.project_name)
    rgba = rgba_of_reference(color_ref) if color_ref else None
    if color_ref and rgba is None:
        rgba = display(ctx, lookup(ctx, "color", color_ref, package, quiet=True))
    roughness = metallic = None
    if references.get("finish"):
        finish = lookup(ctx, "finish", references["finish"], package, quiet=True)
        roughness = getattr(finish, "roughness", None)
        metallic = getattr(finish, "metallic", None)
    return (
        cmf_section.CmfSet(
            color=color_ref,
            material=references.get("material"),
            finish=references.get("finish"),
            origin=origin,
            rgba=rgba,
            roughness=roughness,
            metallic=metallic,
        ),
        drops,
    )


def apply_declared(ctx, shape, envelope, recorded: dict):
    """'(envelope, recorded)' with the part's own CMF applied to its payloads' CMF sections.

    What the part's source stated is kept, completed by what the part declares,
    or - as 'sourceCmf' says - replaced (docs/design/cmf.md, "Where an item's CMF
    comes from"). Done here, in the core and without a CAD kernel: the section
    follows the BREP in the payload and is read and written as bytes, so every
    part type gets it the same way, whatever built it. Nothing changes for a part
    that states no CMF.

    A part's envelope is one node or a tree of them (a script's several
    components), and every payload in it is given the part's own set. A payload
    several nodes carry - the compound a script's components are pieces of (see
    'shape_envelope.KEY_CHILD') - is one payload, given one section and counted
    once: the part's own set holds for every face of it, whichever piece a face
    is in. The tree is copied on the way, never changed in place.

    'recorded' is the metadata the shape was built with, and takes the summary
    of what the sections come to (see 'cmf_section.merge_summaries'). The
    caller applies this to the geometry as it was built, on every read rather
    than once before caching it (see 'Shape._with_cmf').
    """
    from . import cmf_conventions, shape_envelope

    declared, drops = declared_set(ctx, shape)
    # What the source stated, in its own terms, is converted here too, before
    # the part's own CMF completes it (see 'partcad.cmf_conventions').
    converting = cmf_conventions.needs_converting((recorded or {}).get(shape_envelope.METADATA_CMF))
    if declared is None and not drops and not converting:
        return envelope, recorded
    if not shape_envelope.is_node(envelope):
        return envelope, recorded
    import cmf_section

    convention = _parameter_value(getattr(shape, "config", None), CONVENTION)

    done = {}
    summaries = []

    def applied(payload):
        key = shape_envelope.brep_bytes(payload)
        if key not in done:
            # Opened with the core's own bounded reader: the payload may come
            # out of a shared cache (see 'shape_envelope.brep_plain').
            brep, section = cmf_section.split(shape_envelope.brep_plain(key))
            if section is not None and any(cmf_conventions.is_raw(entry.origin) for entry in section.sets):
                section = cmf_conventions.convert(ctx, shape, section, convention)
            section = (section or cmf_section.Section()).without(drops)
            if declared is not None:
                section = section.completed(declared)
            done[key] = shape_envelope.brep_payload(cmf_section.join(brep, section))
            summaries.append(section.summary())
        return done[key]

    def walk(node):
        if not isinstance(node, dict):
            return node
        node = dict(node)
        if shape_envelope.KEY_BREP in node:
            node[shape_envelope.KEY_BREP] = applied(node[shape_envelope.KEY_BREP])
        children = node.get(shape_envelope.KEY_ASSEMBLY)
        if isinstance(children, list):
            node[shape_envelope.KEY_ASSEMBLY] = [walk(child) for child in children]
        return node

    envelope = walk(envelope)
    if not summaries:
        pc_logging.debug("%s:%s: no payload of its own to carry CMF in" % (shape.project_name, shape.name))
        return envelope, recorded
    recorded = dict(recorded or {})
    recorded[shape_envelope.METADATA_CMF] = cmf_section.merge_summaries(summaries)
    return envelope, recorded


def info_of(ctx, summary: dict, relative_to: str) -> dict:
    """A CMF summary as 'pc info' says it: each set's colour, material and finish, in that order.

    Each set says which of its components are display-only ('displayOnly'):
    an 'rgba' colour, or a declaration saying 'manufacturable: false'. What is
    unspecified is said only where something is.
    """
    sets = []
    for entry in summary.get("sets") or []:
        if not isinstance(entry, dict):
            continue
        row = {}
        display_only = []
        for kind in KINDS:
            reference = entry.get(kind)
            if reference is None:
                continue
            row[kind] = reference
            declaration = (
                None if rgba_of_reference(reference) else lookup(ctx, kind, reference, relative_to, quiet=True)
            )
            if rgba_of_reference(reference) is not None or (declaration is not None and not declaration.manufacturable):
                display_only.append(kind)
        if display_only:
            row["displayOnly"] = display_only
        for key in ("display", "roughness", "metallic", "origin", "faces", "solids"):
            if key in entry:
                row[key] = entry[key]
        sets.append(row)
    result = {"sets": sets}
    if summary.get("unspecified"):
        result["unspecified"] = dict(summary["unspecified"])
    return result


def summary_of(shape):
    """The CMF summary recorded with an object's geometry (see 'apply_declared'), or None."""
    from . import shape_envelope

    metadata = getattr(shape, "_metadata", None)
    return metadata.get(shape_envelope.METADATA_CMF) if isinstance(metadata, dict) else None


def assembly_cmf_setters(assembly) -> list:
    """How an assembly sets CMF itself, in words: [] when it does not.

    Its own CMF parameters, a link's CMF 'params:', and a 'properties: color:'
    on it - each a finer-grained way of drawing what it holds, which costs it its
    manufacturability unless it is bought whole (docs/design/cmf.md, section 8).
    """
    setters = ["its own '%s'" % kind for kind in own_parameters(assembly)]
    properties = assembly.config.get("properties") if isinstance(assembly.config, dict) else None
    if isinstance(properties, dict) and properties.get("color"):
        setters.append("its 'properties: color:'")
    children = assembly.connected_children() if hasattr(assembly, "connected_children") else assembly.children
    for child in children:
        for kind in getattr(child, "cmf_parameters", None) or ():
            setters.append("the link '%s' sets '%s'" % (child.name, kind))
    return setters


# --------------------------------------------------------------------------- #
# What the IDE shows                                                          #
# --------------------------------------------------------------------------- #

# What 'declaration_data' says in fields of its own, and so leaves out of the
# rest of what 'pc info' says of a declaration ('facts').
_SAID_APART = ("Path", "Name", "Kind", "Alias of", "Desc", "Display", "Manufacturable", "Ids", "Aliases", "Url")


def own_info(ctx, shape) -> typing.Optional[dict]:
    """An object's own CMF as 'info_of' says it, building nothing; None where it states none.

    What a line of the bill of materials and of the Build vs Buy table shows in
    its Color, Material and Finish columns (docs/design/cmf.md, section 9). The
    summary recorded with the object's geometry where it has been built - in
    this process, or read back from the cache with its geometry - and otherwise
    the colour, material and finish it declares itself, which is what its
    parameters say before its source has been read; that answer carries
    'declared: true', because what a STEP file or a script states is not known
    until it is read. A column is not worth building a part for: the views that
    show one are asked on every show of an object, and the 3D view beside them
    is what builds it.
    """
    if ctx is None:
        ctx = getattr(getattr(shape, "project", None), "ctx", None)
    relative_to = getattr(shape, "project_name", "")
    summary = summary_of(shape)
    if isinstance(summary, dict):
        return info_of(ctx, summary, relative_to)
    declared, _drops = declared_set(ctx, shape, quiet=True)
    if declared is None:
        return None
    result = info_of(ctx, {"sets": [declared.as_dict()]}, relative_to)
    result["declared"] = True
    return result


def declaration_data(ctx, declaration) -> dict:
    """A colour, a material or a finish as the IDE's CMF tab shows it.

    What it is called and where ('reference', canonical: an alias is the
    declaration it names), what it is drawn in ('display', '#RRGGBB[AA]': a
    colour's display, a material's own look or the colour it claims; a finish's
    'roughness' and 'metallic' instead), whether it is a claim that it can be
    had or only a picture ('manufacturable'), what other systems call it, and
    the rest of what 'pc info' says of it ('facts': a material's density, its
    full name). An alias is shown as itself - its name, what it names - with
    the facts of the declaration it resolves to, which are the ones it has.
    """
    shown = declaration
    if declaration.is_alias:
        shown = lookup(ctx, declaration.kind, declaration.reference(), declaration.project_name, quiet=True)
    data = {
        "name": declaration.name,
        "kind": declaration.kind,
        "package": declaration.project_name,
        "reference": (shown or declaration).reference(),
        "manufacturable": (shown or declaration).manufacturable,
    }
    if declaration.is_alias:
        data["aliasOf"] = declaration.source
        if shown is None:
            data["errors"] = ["it is an alias of %s, which resolves to nothing" % declaration.source]
            return data
    desc = declaration.desc or shown.desc
    if desc:
        data["desc"] = desc
    if shown.url:
        data["url"] = shown.url
    if shown.ids:
        data["ids"] = dict(sorted(shown.ids.items()))
    if declaration.aliases or shown.aliases:
        data["aliases"] = list(dict.fromkeys(declaration.aliases + shown.aliases))
    if shown.config.get("parameters"):
        # Named without values, which is its defaults (see 'Project.get_cmf').
        data["parametric"] = sorted(shown.config["parameters"])
    rgba = display(ctx, shown)
    if rgba is not None:
        data["display"] = css_color.to_hex(rgba)
    if shown.display_text is not None:
        data["displayText"] = shown.display_text
    claim = getattr(shown, "color_claim", None)
    if claim:
        data["colorClaim"] = canonical(ctx, "color", claim, shown.project_name)
    for hint in ("roughness", "metallic"):
        value = getattr(shown, hint, None)
        if value is not None:
            data[hint] = value
    info = shown.info()
    facts = {key: value for key, value in info.items() if key not in _SAID_APART + ("Color", "Errors")}
    if facts:
        data["facts"] = facts
    errors = list(declaration.errors) + [error for error in shown.errors if error not in declaration.errors]
    if errors:
        data["errors"] = errors
    return data


async def report_async(ctx, shape) -> dict:
    """What the IDE's CMF tab shows of a part, an assembly or a scene (docs/design/cmf.md, section 9).

    'items' is a row per item: the part itself; or, for an assembly, every
    part it holds and every sub-assembly in it that is bought whole - the
    items the 'cmf' check judges, once each, with how many there are - each
    with its CMF as 'info_of' says it ('cmf') and what keeps it from being
    specified ('findings', in the check's own words). The incomplete ones come
    first, in the order they are met; the rest after them, in that order too.
    'own' is what an assembly sets itself, which draws what it holds rather
    than specifying it.

    Builds what it reports on, the way 'pc test' does: what a part's source
    states is only known once it has been read. The 3D view beside the tab has
    built all of it by the time anybody opens the tab, so it is read back from
    the cache.
    """
    import asyncio

    from .assembly import Assembly
    from .test import cmf as cmf_check

    if not isinstance(shape, Assembly):
        return {"items": [await _item_async(ctx, shape, 1)]}
    counted = {}
    await _collect_async(ctx, shape, counted)
    items = await asyncio.gather(*[_item_async(ctx, item, count) for item, count in counted.values()])
    await shape.do_instantiate()
    return {
        "own": {"cmf": own_info(ctx, shape), "findings": cmf_check.assembly_findings(ctx, shape)},
        # Stable: each half keeps the order its items were met in.
        "items": sorted(items, key=lambda row: 0 if row.get("error") or row["findings"] else 1),
    }


async def _collect_async(ctx, assembly, counted: dict) -> None:
    """Count into 'counted' ('{name: [item, count]}') every item 'assembly' holds that the 'cmf' check judges.

    A part is one; so is a sub-assembly bought whole, which the check judges by
    its own CMF without looking inside (docs/design/cmf.md, section 8). Every
    other sub-assembly - one nested in its parent's file included - is looked
    through.
    """
    from .assembly import Assembly
    from .assembly_guide import resolve_alias

    target = resolve_alias(ctx, assembly)
    await target.do_instantiate()
    for child in target.children:
        item = child.item
        if isinstance(item, Assembly) and not item.is_declared_purchasable():
            await _collect_async(ctx, item, counted)
            continue
        entry = counted.setdefault("%s:%s" % (item.project_name, item.name), [item, 0])
        entry[1] += 1


async def _item_async(ctx, shape, count: int) -> dict:
    """One row of 'report_async': an item, how many of it, its CMF, and what the 'cmf' check finds of it."""
    from .assembly import Assembly
    from .test import cmf as cmf_check

    assembly = isinstance(shape, Assembly)
    row = {"name": "%s:%s" % (shape.project_name, shape.name), "kind": "assembly" if assembly else "part"}
    row["count"] = count
    if getattr(shape, "desc", None):
        row["desc"] = shape.desc
    try:
        if assembly:
            await shape.do_instantiate()
            findings = cmf_check.assembly_findings(ctx, shape)
        elif await shape.get_wrapped(ctx) is None:
            row.update({"cmf": None, "findings": [], "error": "it did not build"})
            return row
        else:
            findings = cmf_check.part_findings(ctx, shape)
        row["cmf"] = own_info(ctx, shape)
    except Exception as e:  # pylint: disable=broad-except
        # One item that cannot say costs its own row, not the tab.
        row.update({"cmf": None, "findings": [], "error": str(e) or type(e).__name__})
        return row
    exempt = cmf_check.CmfTest().inapplicable(shape)
    if exempt is not None:
        # Said rather than left out: a part that is bought still has a colour
        # somebody looks at, it is just not this check's to require one.
        row["exempt"] = exempt
        findings = []
    row["findings"] = findings
    return row
