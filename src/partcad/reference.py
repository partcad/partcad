#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a reference points at, and what it is called before it is made.

Two declarations are references to another object rather than objects of their
own: an 'alias' is another name for one, and an 'enrich' is another name for a
parameterized instance of one (see 'partcad.enrich'). Both spell where that
object is the same way -

    source:  the object's name, which may be a reference of its own
             (':widget', '../other:widget', '//pub/x:widget')
    package: the package it is in, with the object's own name as the default
             when only a package is given ('project' is the older spelling)

- and until this module existed, four places implemented those rules: the part,
  sketch and assembly alias factories, each with its own copy, and the enrich
  resolution, which said in its docstring that it was "spelled the same way an
  alias spells it" and then said it again in code.

The other half of this is 'description()'. A reference takes its description
from what it points at rather than from what it declares, and that used to be
knowable only by building the factory - so a listing of a package's parts had
to create every one of them to print a column. What a reference is called is a
property of the declaration, so it is answered here, from the declaration.
"""

import typing

from .utils import get_child_project_path


def source_of(source_project, target_project_name: str, config: dict, noun: str) -> str:
    """The '<package>:<object>' a reference names, fully qualified.

    'source_project' is the package that authored the declaration, which is
    what a relative reference is relative to; 'target_project_name' is the
    package the object being declared belongs to, which is what a bare package
    name is resolved against. They are the same package for every declaration
    PartCAD reads out of a 'partcad.yaml', and they are separate arguments
    because the distinction is what makes an enrich of another package's object
    land in the right one.

    'noun' is the kind, for the one error this raises: a declaration that names
    neither an object nor a package says nothing about what it points at.
    """
    if "source" in config:
        source_name = config["source"]
    else:
        source_name = config["name"]
        if "project" not in config and "package" not in config:
            raise Exception("A reference needs either the source %s name or the source package name" % noun)

    if "project" in config or "package" in config:
        package_name = config["project"] if "project" in config else config["package"]
        if package_name == "this" or package_name == "":
            package_name = source_project.name
        elif not package_name.startswith("//"):
            # Resolved against the package the object belongs to, so that a
            # relative package name means the same thing wherever the
            # declaration was authored.
            package_name = get_child_project_path(target_project_name, package_name)
        return package_name + ":" + source_name

    if ":" not in source_name:
        return source_project.name + ":" + source_name

    # Written as a reference of its own (':widget', '../other:widget'), so the
    # package that authored it is what it is relative to. Spelled out rather
    # than left to whoever consumes it, because this is also what gets recorded
    # as 'source_resolved', and a consumer walking the stored configuration has
    # no package to read it against.
    return source_project.normalize(source_name)


def split(source: str) -> typing.Tuple[str, str]:
    """A fully qualified reference as (package, object).

    From the right, because a package path holds no ':' and an object name may
    ('a:b' is not a name PartCAD gives out, but rpartition costs nothing and
    does not have to be reasoned about).
    """
    package_name, _, object_name = source.rpartition(":")
    return package_name, object_name


# The object types that are references, and so describe themselves by what they
# point at rather than by what they declare. A 'desc' on one of these is
# ignored, which is a decision these types have always made and not a new one.
REFERENCE_TYPES = frozenset({"alias", "enrich", "compound"})


def describe(config_type: str, target_project_name: str, source: str) -> str:
    """What a reference is called, given the reference it resolved to.

    Its source, because that is what it is: a reference has nothing of its own
    to describe. Here rather than in each factory because a listing needs the
    same answer without building anything (see 'Project.object_descriptions'),
    and two ways of producing one string is how they come to disagree.

    An alias and an enrich name the package only when it is not their own,
    which is the common case and would otherwise be repeated on every row of a
    listing. A compound always spells it out; that is how it has always read.
    """
    package_name, object_name = split(source)
    if config_type == "compound":
        return "Compound of %s" % source
    if package_name == target_project_name:
        return "Alias to %s" % object_name
    return "Alias to %s from %s" % (object_name, package_name)
