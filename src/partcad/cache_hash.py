#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-17
#
# Licensed under Apache License, Version 2.0.
#

import hashlib
import os

from . import logging as pc_logging

# The format of what the caches store, mixed into every hash so that a change
# to it moves every entry to a new key instead of letting an old entry be read
# back under the new rules. Nothing is deleted: the stale files stay on disk
# until the cache is cleaned, they are simply never looked up again.
#
# Bump this whenever the bytes behind a cache key change meaning:
#   1: BREP payloads are zstd-compressed before being base64-encoded
#      (see wrappers/ocp_serialize.py).
#   2: the shape cache stores the payload alone - the outer layer (name, label,
#      placement) is stripped on write and wrapped back on read (see
#      cache_shape.py), and a lone shape is stored as raw BREP bytes.
#   3: a shape's key covers its whole configuration bar the keys that only
#      describe it, instead of 'parameters'/'offset'/'scale' alone (see
#      _NON_GEOMETRIC_CONFIG_KEYS in shape.py). Entries written under 2 were
#      keyed on too little - parts that differ only in a key the allow-list did
#      not name shared one - so none of them may be read back.
#   4: a shape entry carries what was recorded about the geometry as it was
#      built - its measurements, what its source file stated, what that file
#      said about individual elements - in the entry itself rather than in
#      sibling entries keyed on the same hash with a suffix (see cache_shape.py).
#      An entry written under 3 holds the geometry and nothing else, and there
#      is no way to tell that from one whose producer recorded nothing; reading
#      one back would report a part as having no size rather than as one nobody
#      has measured.
#   5: the tree an assembly is stored as changed shape twice over. An ASSY file's
#      root node is the assembly itself rather than a container inside it, so a
#      tree written under 4 has a level in it that nobody declared; and every node
#      now carries what its object declares about connections, which an entry
#      written under 4 has nowhere to have recorded (see shape_envelope.py). Both
#      are the payload's shape rather than the key's, so nothing about a
#      declaration changes when PartCAD does and an old entry would go on being
#      served: a viewer showing an assembly with two roots and no ports in it.
#   6: every value is hashed with a type tag and a length in front of it, rather
#      than as its bare bytes run together (see '_frame'). Under 5 the values
#      of a list, a dictionary's keys and values, and the files a shape depends
#      on were simply concatenated, so 'offset: [1, 23, 0]' and
#      'offset: [12, 3, 0]' were one key - two different parts, one entry.
#      A file is hashed by its size and a sample of its content rather than by
#      all of it (see 'add_filename'). The keys an
#      extrude, a sweep, a compound part and an ASSY assembly are stored under
#      also cover the keys of what they are built from now, so an entry written
#      under 5 was keyed on less than it needed to be.
#   7: a child node's "label" is what the assembly addresses the child by, and
#      nothing else: its own name, or - for a child nothing named - its position
#      in that assembly (see 'Assembly.link_name'). Under 6 such a child was
#      labelled after the object it held, which an ASSY file's unnamed 'links:'
#      made "<assembly>:links" - a label two of them shared, and not a name
#      anything could address. The label is now what a 'connect:', a 'map:' and
#      a filter name, so a reader of the tree can compose a request out of it.
#      The same case as 5, and for the same reason: it is the payload's shape
#      rather than the key's, so nothing about a declaration changes when
#      PartCAD does and an entry written under 6 would go on being served - a
#      panel offering to select links by names the daemon does not know.
#   8: a node placed by a connection that keeps a degree of freedom carries its
#      joint (see 'shape_envelope.KEY_JOINT' and 'partcad.joint'), which an
#      entry written under 7 has nowhere to have recorded. The same case as 5
#      and 7: the payload's shape rather than the key's, so an old entry would
#      go on being served - and an exporter of the mechanism would be handed
#      one with no joints in it, silently.
#   9: a shape's measurements carry where its volume is and how it is spread -
#      its centroid and its inertia at unit density (see 'shape_envelope') -
#      which is what a part's mass, centre of mass and inertia are worked out
#      from. An entry written under 8 measured the volume and nothing else, and
#      reading one back would give a part a mass with no centre and no inertia:
#      a URDF link that weighs what it should and turns as if it were a point.
#  10: every node an assembly or a scene places says what it holds - a part,
#      an assembly or a scene - and so does the root of every assembly and
#      scene; a scene's element marked 'fixed: true' says so too (see
#      'shape_envelope.KEY_KIND' and 'KEY_FIXED'). Those are what decide which
#      nodes are rigid bodies (docs/design/simulation.md, section 7). The same
#      case as 5, 7 and 8: the payload's shape rather than the key's, and an
#      entry written under 9 would go on being served with neither - a scene
#      placed in a scene read as one product, and a table bolted to the floor
#      read as free to fall.
#  11: a node placed by a rigid connection says what it is connected to (see
#      'shape_envelope.KEY_ATTACHED'), and a node a URDF places carries the
#      joint its URDF states. The same case as 5, 7, 8 and 10: an entry written
#      under 10 would go on being served without either - a part bolted to a
#      turning arm read as bolted to the base, and a robot read as one body.
#  12: a joint is what the native joint types make of its declaration
#      (docs/design/simulation.md, section 8.13): its bounds are the
#      parameter's range with 'limits:' laid over it side by side, a ball's
#      turns carry no range and the joint its one bound ('turnLimit'), a
#      'continuous' or '.inf' side is open, and a source says when 'limits:'
#      ran the other way to its parameter ("reversed"). The same case as 5, 7,
#      8, 10 and 11: an entry written under 11 would go on being served with
#      the old joints - a ball read as a composite for the ranges its turns
#      still carried, and a start against its stop said nowhere.
#  13: a joint's freedoms are in their declared order, whatever order
#      'toParams' names them in, and only a joint that is a ball carries a
#      ball's bound. The same case again: an entry written under 12 would go
#      on being served with a floating joint posed by a move first read as a
#      composite, and a revolute carrying the bound of the ball it overrode.
#  14: a 'motion:' that a more specific one overrides still brings along the
#      parameters it implies, as adjustments, so a locked joint ('connect:
#      {motion: fixed}') is welded where its 'toParams' start it. An entry
#      written under 13 would go on being served with the value dropped and
#      the part at nought.
#  15: a BREP payload is OCCT's binary format and carries no triangulation but
#      that of a face with no surface (see 'ocp_serialize.shape_to_brep'), and
#      a shape's measurements say how many of its shells no solid bounds
#      ('shape_envelope.METADATA_FREE_SHELLS'). This release could read an
#      entry written under 14, because it tells the formats apart by their
#      headers; an earlier release handed an entry written now could not, and
#      its sandbox would fail the shape. A tier shared across releases is
#      where the two meet, so they are kept apart.
VERSION = 15

