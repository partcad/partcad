#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Adding a requirement to an object's declaration, and taking one out: 'pc req add', 'pc req remove'.

'partcad.requirements' says what a ``requirements:`` section means; this is how
one is changed without changing anything else it means. Each requirement is
addressed the way 'pc qual test' reports it, by kind and name:

    feature     'features: <name>: <sentence>'
    port        'ports: <name>: <location, sketch>'
    interface   'interfaces: <interface>: ...', or one instance of it
    physics     'physics: <field>', or 'physics: inertia: ixx' as 'inertia.ixx'
    match       'match: <object>: <amount>: <percent>', one amount or all of them
    has         'has_<name>: true|false'

What is written is a value as the section holds it -- the same YAML a person
writes by hand, so it is quoted where YAML needs it ('>0') and read back by the
same 'requirements.parse'. That is also the one rule an edit is held to: a
section that reads with a problem it did not have before the edit, or that the
schema refuses where it did not before, is not written. There is no second
validator here to disagree with the reader.

Adding refuses what is there already, unless 'replace' says to: a requirement
quietly loosened is a different product. Taking a feature out refuses while a
'qual: sim:' entry or an analysis scenario still names it, unless 'references'
says to take those names out as well -- a dangling 'feature:' is a failure the
next 'pc qual test' reports.

