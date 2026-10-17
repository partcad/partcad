#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How a PartCAD name becomes a name a file format accepts, and back.

PartCAD names things for whoever reads them: a body after the link that placed
it ('leg', 'leg-2', see 'kinematics'), a joint after its link pair or its
'joint:' ('shoulder_pan'), a scene after itself ('world'). Those names are what
a validation reads and what a report prints, and they stay PartCAD's. A file
format has rules of its own about names -- which characters, how long, whether
'Cube' and 'cube' are one name, which names mean something already ('world' is
the world in SDFormat and in MJCF) -- and an exporter that writes a PartCAD name
the format refuses writes a file nobody can load. So each format **declares its
rules beside its own code**, as a 'Rules', and every name it writes goes through
a 'Transcoder' made from them: the identity wherever the PartCAD name is
already valid and free, and otherwise the nearest valid name nobody has taken,
deterministically. The transcoder keeps both directions, so that what a format
reports under its own names can be told under PartCAD's (see 'sidecar_path').

Plain Python and nothing else, beside 'kinematics' and 'mass_properties': a
plugin runs in a sandbox with this directory on its path and imports it the
same way. Which rules a format has is that format's: URDF's are in
'//builtin/export/export_urdf.py', MJCF's and SDFormat's in the plugins that
write them.

