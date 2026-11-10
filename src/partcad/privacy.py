#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which objects a package keeps to itself: 'private: true'.

Any object a package declares - a part, an interface, an assembly, a sketch, a
scene or software, the kinds a name is one object of (see
'partcad_utils.object_names') - may say

    parts:
      wall-surface:
        type: wall
        private: true

and is then the package's own: another object *of the same package* may be
built out of it, name it, alias it, place it, extrude it, draw it as its
'visual:'; a reference written anywhere else may not, and is refused with a
message naming the object, the package it is private to and the package the
reference was written in. It is how a package keeps an object it needs for its
own work - a one-sided surface that only stands in for a wall in a picture, a
helper sketch, a fixture of a test - from becoming something other packages
build on, and so from becoming something it cannot change.

What is checked is a *reference*: a name written in a package, by an object of
it, that PartCAD resolves on that object's behalf - an ASSY link, an alias or
an enrich's 'source:', the sketch an extrusion, a sweep, a wall or an interface
names, the wall a 'walls' scene stands up, a part's 'visual:', the software an
object ships with. Whoever resolves
one says which package wrote it, as the 'referrer' of the lookup
('Project.get_part', 'Context.get_part' and their siblings), and the lookup
refuses the object there.

A *command* is not a reference. 'pc render', 'pc qual test', 'pc info', the IDE's
Explorer and an agent's MCP tools name an object to look at it, not to build
something else out of it, and they reach a private object as they reach any
other - which is how the package's own author develops it, and what 'pc qual test
-r' and 'pc render -r' need to go on covering everything a package declares.
That is the line Bazel's visibility draws too, and PartCAD's '//package:object'
names are Bazel's: a private target is still built by naming it on the command
line, and refused only as a dependency of a target in another package. A lookup
with no referrer is therefore never refused for privacy.

Not to be confused with a *package*'s own top-level 'private: true', which is
older and says something else - that the package does not track the public
index ('pc init -p') - and makes none of its objects private.

A private object's own parametrized instances ('wall-surface;length=4200') are
as private as it is - they are copies of its declaration - and so is every name
its 'aliases:' give it. An alias *declared* in the same package under a name of
its own, with no 'private:', is public: that is the package deciding to publish
the object under that name, which only the package can do.
"""

from typing import Optional

from partcad_utils import object_names

# The key, on any object's declaration.
PRIVATE_KEY = "private"


def is_private(obj) -> bool:
    """Whether 'obj' - an object, or a declaration - says 'private: true'.

    Only a real 'true' counts, the way 'fixed:' is read: a quoted "yes" is a
    mistake the schema reports, and a mistake must not quietly make an object
    the whole world can build on.
    """
    config = obj if isinstance(obj, dict) else getattr(obj, "config", None)
    return isinstance(config, dict) and config.get(PRIVATE_KEY) is True


def refusal(kind: str, package: str, name: str, referrer: Optional[str]) -> Optional[str]:
    """Why a reference from 'referrer' may not name the private object 'package:name', or None if it may.

    None for a lookup with no referrer (a command, or the package asking for
    its own object) and for a reference written in the package itself.
    """
    if not referrer or referrer == package:
        return None
    return "%s '%s:%s' is private to %s, and a reference written in %s cannot name it" % (
        object_names.describe(kind).capitalize(),
        package,
        name,
        package,
        referrer,
    )