The functions work on the object's own declaration as a mapping (a 'ruamel'
one, when 'Project.edit_object_declaration' hands it over, so the rest of the
file stays as it was written), and change it in place.
"""

from __future__ import annotations

import copy
import typing

from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import SingleQuotedScalarString

from partcad_utils import config_yaml

from . import cae
from . import requirements as req
from .qual import config as qual_config
from .simulation import FEATURE as SIM_FEATURE
from .simulation import declared_features

# The kinds of requirement, as 'pc req add <kind>' names them, and the section of
# 'requirements:' each lives in ('has' is a key of the section itself).
KINDS = {
    "feature": req.FEATURES,
    "port": req.PORTS,
    "interface": req.INTERFACES,
    "physics": req.PHYSICS,
    "match": req.MATCH,
    "has": req.HAS,
}

# The keys of an object's declaration an edit here may change: the section, and
# what names a feature ('feature:' of a simulation or an analysis scenario).
TOUCHED = (req.SECTION, qual_config.SECTION) + tuple(cae.ANALYSES)

# The keys of a location requirement, and of a port's beside it.
LOCATION_KEYS = ("position", "direction", "angle")
PORT_KEYS = LOCATION_KEYS + ("sketch",)

# The amounts a 'match:' requirement holds an object to, by every key each may be written with.
AMOUNTS = {"volume": ("volume",), "displacement": ("displacement",), "mass": ("mass", "weight")}


class EditError(ValueError):
    """A change that is not made, and why: said to whoever asked for it, nothing written."""


def has_names() -> list:
    """The yes-or-no requirements, as 'pc req add has' names them: 'color', ..., 'private_dependencies'."""
    return [key[len("has_") :] for key in req.HAS_KEYS if key not in req._HAS_NAMES]


def has_key(name: str) -> str:
    """The key a yes-or-no requirement is written with, from any of its spellings: 'material', 'has-material'."""
    text = str(name or "").strip().lower().replace("-", "_")
    if not text.startswith("has_"):
        text = "has_" + text
    if text not in req.HAS_KEYS:
        raise EditError("'%s' is not a yes-or-no requirement: it is one of %s" % (name, ", ".join(has_names())))
    return req._HAS_NAMES.get(text, text)


def physics_fields() -> dict:
    """{field: 'value' | 'vector' | [members]} a physics requirement may name (read off the schema)."""
    return req._physics_fields()


# --- the section ---------------------------------------------------------------


def _mapping(like=None):
    return CommentedMap() if like is None or isinstance(like, CommentedMap) else {}


def structured(section, like=None):
    """'section' as a mapping: the free-form shapes it had before it had structure are its features.

    A paragraph is the feature 'general', a list one feature per item numbered
    from 1 -- read exactly as 'requirements.parse' reads them, so nothing changes
    meaning by being rewritten. A mapping is returned as it is.
    """
    if isinstance(section, dict):
        return section
    result = _mapping(like)
    if section is None:
        return result
    features = _mapping(like)
    declaration = req.parse(section)
    for name, desc in (declaration.features if declaration is not None else {}).items():
        features[_text(name)] = _text(desc)
    if features:
        result[req.FEATURES] = features
    return result


def _plain(value):
    """'value' as plain data: what the schema and a JSON answer are handed.

    A scalar YAML reads as something JSON has no type for -- '2026-03-01' is a
    date -- is the text it was written as, which is also what the schema
    makes of it.
    """
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def _holds_mapping(value) -> bool:
    if isinstance(value, dict):
        return True
    return isinstance(value, (list, tuple)) and any(_holds_mapping(item) for item in value)


# What opens a Jinja2 expression, statement or comment: 'partcad.yaml' is rendered
# as a template before it is read as YAML.
TEMPLATE_OPENINGS = ("{{", "{%", "{#")


def refuse_template_text(value) -> None:
    """Refuse a string that 'partcad.yaml' would render rather than read: one holding '{{', '{%' or '{#'.

    The file is a Jinja2 template, so such text written into it is not what is
    read back -- and an unclosed '{%' fails the whole package -- and a file that
    holds one is a template no edit here writes into again. Written by hand, it
    is written knowing that.
    """
    if isinstance(value, str) and any(opening in value for opening in TEMPLATE_OPENINGS):
        raise EditError(
            "'%s' holds '{{', '{%%' or '{#', which 'partcad.yaml' would render as a Jinja2 template rather than"
            " read: write it by hand" % value
        )


def _text(value):
    """A string as it is written: in quotes where PartCAD would read the same text, unquoted, as something else.

    The file is written by 'ruamel', which writes YAML 1.2 and quotes a string
    only where YAML 1.2 would read it as something else; PartCAD reads it as
    YAML 1.1 ('config_yaml.load'), which reads more words as other things. So a
    feature called 'off' would be written 'off:' and read back as the key
    False, and a sentence 'yes' as True. What decides is the reader that reads
    the file next, so it is asked. Anything but a plain string -- a number, a
    boolean, a string 'ruamel' read with quotes of its own -- is left as it is.
    """
    if type(value) is not str:  # noqa: E721 - a subclass of str carries a style of its own
        return value
    refuse_template_text(value)
    try:
        read = config_yaml.load(value)
    except Exception:  # pylint: disable=broad-except
        read = None
    if isinstance(read, str) and read == value:
        return value
    return SingleQuotedScalarString(value)


def _written(value):
    """'value' as it is put into the file: a list of scalars on one line, as a location is written by hand."""
    if isinstance(value, dict):
        mapping = CommentedMap()
        for key, item in value.items():
            mapping[_text(key)] = _written(item)
        return mapping
    if isinstance(value, (list, tuple)):
        sequence = CommentedSeq([_written(item) for item in value])
        if not _holds_mapping(value):
            # On one line, as a location is written by hand: '[[0, 0, 0], [0, 0, 1], 90]'.
            sequence.fa.set_flow_style()
        return sequence
    return _text(value)


def _schema_errors(section) -> list:
    """What the schema says of 'section' as a 'requirements:' section: [message], each with where."""
    import jsonschema

    from partcad_utils import assy_lint

    schema = assy_lint.get_schema(assy_lint.PARTCAD_SCHEMA)
    definitions = schema["definitions"]
    validator_class = jsonschema.validators.validator_for(schema)
    data = _plain(section)
    target = {"$ref": "#/definitions/requirements"}
    if isinstance(data, dict):
        # Against the mapping's own branch of the section's 'oneOf', which
        # reports each entry that is wrong; the 'oneOf' itself would report one
        # of them, and an edit would be compared against whichever that was.
        for branch in definitions["requirements"].get("oneOf", []):
            if branch.get("type") == "object":
                target = branch
    validator = validator_class({**target, "definitions": definitions})
    messages = []
    for error in validator.iter_errors(data):
        error = assy_lint._most_specific(error)
        where = ".".join(str(part) for part in error.absolute_path)
        messages.append(("%s: %s" % (where, assy_lint._describe(error))) if where else assy_lint._describe(error))
    return messages


def _problems(section) -> list:
    declaration = req.parse(_plain(section))
    if declaration is None:
        return []
    return ["%s: %s" % (problem.name, problem.detail) for problem in declaration.problems]


def _check(before, after) -> None:
    """Refuse an edit that leaves the section reading worse than it did: a problem, or a schema error, it lacked."""
    new = [problem for problem in _problems(after) if problem not in _problems(before)]
    if after is not None:
        new += [error for error in _schema_errors(after) if before is None or error not in _schema_errors(before)]
    if new:
        raise EditError("Nothing was written, because the requirements would not read: %s" % "; ".join(new))


def _store(declaration: dict, section) -> None:
    """Put 'section' back as the object's requirements, or take the key out when nothing is left in it."""
    for key in list(section.keys()) if isinstance(section, dict) else []:
        value = section[key]
        if isinstance(value, dict) and not value and key in KINDS.values():
            del section[key]
    if isinstance(section, dict) and not section:
        declaration.pop(req.SECTION, None)
    else:
        declaration[req.SECTION] = section


