#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the Digital Thread draws of a part, and its CAM tab: what the part's machine makes.

Two questions about one object, answered here so that the daemon, the CLI and
anything else showing a part ask them the same way.

**What the 3D view draws** ('representation'). The view has an "Extra details"
box. Cleared, it draws what it always drew: every part that names a 'visual:'
as that visual, and a print or a molding as its design (see 'partcad.visual'),
at the preview's level of detail ('shape_gltf.DETAIL_LOW'). Ticked, it draws the
object as it is - no part in it drawn as anything else - at the finer level
('shape_gltf.DETAIL_HIGH'). A part or a sketch is looked at closely, and starts
out ticked; an assembly, a scene, an interface starts out cleared
('default_extra_details').

A part made by following a route - 'additive', 'subtractive' or 'forming'
('MADE_METHODS') - is drawn, with the box ticked, as what its machine makes:
its own geometry, so "as it is" is that, with the faces nothing can see left out
(see 'shape_visible'). A print is the one exception to the level of detail: the
deposit of its route is planar beads, every face of them flat, which a finer
tessellation makes no finer and only slower, so it is drawn at the preview's
level whichever way the box is. What a router leaves of its stock or a mold
gives back of its cavity has curved faces like any part - a drilled hole, a
molded knob - and follows the box.

