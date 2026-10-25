#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""One name, one object: the rule a package's object names follow, as both ends read it.

A command is handed an object by name -- ``pc render bolt``, ``pc test
//pub/std:m3`` -- and used to be told separately what kind of object the name
was, with ``-a``, ``-s``, ``-i``, ``-S`` or ``-w``, because a package kept a
namespace per kind and ``bolt`` could be a part and an assembly at once. It no
longer can. Within a package a name means one object, whatever its kind, so the
name alone says which object it is and the kind can be looked up rather than
asked for (see ``Project.object_kind``). The flags are still taken, and saying
the kind skips the lookup, which is all they are for now.

The rule covers the kinds a command names: :data:`NAMED_KINDS`. Materials,
providers, repositories and part types keep namespaces of their own, because
nothing names one of them without saying what it is -- a part's ``material:``,
``pc supply --provider``, a part's ``type:``.

:data:`NAMED_KINDS` is also the order a name of unknown kind is looked for in:
the kinds a package holds most of first, so that the usual answer is the first
one asked. In a package that breaks the rule, the same order decides which
declaration keeps the name -- the one a bare name resolves to -- and every later
one is refused, by PartCAD as it loads the package and by the linter as it reads
the file (see :func:`duplicates`).

It lives here rather than in ``partcad`` because it is read at both ends: by
``partcad.project`` as a package loads, and by ``partcad_utils.assy_lint`` --
which the client runs over a file an editor has open and the daemon runs over a
package -- and a rule with a copy per reader is a rule whose copies disagree
about which object a name is.
"""

from typing import Iterator, Mapping, NamedTuple, Optional

# The kinds of object a command names, in the order a name is looked for in:
# the most frequent first.
NAMED_KINDS = ("part", "interface", "assembly", "sketch", "scene", "software")

# The 'partcad.yaml' section each of them is declared in.
SECTIONS = {
    "part": "parts",
    "interface": "interfaces",
    "assembly": "assemblies",
    "sketch": "sketches",
    "scene": "scenes",
    "software": "software",
}

_ARTICLES = {
    "part": "a part",
    "interface": "an interface",
    "assembly": "an assembly",
    "sketch": "a sketch",
    "scene": "a scene",
    "software": "software",
}


def describe(kind: str) -> str:
    """'a part', 'an interface', ...: a kind as a sentence names one."""
    return _ARTICLES.get(kind, kind)


def claimed_names(declarations: Optional[Mapping]) -> Iterator[tuple]:
    """Every name a section of a package claims, as ``(name, alias_of)``.

    The keys of the section, each with ``alias_of`` None, and then the names
    their ``aliases:`` ask for, each with the declaration that asks for it. An
    alias is created under that name as surely as a declaration is, so it is a
    name of the package like any other. A parametrized declaration's parameters
    travel to its aliases, which is how PartCAD creates them
    (``Project.init_object_by_config``) and so how they are named here.
    """
    if not declarations:
        return
    yield from ((name, None) for name in declarations)
    for owner, config in declarations.items():
        if not isinstance(config, Mapping):
            # A bare string is the short form of an alias, and asks for no
            # aliases of its own.
            continue
        aliases = config.get("aliases")
        if not isinstance(aliases, (list, tuple)):
            continue
        for alias in aliases:
            if not isinstance(alias, str):
                continue
            if ";" in owner:
                alias += owner[owner.index(";") :]
            yield alias, owner


class Duplicate(NamedTuple):
    """A name that one declaration may not have, because an earlier one has it.

    ``kind`` and ``name`` are the declaration refused, ``alias_of`` the
    declaration whose ``aliases:`` asked for it when it is an alias. ``owner_*``
    is the same about the one that keeps the name.
    """

    kind: str
    name: str
    alias_of: Optional[str]
    owner_kind: str
    owner_alias_of: Optional[str]


def duplicates(sections: Mapping) -> list:
    """The declarations that may not have their name, because another kind has it.

    ``sections`` maps each kind of :data:`NAMED_KINDS` to its declarations as
    ``{name: config}``; a kind that is absent, or None, is one nothing is known
    about yet, and is left out of the comparison rather than read as empty.

    Two declarations of the same kind under one name are not reported: within a
    kind that is the YAML mapping's business (it has one key per name), and an
    alias clashing with a declaration of its own kind is refused as it is made
    (``Project.register_object``).
    """
    claimed = {}
    found = []
    for kind in NAMED_KINDS:
        for name, alias_of in claimed_names(sections.get(kind)):
            owner = claimed.get(name)
            if owner is None:
                claimed[name] = (kind, alias_of)
            elif owner[0] != kind:
                found.append(Duplicate(kind, name, alias_of, owner[0], owner[1]))
    return found


def message(duplicate: Duplicate) -> str:
    """Why ``duplicate`` is refused, in the words PartCAD and the linter both use."""
    owner = describe(duplicate.owner_kind)
    if duplicate.owner_alias_of is not None:
        owner += " (an alias of '%s')" % duplicate.owner_alias_of
    refused = "'%s'" % duplicate.name
    if duplicate.alias_of is not None:
        refused = "the alias '%s' of the %s '%s'" % (duplicate.name, duplicate.kind, duplicate.alias_of)
    return (
        "%s is already the name of %s in this package, and a name means one object of a package whatever its "
        "kind: rename one of them" % (refused, owner)
    )