def _section_of(declaration: dict):
    """The object's requirements as a mapping, and what they were before (for '_check')."""
    if not isinstance(declaration, dict):
        raise EditError("The object's declaration is not a mapping, so there is nowhere to write its requirements")
    raw = declaration.get(req.SECTION)
    before = copy.deepcopy(_plain(raw)) if raw is not None else None
    return structured(raw, declaration), before


def _sub(section, key: str, like):
    """The mapping 'section[key]', made when it is missing; refused when it is something else."""
    value = section.get(key)
    if value is None:
        value = _mapping(like)
        section[key] = value
    if not isinstance(value, dict):
        raise EditError("'%s: %s' is not a mapping: rewrite it by hand first" % (req.SECTION, key))
    return value


def _exists(what: str) -> EditError:
    return EditError("%s is required already: say '--replace' to replace it" % what)


# --- adding --------------------------------------------------------------------


def add(declaration: dict, kind: str, name: str, value=None, instances=None, replace: bool = False) -> str:
    """Write one requirement into 'declaration' (the object's own), and say what was written.

    'value' is what the requirement's place in the section holds, as YAML holds
    it: a feature's sentence, a port's location (or None), an interface's
    requirement -- or, with 'instances', where each of those instances has to be
    -- a physical property's value (three of them for a vector), the percentages
    of a match by amount, a yes-or-no requirement's boolean.
    """
    if kind not in KINDS:
        raise EditError("'%s' is not a kind of requirement: it is one of %s" % (kind, ", ".join(KINDS)))
    if not isinstance(name, str) or not name.strip():
        raise EditError("A requirement needs a name")
    name = name.strip()

    def edit(target: dict) -> str:
        section, before = _section_of(target)
        said = globals()["_add_" + kind](section, target, name, copy.deepcopy(value), instances, replace)
        _check(before, section)
        _store(target, section)
        return said

    return _all_or_nothing(declaration, edit)


def _all_or_nothing(declaration: dict, edit) -> str:
    """Make 'edit' on 'declaration' only once it is known to succeed: tried on a copy first.

    A refused edit has to leave the declaration as it was, and checking is done
    on the edited section, so it is made twice: on a copy, where a refusal costs
    nothing, and then for real. Every edit here is a function of what it is
    applied to, so the second makes exactly what the first did.
    """
    edit(copy.deepcopy(declaration))
    return edit(declaration)


