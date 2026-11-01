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
        """What other systems call this, as '{system: identifier}', every identifier a string."""
        ids = self.config.get("ids")
        if not isinstance(ids, dict):
            return {}
        return {str(system): str(identifier) for system, identifier in ids.items() if identifier is not None}

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
            info["Ids"] = ", ".join("%s: %s" % item for item in sorted(self.ids.items()))
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