**The CAM tab** ('settings', 'product_async', 'save_settings'). For such a part
the Digital Thread has a tab of its own: what the machine makes, drawn finely,
beside every setting of the machine the part names - what its schema says that
machine takes ('partcad_utils/schema/partcad.json': 'additive-fff',
'forming-mold', 'subtractive-cnc' and its siblings) - which can be changed, the
product made again with them, and saved into the part's declaration. Made
again by 'Shape.materialize_async', asked as if the part declared the changed
settings itself, which is also how a setting nobody can pass to a route as a
job parameter - the axis a print is laid down along, a nozzle - is tried out.
"""

import collections
import copy
import json
import os
import threading
import typing

from . import logging as pc_logging
from . import shape_envelope, shape_gltf
from .part_config_manufacturing import (
    FORMERS,
    IMPLIED_TYPE_KEY,
    MATERIALIZED_METHODS,
    PRINT_DEFAULTS,
    PRINTERS,
    PartConfigManufacturing,
)

# The methods whose part is what a machine makes by following a route, and so
# have a CAM tab.
MADE_METHODS = MATERIALIZED_METHODS

# The one of them whose product is drawn at the preview's level whatever the
# "Extra details" box says: a print, every face of which is flat. As
# 'method_of' answers, spelled as the declaration spells it.
PRINTED = "additive"

# The kinds of object the "Extra details" box starts out ticked for.
DETAILED_KINDS = ("part", "sketch")

# The schema definition each machine's controls are read from.
_SCHEMA_DEFINITIONS = {
    "fff": "additive-fff",
    "mold": "forming-mold",
    "cnc": "subtractive-cnc",
    "laser": "subtractive-laser",
    "drill": "subtractive-drill",
    "cut": "subtractive-cut",
}

# What a machine's subsection may hold that is not one of its settings: who
# writes the route, a description, the second spelling of the axis, and a saw's
# list of cuts, which is a list rather than a setting.
_NOT_SETTINGS = ("implementation", "desc", "along", "cuts")

# The axes a machine's axis is chosen from, in the order a menu offers them.
_AXES = ("-Z", "+Z", "-Y", "+Y", "-X", "+X")


def default_extra_details(kind) -> bool:
    """What the "Extra details" box starts out as for an object of 'kind'."""
    return kind in DETAILED_KINDS


def method_of(shape) -> typing.Optional[str]:
    """The manufacturing method a part names ('additive', ...), or None for anything else."""
    if getattr(shape, "kind", None) != "part":
        return None
    try:
        config = shape.get_final_config()
    except Exception:  # pylint: disable=broad-except
        config = getattr(shape, "config", None)
    section = config.get("manufacturing") if isinstance(config, dict) else None
    method = section.get("method") if isinstance(section, dict) else None
    return method if isinstance(method, str) else None


def made_by_machine(shape) -> bool:
    """Whether a shape is a part made by following a route, and so has a CAM tab."""
    return method_of(shape) in MADE_METHODS


class Representation(typing.NamedTuple):
    """How the Digital Thread draws an object."""

    # What the "Extra details" box says: the object as it is, finely.
    extra_details: bool
    # Whether parts are drawn as their visuals (see 'partcad.visual').
    visuals: bool
    # The level of detail it is tessellated at ('shape_gltf.DETAILS').
    detail: str
    # Whether the faces of a print nothing can see are left out ('shape_visible').
    stripped: bool


def representation(shape, extra_details=None, detail=None, cam=False) -> Representation:
    """How 'shape' is drawn with the "Extra details" box as 'extra_details' (None: as it starts out).

    'detail' outranks the level the box would choose, for a caller that knows.
    'cam' is the CAM tab's drawing: what the machine makes, finely, its hidden
    faces left out.
    """
    kind = getattr(shape, "kind", None)
    if extra_details is None:
        extra_details = default_extra_details(kind)
    extra_details = bool(extra_details)
    printed = method_of(shape) == PRINTED
    if cam:
        chosen = shape_gltf.DETAIL_HIGH
    elif printed:
        # A print is flat faces, which no level draws any finer: see the module.
        chosen = shape_gltf.DETAIL_LOW
    else:
        chosen = shape_gltf.DETAIL_HIGH if extra_details else shape_gltf.DETAIL_LOW
    return Representation(
        extra_details=extra_details,
        visuals=not extra_details and not cam,
        detail=shape_gltf.detail_of(detail if detail is not None else chosen),
        # Only a print is a deposit of prisms, most of them out of sight: a cut
        # part or a molding is a solid like any other, its faces each its own.
        stripped=printed and (extra_details or cam),
    )


#
# The settings
#


def _schema_definition(machine: str) -> dict:
    from partcad_utils import assy_lint

    definitions = assy_lint.get_schema(assy_lint.PARTCAD_SCHEMA).get("definitions") or {}
    return definitions.get(_SCHEMA_DEFINITIONS.get(machine, ""), {})


def _resolved(schema: dict) -> tuple:
    """A property's schema with its '$ref' followed one step: (schema, the definition's name or None)."""
    reference = schema.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/definitions/"):
        return schema, None
    from partcad_utils import assy_lint

    name = reference[len("#/definitions/") :]
    definitions = assy_lint.get_schema(assy_lint.PARTCAD_SCHEMA).get("definitions") or {}
    merged = dict(definitions.get(name) or {})
    merged.update({key: value for key, value in schema.items() if key != "$ref"})
    return merged, name


def _control(key: str, schema: dict) -> dict:
    """How one setting is edited, from its schema: what kind of value it is, its choices and limits, and what it is."""
    resolved, definition = _resolved(schema)
    control = {"key": key, "description": resolved.get("description") or ""}
    if definition == "machine-axis":
        control["type"] = "axis"
        control["choices"] = list(_AXES)
    elif definition == "cam-length":
        control["type"] = "length"
    elif definition == "cam-feed":
        control["type"] = "feed"
    elif resolved.get("type") == "integer":
        control["type"] = "count"
        if "minimum" in resolved:
            control["minimum"] = resolved["minimum"]
    elif resolved.get("type") == "string" and isinstance(resolved.get("enum"), list):
        control["type"] = "choice"
        control["choices"] = list(resolved["enum"])
    elif isinstance(resolved.get("oneOf"), list) and any(
        isinstance(option, dict) and option.get("pattern", "").find("%") >= 0 for option in resolved["oneOf"]
    ):
        # A share: '20%', or 0.2.
        control["type"] = "fraction"
    elif resolved.get("type") == "number":
        control["type"] = "number"
        for limit in ("minimum", "maximum"):
            if limit in resolved:
                control[limit] = resolved[limit]
    else:
        control["type"] = "text"
    return control


def machine_controls(machine: str) -> list:
    """Every setting a machine takes, as its schema states it, in the order it states them: what the CAM tab offers."""
    properties = _schema_definition(machine).get("properties") or {}
    return [_control(key, schema) for key, schema in properties.items() if key not in _NOT_SETTINGS]


def _plain(value):
    """A declared value as JSON carries it: a number or a string as written, anything else as text."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def settings(ctx, part) -> dict:
    """What the CAM tab shows of a part: what it is made by and after, and every setting of its machine.

    '{object, method, machine, machines, declared, design, instructions,
    description, controls, materialized, refused}' - 'controls' one per setting
    the machine takes, each with what the part states ('value', as written),
    what is taken where it states nothing ('default', for a printer), and how it
    is edited ('type', 'choices', 'description'). 'refused' says why there is
    no tab, for a part that is not made by following a route; the rest is
    absent then.
    """
    name = "%s:%s" % (part.project_name, part.name)
    method = method_of(part)
    answer = {"object": name, "method": method, "description": (part.config or {}).get("desc") or ""}
    if method not in MADE_METHODS:
        answer["refused"] = (
            "%s says no manufacturing method a machine follows a route for: only an 'additive', a 'subtractive'"
            " or a 'forming' part has one" % name
            if method is None
            else "%s is made by '%s', which no machine follows a route for" % (name, method)
        )
        return answer
    config = part.get_final_config()
    data = PartConfigManufacturing(config)
    choices = data.machine_choices()
    chosen = data.machine
    kind = chosen.kind if chosen is not None else (choices[0] if choices else None)
    if kind is None:
        kind = PRINTERS[0] if method == "additive" else FORMERS[0] if method == "forming" else "cnc"
    section = config.get("manufacturing") or {}
    stated = section.get(kind) if isinstance(section.get(kind), dict) else {}
    defaults = PRINT_DEFAULTS.get(kind, {})
    controls = []
    for control in machine_controls(kind):
        key = control["key"]
        control["value"] = _plain(stated.get(key))
        if key == "toolAxis" and control["value"] is None:
            control["value"] = _plain(stated.get("along"))
        control["default"] = _plain(defaults.get(key, "-Z" if key == "toolAxis" else None))
        controls.append(control)
    answer.update(
        {
            "machine": kind,
            "machines": choices or [kind],
            "declared": bool(chosen is not None and chosen.declared),
            "design": data.source,
            "instructions": data.instructions,
            "error": data.machine_error,
            "controls": controls,
            "materialized": _materialized(ctx, part),
        }
    )
    return answer


