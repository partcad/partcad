#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Core-side entry point for 'pc copy'.

``pc copy <object-from> <object-to>`` declares a second object that is what the
first one is, by writing the first one's declaration *as the context holds it*
(see 'partcad.serialize') under the new name -- not by copying the text of the
'partcad.yaml' it came from. So a copy of an object declared by a Jinja2 loop is
the object that loop produced, with the parameters the user configuration
overrides set to what they are overridden to, and with nothing in it that only
says what PartCAD would assume anyway; and a copy into another package still
refers to what the original referred to, and still reads the file the original
reads.

The source may be anywhere the context can reach, a revision included
('//pkg@v1.2:bracket'): that is how an object is brought back from an earlier
revision of its package, under a name of its own.
"""

from .. import logging as pc_logging
from .. import serialize
from ..project import OBJECT_KIND_SECTIONS


def copy_object_action(
    source_project,
    kind: str,
    source_name: str,
    target_project,
    target_name: str,
    dry_run: bool = False,
) -> dict:
    """Declare 'target_name' in 'target_project' as a copy of the 'kind' 'source_name' of 'source_project'.

    Refused, with ValueError, for an object the source package does not
    declare, and for a target name the target package already uses -- for any
    kind of object, since a name is one object of its package. With 'dry_run',
    nothing is written and the declaration that would be is returned all the
    same.

    Returns what was done: the kind, both names, and the declaration as YAML.
    """
    section = OBJECT_KIND_SECTIONS.get(kind)
    if section is None:
        raise ValueError("'%s' is not a kind of object that can be copied" % kind)
    if "@" in target_project.name:
        raise ValueError("%s is a revision, which is never written to" % target_project.name)
    declaration = serialize.declaration(source_project, kind, source_name, target_project, target_name)

    taken = target_project.name_taken(kind, target_name)
    if taken is None and target_project.object_kind(target_name) is not None:
        taken = "the package declares an object of that name already"
    if taken is None and kind in ("material", "color", "finish") and target_project.declares_cmf(kind, target_name):
        taken = "the package declares a %s of that name already" % kind
    if taken is not None:
        raise ValueError("%s:%s cannot be declared: %s" % (target_project.name, target_name, taken))

    text = serialize.yaml_text(target_name, declaration)
    result = {
        "kind": kind,
        "source": "%s:%s" % (source_project.name, source_name),
        "target": "%s:%s" % (target_project.name, target_name),
        "declaration": text,
        "dry_run": bool(dry_run),
        "written": False,
    }
    if dry_run:
        return result
    if not target_project.add_object_config(section, target_name, serialize.styled(declaration)):
        raise ValueError("%s could not be declared in %s" % (result["target"], target_project.config_path))
    result["written"] = True
    pc_logging.info("Declared %s, a copy of %s" % (result["target"], result["source"]))
    return result
