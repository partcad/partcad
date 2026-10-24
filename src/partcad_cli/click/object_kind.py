#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the flags saying what kind of object OBJECT is are for, now that they are optional.

A name is one object of its package whatever its kind (see
`partcad_utils.object_names`), so a command no longer needs telling whether
`bolt` is a part or an assembly: the daemon looks it up, from what it has in
memory first and only then -- for a package a plugin serves -- by asking, the
most frequent kinds first. `-s`, `-i`, `-a`, `-S` and `-w` are kept for a caller
who knows, and would rather not pay for being asked; they skip the lookup and
nothing else.

The words are here so that every command says it the same way. The flags
themselves still go over the wire as the booleans they always were, and the
daemon reads them in one place (`operations._object_kind`).
"""

# Said once, in the help of each command that takes an OBJECT.
LOOKED_UP = "OBJECT is found by its name, whatever kind of object it is; a flag saying the kind skips looking it up"


def flag_help(kind: str) -> str:
    """The help of one kind flag: 'a sketch', 'an interface', ..."""
    return "The object is %s (optional: saying it skips looking the kind up)" % kind