def _materialized(ctx, part) -> typing.Optional[dict]:
    """Where a part whose geometry is what its machine makes keeps it: '{path, exists}', or None for a part that has a file of its own."""
    if not (part.config or {}).get(IMPLIED_TYPE_KEY):
        return None
    from .part_factory_manufactured import materialized_path

    project = ctx.get_project(part.project_name)
    if project is None:
        return None
    path = materialized_path(project, part.config)
    return {"path": os.path.relpath(path, project.config_dir), "exists": os.path.isfile(path)}


def _machine_of(part, machine=None) -> str:
    """The machine a part's settings are those of: the one asked for, else the one it names, else its method's usual one."""
    if machine:
        return str(machine)
    data = PartConfigManufacturing(part.get_final_config())
    if data.machine is not None:
        return data.machine.kind
    method = method_of(part)
    return PRINTERS[0] if method == "additive" else FORMERS[0] if method == "forming" else "cnc"


def with_settings(config: dict, machine: str, values: dict) -> dict:
    """A copy of a part's declaration with 'values' written into its 'manufacturing: <machine>:' section.

    A value of None takes that setting out, back to whatever is taken where the
    part states nothing. An axis written under one spelling takes the other one
    out, since a section that says both is refused.
    """
    config = copy.deepcopy(config)
    section = config.get("manufacturing")
    section = dict(section) if isinstance(section, dict) else {}
    machine_section = section.get(machine)
    machine_section = dict(machine_section) if isinstance(machine_section, dict) else {}
    for key, value in (values or {}).items():
        if value is None or value == "":
            machine_section.pop(key, None)
            continue
        machine_section[key] = value
        if key == "toolAxis":
            machine_section.pop("along", None)
        elif key == "along":
            machine_section.pop("toolAxis", None)
    section[machine] = machine_section
    config["manufacturing"] = section
    return config


def _tried(part, machine: str, values: dict):
    """'part' as if it declared 'values' for 'machine': a copy, which nothing but the caller sees.

    Shallow, sharing everything with the part but its declaration - which is
    all that says how it is made ('PartConfiguration.get_manufacturing_data'
    reads it afresh) - so that the design it is made after, its package and its
    cache are the part's own.
    """
    tried = copy.copy(part)
    tried.config = with_settings(part.config, machine, values)
    return tried


# What the CAM tab asked for last, kept: a section moved, the box ticked, the tab
# opened again ask for the same product, which is a route run in a sandbox. Keyed
# by the part's key and the settings tried, a handful at a time.
_PRODUCTS: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
_PRODUCTS_KEPT = 8
_products_lock = threading.Lock()


def _remembered(key, made=None):
    with _products_lock:
        if made is None:
            found = _PRODUCTS.get(key)
            if found is not None:
                _PRODUCTS.move_to_end(key)
            return found
        _PRODUCTS[key] = made
        while len(_PRODUCTS) > _PRODUCTS_KEPT:
            _PRODUCTS.popitem(last=False)
        return made


def forget_products() -> None:
    """Let go of every product kept: what a part makes may have changed (a declaration saved)."""
    with _products_lock:
        _PRODUCTS.clear()