# What the version contributes to a hash. Namespaced so that it cannot be
# confused with the data hashed after it.
_VERSION_TAG = ("partcad-cache-v%d" % VERSION).encode()

# How much of a file's content is hashed, at most: all of a file up to this
# size, and half of it from each end of a larger one, which is what keeps
# hashing a large STEP file from costing a read of all of it. What is in between
# is covered by the size alone, so an edit there that keeps the size is not
# seen. The modification time is not hashed, deliberately: it differs between
# two clones of one repository, and a key that did would never be found by
# another machine in a shared tier.
_SAMPLE_SIZE = 1 << 20


def _header(tag: bytes, length: int) -> bytes:
    """What goes in front of every value: its type, and how long it is.

    Without it the hash is of the values run together, and different values
    run together into the same bytes: ["1", "23"] and ["12", "3"], a key "ab"
    with the value "c" and a key "a" with the value "bc". The length is what
    says where one value ends; the tag is what keeps 1 apart from "1".
    """
    return tag + length.to_bytes(8, "big")


def _frame(tag: bytes, data: bytes) -> bytes:
    return _header(tag, len(data)) + data


def _scalar(val) -> bytes:
    """A value that holds no others, framed with a tag saying what type it is."""
    if isinstance(val, str):
        return _frame(b"s", val.encode())
    if val is None:
        return _header(b"n", 0)
    if isinstance(val, bool):
        # Before 'int': a bool is one, and True is not 1 here.
        return _frame(b"t", str(val).encode())
    if isinstance(val, int):
        return _frame(b"i", str(val).encode())
    if isinstance(val, float):
        return _frame(b"r", repr(val).encode())
    return _frame(b"o", str(val).encode())


def file_stat(filename: str):
    """What a file looks like from outside, to tell later whether it changed.

    Modification time and size, which is what 'make' trusts too: a stat, not a
    read. None for a file that is not there.
    """
    try:
        st = os.stat(filename)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


