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
VERSION = 6

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
                for k in sorted(val.keys(), key=str):
                    self.hasher.update(_frame(b"k", str(k).encode()))
                    recurse(val[k])
            elif isinstance(val, str):
                self.hasher.update(_frame(b"s", val.encode()))
            elif isinstance(val, (list, tuple, set, frozenset)):
                items = val if isinstance(val, (list, tuple)) else sorted(val, key=str)
                self.hasher.update(_header(b"l", len(items)))
                for item in items:
                    recurse(item)
            elif val is None:
                self.hasher.update(_header(b"n", 0))
            elif isinstance(val, bool):
                # Before 'int': a bool is one, and True is not 1 here.
                self.hasher.update(_frame(b"t", str(val).encode()))
            elif isinstance(val, int):
                self.hasher.update(_frame(b"i", str(val).encode()))
            elif isinstance(val, float):
                self.hasher.update(_frame(b"r", repr(val).encode()))
            else:
                self.hasher.update(_frame(b"o", str(val).encode()))

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