async def product_async(ctx, part, machine=None, values=None) -> dict:
    """What a part's machine makes with 'values' tried in place of what it states: 'Shape.materialize_async' answered.

    'values' are settings of 'machine' (the part's own, where None) by key, as a
    person would write them ('20%', '0.2 mm', 3), and None for one taken out.
    Nothing is written. The answer is kept for the next time the same is asked
    (see '_PRODUCTS').

    Raises:
        partcad.cam.CamConfigError: the part is not made by following anything,
            or a value tried is not one its machine takes - said in the words
            'pc qual test' would say it in.
    """
    from . import cam as pc_cam

    kind = _machine_of(part, machine)
    values = {key: value for key, value in (values or {}).items()}
    subject = part
    if values:
        subject = _tried(part, kind, values)
        problem = PartConfigManufacturing(subject.get_final_config()).machine_error
        if problem:
            raise pc_cam.CamConfigError("%s:%s: %s" % (part.project_name, part.name, problem))
    key = None
    try:
        if part.get_cacheable():
            key = json.dumps(
                [await part.get_cache_key_async(), kind, values, part.config.get("manufacturing")],
                sort_keys=True,
                default=str,
            )
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("%s:%s: what its machine makes is not kept: %s" % (part.project_name, part.name, e))
    if key is not None:
        found = _remembered(key)
        if found is not None:
            return found
    made = await subject.materialize_async(ctx, machine=kind if machine or values else None)
    if made.get("product") is None:
        raise pc_cam.CamFailed("%s:%s: the 'pc cam' implementation made nothing" % (part.project_name, part.name))
    if key is not None:
        _remembered(key, made)
    return made


def product_tree(ctx, part, made: dict) -> dict:
    """The product 'product_async' made, as the tree of the part that is drawn: its name, and what it is drawn in."""
    from . import cmf as pc_cmf

    node = dict(made["product"])
    node["name"] = "%s:%s" % (part.project_name, part.name)
    node.setdefault("label", part.name)
    node[shape_envelope.KEY_KIND] = "part"
    try:
        applied, after = pc_cmf.apply_declared(ctx, part, node, node.get(shape_envelope.KEY_METADATA))
        if applied is not node:
            node = dict(applied)
            if after:
                node[shape_envelope.KEY_METADATA] = after
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("%s:%s: its product is drawn without its CMF: %s" % (part.project_name, part.name, e))
    properties = part._shape_properties()  # pylint: disable=protected-access
    if properties:
        node[shape_envelope.KEY_PROPERTIES] = {**properties, **(node.get(shape_envelope.KEY_PROPERTIES) or {})}
    return node


def written_value(value):
    """A setting as it is written into 'partcad.yaml': a number where the text is one, the text as typed otherwise."""
    if isinstance(value, str):
        text = value.strip()
        try:
            number = float(text)
        except ValueError:
            return text
        return int(number) if number.is_integer() and "." not in text and "e" not in text.lower() else number
    return value


def save_settings(ctx, part, machine=None, values=None) -> str:
    """Write settings into a part's declaration: the 'partcad.yaml' written, which the caller reloads.

    'values' as 'product_async' takes them, written into the part's own
    'manufacturing: <machine>:' section of its package's 'partcad.yaml' - a
    number where the text is one, the text as typed otherwise, and a None taking
    the setting out - with the rest of the file kept as its author wrote it
    ('Project.set_machine_settings'). Nothing is written where the values are
    not ones the machine takes.

    Raises:
        partcad.cam.CamConfigError: the values are not ones the machine takes.
        ValueError: the part is not declared in its package's own file.
    """
    from . import cam as pc_cam
    from .utils import parse_parameterized_name

    kind = _machine_of(part, machine)
    written = {key: (None if value in (None, "") else written_value(value)) for key, value in (values or {}).items()}
    problem = PartConfigManufacturing(with_settings(part.get_final_config(), kind, written)).machine_error
    if problem:
        raise pc_cam.CamConfigError("%s:%s: %s" % (part.project_name, part.name, problem))
    project = ctx.get_project(part.project_name)
    base, _ = parse_parameterized_name(part.config.get("orig_name") or part.name)
    project.set_machine_settings(base, kind, written)
    forget_products()
    return project.config_path


async def rematerialize_async(ctx, part, machine=None) -> typing.Optional[dict]:
    """Make a part's product again and write it over its materialized file, where it has one; None where it has none.

    For after its settings were saved ('save_settings'), with 'part' as its
    package now reads: so that the declaration and the file the part is read from
    cannot come to disagree. '{written, stats}'.
    """
    materialized = _materialized(ctx, part)
    if materialized is None or not materialized["exists"]:
        return None
    made = await part.materialize_async(ctx, machine=machine or None, write=True)
    return {"written": made.get("written"), "stats": made.get("stats") or {}}
