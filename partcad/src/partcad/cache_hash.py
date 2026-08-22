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
import struct

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
VERSION = 2

# What the version contributes to a hash. Namespaced so that it cannot be
# confused with the data hashed after it.
_VERSION_TAG = ("partcad-cache-v%d" % VERSION).encode()


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
                for k in sorted(val.keys()):
                    self.hasher.update(str(k).encode())
                    recurse(val[k])
            elif isinstance(val, str):
                self.hasher.update(val.encode())
            elif isinstance(val, (list, tuple, set)):
                for item in sorted(val) if not isinstance(val, list) else val:
                    recurse(item)
            else:
                self.hasher.update(str(val).encode())

        recurse(data)
        self.touch()

    def add_string(self, string: str):
        if not self.hasher:
            # Caching is disabled
            return
        if string is None:
            # Do not consider it not being empty
            return

        self.hasher.update(string.encode())
        self.touch()

    def add_bytes(self, bytes: bytes):
        if not self.hasher:
            # Caching is disabled
            return
        if bytes is None or len(bytes) == 0:
            # Do not consider it not being empty
            return

        self.hasher.update(bytes)
        self.touch()

    def add_filename(self, filename: str):
        if not self.hasher:
            # Caching is disabled
            return
        if filename is None:
            # Do not consider it not being empty
            return

        try:
            # Track changes to the file content
            with open(filename, "rb") as f:
                self.hasher.update(f.read())

            # TODO(clairbee): optionally, track changes by file modification time only
            # self.hasher.update(struct.pack("f", os.path.getmtime(filename)))
        except FileNotFoundError:
            # TODO(clairbee): trigger preload if content hashing is back
            # This happens for all files that are not yet downloaded
            return
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
