#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An object's declaration, written back out of what the context holds of it.

What 'pc copy' writes, and what the IDE's Revisions tab compares two revisions of
an object by. It is the object *as PartCAD read it* -- the declaration after it
was rendered, parsed and normalized, with the user's parameter overrides applied
-- rather than the text of the 'partcad.yaml' it came from, so that a copy says
what the original meant and two revisions are compared by what they mean. A
comment, a YAML anchor, a Jinja2 loop: none of them survives, and that is the
point of reading it this way.

Three things are taken out again on the way, because they are PartCAD's and not
the declaration's:

* **What PartCAD derives.** The name an object is declared under ('name',
  'orig_name'), the reference an alias resolved to ('source_resolved'), and the
  properties making the object recorded into its declaration (the declaration's
  own 'properties:' are kept).
* **Defaults.** A value PartCAD would have used had the key not been there:
  'manufacturable' as the package says it, a parameter written out in the long
  form it is expanded to ('size: {type: int, default: 3}' is 'size: 3'), the
  type of a parameter that is a 'float' anyway, a 'path' that is the object's
  name and its type's extension, and a key with no value.
* **Where it was read.** A copy into another package refers to what the
  original referred to, so a relative reference ('source: :bolt') is written out
  in full, and a file the original reads is named from where the copy is.