class CacheHash:
    def __init__(self, name: str, algo="md5", hasher=None, cache=False):
        self.name = name
        self.is_empty = True
        self.is_used = False
        # Set before the early return below: get() walks this list, and it is
        # reached with caching disabled too (a disabled hash still answers
        # None, it just never hashes anything).
        self.dependencies = []
        if not cache:
            # Caching is disabled, no initialization needed
            self.hasher = None
            return

        if hasher is not None:
            # Continues a hash that already carries the version below
            self.hasher = hasher.copy()
        else:
            if algo == "md5":
                self.hasher = hashlib.md5()
            elif algo == "sha1":
                self.hasher = hashlib.sha1()
            elif algo == "sha256":
                self.hasher = hashlib.sha256()
            else:
                raise ValueError(f"Unknown hash algorithm: {algo}")

            # Every hash starts from the cache format version. Deliberately not
            # a touch(): the version alone is not data to cache, so a hash that
            # got nothing else must still report itself as empty.
            self.hasher.update(_VERSION_TAG)

    def touch(self):
        if self.is_used:
            pc_logging.warning(f"Hash update after being used: {self.name}")
        self.is_empty = False

    # TODO(clairbee): do not "add_" anything to the hash immediately.
    # Instead, add the data to a list and then add it to the hash when needed.

    def add_dict(self, data: dict):
        if not self.hasher:
            # Caching is disabled
            return
        if data is None or len(data.keys()) == 0:
            # Do not consider it not being empty
            return

        def recurse(val):
            if isinstance(val, dict):
                self.hasher.update(_header(b"d", len(val)))
                # Keys framed with their type like any other value, so that
                # 1 and "1" are two keys here as they are to whoever reads the
                # dictionary - and sorted by that, which is total whatever the
                # keys are, where comparing the keys themselves is not.
                for encoded, k in sorted(((_scalar(k), k) for k in val.keys()), key=lambda pair: pair[0]):
                    self.hasher.update(encoded)
                    recurse(val[k])
            elif isinstance(val, (list, tuple)):
                self.hasher.update(_header(b"l", len(val)))
                for item in val:
                    recurse(item)
            elif isinstance(val, (set, frozenset)):
                self.hasher.update(_header(b"l", len(val)))
                for encoded in sorted(_scalar(item) for item in val):
                    self.hasher.update(encoded)
            else:
                self.hasher.update(_scalar(val))

        recurse(data)
        self.touch()

    def add_string(self, string: str):
        if not self.hasher:
            # Caching is disabled
            return
        if string is None:
            # Do not consider it not being empty
            return

        self.hasher.update(_frame(b"s", string.encode()))
        self.touch()

    def add_bytes(self, bytes: bytes):
        if not self.hasher:
            # Caching is disabled
            return
        if bytes is None or len(bytes) == 0:
            # Do not consider it not being empty
            return

        self.hasher.update(_frame(b"b", bytes))
        self.touch()

    def add_filename(self, filename: str):
        if filename is None:
            # Do not consider it not being empty
            return

        if not self.hasher:
            # Caching is disabled
            return

        try:
            with open(filename, "rb") as f:
                size = os.fstat(f.fileno()).st_size
                # The size first: it is what tells two versions of a large file
                # apart when an edit falls outside the sample below.
                self.hasher.update(_frame(b"f", str(size).encode()))
                if size <= _SAMPLE_SIZE:
                    self.hasher.update(_frame(b"c", f.read()))
                else:
                    half = _SAMPLE_SIZE // 2
                    self.hasher.update(_frame(b"c", f.read(half)))
                    f.seek(-half, os.SEEK_END)
                    self.hasher.update(_frame(b"c", f.read(half)))
        except FileNotFoundError:
            # Hashed as missing rather than skipped: skipped, a dependency that
            # is not there and one that is empty or absent from the list are all
            # the same key, and the entry built without the file goes on being
            # served once the file appears.
            self.hasher.update(_header(b"m", 0))
        self.touch()

    def set_dependencies(self, dependencies: list[str]) -> None:
        self.dependencies = dependencies

    def get(self) -> str | None:
        if not self.is_used:
            # TODO(clairbee): make I/O asynchronous and parallel, but maintain the order of hashing
            for filename in self.dependencies:
                self.add_filename(filename)

        self.is_used = True
        if self.is_empty:
            return None

        return self.hasher.hexdigest()