def _add_feature(section, like, name, value, _instances, replace) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EditError("The feature '%s' needs a sentence saying what it is" % name)
    features = _sub(section, req.FEATURES, like)
    # A heading of the free-form shape is a feature by that name too.
    heading = name in section and name not in KINDS.values() and name not in req.HAS_KEYS
    if (name in features or heading) and not replace:
        raise _exists("The feature '%s'" % name)
    if heading:
        del section[name]
    features[_text(name)] = _text(value.strip())
    return "the feature '%s'" % name


def _location(value, keys=LOCATION_KEYS, what="a location"):
    """A location requirement as a mapping of its keys, the ones that are null left out; None when all are."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 3:
        value = dict(zip(LOCATION_KEYS, value))
    if not isinstance(value, dict):
        raise EditError("'%s' is not %s: it is a mapping of %s" % (value, what, ", ".join(keys)))
    unknown = [key for key in value if key not in keys]
    if unknown:
        raise EditError(
            "%s is not a key of %s, which takes %s"
            % (", ".join("'%s'" % key for key in unknown), what, ", ".join(keys))
        )
    kept = {key: value[key] for key in keys if value.get(key) is not None}
    return _written(kept) if kept else None


def _add_port(section, like, name, value, _instances, replace) -> str:
    ports = _sub(section, req.PORTS, like)
    if name in ports and not replace:
        raise _exists("The port '%s'" % name)
    ports[_text(name)] = _location(value, PORT_KEYS, "a port requirement")
    return "the port '%s'" % name


def _instance_map(current, like):
    """An interface requirement as {instance: location}, from whichever shape it was written in."""
    if current is None:
        return _mapping(like)
    if isinstance(current, str):
        mapping = _mapping(like)
        mapping[_text(current)] = None
        return mapping
    if isinstance(current, list) and all(isinstance(item, str) for item in current):
        mapping = _mapping(like)
        for item in current:
            mapping[_text(item)] = None
        return mapping
    if isinstance(current, dict):
        return current
    raise EditError(
        "the interface is required at a location for any one of its instances: replace that requirement to name "
        "instances instead"
    )


def _add_interface(section, like, name, value, instances, replace) -> str:
    interfaces = _sub(section, req.INTERFACES, like)
    if not instances:
        if name in interfaces and not replace:
            raise _exists("The interface '%s'" % name)
        if isinstance(value, (list, tuple)) and len(value) == 3 and not all(isinstance(v, str) for v in value):
            # A location of any instance: written as the list, since a mapping
            # here is one of instance names.
            interfaces[_text(name)] = _written(list(value))
        elif isinstance(value, dict) and set(value) <= set(LOCATION_KEYS):
            located = _location(value)
            interfaces[_text(name)] = None if located is None else _written([located.get(key) for key in LOCATION_KEYS])
        else:
            interfaces[_text(name)] = _written(value)
        return "the interface '%s'" % name
    try:
        mapping = _instance_map(interfaces.get(name), like)
    except EditError as e:
        raise EditError("Not adding an instance of '%s': %s" % (name, e)) from None
    taken = [instance for instance in instances if instance in mapping]
    if taken and not replace:
        raise _exists("The instance%s %s of '%s'" % ("s" if len(taken) > 1 else "", ", ".join(taken), name))
    for instance in instances:
        mapping[_text(instance)] = _location(value)
    interfaces[_text(name)] = mapping
    return "the instance%s %s of the interface '%s'" % (
        "s" if len(instances) > 1 else "",
        ", ".join("'%s'" % instance for instance in instances),
        name,
    )


def _add_physics(section, like, name, value, _instances, replace) -> str:
    field, _, member = name.partition(".")
    fields = physics_fields()
    kind = fields.get(field)
    if kind is None:
        raise EditError("'%s' is not a physical property: it is one of %s" % (field, ", ".join(sorted(fields))))
    if member and not isinstance(kind, list):
        raise EditError("'%s' has no members: it is required as one %s" % (field, kind))
    if member and member not in kind:
        raise EditError("'%s' is not a member of '%s': it is one of %s" % (member, field, ", ".join(kind)))
    if value is None:
        raise EditError("Say what '%s' is required to be: a value, or nothing to require leaves it out" % name)
    physics = _sub(section, req.PHYSICS, like)
    if member:
        members = physics.get(field)
        if members is None:
            members = _mapping(like)
            physics[field] = members
        if not isinstance(members, dict):
            raise EditError("'physics: %s' is not a mapping: rewrite it by hand first" % field)
        if member in members and not replace:
            raise _exists("The physical property '%s'" % name)
        members[member] = _written(value)
    else:
        if field in physics and not replace:
            raise _exists("The physical property '%s'" % name)
        physics[field] = _written(value)
    return "the physical property '%s'" % name


def _amount(key: str) -> str:
    for amount, spellings in AMOUNTS.items():
        if key in spellings:
            return amount
    raise EditError("'%s' is not matched: what is, is %s" % (key, ", ".join(AMOUNTS)))


def _add_match(section, like, name, value, _instances, replace) -> str:
    if not isinstance(value, dict) or not value:
        raise EditError("Say how closely '%s' has to be matched: a percentage of its %s" % (name, ", ".join(AMOUNTS)))
    match = _sub(section, req.MATCH, like)
    limits = match.get(name)
    if limits is None:
        limits = _mapping(like)
        match[_text(name)] = limits
    if not isinstance(limits, dict):
        raise EditError("'match: %s' is not a mapping: rewrite it by hand first" % name)
    asked = {}
    for key, percent in value.items():
        amount = _amount(str(key))
        if amount in asked:
            raise EditError("'%s' and '%s' are both the %s: say it once" % (asked[amount][0], key, amount))
        asked[amount] = (key, percent)
    taken = [amount for amount in asked if any(spelling in limits for spelling in AMOUNTS[amount])]
    if taken and not replace:
        raise _exists("Matching the %s of '%s'" % (" and ".join(taken), name))
    for amount, (_key, percent) in asked.items():
        for spelling in AMOUNTS[amount]:
            limits.pop(spelling, None)
        limits[amount] = _written(percent)
    return "matching the %s of '%s'" % (" and ".join(asked), name)


def _add_has(section, _like, name, value, _instances, replace) -> str:
    key = has_key(name)
    if not isinstance(value, bool):
        raise EditError("'%s' is true or false, not %s" % (key, value))
    spellings = [spelling for spelling in req.HAS_KEYS if req._HAS_NAMES.get(spelling, spelling) == key]
    if any(spelling in section for spelling in spellings) and not replace:
        raise _exists("'%s'" % key)
    for spelling in spellings:
        section.pop(spelling, None)
    section[key] = value
    return "'%s: %s'" % (key, "true" if value else "false")


# --- taking out ----------------------------------------------------------------


def references(declaration: dict, feature: str) -> list:
    """What in 'declaration' names the feature: [(section, entry)] -- a 'qual: sim:' entry or an analysis scenario."""
    found = []
    qual = declaration.get(qual_config.SECTION)
    sims = qual.get(qual_config.SIM) if isinstance(qual, dict) else None
    for name, entry in (sims or {}).items() if isinstance(sims, dict) else []:
        if isinstance(entry, dict) and feature in declared_features(entry.get(SIM_FEATURE)):
            found.append(("%s: %s" % (qual_config.SECTION, qual_config.SIM), name))
    for analysis in cae.ANALYSES:
        scenarios = declaration.get(analysis)
        for name, entry in scenarios.items() if isinstance(scenarios, dict) else []:
            if isinstance(entry, dict) and feature in declared_features(entry.get(cae.FEATURE)):
                found.append((analysis, name))
    return found


def _unname(declaration: dict, feature: str) -> None:
    """Take the feature out of every 'feature:' in 'declaration' that names it, and the key where none is left."""
    holders = []
    qual = declaration.get(qual_config.SECTION)
    sims = qual.get(qual_config.SIM) if isinstance(qual, dict) else None
    if isinstance(sims, dict):
        holders.extend((entry, SIM_FEATURE) for entry in sims.values() if isinstance(entry, dict))
    for analysis in cae.ANALYSES:
        scenarios = declaration.get(analysis)
        if isinstance(scenarios, dict):
            holders.extend((entry, cae.FEATURE) for entry in scenarios.values() if isinstance(entry, dict))
    for entry, key in holders:
        named = entry.get(key)
        if isinstance(named, str) and named == feature:
            del entry[key]
        elif isinstance(named, list) and feature in named:
            kept = [item for item in named if item != feature]
            if not kept:
                del entry[key]
            elif len(kept) == 1:
                entry[key] = _text(kept[0])
            else:
                entry[key] = _written(kept)


def remove(
    declaration: dict,
    kind: str,
    name: str,
    instances=None,
    amounts=None,
    with_references: bool = False,
) -> str:
    """Take one requirement out of 'declaration' (the object's own), and say what was taken out.

    'instances' takes only those instances of an interface out, 'amounts' only
    those amounts of a match. 'with_references' takes a feature out of the
    simulations and analysis scenarios that name it too; without it, a feature
    something names is refused.
    """
    if kind not in KINDS:
        raise EditError("'%s' is not a kind of requirement: it is one of %s" % (kind, ", ".join(KINDS)))
    name = str(name or "").strip()

    def edit(target: dict) -> str:
        section, before = _section_of(target)
        said = globals()["_remove_" + kind](section, target, name, instances, amounts, with_references)
        _check(before, section)
        _store(target, section)
        return said

    return _all_or_nothing(declaration, edit)


def _missing(what: str) -> EditError:
    return EditError("%s is not required, so there is nothing to remove" % what)


def _remove_feature(section, declaration, name, _instances, _amounts, with_references) -> str:
    features = section.get(req.FEATURES)
    heading = name in section and name not in KINDS.values() and name not in req.HAS_KEYS
    if not heading and not (isinstance(features, dict) and name in features):
        raise _missing("The feature '%s'" % name)
    named_by = references(declaration, name)
    if named_by and not with_references:
        raise EditError(
            "The feature '%s' is named by %s: say '--with-references' to take it out of those as well"
            % (name, ", ".join("'%s: %s'" % (where, entry) for where, entry in named_by))
        )
    if named_by:
        _unname(declaration, name)
    # Both, where both are written: a heading of the free-form shape and an
    # entry of 'features:' are the same feature, and leaving either is
    # leaving it required.
    if heading:
        del section[name]
    if isinstance(features, dict) and name in features:
        del features[name]
    return "the feature '%s'%s" % (
        name,
        (
            (", and %s that named it" % ", ".join("'%s: %s'" % (where, entry) for where, entry in named_by))
            if named_by
            else ""
        ),
    )


def _names(listed, what: str) -> dict:
    """A list of names, as the mapping it means; refused when it holds anything but names."""
    if not all(isinstance(item, str) for item in listed):
        raise EditError("'%s' is not a list of names: rewrite it by hand first" % what)
    return {item: None for item in listed}


def _remove_port(section, _declaration, name, *_rest) -> str:
    ports = section.get(req.PORTS)
    if isinstance(ports, str):
        ports = {ports: None}
        section[req.PORTS] = ports
    elif isinstance(ports, list):
        ports = _names(ports, "%s: %s" % (req.SECTION, req.PORTS))
        section[req.PORTS] = ports
    if not isinstance(ports, dict) or name not in ports:
        raise _missing("The port '%s'" % name)
    del ports[name]
    return "the port '%s'" % name


def _remove_interface(section, declaration, name, instances, *_rest) -> str:
    interfaces = section.get(req.INTERFACES)
    if isinstance(interfaces, str):
        interfaces = {interfaces: None}
        section[req.INTERFACES] = interfaces
    elif isinstance(interfaces, list):
        interfaces = _names(interfaces, "%s: %s" % (req.SECTION, req.INTERFACES))
        section[req.INTERFACES] = interfaces
    if not isinstance(interfaces, dict) or name not in interfaces:
        raise _missing("The interface '%s'" % name)
    if not instances:
        del interfaces[name]
        return "the interface '%s'" % name
    try:
        mapping = _instance_map(interfaces[name], declaration)
    except EditError as e:
        raise EditError("Not taking an instance of '%s' out: %s" % (name, e)) from None
    absent = [instance for instance in instances if instance not in mapping]
    if absent:
        raise _missing("The instance %s of '%s'" % (", ".join("'%s'" % i for i in absent), name))
    for instance in instances:
        del mapping[instance]
    if mapping:
        interfaces[name] = mapping
    else:
        # No instance left is no requirement on the interface left: an empty
        # mapping would read as "any instance", which nobody asked for.
        del interfaces[name]
    return "the instance%s %s of the interface '%s'" % (
        "s" if len(instances) > 1 else "",
        ", ".join("'%s'" % instance for instance in instances),
        name,
    )


def _remove_physics(section, _declaration, name, *_rest) -> str:
    field, _, member = name.partition(".")
    physics = section.get(req.PHYSICS)
    if not isinstance(physics, dict) or field not in physics:
        raise _missing("The physical property '%s'" % name)
    if member:
        members = physics[field]
        if not isinstance(members, dict) or member not in members:
            raise _missing("The physical property '%s'" % name)
        del members[member]
        if not members:
            del physics[field]
    else:
        del physics[field]
    return "the physical property '%s'" % name


def _remove_match(section, _declaration, name, _instances, amounts, _with) -> str:
    match = section.get(req.MATCH)
    if not isinstance(match, dict) or name not in match:
        raise _missing("Matching '%s'" % name)
    if not amounts:
        del match[name]
        return "matching '%s'" % name
    limits = match[name]
    if not isinstance(limits, dict):
        raise EditError("'match: %s' is not a mapping: rewrite it by hand first" % name)
    taken = []
    for key in amounts:
        amount = _amount(str(key))
        present = [spelling for spelling in AMOUNTS[amount] if spelling in limits]
        if not present:
            raise _missing("Matching the %s of '%s'" % (amount, name))
        if len(present) > 1 and str(key) in present:
            # Written twice ('mass:' and 'weight:'), which reads as a problem:
            # the spelling named is the one taken out, and the other stays.
            present = [str(key)]
        for spelling in present:
            del limits[spelling]
        taken.append(amount)
    if not limits:
        del match[name]
    return "matching the %s of '%s'" % (" and ".join(taken), name)


def _remove_has(section, _declaration, name, *_rest) -> str:
    key = has_key(name)
    spellings = [spelling for spelling in req.HAS_KEYS if req._HAS_NAMES.get(spelling, spelling) == key]
    present = [spelling for spelling in spellings if spelling in section]
    if not present:
        raise _missing("'%s'" % key)
    written = str(name).strip().lower().replace("-", "_")
    if len(present) > 1 and written in present:
        # Written twice ('has_weight:' and 'has_mass:'), which reads as a
        # problem: the spelling named is the one taken out, and the other stays.
        present = [written]
    for spelling in present:
        del section[spelling]
    return "'%s'" % present[0] if len(present) == 1 else "'%s'" % key


def section_as_data(section) -> typing.Any:
    """A 'requirements:' section as plain data, for an answer: JSON can carry it, YAML can print it."""
    return _plain(section)