The order of the keys is the declaration's own: normalizing and making an object
only ever *adds* keys, at the end, and those are the ones taken out.
"""

import copy
import glob
import io
import os
import typing

from partcad_utils.parameters import normalize_parameters

from .assembly_config_manufacturing import METHOD_ASSY as ASSEMBLY_METHOD_ASSY
from .config import declared_parameter_type

# The keys PartCAD writes into a declaration as it reads it or makes the object.
DERIVED_KEYS = ("name", "orig_name", "source_resolved")

# The keys whose value names another object or a package, which a copy into
# another package has to spell out in full.
REFERENCE_KEYS = frozenset({"source", "sketch", "openings", "visual"})

# The keys that are prose, which are never read as a reference however they look.
PROSE_KEYS = frozenset({"desc", "docs", "requirements", "url", "fileUrl", "poc", "how"})

# The kinds 'Project.object_config' serves a normalized declaration of.
_DECLARED = ("sketch", "part", "assembly", "scene", "software", "provider", "repository")


def _declared_properties(project, kind: str, name: str):
    """The 'properties:' the declaration itself states, or None (see 'Project._remember_declared_properties')."""
    known = getattr(project, "_declared_properties", {}).get(kind, {}).get(name)
    if known is None:
        return False  # nothing remembered: keep what is there
    return copy.deepcopy(known[2])


def compact_parameter(declared):
    """A parameter declaration in the shortest form that reads back as the same declaration.

    The inverse of 'normalize_parameters', where it has one: '{type: int,
    default: 3}' is '3', and a 'float' needs no 'type' at all. Anything that says
    more than a type and a default stays as it is, less a 'type: float'.
    """
    if not isinstance(declared, dict):
        return declared
    result = dict(declared)
    declared_type = result.get("type")
    if set(result) <= {"type", "default"} and "default" in result:
        value = result["default"]
        if value is not None and declared_parameter_type(value) == declared_type:
            # Read back by 'normalize_parameters' as exactly this.
            probe = {"p": copy.deepcopy(value)}
            normalize_parameters(probe)
            if probe["p"] == {"type": declared_type, "default": value}:
                return value
    if declared_type == "float":
        del result["type"]
    return result


def _is_reference(value: str) -> bool:
    """Whether a string reads as '<package>:<object>' or a package path rather than as prose."""
    if not value or any(character.isspace() for character in value.partition(";")[0]):
        return False
    return ":" in value or value.startswith("/") or value.startswith(".")


def _spell_out(project, value):
    """A reference written in 'project', as one that reads the same from any package."""
    if not isinstance(value, str) or not _is_reference(value):
        if isinstance(value, str) and value and ":" not in value and not value.startswith("/"):
            # A bare name: an object of the package that wrote it.
            return "%s:%s" % (project.name, value)
        return value
    if value.startswith("//") and ":" in value:
        return project.relocate(value)
    try:
        return project.normalize(value)
    except Exception:  # pylint: disable=broad-except
        return value


def _spell_out_references(project, config: dict) -> None:
    """Write every reference in 'config' out in full, in place (see '_spell_out')."""
    if "package" in config or "project" in config:
        key = "package" if "package" in config else "project"
        package = config[key]
        if isinstance(package, str) and package not in ("this", ""):
            if not package.startswith("//"):
                from .utils import get_child_project_path

                config[key] = get_child_project_path(project.name, package)
        elif isinstance(package, str):
            config[key] = project.name
        # 'source' is relative to that package, which is now spelled out.
        return
    for key, value in list(config.items()):
        if key in PROSE_KEYS:
            continue
        if key in REFERENCE_KEYS:
            if isinstance(value, str):
                config[key] = _spell_out(project, value)
            elif isinstance(value, list):
                config[key] = [_spell_out(project, item) for item in value]
        elif isinstance(value, dict):
            _spell_out_references(project, value)


def _object(project, kind: str, name: str):
    getter = {
        "part": project.get_part,
        "sketch": project.get_sketch,
        "assembly": project.get_assembly,
        "scene": project.get_scene,
    }.get(kind)
    if getter is None:
        return None
    try:
        return getter(name, quiet=True)
    except Exception:  # pylint: disable=broad-except
        return None


def _file_path(project, kind: str, name: str, config: dict, target_project, target_name: str):
    """What 'path' says in the copy: None where it is the copy's default, the original's file otherwise."""
    if config.get("fileFrom") is not None:
        # Downloaded: 'path' is where it is kept, which the declaration says or not.
        return config.get("path")
    if "path" not in config:
        # Where a file of its own would be if it had one: '<name>.<extension>'.
        # Nothing there, and nothing named, is an object with no file -- a basic
        # shape, an alias -- which there is no need to make to find that out.
        stem = os.path.join(project.config_dir, str(config.get("orig_name", name)))
        if not glob.glob(glob.escape(stem) + ".*"):
            return None
    obj = _object(project, kind, name)
    source_file = getattr(obj, "path", None) if obj is not None else None
    if not isinstance(source_file, str) or not source_file:
        return config.get("path")
    source_file = os.path.normpath(os.path.abspath(source_file))
    extension = os.path.splitext(source_file)[1]
    default = os.path.normpath(os.path.join(os.path.abspath(target_project.config_dir), target_name + extension))
    if default == source_file:
        return None
    return os.path.relpath(source_file, os.path.abspath(target_project.config_dir)).replace(os.sep, "/")


def config_of(project, kind: str, name: str):
    """The declaration of 'name' as the context holds it, normalized; None if there is none."""
    if kind in _DECLARED:
        return project.object_config(kind, name)
    if kind == "interface":
        return project.normalized_interface_config(name, deep_copy=True)
    return project.object_configs(kind).get(name)


def declaration(project, kind: str, name: str, target_project=None, target_name: typing.Optional[str] = None):
    """The declaration of 'kind' 'name' of 'project', as a copy of it named 'target_name' in 'target_project' would say it.

    The copy defaults to the original itself -- the same name in the same
    package -- which is how the Revisions tab reads both sides of a comparison.
    Raises ValueError for an object the package does not declare.
    """
    target_project = project if target_project is None else target_project
    target_name = name if target_name is None else target_name
    config = config_of(project, kind, name)
    if config is None:
        raise ValueError("%s declares no %s '%s'" % (project.name, kind, name))
    if not isinstance(config, dict):
        # A short-form declaration that is a value of its own (a colour's hex).
        return copy.deepcopy(config)
    result = copy.deepcopy(config)

    for key in DERIVED_KEYS:
        result.pop(key, None)
    # A scene is an arrangement rather than a product, and is not manufacturable
    # unless it says so (see 'SceneConfiguration'); anything else is what its
    # package is.
    default_manufacturable = False if kind == "scene" else getattr(project, "is_manufacturable", None)
    if "manufacturable" in result and result["manufacturable"] == default_manufacturable:
        result.pop("manufacturable")
    manufacturing = result.get("manufacturing")
    if kind == "assembly" and result.get("type") == "assy" and isinstance(manufacturing, dict):
        # An ASSY file's own instructions are how it is put together unless it
        # says otherwise (see 'AssemblyConfiguration.normalize').
        if manufacturing.get("method") == ASSEMBLY_METHOD_ASSY:
            manufacturing.pop("method")
        if not manufacturing:
            result.pop("manufacturing")
    declared = _declared_properties(project, kind, name)
    if declared is not False:
        if declared is None:
            result.pop("properties", None)
        else:
            result["properties"] = declared
    if isinstance(result.get("parameters"), dict) and kind != "interface":
        result["parameters"] = {key: compact_parameter(value) for key, value in result["parameters"].items()}

    if kind in ("part", "sketch", "assembly", "scene"):
        path = _file_path(project, kind, name, config, target_project, target_name)
        if path is None:
            result.pop("path", None)
        else:
            # Where it was if the declaration said so; after everything it
            # said, if the original found its file without being told.
            result["path"] = path

    if target_project is not project:
        _spell_out_references(project, result)

    for key in [key for key, value in result.items() if value is None]:
        del result[key]
    return result


def yaml_text(name: str, value) -> str:
    """'name: value' as YAML, keys in the order they are in, wide enough never to fold a line (see 'styled')."""
    import ruamel.yaml

    yaml = ruamel.yaml.YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    stream = io.StringIO()
    yaml.dump(styled({name: value}), stream)
    return stream.getvalue()


# The most scalars a list is written on one line with: a location, a vector, a
# size. A longer one is a list somebody reads an item at a time.
_FLOW_ITEMS = 8


def _is_scalar(value) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None


def _flows(value) -> bool:
    """Whether a list is short and flat enough to be written on one line, as a location is: '[[0, 0, 0], [0, 0, 1], 0]'."""
    if not isinstance(value, (list, tuple)) or len(value) > _FLOW_ITEMS:
        return False
    for item in value:
        if isinstance(item, (list, tuple)):
            if len(item) > _FLOW_ITEMS or not all(_is_scalar(each) and not _multiline(each) for each in item):
                return False
        elif not _is_scalar(item) or _multiline(item):
            return False
    return True


def _multiline(value) -> bool:
    return isinstance(value, str) and "\n" in value


def styled(value):
    """'value' as ruamel writes it the way a person writes a 'partcad.yaml'.

    Every mapping a mapping and every sequence a list, which is all a dumper
    knows; a short flat list on one line, as a location or a vector is written;
    and text of several lines as a block ('|'), not as one line of escapes.
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
    from ruamel.yaml.scalarstring import LiteralScalarString

    if isinstance(value, dict):
        result = CommentedMap()
        for key, item in value.items():
            result[str(key)] = styled(item)
        return result
    if isinstance(value, (list, tuple)):
        result = CommentedSeq(styled(item) for item in value)
        if _flows(value):
            result.fa.set_flow_style()
        return result
    if _multiline(value):
        return LiteralScalarString(value)
    if _is_scalar(value):
        return value
    return str(value)