``Rules(format, allowed=None, forbidden=(), reserved=(), reserved_patterns=(),
case_sensitive=True, max_length=None)``
    What one format allows a name to be. 'allowed' is a compiled pattern
    matching one allowed character (None: any character an XML attribute can
    carry, 'XML_CHARACTER'); 'forbidden' substrings no name may contain even of
    allowed characters (SDFormat's scope separator '::'); 'reserved' names the
    format gives a meaning of its own, and 'reserved_patterns' patterns of them
    (SDFormat's '__*__'), both compared as the format compares names;
    'case_sensitive', whether it does; 'max_length', in characters, if any.
    'valid(name)' says whether a name is one the format accepts as it is.

``transcode(rules, name, fallback="name")``
    The name made valid, uniqueness aside: every run of characters the format
    does not allow becomes one '_' (dropped at either end, where it would only
    be noise), a forbidden substring '_' too, and the result cut to length. A
    name already valid comes back as it is, leading underscore and all.

``Transcoder(rules, separator="-", first=2)``
    One namespace of a format -- the names that must differ from each other:
    MJCF's bodies, URDF's links, a whole SDFormat world. 'claim(name, kind)'
    hands out the internal name of a PartCAD name, and the same one every time
    it is asked for the same (kind, name); a name already taken, or reserved,
    is told apart by '<separator><n>' counting from 'first' -- 'leg-2' after
    'leg', as 'kinematics' tells a second body of one name apart. 'derive(name)'
    hands out a name for something PartCAD does not name (a model's root link,
    a dummy link, a mesh) from the same pool, unmapped and fresh every time.
    'release(internal)' gives a name back. 'internal(name, kind)' and
    'partcad(internal)' read the mapping either way, 'mapping()' is all of it
    by kind, and 'renamed()' the entries where the two differ -- what an
    exporter says it did.

**Order.** A derived name yields to a PartCAD one: an exporter claims every
PartCAD name it will write before it derives anything ('claim_all'), so a body
somebody called 'cube_link' keeps its name and the root link of a model 'cube'
is the one told apart. Within the PartCAD names, the first claimed keeps it.

**The sidecar.** An exporter whose file a simulation reads writes, beside it,
``<file>.names.json`` ('sidecar_path', 'write_sidecar'): which internal name
each PartCAD name became and where in the file each body and each reported
joint is, so that the simulation reports under PartCAD's names without knowing
how the exporter named anything (docs/design/simulation.md, section 4.2):

    {"version": 1, "format": "mjcf",
     "names":  {"<kind>": {"<PartCAD name>": "<internal name>"}},
     "bodies": {"<PartCAD body>": {"path": ["<internal>", ...]}},
     "joints": {"<reported joint>": {"path": ["<internal>", ...], "joint": "<PartCAD joint>"}}}

A 'path' is the internal names from the outermost entity down -- an MJCF body
by its name alone, an SDFormat link by its model's and its own. 'bodies' and
'joints' are open: an entry is a dict so that what a later exporter knows about
a body or a joint (a joint's starting value, to re-zero a reading by) is a key
added, not a shape changed. A reader ignores keys it does not know, and so does
'read_sidecar'.
"""

import json
import os
import re

# One character an XML 1.0 document can carry in an attribute, unescaped by
# anything but the writer's own '&', '<' and '"': the 'Char' production less
# the control characters, which an attribute value normalises to spaces (and
# most of which XML 1.0 forbids outright).
XML_CHARACTER = re.compile("[ -퟿-�\U00010000-\U0010ffff]")

# What 'transcode' puts where the characters a format does not allow were.
REPLACEMENT = "_"

# What the sidecar beside an exported file is called after it, and the version
# of its shape: raised only when a reader of the old one would misread the new.
SIDECAR_SUFFIX = ".names.json"
SIDECAR_VERSION = 1


class Rules:
    """What one file format allows a name to be. See the module docstring."""

    def __init__(
        self,
        format,
        allowed=None,
        forbidden=(),
        reserved=(),
        reserved_patterns=(),
        case_sensitive=True,
        max_length=None,
    ):
        self.format = format
        self.allowed = allowed if allowed is not None else XML_CHARACTER
        self.forbidden = tuple(forbidden)
        self.case_sensitive = case_sensitive
        self.max_length = max_length
        self.reserved = frozenset(self.key(name) for name in reserved)
        self.reserved_patterns = tuple(
            re.compile(pattern, 0 if case_sensitive else re.IGNORECASE) if isinstance(pattern, str) else pattern
            for pattern in reserved_patterns
        )

    def key(self, name):
        """What 'name' is compared as: itself, or case-folded for a format that ignores case."""
        return name if self.case_sensitive else name.casefold()

    def is_reserved(self, name):
        return self.key(name) in self.reserved or any(pattern.fullmatch(name) for pattern in self.reserved_patterns)

    def valid(self, name):
        """Whether the format accepts 'name' as it is (uniqueness aside)."""
        return (
            isinstance(name, str)
            and bool(name)
            and all(self.allowed.fullmatch(character) for character in name)
            and not any(part in name for part in self.forbidden)
            and (self.max_length is None or len(name) <= self.max_length)
            and not self.is_reserved(name)
        )

    def __repr__(self):
        return "Rules(%r)" % self.format


# What a file an exporter writes beside its own may be called -- a mesh, say --
# which is the filesystem's rule rather than any format's: the one a file
# copied to any machine still answers to. Letters, digits, '_' and '-' -- no
# '.', which would make a hidden file of one and a second extension of another;
# compared ignoring case, as Windows and macOS do by default, so that 'Cube'
# and 'cube' are not one file there; none of the names Windows keeps for a
# device, which it keeps with any extension after them ('con.stl' cannot be
# created); and short enough, with an extension after it, for the 255
# characters a component may have.
FILE_NAMES = Rules(
    "a file name",
    allowed=re.compile(r"[A-Za-z0-9_-]"),
    reserved=("CON", "PRN", "AUX", "NUL")
    + tuple("COM%d" % n for n in range(1, 10))
    + tuple("LPT%d" % n for n in range(1, 10)),
    case_sensitive=False,
    max_length=200,
)


def _replace_runs(rules, name):
    """'name' with each run of characters 'rules' does not allow made one REPLACEMENT."""
    out = []
    replaced_at = []
    for character in name:
        if rules.allowed.fullmatch(character):
            out.append(character)
        elif not replaced_at or replaced_at[-1] != len(out) - 1:
            replaced_at.append(len(out))
            out.append(REPLACEMENT)
    # A replacement at either end stands for nothing a reader wants to see:
    # '//pub/examples:logo' is 'pub_examples_logo', not '_pub_examples_logo'.
    # Only one this made, though: a name of its own that starts with '_' keeps it.
    if replaced_at and replaced_at[-1] == len(out) - 1:
        out.pop()
    if replaced_at and replaced_at[0] == 0 and out:
        out.pop(0)
    return "".join(out)


def transcode(rules, name, fallback="name"):
    """'name' made a name 'rules' accepts, uniqueness and reservation aside. See the module docstring."""
    name = "" if name is None else str(name)
    if not rules.valid(name):
        name = _replace_runs(rules, name)
        for part in rules.forbidden:
            while part in name:
                name = name.replace(part, REPLACEMENT)
    if not name:
        name = _replace_runs(rules, str(fallback)) or "name"
    if rules.max_length is not None:
        name = name[: rules.max_length]
    return name


class Transcoder:
    """One namespace of a format: PartCAD names in, unique valid internal names out. See the module docstring."""

    def __init__(self, rules, separator="-", first=2):
        if not all(rules.allowed.fullmatch(character) for character in separator):
            raise ValueError("%s does not allow %r, so it cannot tell two names apart with it" % (rules, separator))
        self.rules = rules
        self.separator = separator
        self.first = first
        self._taken = set()
        self._to = {}
        self._from = {}

    def _free(self, base):
        """The first of 'base', 'base-2', 'base-3' ... that is valid and not taken."""
        candidate = base
        suffix = self.first
        while self.rules.key(candidate) in self._taken or self.rules.is_reserved(candidate):
            if suffix - self.first > 100000:
                # A reserved pattern no suffix gets out of, which is a mistake
                # in the rules rather than anything a name can do.
                raise ValueError("%s leaves no name free for %r" % (self.rules, base))
            tail = "%s%d" % (self.separator, suffix)
            head = base if self.rules.max_length is None else base[: max(0, self.rules.max_length - len(tail))]
            candidate = head + tail
            suffix += 1
        self._taken.add(self.rules.key(candidate))
        return candidate

    def claim(self, name, kind=None, fallback="name", preferred=None):
        """The internal name of the PartCAD name 'name', of 'kind': the same one each time it is asked.

        'preferred' is what to write it as where that is not 'name' itself: a
        URDF root link is the body named after its assembly, written after the
        one part it is made of.
        """
        entry = (kind, str(name))
        if entry not in self._to:
            internal = self._free(transcode(self.rules, name if preferred is None else preferred, fallback))
            self._to[entry] = internal
            self._from[internal] = entry
        return self._to[entry]

    def claim_all(self, names, kind=None):
        for name in names:
            self.claim(name, kind)

    def derive(self, name, fallback="name"):
        """A fresh internal name for something PartCAD does not name, from the same pool."""
        return self._free(transcode(self.rules, name, fallback))

    def reserve(self, internal):
        """Take 'internal' as it is, for something the format itself names ('world' in a URDF of several roots)."""
        self._taken.add(self.rules.key(internal))
        return internal

    def release(self, internal):
        """Give 'internal' back: what it named is not written after all."""
        self._taken.discard(self.rules.key(internal))
        entry = self._from.pop(internal, None)
        if entry is not None:
            del self._to[entry]

    def internal(self, name, kind=None):
        return self._to.get((kind, str(name)))

    def partcad(self, internal):
        """The PartCAD name 'internal' stands for, or None for a derived one."""
        entry = self._from.get(internal)
        return None if entry is None else entry[1]

    def mapping(self):
        """{kind: {PartCAD name: internal name}}, the kind None as ''."""
        out = {}
        for (kind, name), internal in self._to.items():
            out.setdefault(kind or "", {})[name] = internal
        return out

    def renamed(self):
        """(kind, PartCAD name, internal name) of every name written differently from PartCAD's, in claim order."""
        return [(kind, name, internal) for (kind, name), internal in self._to.items() if internal != name]


def renamed_warning(rules, *transcoders):
    """One sentence naming every name the format made PartCAD write differently, or None."""
    changes = [entry for transcoder in transcoders for entry in transcoder.renamed()]
    if not changes:
        return None
    return "%s does not accept these PartCAD names as they are, so they are written under others: %s" % (
        rules.format,
        ", ".join(
            "%s'%s' as '%s'" % ("%s " % kind if kind else "", name, internal) for kind, name, internal in changes
        ),
    )


def merged_mapping(*transcoders):
    """The 'names' of a sidecar: every transcoder's mapping, kind by kind."""
    out = {}
    for transcoder in transcoders:
        for kind, names in transcoder.mapping().items():
            out.setdefault(kind, {}).update(names)
    return out


def sidecar_path(path):
    """Where the sidecar of the file at 'path' is: beside it, named after all of it."""
    return str(path) + SIDECAR_SUFFIX


def write_sidecar(path, format, names, bodies=None, joints=None):
    """Write the sidecar of the file at 'path' (see the module docstring) and return where."""
    sidecar = sidecar_path(path)
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(
            {
                "version": SIDECAR_VERSION,
                "format": format,
                "names": names,
                "bodies": bodies or {},
                "joints": joints or {},
            },
            f,
            indent=1,
            sort_keys=True,
        )
        f.write("\n")
    return sidecar


def read_sidecar(path):
    """The sidecar of the file at 'path', or None where there is none this can read."""
    sidecar = sidecar_path(path)
    if not os.path.isfile(sidecar):
        return None
    try:
        with open(sidecar, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != SIDECAR_VERSION:
        return None
    for key in ("names", "bodies", "joints"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    return data
